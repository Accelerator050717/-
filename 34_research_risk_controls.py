"""条件研究：若第三批无准入者，固定6个仓位规则对照，禁止择优改阈值。"""
import importlib
import json
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

import research_features as rf
import research_horizons as rh
from research_backtest import run_backtest
from research_evaluation import evaluate_candidates, _returns_from_initial_cash
from panel_config import ROOT, SYMBOLS

runner = importlib.import_module("28_train_multihorizon")
OUT = ROOT / "data/experiments/risk_controls_v4"
POLICIES = ("vol15", "trend25", "combined")


def register():
    OUT.mkdir(parents=True,exist_ok=True)
    plan = {"conditional_start":"Only if v3 all92 has zero gate passes; otherwise skip and honor v3 unique frozen holdout protocol.",
            "sources":"Fixed old control v3_elastic_h5_price_top5; plus highest-IR new48 entry from a model whose control_name is None, candidate name ascending tie break.",
            "policies":{
                "vol15":"min(1, 0.15 / (SPY trailing20 daily adjusted-close return sample std * sqrt252))",
                "trend25":"1 if SPY current adjusted close >= trailing200 session mean else 0.25",
                "combined":"vol15 * trend25"},
            "decision":"Use information at observation close; target gross exposure next open, only on original5-session rebalance grid. No intraday stop-loss.",
            "cash":"Zero interest, no borrowing; target weights gross/topK. Exposure can drift between rebalances.",
            "comparison":"Same stock scores/topK, cost10/20. Compare original fully-invested EW/SPY and separate EW under identical risk rule.",
            "selection":"Old92 plus new6 jointly use unchanged full-EW gates and max-t20-session bootstrap. Matched-risk EW is attribution diagnostic, not an easier replacement selection benchmark.",
            "risk_rules_are_not_new_model_fits":True,
            "limits":"Follow-up development experiment; thresholds not searched. Risk reduction is not proof of increased prediction skill.",
            "holdout":"If new all98 gate passes, one uniquely selected model+policy+topK may be frozen with unchanged v3 holdout dates and final-training recipe. No 2026 quote before complete manifest."}
    path = OUT/"plan.json"
    if path.exists():
        previous = json.loads(path.read_text(encoding="utf-8"))
        previous.pop("registered_at_utc")
        assert previous == plan
    else:
        runner.save_json(path,{**plan,"registered_at_utc":datetime.now(timezone.utc).isoformat()})


def exposure_rules(close):
    daily_std = close.pct_change(fill_method=None).rolling(20).std(ddof=1)
    vol15 = (0.15/(daily_std*np.sqrt(252))).clip(upper=1)
    mean = close.rolling(200).mean()
    trend25 = pd.Series(np.where(close>=mean,1.0,0.25),index=close.index).where(mean.notna())
    return pd.DataFrame({"vol15":vol15,"trend25":trend25,"combined":vol15*trend25})


