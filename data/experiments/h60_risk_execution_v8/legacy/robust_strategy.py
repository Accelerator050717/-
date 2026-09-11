"""每日OHLC代理下的固定风险策略。只做历史模拟，不连接或下单到券商。

阈值只使用已结束的日线。日内止损成交是假设，跳空用更差的开盘价；
这不能证明停牌、订单排队或真实公司行动下的可成交性。
"""
from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd

from research_backtest import _check_dates, _rebalance


@dataclass(frozen=True)
class Policy:
    top_k: int = 10
    retain_rank: int = 15
    max_stock: float = .10
    max_group: float = .25
    max_cluster: float = .35
    risk_per_stock: float = .0075
    risk_total: float = .05
    target_vol: float = .15
    soft_dd: float = .08
    hard_dd: float = .12
    pause_sessions: int = 20
    recovery_sessions: int = 10
    stock_cooldown: int = 5


TECH_CLUSTER = frozenset(("AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META"))


def risk_inputs(ohlc, spy_close):
    """所有结果在索引当天收盘后才可用；不回填预热缺失。"""
    close = ohlc["Close"]
    previous = close.shift(1)
    tr = np.maximum(ohlc["High"] - ohlc["Low"],
                    np.maximum((ohlc["High"] - previous).abs(),
                               (ohlc["Low"] - previous).abs()))
    returns = close.pct_change(fill_method=None)
    return dict(distance=(3 * tr.rolling(14).mean() / close).clip(.05, .12),
                vol=returns.rolling(60).std(ddof=1), returns=returns,
                trend=spy_close.ge(spy_close.rolling(200).mean()),
                spy_exposure=(.15 / (spy_close.pct_change(fill_method=None)
                                    .rolling(20).std(ddof=1) * np.sqrt(252))).clip(upper=1))


def clip_weights(weights, groups, policy, distances=None):
    """只减不增，不把被约束释放的现金再分配给其他股票。"""
    w = weights.clip(lower=0, upper=policy.max_stock).copy()
    if distances is not None:
        w = np.minimum(w, policy.risk_per_stock / distances)
    for group in sorted(set(groups.values())):
        names = [s for s in w.index if groups[s] == group]
        total = w.loc[names].sum()
        if total > policy.max_group:
            w.loc[names] *= policy.max_group / total
    names = [s for s in w.index if s in TECH_CLUSTER]
    total = w.loc[names].sum()
    if total > policy.max_cluster:
        w.loc[names] *= policy.max_cluster / total
    if distances is not None:
        risk = float((w * distances).sum())
        if risk > policy.risk_total:
            w *= policy.risk_total / risk
    return w


def allocate(scores, holdings, distances, vol, past_returns, groups, trend,
             multiplier=1.0, eligible=None, all_stocks=False, policy=Policy()):
    """输入观察日信号与历史风险，输出下一开盘目标权重；没有未来收益输入。"""
    if (not np.isfinite(scores).all() or not np.isfinite(distances).all()
            or not np.isfinite(vol).all() or (vol <= 0).any()
            or len(past_returns) != 60 or not np.isfinite(past_returns).all().all()):
        raise ValueError("信号或60日风险历史不完整，禁止补价或继续交易。")
    eligible = set(scores.index) if eligible is None else set(eligible)
    order = sorted(eligible, key=lambda s: (-float(scores[s]), s))
    if all_stocks:
        selected = order
    else:
        retained = [s for s in order[:policy.retain_rank] if s in holdings]
        selected = (retained + [s for s in order if s not in retained])[:policy.top_k]
    w = pd.Series(0., index=scores.index)
    if not selected:
        return w, 0.
    inv = 1 / vol.loc[selected]
    w.loc[selected] = inv / inv.sum()
    w = clip_weights(w, groups, policy, distances)
    covariance = past_returns.cov().to_numpy()
    covariance = .8 * covariance + .2 * np.diag(np.diag(covariance))
    estimate = float(np.sqrt(max(0., w.to_numpy() @ covariance @ w.to_numpy()) * 252))
    scale = min(1., policy.target_vol / estimate) if estimate > 0 else 1.
    w *= scale
    if not trend and w.sum() > .5:
        w *= .5 / w.sum()
    w *= multiplier
    return w, estimate * scale * multiplier


def stop_fill(opened, low, threshold, extra_bps):
    """单个已生效卖出止损的日线代理成交；返回价格及原因。"""
    if not 0 <= extra_bps < 10000:
        raise ValueError("止损额外滑点超界。")
    if opened <= threshold:
        return opened * (1 - extra_bps / 10000), "stop_gap"
    if low <= threshold:
        return threshold * (1 - extra_bps / 10000), "stop_intraday"
    return None, None


@dataclass
class DrawdownState:
    episode_peak: float = 1.
    paused_until: int = -1
    recovery_until: int = -1
    soft: bool = False
    paused: bool = False
    pending_flat: bool = False
    pending_half: bool = False

    def observe(self, day, equity, policy):
        self.episode_peak = max(self.episode_peak, equity)
        dd = equity / self.episode_peak - 1
        if not self.paused and dd <= -policy.hard_dd:
            self.paused = self.pending_flat = True
            self.paused_until = day + 1 + policy.pause_sessions
            self.pending_half = False
            return "portfolio_halt"
        if not self.paused and not self.soft and dd <= -policy.soft_dd:
            self.soft = self.pending_half = True
            return "portfolio_half"
        return None

    def resume(self, day, equity, trend, scheduled, policy):
        if self.paused and day >= self.paused_until and trend and scheduled:
            self.paused = self.soft = False
            self.episode_peak = equity
            self.recovery_until = day + policy.recovery_sessions
            return True
        return False

    def multiplier(self, day):
        return 0. if self.paused else (.5 if self.soft or day < self.recovery_until else 1.)


