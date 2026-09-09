"""执行v6固定对照与压力测试；失败不调参数、不开启2026或券商订单。"""
import importlib
import json
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

import research_features as rf
from panel_config import ROOT, SYMBOLS
from robust_strategy import simulate, risk_inputs, Policy, TECH_CLUSTER
from research_evaluation import _annual_returns

train = importlib.import_module("38_train_robust_strategy")
OUT, PRIOR = train.OUT, train.PRIOR
RAW = ROOT/"data/raw/extended_2012_2025"
CASES = [
    dict(id="incumbent",score="ridge_h60_price",mode="incumbent",stops=False,breaker=False),
    dict(id="ensemble_allocation",score="ensemble",stops=False,breaker=False),
    dict(id="ensemble_stops",score="ensemble",stops=True,breaker=False),
    dict(id="ensemble_full",score="ensemble",stops=True,breaker=True),
    dict(id="momentum_full",score="momentum",stops=True,breaker=True),
    dict(id="equal_risk_full",score=None,stops=True,breaker=True,all_stocks=True),
    dict(id="equal_full",score=None,mode="equal",stops=False,breaker=False),
    dict(id="spy_full",score=None,mode="spy",stops=False,breaker=False),
]


def load_data():
    frames, hashes = {}, {}
    for symbol in (*SYMBOLS,"SPY"):
        path = RAW/f"{symbol}.csv"
        meta = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        assert train.sha(path) == meta["sha256"]
        assert meta["parameters"]["end"] == "2026-01-01"
        frames[symbol] = pd.read_csv(path,index_col="Date",parse_dates=["Date"],float_precision="round_trip").loc["2012-05-18":]
        assert frames[symbol].index.max() <= pd.Timestamp("2025-12-31")
        hashes[symbol] = meta["sha256"]
    for frame in frames.values():
        assert frame.index.equals(frames["SPY"].index)
    bars = {field:pd.DataFrame({s:frames[s][field]*frames[s]["Adj Close"]/frames[s].Close for s in SYMBOLS})
            for field in ("Open","High","Low")}
    bars["Close"] = pd.DataFrame({s:frames[s]["Adj Close"] for s in SYMBOLS})
    spy_bars = {field:(frames["SPY"][field]*frames["SPY"]["Adj Close"]/frames["SPY"].Close).to_frame("SPY")
                for field in ("Open","High","Low")}
    spy_bars["Close"] = frames["SPY"][["Adj Close"]].rename(columns={"Adj Close":"SPY"})
    spy = frames["SPY"]["Adj Close"]
    cutoff = pd.Timestamp("2024-06-28")
    full = risk_inputs(bars,spy)
    prefix = risk_inputs({k:v.loc[:cutoff] for k,v in bars.items()},spy.loc[:cutoff])
    for key in full:
        if isinstance(full[key],pd.Series):
            pd.testing.assert_series_equal(full[key].loc[:cutoff],prefix[key],check_exact=True)
        else:
            pd.testing.assert_frame_equal(full[key].loc[:cutoff],prefix[key],check_exact=True)
    old_open = pd.read_csv(PRIOR/"adjusted_opens.csv",index_col="Date",parse_dates=["Date"],float_precision="round_trip")
    pd.testing.assert_frame_equal(bars["Open"],old_open,check_exact=True)
    train.save(OUT/"INPUT_CHECKS.json",dict(raw_files=31,sha256=hashes,
                common_dates=len(spy),calendar_and_positive_OHLC_checked_by_engine=True,
                risk_features_physical_prefix_exact=True,open_prices_exactly_match_v5=True,
                last_price_date=str(spy.index[-1].date()),prices_2026_accessed=False))
    return bars,spy_bars,spy


