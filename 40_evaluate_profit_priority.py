"""v7固定精简修订；保留v6全部结果，并增加相同估值时点的比较。"""
import importlib
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from panel_config import ROOT, SYMBOLS
import research_features as rf
import robust_strategy as v6engine
import profit_priority_strategy as engine
from research_evaluation import _annual_returns

v6 = importlib.import_module("39_evaluate_robust_strategy")
train = importlib.import_module("38_train_robust_strategy")
OUT = ROOT/"data/experiments/profit_priority_v7"
CASES = [
    dict(id="h60_allocation",score="ridge_h60_price",stops=False,breaker=False),
    dict(id="h60_stops",score="ridge_h60_price",stops=True,breaker=False),
    dict(id="h60_full",score="ridge_h60_price",stops=True,breaker=True),
    dict(id="momentum_full",score="momentum",stops=True,breaker=True),
    dict(id="equal_risk_full",score=None,stops=True,breaker=True,all_stocks=True),
]


def register():
    plan = dict(design_sha256=train.sha(OUT/"DESIGN.md"),
                policy=asdict(engine.Policy()),cases=CASES,
                source_sha256={p:train.sha(ROOT/p) for p in ("profit_priority_strategy.py","40_evaluate_profit_priority.py")},
                v6_scores_sha256=train.sha(train.OUT/"all_scores.csv"),
                ordinary_costs=[10,20],stop_distance=.15,stop_extra_bps=10,
                new_fits=0,selection="Adaptive diagnostic after v6 failure; no independent validation or live enablement")
    path = OUT/"plan.json"
    if path.exists():
        old = json.loads(path.read_text(encoding="utf-8"));old.pop("registered_at_utc")
        assert old==plan
    else:
        train.save(path,dict(registered_at_utc=datetime.now(timezone.utc).isoformat(),**plan))


def audit(result,bars,mode="v7"):
    # 复用现金和股份账本核对；v7上限不同，单独核对。
    checked = v6.audit(result,bars,"v7")
    policy = engine.Policy()
    t = result["targets"]
    w = t[list(SYMBOLS)]
    assert w.max().max()<=policy.max_stock+1e-10
    for group in set(rf.SECTOR_PROXY.values()):
        assert w[[s for s in SYMBOLS if rf.SECTOR_PROXY[s]==group]].sum(axis=1).max()<=policy.max_group+1e-10
    assert w[list(engine.TECH_CLUSTER)].sum(axis=1).max()<=policy.max_cluster+1e-10
    scheduled = t.loc[t.reason.eq("scheduled"),list(SYMBOLS)]
    assert (scheduled*.15).max().max()<=policy.risk_per_stock+1e-10
    assert (scheduled.sum(axis=1)*.15<=policy.risk_total+1e-10).all()
    return checked


def store(name,result):
    folder = OUT/"backtests";folder.mkdir(exist_ok=True)
    for key in ("daily","trades","positions","targets","events"):
        result[key].to_csv(folder/f"{name}_{key}.csv",index=key in ("daily","positions"),date_format="%Y-%m-%d")
    train.save(folder/f"{name}_metrics.json",result["metrics"])