def simulate(scores, ohlc, spy_close, groups, observations, final_date, *,
             mode="risk", stops=True, breaker=True, cost_bps=10,
             stop_extra_bps=10, delayed_stops=False, excluded=(),
             all_stocks=False, policy=Policy()):
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
    if mode not in ("risk", "incumbent", "equal", "spy"):
        raise ValueError("未知模式。")
    if not 0 <= cost_bps < 10000 or not 0 <= stop_extra_bps < 10000:
        raise ValueError("费用参数越界。")
    if mode != "risk" and (stops or breaker):
        raise ValueError("旧策略对照必须关闭新增风控。")
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
    risk = risk_inputs(ohlc, spy_close)
    q = np.zeros(len(names)); cash = 1.; fee_rate = cost_bps / 10000
    threshold = np.full(len(names), np.nan); peak = np.full(len(names), np.nan)
    blocked_until = np.full(len(names), -1); pending_stop = set()
    pending_cap = None
    dd_state = DrawdownState()
    trades, daily, holdings, targets, events = [], [], [], [], []
    cumulative_cost = 0.

    def trade(day, j, delta, price, reason, observation=None):
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
                           reason=reason, signed_units=float(delta), proxy_fill=float(price),
                           signed_notional=float(notional), fee=float(fee),
                           cash_change=float(-notional-fee), stop_threshold=float(threshold[j]),
                           session_open=float(ohlc["Open"].iloc[day,j]),
                           stop_extra_bps=stop_extra_bps if reason.startswith("stop_") else 0))

    def rebalance(day, w, reason, observation):
        nonlocal cash
        prices = ohlc["Open"].iloc[day].to_numpy()
        old = q * prices
        target, expected_cash, change, _ = _rebalance(old, cash, w.to_numpy(), fee_rate)
        before_q = q.copy()
        for j in np.argsort(change, kind="stable"):  # 先卖后买，避免途中借款。
            trade(day, j, change[j] / prices[j], prices[j], reason, observation)
        np.testing.assert_allclose(cash, expected_cash, atol=1e-10, rtol=1e-10)
        cash = max(0., expected_cash)
        np.testing.assert_allclose(q * prices, target, atol=1e-10, rtol=1e-10)
        if stops:
            distance = risk["distance"].iloc[day - 1].to_numpy()
            for j in range(len(names)):
                if q[j] == 0:
                    threshold[j] = peak[j] = np.nan
                elif before_q[j] == 0:
                    threshold[j] = prices[j] * (1 - distance[j])
                    peak[j] = prices[j]
                elif q[j] > before_q[j]:
                    threshold[j] = max(threshold[j], prices[j] * (1 - distance[j]))
        targets.append(dict(Date=calendar[day], observation_date=observation, reason=reason,
                            **{s:float(w[s]) for s in names}))

    for day in range(first, finish + 1):
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
            if dd_state.pending_flat:
                rebalance(day, pd.Series(0., index=names), "portfolio_flat", calendar[day-1])
                dd_state.pending_flat = False
                pending_cap = None
            if breaker and dd_state.resume(day, cash + float(q @ opened),
                                            bool(risk["trend"].iloc[day-1]), scheduled, policy):
                events.append(dict(Date=calendar[day], event="portfolio_resume", equity=cash+float(q@opened)))
            if scheduled and not dd_state.paused:
                obs = schedule[day]
                s = scores.loc[calendar[obs]]
                w = pd.Series(0., index=names)
                if mode in ("equal", "spy"):
                    w[:] = 1 / len(names)
                elif mode == "incumbent":
                    selected = sorted(names, key=lambda symbol: (-float(s[symbol]), symbol))[:5]
                    w.loc[selected] = float(risk["spy_exposure"].iloc[obs]) / 5
                else:
                    eligible = [s for j,s in enumerate(names) if day >= blocked_until[j] and s not in excluded]
                    w, _ = allocate(s, set(names[q > 0]), risk["distance"].iloc[obs],
                                    risk["vol"].iloc[obs], risk["returns"].iloc[obs-59:obs+1],
                                    groups, bool(risk["trend"].iloc[obs]),
                                    multiplier=dd_state.multiplier(day) if breaker else 1.,
                                    eligible=eligible, all_stocks=all_stocks, policy=policy)
                if not np.isfinite(w).all() or w.sum() > 1+1e-10:
                    raise ValueError("目标非法或借款。")
                rebalance(day, w, "scheduled", calendar[obs])
                dd_state.pending_half = False
                pending_cap = None
            elif (dd_state.pending_half or pending_cap is not None) and not dd_state.paused:
                previous_values = pd.Series(q * ohlc["Close"].iloc[day-1].to_numpy(), index=names)
                w = previous_values / (cash + previous_values.sum())
                if pending_cap is not None:
                    w = np.minimum(w, pending_cap)
                if dd_state.pending_half:
                    w *= .5
                rebalance(day, w, "daily_risk_reduce", calendar[day-1])
                dd_state.pending_half = False
                pending_cap = None
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
            # 只用收盘峰值生成下一交易日的阈值，绝不读取当天High来提前触发。
            distance = risk["distance"].iloc[day].to_numpy()
            for j in np.flatnonzero(q > 0):
                peak[j] = max(peak[j], close[j])
                threshold[j] = max(threshold[j], peak[j] * (1-distance[j]))
        close_nav = cash + float(q @ close)
        if cash < -1e-10 or (q < -1e-10).any() or close_nav <= 0:
            raise AssertionError("现金/仓位/净值账本非法。")
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
        holdings.append(dict(Date=calendar[day], **{s:float(q[j]) for j,s in enumerate(names)}))
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
                policy=asdict(policy))