def audit(result,bars,mode):
    daily,trades,positions = result["daily"],result["trades"],result["positions"]
    changes = trades.groupby("Date").cash_change.sum().reindex(daily.index,fill_value=0)
    np.testing.assert_allclose(1+changes.cumsum(),daily.cash,rtol=1e-10,atol=1e-10)
    units = trades.pivot_table(index="Date",columns="symbol",values="signed_units",aggfunc="sum",fill_value=0)
    units = units.reindex(index=daily.index,columns=positions.columns,fill_value=0).cumsum()
    np.testing.assert_allclose(units,positions,rtol=1e-9,atol=1e-10)
    nav = daily.cash + (positions*bars["Close"].loc[daily.index]).sum(axis=1)
    np.testing.assert_allclose(nav,daily.equity,rtol=1e-11,atol=1e-11)
    np.testing.assert_allclose(trades.fee.sum(),daily.fees.sum(),rtol=1e-10,atol=1e-12)
    assert (daily.cash>=-1e-10).all() and (positions>=-1e-10).all().all()
    assert positions.iloc[-1].eq(0).all()
    target = result["targets"]
    assert target.observation_date.lt(target.Date).all()
    if mode=="risk":
        values = target[list(SYMBOLS)]
        assert values.max().max() <= .10+1e-10
        for group in set(rf.SECTOR_PROXY.values()):
            group_names = [s for s in SYMBOLS if rf.SECTOR_PROXY[s]==group]
            assert (values[group_names].sum(axis=1)<=.25+1e-10).all()
        assert (values[list(TECH_CLUSTER)].sum(axis=1)<=.35+1e-10).all()
        scheduled = target.loc[target.reason.eq("scheduled")]
        distances = risk_inputs(bars,pd.Series(1.,index=bars["Close"].index))["distance"]
        risk_weights = scheduled[list(SYMBOLS)].to_numpy()*distances.loc[scheduled.observation_date].to_numpy()
        assert risk_weights.max()<=.0075+1e-10 and (risk_weights.sum(axis=1)<=.05+1e-10).all()
    stopped = trades.loc[trades.reason.str.startswith("stop_")]
    for row in stopped.itertuples():
        if row.reason=="stop_intraday":
            assert bars["Low"].loc[row.Date,row.symbol] <= row.stop_threshold
            assert row.proxy_fill <= row.stop_threshold
        else:
            assert row.proxy_fill <= row.session_open
    return dict(ledger_checked_days=len(daily),trades_checked=len(trades),target_rows=len(target),
                final_flat=True,all_checks_passed=True)


def store_result(name,result):
    folder = OUT/"backtests"; folder.mkdir(exist_ok=True)
    for key in ("daily","trades","positions","targets","events"):
        result[key].to_csv(folder/f"{name}_{key}.csv",index=key in ("daily","positions"),date_format="%Y-%m-%d")
    train.save(folder/f"{name}_metrics.json",result["metrics"])


