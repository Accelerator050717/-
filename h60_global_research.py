"""v13 adapter of the frozen v8 research loop, with explicit fund-risk hooks.

Original strategy functions remain unchanged in profit_priority_strategy.py.
Record-only mode must reproduce every original target/trade/balance exactly.
Session event journal commits actual fills, strategy checkpoint and fund risk
atomically; restarting loads those facts instead of initializing new capital.
All prices/fills here remain adjusted historical research proxies, not brokers.
"""
from dataclasses import asdict
from pathlib import Path
import hashlib
import json
import uuid
import numpy as np
import pandas as pd
from research_backtest import _check_dates, _rebalance, reduce_only
from profit_priority_strategy import (Policy, DrawdownState, risk_inputs, scheduled_weights,
    reduction_weights, protection_floor, stop_fill, clip_weights)
from h60_global_control import GlobalPolicy, GlobalRisk
from strategy_fund_journal import FundJournal


def json_safe(value):
    if isinstance(value, dict):
        return {str(k):json_safe(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value,pd.Timestamp):
        return str(value.date())
    if isinstance(value,np.generic):
        value=value.item()
    if isinstance(value,float) and not np.isfinite(value):
        return None
    return value


def restore_rows(rows):
    for row in rows:
        row=dict(row)
        for key in ('Date','observation_date'):
            if row.get(key) is not None:
                row[key]=pd.Timestamp(row[key])
        yield row


def input_signature(scores, ohlc, spy, observations, final, spec):
    digest=hashlib.sha256(json.dumps(json_safe(spec),sort_keys=True).encode())
    for frame in [scores,*[ohlc[k] for k in ('Open','High','Low','Close')],spy]:
        digest.update(pd.util.hash_pandas_object(frame,index=True).to_numpy().tobytes())
    digest.update(json.dumps([list(map(str,observations)),str(final),list(scores.columns)]).encode())
    return digest.hexdigest()


def simulate(scores, ohlc, spy_close, groups, observations, final_date, *,
             mode="risk", stops=True, breaker=True, cost_bps=10,
             stop_extra_bps=10, delayed_stops=False, excluded=(),
             all_stocks=False, policy=Policy(), global_control=False, global_policy=GlobalPolicy(),
             journal_path=None, scope_id=None, create_journal=False, stop_after_session=None,
             model_versions=None, run_id=None):
    """同日先处理旧止损/强制退出，再执行昨晚目标，日内触发止损，收盘更新阈值。

    mode=incumbent/equal/spy 为固定对照；risk 为新仓位规则。
    全部金额以初始权益1计，碎股、零息现金；open sizing沿用旧研究代理。
    返回每日开/收盘权益、压力估值、逐笔交易、每日持仓、目标、风控事件。
    """
    calendar, names = ohlc["Open"].index, ohlc["Open"].columns
    _check_dates(calendar, "OHLC")
    _check_dates(scores.index, "scores")
    if not scores.columns.equals(names) or set(groups) != set(names):
        raise ValueError("股票顺序或风险分组不一致。")
    if not spy_close.index.equals(calendar):
        raise ValueError("SPY日期与股票日历不一致。")
    for field in ("Open", "High", "Low", "Close"):
        frame = ohlc[field]
        if not frame.index.equals(calendar) or not frame.columns.equals(names):
            raise ValueError("OHLC日历或列不一致。")
        if not np.isfinite(frame).all().all() or (frame <= 0).any().any():
            raise ValueError("行情缺失或非法，不允许补可交易价格。")
    if ((ohlc["Low"] > np.minimum(ohlc["Open"], ohlc["Close"]) + 1e-10).any().any()
            or (ohlc["High"] < np.maximum(ohlc["Open"], ohlc["Close"]) - 1e-10).any().any()):
        raise ValueError("OHLC关系非法。")
    if mode not in ("risk", "incumbent", "equal", "spy", "simple_h60", "simple_spy"):
        raise ValueError("未知模式。")
    if not 0 <= cost_bps < 10000 or not 0 <= stop_extra_bps < 10000:
        raise ValueError("费用参数越界。")
    if mode in ("incumbent", "equal", "spy") and (stops or breaker):
        raise ValueError("旧策略对照必须关闭新增风控。")
    if mode.startswith("simple_") and stops:
        raise ValueError("简单预算对照不模拟个股保护单。")
    if not set(excluded).issubset(names):
        raise ValueError("排除名单包含未知股票。")
    observations = pd.DatetimeIndex(observations)
    _check_dates(observations, "observations")
    if (not observations.isin(scores.index).all() or not observations.isin(calendar).all()
            or final_date not in calendar or final_date <= observations[-1]):
        raise ValueError("调仓日期缺评分或最后出场日期非法。")
    if not np.isfinite(scores.loc[observations]).all().all():
        raise ValueError("调仓日缺评分。")
    positions = calendar.get_indexer(observations)
    schedule = {int(p + 1): int(p) for p in positions}
    first, finish = int(positions[0] + 1), int(calendar.get_loc(final_date))
    risk = risk_inputs(ohlc, spy_close, policy.target_vol)
    q = np.zeros(len(names)); cash = 1.; fee_rate = cost_bps / 10000
    threshold = np.full(len(names), np.nan); peak = np.full(len(names), np.nan)
    blocked_until = np.full(len(names), -1); pending_stop = set()
    pending_cap = None
    dd_state = DrawdownState()
    trades, daily, holdings, targets, events = [], [], [], [], []
    cumulative_cost = 0.
    global_state=GlobalRisk()
    high_water=1.;fund_shares=1.
    journal=None
    run_id=run_id or str(uuid.uuid4())
    signature=input_signature(scores,ohlc,spy_close,observations,final_date,
        dict(mode=mode,stops=stops,breaker=breaker,cost_bps=cost_bps,stop_extra_bps=stop_extra_bps,
             delayed_stops=delayed_stops,excluded=list(excluded),all_stocks=all_stocks,
             policy=asdict(policy),groups=dict(sorted(groups.items())),
             global_control=global_control,global_policy=asdict(global_policy)))
    next_day=first
    if journal_path is not None:
        if not scope_id:
            raise ValueError('Persistent research fund requires a stable explicit scope ID')
        scope=dict(scope_id=scope_id,currency='USD',owner='isolated_h60_research_capital',universe=list(names))
        if create_journal:
            journal=FundJournal.create(journal_path,scope,1.,str(calendar[first-1].date())+'T21:00:00+00:00')
        else:
            journal=FundJournal(journal_path,scope)
        stored=journal.read()
        if stored.get('blocked'):
            journal.close();raise ValueError('Fund journal quarantined; no new risk or implicit reset')
        cp=stored.get('checkpoint')
        if cp:
            if cp['simulation_identity']!=signature:
                journal.close();raise ValueError('Persisted simulation/input identity differs')
            q=np.asarray(cp['q'],dtype=float);cash=float(cp['cash'])
            threshold=np.asarray(cp['threshold'],dtype=float);peak=np.asarray(cp['peak'],dtype=float)
            blocked_until=np.asarray(cp['blocked_until'],dtype=int);pending_stop=set(cp['pending_stop'])
            pending_cap=pd.Series(cp['pending_cap']).reindex(names) if cp['pending_cap'] is not None else None
            dd_state=DrawdownState(**cp['episode']);global_state=GlobalRisk(**cp['global'])
            cumulative_cost=float(cp['cumulative_cost']);next_day=int(cp['day'])+1
            high_water=float(stored['high_water_nav']);fund_shares=float(stored['fund_shares'])
            for row in journal.history():
                if row['kind']!='commit' or not row.get('checkpoint'):
                    continue
                output=row['checkpoint']['session_output']
                daily.extend(restore_rows([output['daily']]))
                holdings.extend(restore_rows([output['holdings']]))
                for name,destination in (('trades',trades),('targets',targets),('events',events)):
                    destination.extend(restore_rows(output[name]))

    def trade(day, j, delta, price, reason, observation=None, risk_action=""):
        nonlocal cash, cumulative_cost
        if abs(delta) < 1e-14:
            return
        notional = delta * price
        fee = abs(notional) * fee_rate
        cash -= notional + fee
        q[j] += delta
        if abs(q[j]) < 1e-12:
            q[j] = 0.
        cumulative_cost += fee
        trades.append(dict(Date=calendar[day], observation_date=observation, symbol=names[j],
                           reason=reason, risk_action=risk_action, signed_units=float(delta), proxy_fill=float(price),
                           signed_notional=float(notional), fee=float(fee),
                           cash_change=float(-notional-fee), stop_threshold=float(threshold[j]),
                           session_open=float(ohlc["Open"].iloc[day,j]),
                           stop_extra_bps=stop_extra_bps if reason.startswith("stop_") else 0))

    def rebalance(day, w, reason, observation, reduction=False, risk_action=""):
        nonlocal cash
        prices = ohlc["Open"].iloc[day].to_numpy()
        old = q * prices
        sizing = reduce_only if reduction else _rebalance
        target, expected_cash, change, _ = sizing(old, cash, w.to_numpy(), fee_rate)
        before_q = q.copy()
        for j in np.argsort(change, kind="stable"):  # 先卖后买，避免途中借款。
            trade(day, j, change[j] / prices[j], prices[j], reason, observation, risk_action)
        if reduction:
            assert (q <= before_q + 1e-12).all(), "非计划减仓不得增加任何股票股数。"
        np.testing.assert_allclose(cash, expected_cash, atol=1e-10, rtol=1e-10)
        cash = max(0., expected_cash)
        np.testing.assert_allclose(q * prices, target, atol=1e-10, rtol=1e-10)
        if stops:
            distance = risk["distance"].iloc[day - 1].to_numpy()
            for j in range(len(names)):
                if q[j] == 0:
                    threshold[j] = peak[j] = np.nan
                elif before_q[j] == 0:
                    threshold[j] = protection_floor(np.nan, prices[j], new_position=True)
                    peak[j] = prices[j]
                elif reason == "scheduled" or q[j] > before_q[j]:
                    threshold[j] = protection_floor(threshold[j], prices[j], scheduled=True)
        targets.append(dict(Date=calendar[day], observation_date=observation, reason=reason,
                            reduce_only=reduction, risk_action=risk_action,
                            **{s:float(w[s]) for s in names}))

    for day in range(next_day, finish + 1):
        ntrades,ntargets,nevents=len(trades),len(targets),len(events)
        opened = ohlc["Open"].iloc[day].to_numpy()
        low = ohlc["Low"].iloc[day].to_numpy()
        close = ohlc["Close"].iloc[day].to_numpy()
        cost_before = cumulative_cost
        scheduled = day in schedule
        # 前一日触发的延迟止损，或早已生效且开盘已穿价的正常止损。
        for j in list(np.flatnonzero(q > 0)):
            if j in pending_stop or (stops and not delayed_stops and opened[j] <= threshold[j]):
                price = opened[j] * (1-stop_extra_bps/10000)
                reason = "stop_delayed" if j in pending_stop else "stop_gap"
                trade(day, j, -q[j], price, reason, calendar[day-1])
                blocked_until[j] = day + policy.stock_cooldown
                threshold[j] = peak[j] = np.nan
        pending_stop.clear()
        if day == finish:
            rebalance(day, pd.Series(0., index=names), "final_liquidation", calendar[day-1])
        else:
            global_flat=global_control and global_state.mode in ('HALTED','REVIEW_LOCKED')
            if dd_state.pending_flat or (global_flat and (global_state.pending_flat or (q>0).any())):
                # Individual gap stops have already been applied; exit only actual remainder.
                rebalance(day,pd.Series(0.,index=names),'global_flat' if global_flat else 'portfolio_flat',
                          calendar[day-1],reduction=bool(global_flat),risk_action='global' if global_flat else '')
                dd_state.pending_flat=False;pending_cap=None
                if global_flat:
                    global_state.pending_flat=bool((q>0).any())
            trend=bool(risk['trend'].iloc[day-1])
            if global_control:
                episode_ready=(not dd_state.paused or (day>=dd_state.paused_until and trend and scheduled))
                if global_state.try_resume(day,(cash+float(q@opened))/fund_shares,high_water,
                       trend=trend,scheduled=scheduled,confirmed_flat=bool((q==0).all()),
                       no_pending_orders=not pending_stop,episode_ready=episode_ready,policy=global_policy):
                    events.append(dict(Date=calendar[day],event='global_resume',equity=cash+float(q@opened),
                                       unit_nav=(cash+float(q@opened))/fund_shares,high_water_nav=high_water,
                                       recovery_floor=global_state.recovery_floor,reason=global_state.reason))
            global_allows=not global_control or global_state.mode not in ('HALTED','REVIEW_LOCKED')
            if breaker and global_allows and dd_state.resume(day, cash + float(q @ opened),
                                            bool(risk["trend"].iloc[day-1]), scheduled, policy):
                events.append(dict(Date=calendar[day], event="portfolio_resume", equity=cash+float(q@opened)))
            if scheduled and not dd_state.paused and global_allows:
                obs = schedule[day]
                s = scores.loc[calendar[obs]]
                w = pd.Series(0., index=names)
                if mode in ("equal", "spy"):
                    w[:] = 1 / len(names)
                elif mode in ("incumbent", "simple_h60", "simple_spy"):
                    selected = sorted((n for n in names if n not in excluded), key=lambda symbol: (-float(s[symbol]), symbol))[:5]
                    gross = float(risk["spy_exposure"].iloc[obs])
                    if mode.startswith("simple_"):
                        gross *= min(1., policy.risk_total/.15) * dd_state.multiplier(day)
                    w.loc[selected] = gross / len(selected)
                else:
                    eligible = [s for j,s in enumerate(names) if day >= blocked_until[j] and s not in excluded]
                    w = scheduled_weights(s, set(names[q > 0]), risk, obs, groups,
                                          multiplier=dd_state.multiplier(day) if breaker else 1.,
                                          eligible=eligible, all_stocks=all_stocks, policy=policy)
                if global_control:
                    cap=global_state.cap((cash+float(q@opened))/fund_shares,high_water,global_policy)
                    if w.sum()>cap:
                        w*=cap/float(w.sum())
                if not np.isfinite(w).all() or w.sum() > 1+1e-10:
                    raise ValueError("目标非法或借款。")
                rebalance(day, w, "scheduled", calendar[obs])
                dd_state.pending_half = False
                pending_cap = None
            elif (dd_state.pending_half or pending_cap is not None) and not dd_state.paused and global_allows:
                previous_values = pd.Series(q * ohlc["Close"].iloc[day-1].to_numpy(), index=names)
                w = reduction_weights(previous_values, cash, pending_cap, dd_state.pending_half)
                action = "cap_and_soft" if pending_cap is not None and dd_state.pending_half else "soft" if dd_state.pending_half else "cap"
                if global_control:
                    cap=global_state.cap((cash+float(q@opened))/fund_shares,high_water,global_policy)
                    if w.sum()>cap:
                        w*=cap/float(w.sum());action+='|global_cap'
                rebalance(day, w, "daily_risk_reduce", calendar[day-1], reduction=True, risk_action=action)
                dd_state.pending_half = False
                pending_cap = None
            if global_control and global_allows and not dd_state.paused and not scheduled:
                # Independent cumulative cap: nonplanned changes can only sell.
                current_values=pd.Series(q*opened,index=names)
                w=reduction_weights(current_values,cash)
                cap=global_state.cap((cash+float(q@opened))/fund_shares,high_water,global_policy)
                if w.sum()>cap+1e-10:
                    w*=cap/float(w.sum())
                    rebalance(day,w,'global_risk_reduce',calendar[day-1],reduction=True,risk_action='global_cap')
        open_nav = cash + float(q @ opened)
        # 悲观压力估值：假设持仓同时到Low且不享受止损保护，不称真实盘中净值。
        low_mark = cash + float(q @ low)
        if day != finish and stops:
            for j in list(np.flatnonzero(q > 0)):
                price, reason = stop_fill(opened[j], low[j], threshold[j], stop_extra_bps)
                if reason is not None:
                    if delayed_stops:
                        pending_stop.add(j)
                    else:
                        trade(day, j, -q[j], price, reason, calendar[day-1])
                        blocked_until[j] = day + policy.stock_cooldown
                        threshold[j] = peak[j] = np.nan
            # 15%保护底线只在计划调仓时提高，不逐日追踪峰值。
        close_nav = cash + float(q @ close)
        if cash < -1e-10 or (q < -1e-10).any() or close_nav <= 0:
            raise AssertionError("现金/仓位/净值账本非法。")
        unit_nav=close_nav/fund_shares
        high_water=max(high_water,unit_nav)
        if global_control:
            for event in global_state.observe(day,unit_nav,high_water,global_policy):
                events.append(dict(Date=calendar[day],equity=close_nav,unit_nav=unit_nav,
                                   high_water_nav=high_water,cumulative_drawdown=unit_nav/high_water-1,**event))
            if day==finish and not (q>0).any():
                global_state.pending_flat=False
        if day != finish and breaker:
            event = dd_state.observe(day, close_nav, policy)
            if event:
                events.append(dict(Date=calendar[day], event=event, equity=close_nav,
                                   episode_drawdown=close_nav/dd_state.episode_peak-1))
        if day != finish and mode == "risk" and not dd_state.paused:
            live_w = pd.Series(q*close/close_nav, index=names)
            clipped = clip_weights(live_w, groups, policy)
            if (clipped < live_w-1e-8).any():
                pending_cap = clipped
        daily.append(dict(Date=calendar[day], open_equity=open_nav, equity=close_nav,
                          low_stress_equity=min(low_mark, close_nav), cash=cash,
                          invested=float(q@close), gross=float(q@close)/close_nav,
                          fees=cumulative_cost-cost_before, cumulative_fees=cumulative_cost,
                          paused=dd_state.paused, soft=dd_state.soft,
                          episode_peak=dd_state.episode_peak))
        daily[-1].update(unit_nav=unit_nav,high_water_nav=high_water,fund_shares=fund_shares,
            cumulative_fund_drawdown=unit_nav/high_water-1,global_mode=global_state.mode if global_control else 'RECORD_ONLY',
            global_cap=global_state.cap(unit_nav,high_water,global_policy) if global_control else 1.,
            global_paused=global_control and global_state.mode in ('HALTED','REVIEW_LOCKED'))
        holdings.append(dict(Date=calendar[day], **{s:float(q[j]) for j,s in enumerate(names)}))
        if journal is not None:
            at=str(calendar[day].date())+'T21:00:00+00:00'
            fact_events=[dict(id=f'research-fill:{day}:{i}',at=at,kind='fill',symbol=t['symbol'],
                quantity=t['signed_units'],price=t['proxy_fill'],fee=t['fee']) for i,t in enumerate(trades[ntrades:])]
            checkpoint=json_safe(dict(simulation_identity=signature,day=day,q=q.tolist(),cash=cash,
                threshold=threshold.tolist(),peak=peak.tolist(),blocked_until=blocked_until.tolist(),
                pending_stop=sorted(pending_stop),pending_cap=None if pending_cap is None else pending_cap.to_dict(),
                episode=asdict(dd_state),global_state_enabled=global_control,global_=asdict(global_state),
                cumulative_cost=cumulative_cost,session_output=dict(daily=list(daily[-1].items()),holdings=list(holdings[-1].items()),
                trades=[list(row.items()) for row in trades[ntrades:]],
                targets=[list(row.items()) for row in targets[ntargets:]],
                events=[list(row.items()) for row in events[nevents:]])))
            checkpoint['global']=checkpoint.pop('global_')
            persisted=journal.commit(f'session:{day}',at,fact_events,dict(zip(names,map(float,close))),checkpoint,
                model_version=(model_versions or {}).get(calendar[day].year,'frozen-A'),run_id=run_id,
                expected_cash=cash,expected_positions=dict(zip(names,map(float,q))),
                risk_state=dict(**asdict(global_state),record_only=not global_control))
            if persisted.get('blocked'):
                journal.close();raise ValueError('Research event reconciliation blocked: '+str(persisted['blocked']))
            np.testing.assert_allclose([persisted['equity'],persisted['unit_nav'],persisted['high_water_nav']],
                                       [close_nav,unit_nav,high_water],rtol=1e-10,atol=1e-11)
        if stop_after_session is not None and len(daily)>=stop_after_session and day<finish:
            if journal is None:
                raise ValueError('Partial execution requires a persisted journal')
            state=journal.read();journal.close()
            return dict(partial=True,last_session=str(calendar[day].date()),fund_state=state)
    final_fund=journal.read() if journal is not None else None
    if journal is not None:
        journal.close()
    daily = pd.DataFrame(daily).set_index("Date")
    trades = pd.DataFrame(trades)
    positions = pd.DataFrame(holdings).set_index("Date")
    daily["return"] = daily.equity / daily.equity.shift(1, fill_value=1.) - 1
    daily["drawdown"] = daily.equity / daily.equity.cummax().clip(lower=1.) - 1
    daily["open_drawdown"] = daily.open_equity / daily.open_equity.cummax().clip(lower=1.) - 1
    daily["low_stress_drawdown"] = daily.low_stress_equity / daily.equity.cummax().clip(lower=1.) - 1
    duration = (daily.index[-1]-daily.index[0]).days/365.25
    sigma = daily["return"].std(ddof=1)
    metrics = dict(cagr=float(daily.equity.iloc[-1] ** (1/duration)-1),
                   final_equity=float(daily.equity.iloc[-1]),
                   max_drawdown=float(daily.drawdown.min()),
                   open_max_drawdown=float(daily.open_drawdown.min()),
                   low_stress_drawdown=float(daily.low_stress_drawdown.min()),
                   annualized_vol=float(sigma*np.sqrt(252)),
                   sharpe_zero_rf=float(daily["return"].mean()/sigma*np.sqrt(252)) if sigma>0 else 0.,
                   average_gross=float(daily.gross.mean()), worst_day=float(daily["return"].min()),
                   fees=float(cumulative_cost), trades=len(trades),
                   stop_exits=int(trades.reason.str.startswith("stop_").sum()) if len(trades) else 0,
                   gap_stops=int(trades.reason.eq("stop_gap").sum()) if len(trades) else 0,
                   halts=sum(e["event"]=="portfolio_halt" for e in events),
                   cost_bps=cost_bps, stop_extra_bps=stop_extra_bps,
                   first_entry=str(daily.index[0].date()), final_exit=str(daily.index[-1].date()))
    return dict(daily=daily, trades=trades, positions=positions,
                targets=pd.DataFrame(targets), events=pd.DataFrame(events), metrics=metrics,
                policy=asdict(policy),fund_state=final_fund,global_policy=asdict(global_policy),
                global_control=global_control)