def main():
    register()
    if "--register-only" in sys.argv:
        print("Conditional six-policy comparisons registered before main results.")
        return
    completion = json.loads((runner.OUTPUT/"completion.json").read_text(encoding="utf-8"))
    if completion["gate_passes"]:
        runner.save_json(OUT/"skipped.json",{"reason":"v3 gate passed; retain its unique frozen validation protocol, no further selection."})
        print("Skipped: a v3 candidate already passed.")
        return
    if (OUT/"completion.json").exists():
        print("Risk comparison already complete; not overwritten.")
        return
    comparison = pd.read_csv(runner.OUTPUT/"comparison_new48.csv",float_precision="round_trip")
    novel_models = [m["id"] for m in runner.MODELS if runner.control_name(m) is None]
    novel = comparison.loc[comparison.model.isin(novel_models)].sort_values(["information_ratio","candidate"],ascending=[False,True]).iloc[0].candidate
    source_names = ["v3_elastic_h5_price_top5",novel]
    source_rows = comparison.set_index("candidate").loc[source_names]
    scores = pd.read_csv(runner.OUTPUT/"all_model_scores.csv",parse_dates=["Date"],float_precision="round_trip")
    equity = pd.read_csv(runner.OUTPUT/"equity_all92.csv",index_col="Date",parse_dates=["Date"],float_precision="round_trip")
    ranking = pd.read_csv(runner.OUTPUT/"ranking_all92.csv",float_precision="round_trip")
    costs = json.loads((runner.OUTPUT/"cost_metrics_all92.json").read_text(encoding="utf-8"))
    stress = json.loads((runner.OUTPUT/"stress_metrics_all92.json").read_text(encoding="utf-8"))
    opens,spy = rh.adjusted_opens()
    raw,_ = rf.load_inputs()
    policies = exposure_rules(raw["SPY"]["Adj Close"])
    cutoff = pd.Timestamp("2024-06-28")
    prefix = exposure_rules(raw["SPY"].loc[:cutoff,"Adj Close"])
    pd.testing.assert_frame_equal(policies.loc[:cutoff],prefix,check_exact=True)
    dates = pd.DatetimeIndex(scores.Date.unique()).sort_values()
    policies = policies.reindex(dates)
    assert np.isfinite(policies).all().all() and policies.ge(0).all().all() and policies.le(1).all().all()
    policies.to_csv(OUT/"observation_exposures.csv",date_format="%Y-%m-%d")
    meta,ranks = [],[]
    folder = OUT/"backtests"
    folder.mkdir(exist_ok=True)
    matched = {}
    for policy in POLICIES:
        for cost in (10,20):
            result = run_backtest(pd.DataFrame(0.0,index=dates,columns=SYMBOLS),opens,spy,
                                  top_k=None,cost_bps=cost,gross_exposure=policies[policy])
            matched[(policy,cost)] = result
            result["daily_equity"].to_csv(folder/f"matched_equal_{policy}_cost{cost}.csv",date_format="%Y-%m-%d")
    for source,row in source_rows.iterrows():
        values = scores.pivot(index="Date",columns="symbol",values=row.model).reindex(columns=SYMBOLS)
        # 使用新可选参数后的原满仓路径必须精确重现保存结果。
        control = run_backtest(values,opens,spy,top_k=int(row.top_k),cost_bps=10,gross_exposure=pd.Series(1.0,index=dates))
        np.testing.assert_array_equal(control["daily_equity"].equity,equity[source])
        for policy in POLICIES:
            name = f"v4_{source.removeprefix('v3_')}_{policy}"
            result = run_backtest(values,opens,spy,top_k=int(row.top_k),cost_bps=10,gross_exposure=policies[policy])
            stressed = run_backtest(values,opens,spy,top_k=int(row.top_k),cost_bps=20,gross_exposure=policies[policy])
            assert result["daily_equity"].index.equals(equity.index)
            costs[name],stress[name] = result["metrics"],stressed["metrics"]
            equity[name] = result["daily_equity"].equity
            rank = ranking.set_index("candidate").loc[source].to_dict()
            ranks.append({"candidate":name,**rank})
            risk_benchmark = matched[(policy,10)]
            daily = pd.DataFrame({"model":result["daily_equity"].equity,"matched":risk_benchmark["daily_equity"].equity})
            ret = _returns_from_initial_cash(daily)
            active = ret.model-ret.matched
            ir = float(np.sqrt(252)*active.mean()/active.std(ddof=1))
            mean_gross = float((result["daily_equity"].invested/result["daily_equity"].equity).mean())
            meta.append({"candidate":name,"source_candidate":source,"model":row.model,"horizon":int(row.horizon),
                         "top_k":int(row.top_k),"policy":policy,"realized_average_gross":mean_gross,
                         "unmanaged_cagr":float(row.cagr),"unmanaged_drawdown":float(row.max_drawdown),
                         "matched_risk_equal_cagr":risk_benchmark["metrics"]["cagr"],
                         "matched_risk_equal_drawdown":risk_benchmark["metrics"]["max_drawdown"],
                         "IR_vs_matched_risk_equal":ir})
            for key in ("daily_equity","periods","trades"):
                result[key].to_csv(folder/f"{name}_{key}.csv",index=key=="daily_equity",date_format="%Y-%m-%d")
            runner.save_json(folder/f"{name}_metrics.json",{"cost10":result["metrics"],"cost20":stressed["metrics"]})
            print(f"{name}: CAGR={result['metrics']['cagr']:.2%}, DD={result['metrics']['max_drawdown']:.2%}, matchedEW={risk_benchmark['metrics']['cagr']:.2%}",flush=True)
    all_ranks = pd.concat([ranking,pd.DataFrame(ranks)],ignore_index=True)
    all_comparison,bootstrap = evaluate_candidates(equity,all_ranks,stress,costs)
    assert len(all_comparison)==98 and bootstrap["family_size"]==98
    new = all_comparison.merge(pd.DataFrame(meta),on="candidate",validate="one_to_one")
    new.to_csv(OUT/"comparison_new6.csv",index=False)
    all_comparison.to_csv(OUT/"comparison_all98.csv",index=False)
    all_ranks.to_csv(OUT/"ranking_all98.csv",index=False)
    equity.to_csv(OUT/"equity_all98.csv",date_format="%Y-%m-%d")
    runner.save_json(OUT/"bootstrap_all98.json",bootstrap)
    runner.save_json(OUT/"cost_metrics_all98.json",costs)
    runner.save_json(OUT/"stress_metrics_all98.json",stress)
    runner.save_json(OUT/"completion.json",{"completed_at_utc":datetime.now(timezone.utc).isoformat(),
                    "model_refits":0,"risk_strategy_entries":6,"joint_entries":98,"source_candidates":source_names,
                    "gate_passes":int(all_comparison.gate_all.sum()),"selected_candidate":bootstrap["selected_candidate"],
                    "prefix_exposure_check":True,"full_exposure_control_checks":2,"2026_market_prices_accessed":False,"orders_sent":0})
    print(new[["candidate","cagr","max_drawdown","mean_rank_ic","gate_all"]].to_string(index=False))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