def main():
    register()
    if (OUT/"completion.json").exists():
        print("v7 complete, preserving outputs; no orders or new data.")
        return
    bars,_,spy = v6.load_data()
    scores = pd.read_csv(train.OUT/"all_scores.csv",parse_dates=["Date"],float_precision="round_trip")
    periods = pd.read_csv(train.PRIOR/"backtests/ridge_h60_price_vol15_cost10_periods.csv",parse_dates=["observation_date","exit_date"])
    obs,final = pd.DatetimeIndex(periods.observation_date),periods.exit_date.iloc[-1]
    dates = pd.DatetimeIndex(scores.Date.unique()).sort_values()
    rows,equity,checks,cache = [],{},{},{}
    for cost in (10,20):
        for case in CASES:
            name = f"{case['id']}_cost{cost}"
            values = (pd.DataFrame(0.,index=dates,columns=SYMBOLS) if case["score"] is None else
                      scores.pivot(index="Date",columns="symbol",values=case["score"]).reindex(columns=SYMBOLS))
            result = engine.simulate(values,bars,spy,rf.SECTOR_PROXY,obs,final,cost_bps=cost,
                                     **{k:v for k,v in case.items() if k not in ("id","score")})
            checks[name] = audit(result,bars)
            store(name,result)
            equity[name] = result["daily"].equity
            rows.append(dict(candidate=name,**result["metrics"]))
            cache[name] = result
            pd.DataFrame(rows).to_csv(OUT/"comparison.csv",index=False)
            print(f"{name}: CAGR {result['metrics']['cagr']:.2%}, DD {result['metrics']['max_drawdown']:.2%}, stops {result['metrics']['stop_exits']}",flush=True)
    pd.DataFrame(equity).to_csv(OUT/"equity.csv",date_format="%Y-%m-%d")
    _annual_returns(pd.DataFrame(equity)).to_csv(OUT/"annual_returns.csv")
    values = scores.pivot(index="Date",columns="symbol",values="ridge_h60_price").reindex(columns=SYMBOLS)
    diagnostic = v6engine.simulate(values,bars,spy,rf.SECTOR_PROXY,obs,final,stops=False,breaker=False)
    checks["v6_policy_h60_only"] = v6.audit(diagnostic,bars,"risk")
    store("v6_policy_h60_only",diagnostic)
    train.save(OUT/"score_ablation.json",dict(h60_v6_allocation=diagnostic["metrics"],
               ensemble_v6_allocation=json.loads((train.OUT/"backtests/ensemble_allocation_cost10_metrics.json").read_text(encoding="utf-8"))))
    stress_rows = []
    stresses = [dict(id="cost30_stop50",cost_bps=30,stop_extra_bps=50),
                dict(id="delayed_next_open_cost20_stop50",cost_bps=20,stop_extra_bps=50,delayed_stops=True),
                dict(id="exclude_NVDA_no_retrain",excluded=("NVDA",))]
    for stress in stresses:
        result = engine.simulate(values,bars,spy,rf.SECTOR_PROXY,obs,final,**{k:v for k,v in stress.items() if k!="id"})
        checks[stress["id"]] = audit(result,bars)
        store(stress["id"],result)
        stress_rows.append(dict(candidate=stress["id"],**result["metrics"]))
        print(f"Stress {stress['id']}: CAGR {result['metrics']['cagr']:.2%}, DD {result['metrics']['max_drawdown']:.2%}",flush=True)
    calendar = bars["Open"].index
    positions = calendar.get_indexer(obs)
    for phase in range(5):
        if phase==0:
            result = cache["h60_full_cost10"]
        else:
            phase_obs = calendar[positions+phase]
            phase_obs = phase_obs[phase_obs.isin(values.index) & (phase_obs<final)]
            result = engine.simulate(values,bars,spy,rf.SECTOR_PROXY,phase_obs,final)
            checks[f"phase_{phase}"] = audit(result,bars)
            store(f"phase_{phase}",result)
        stress_rows.append(dict(candidate=f"phase_{phase}",**result["metrics"]))
        print(f"Phase {phase}: CAGR {result['metrics']['cagr']:.2%}, DD {result['metrics']['max_drawdown']:.2%}",flush=True)
    pd.DataFrame(stress_rows).to_csv(OUT/"stress_comparison.csv",index=False)
    table = pd.DataFrame(rows).set_index("candidate")
    prior = pd.read_csv(train.OUT/"comparison.csv",index_col="candidate")
    chosen,old = table.loc["h60_full_cost10"],prior.loc["incumbent_cost10"]
    gates = dict(cagr_at_least_80pct_incumbent=bool(chosen.cagr>=.8*old.cagr),
                 beats_full_spy=bool(chosen.cagr>prior.loc["spy_full_cost10","cagr"]),
                 beats_both_non_ml_risk_controls=bool(chosen.cagr>max(table.loc["momentum_full_cost10","cagr"],table.loc["equal_risk_full_cost10","cagr"])),
                 close_drawdown_better_than_20pct=bool(chosen.max_drawdown>=-.20),
                 close_drawdown_improves_25pct=bool(abs(chosen.max_drawdown)<=.75*abs(old.max_drawdown)),
                 cost20_beats_both_non_ml_risk_controls=bool(table.loc["h60_full_cost20","cagr"]>max(table.loc["momentum_full_cost20","cagr"],table.loc["equal_risk_full_cost20","cagr"])))
    gates["all_passed"] = all(gates.values())
    train.save(OUT/"diagnostic_gates.json",gates)
    train.save(OUT/"RUN_CHECKS.json",checks)
    train.save(OUT/"completion.json",dict(completed_at_utc=datetime.now(timezone.utc).isoformat(),new_fits=0,
               main_backtests=10,score_ablation_backtests=1,additional_stress_backtests=7,
               diagnostic_all_passed=gates["all_passed"],prices_2026_accessed=False,orders_sent=0,
               adaptive_research_only=True))


if __name__=="__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