def main():
    train.register()
    source_hash = {p:train.sha(ROOT/p) for p in ("robust_strategy.py","39_evaluate_robust_strategy.py")}
    if (OUT/"completion.json").exists():
        completion = json.loads((OUT/"completion.json").read_text(encoding="utf-8"))
        assert completion["source_sha256"]==source_hash
        print("v6 evaluations complete; preserved. No trading or holdout access.")
        return
    bars,spy_bars,spy = load_data()
    scores = pd.read_csv(OUT/"all_scores.csv",parse_dates=["Date"],float_precision="round_trip")
    periods = pd.read_csv(PRIOR/"backtests/ridge_h60_price_vol15_cost10_periods.csv",parse_dates=["observation_date","exit_date"])
    obs = pd.DatetimeIndex(periods.observation_date)
    final = periods.exit_date.iloc[-1]
    score_dates = pd.DatetimeIndex(scores.Date.unique()).sort_values()
    rows,checks,equity,cache = [],[],{},{}
    for cost in (10,20):
        for case in CASES:
            params = {k:v for k,v in case.items() if k not in ("id","score")}
            use_bars = spy_bars if case["id"]=="spy_full" else bars
            names = use_bars["Open"].columns
            values = (pd.DataFrame(0.,index=score_dates,columns=names) if case["score"] is None else
                      scores.pivot(index="Date",columns="symbol",values=case["score"]).reindex(columns=SYMBOLS))
            result = simulate(values,use_bars,spy,{s:rf.SECTOR_PROXY.get(s,"market") for s in names},
                              obs,final,cost_bps=cost,**params)
            name = f"{case['id']}_cost{cost}"
            check = audit(result,use_bars,case.get("mode","risk"))
            if case["id"]=="incumbent":
                old = pd.read_csv(PRIOR/f"backtests/ridge_h60_price_vol15_cost{cost}_daily.csv",
                                  index_col="Date",parse_dates=["Date"],float_precision="round_trip")
                pd.testing.assert_index_equal(old.index,result["daily"].index)
                np.testing.assert_allclose(old.equity,result["daily"].open_equity,rtol=2e-12,atol=2e-12)
                check["old_open_NAV_max_absolute_difference"] = float((old.equity-result["daily"].open_equity).abs().max())
            checks.append(dict(candidate=name,**check))
            store_result(name,result)
            rows.append(dict(candidate=name,case=case["id"],**result["metrics"]))
            equity[name] = result["daily"].equity
            cache[name] = result
            pd.DataFrame(rows).to_csv(OUT/"comparison.csv",index=False)
            print(f"{name}: CAGR {result['metrics']['cagr']:.2%}, closeDD {result['metrics']['max_drawdown']:.2%}, stops {result['metrics']['stop_exits']}",flush=True)
    equity = pd.DataFrame(equity)
    equity.to_csv(OUT/"equity.csv",date_format="%Y-%m-%d")
    annual = _annual_returns(equity)
    annual.to_csv(OUT/"annual_returns.csv")
    # 同风险动量和等风险全池均为无ML基准，主候选不因结果改变。
    table = pd.DataFrame(rows).set_index("candidate")
    principal = table.loc["ensemble_full_cost10"]
    old = table.loc["incumbent_cost10"]
    gates = dict(cagr_at_least_80pct_incumbent=bool(principal.cagr>=.8*old.cagr),
                 beats_full_spy=bool(principal.cagr>table.loc["spy_full_cost10","cagr"]),
                 beats_both_non_ml_risk_controls=bool(principal.cagr>max(table.loc["momentum_full_cost10","cagr"],table.loc["equal_risk_full_cost10","cagr"])),
                 close_drawdown_better_than_20pct=bool(principal.max_drawdown>=-.20),
                 close_drawdown_improves_25pct=bool(abs(principal.max_drawdown)<=.75*abs(old.max_drawdown)),
                 cost20_beats_both_non_ml_risk_controls=bool(table.loc["ensemble_full_cost20","cagr"]>max(table.loc["momentum_full_cost20","cagr"],table.loc["equal_risk_full_cost20","cagr"])))
    gates["all_passed"] = all(gates.values())
    train.save(OUT/"diagnostic_gates.json",gates)
    stress_rows = []
    ensemble = scores.pivot(index="Date",columns="symbol",values="ensemble").reindex(columns=SYMBOLS)
    stresses = [dict(id="cost30_stop50",cost_bps=30,stop_extra_bps=50),
                dict(id="delayed_next_open_cost20_stop50",cost_bps=20,stop_extra_bps=50,delayed_stops=True),
                dict(id="exclude_NVDA_no_retrain",excluded=("NVDA",))]
    for stress in stresses:
        params = {k:v for k,v in stress.items() if k!="id"}
        result = simulate(ensemble,bars,spy,rf.SECTOR_PROXY,obs,final,**params)
        checks.append(dict(candidate=stress["id"],**audit(result,bars,"risk")))
        store_result(stress["id"],result)
        stress_rows.append(dict(candidate=stress["id"],**result["metrics"]))
        print(f"Stress {stress['id']}: CAGR {result['metrics']['cagr']:.2%}, DD {result['metrics']['max_drawdown']:.2%}",flush=True)
    calendar = bars["Open"].index
    original = calendar.get_indexer(obs)
    for phase in range(5):
        if phase==0:
            result = cache["ensemble_full_cost10"]
        else:
            phase_obs = calendar[original+phase]
            phase_obs = phase_obs[phase_obs.isin(ensemble.index) & (phase_obs<final)]
            result = simulate(ensemble,bars,spy,rf.SECTOR_PROXY,phase_obs,final)
            checks.append(dict(candidate=f"phase_{phase}",**audit(result,bars,"risk")))
            store_result(f"phase_{phase}",result)
        stress_rows.append(dict(candidate=f"phase_{phase}",**result["metrics"]))
        print(f"Phase {phase}: CAGR {result['metrics']['cagr']:.2%}, DD {result['metrics']['max_drawdown']:.2%}",flush=True)
    pd.DataFrame(stress_rows).to_csv(OUT/"stress_comparison.csv",index=False)
    train.save(OUT/"RUN_CHECKS.json",checks)
    train.save(OUT/"completion.json",dict(completed_at_utc=datetime.now(timezone.utc).isoformat(),
               main_backtests=16,additional_stress_backtests=7,new_fits=10,source_sha256=source_hash,
               diagnostic_all_passed=gates["all_passed"],old_0_of_98_unchanged=True,
               prices_2026_accessed=False,orders_sent=0))


if __name__=="__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
