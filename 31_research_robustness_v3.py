"""固定附加诊断：不改主门槛、不增添冠军候选、不读取留出期。"""
import importlib
import json
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

import research_horizons as rh
from panel_config import SYMBOLS
from research_backtest import run_backtest
from research_evaluation import _returns_from_initial_cash, _simultaneous_lower_bounds

runner = importlib.import_module("28_train_multihorizon")
OUTPUT = runner.OUTPUT / "robustness"


def register():
    OUTPUT.mkdir(exist_ok=True)
    plan = {"selection": "After all48 primary rows exist, highest information_ratio then candidate id among new48; plus fixed v3_elastic_h5_price_top5 old control.",
            "diagnostics_only": True, "main_gates_unchanged": True,
            "phases": [0,1,2,3,4], "fees_bps": [10,30],
            "exclude_tradable_symbol": "NVDA", "exclude_is_not_retraining": True,
            "matched_benchmark": "same schedule and tradable universe equal weight",
            "bootstrap_blocks": [5,20,60], "bootstrap_repetitions":2000, "seed":20260907,
            "contribution": "Dollar P&L relative initial NAV from actual period holdings and adjusted-open returns; subtract per-symbol trade fees; no counterfactual refit claim."}
    path = OUTPUT / "plan.json"
    if path.exists():
        previous = json.loads(path.read_text(encoding="utf-8"))
        previous.pop("registered_at_utc")
        assert previous == plan
    else:
        runner.save_json(path, {**plan,"registered_at_utc":datetime.now(timezone.utc).isoformat()})


def main():
    register()
    if "--register-only" in sys.argv:
        print("Diagnostic rules registered; no model results read.")
        return
    comparison = pd.read_csv(runner.OUTPUT/"comparison_new48.csv", float_precision="round_trip")
    best = comparison.sort_values(["information_ratio","candidate"],ascending=[False,True]).iloc[0].candidate
    names = list(dict.fromkeys([best,"v3_elastic_h5_price_top5"]))
    scores = pd.read_csv(runner.OUTPUT/"all_model_scores.csv", parse_dates=["Date"], float_precision="round_trip")
    opens, spy = rh.adjusted_opens()
    rows, contributions = [], []
    for candidate in names:
        info = comparison.set_index("candidate").loc[candidate]
        values = scores.pivot(index="Date",columns="symbol",values=info.model).reindex(columns=SYMBOLS)
        for phase in range(5):
            start = str(values.index[phase].date())
            result = run_backtest(values,opens,spy,start=start,top_k=int(info.top_k),cost_bps=10)
            equal = run_backtest(values*0,opens,spy,start=start,top_k=None,cost_bps=10)
            assert result["daily_equity"].index.equals(equal["daily_equity"].index)
            rows.append({"candidate":candidate,"diagnostic":"phase","value":phase,
                         **result["metrics"],"matched_equal_cagr":equal["metrics"]["cagr"]})
        for cost, exclude in ((30,False),(10,True)):
            symbols = [s for s in SYMBOLS if not exclude or s!="NVDA"]
            result = run_backtest(values[symbols],opens[symbols],spy,top_k=int(info.top_k),cost_bps=cost)
            equal = run_backtest(values[symbols]*0,opens[symbols],spy,top_k=None,cost_bps=cost)
            rows.append({"candidate":candidate,"diagnostic":"exclude_tradable_NVDA" if exclude else "cost_bps",
                         "value":0 if exclude else cost,**result["metrics"],"matched_equal_cagr":equal["metrics"]["cagr"]})
        periods = pd.read_csv(runner.OUTPUT/f"backtests/{candidate}_periods.csv",float_precision="round_trip",parse_dates=["entry_date","exit_date"])
        trades = pd.read_csv(runner.OUTPUT/f"backtests/{candidate}_trades.csv",float_precision="round_trip")
        pnl = {s:0.0 for s in SYMBOLS}
        exposure = {s:0 for s in SYMBOLS}
        for period in periods.itertuples():
            holdings = period.holdings.split("|")
            allocation = period.invested_equity/len(holdings)
            for s in holdings:
                pnl[s] += allocation*(opens.loc[period.exit_date,s]/opens.loc[period.entry_date,s]-1)
                exposure[s] += 1
        costs = trades.groupby("symbol").cost.sum()
        for s in SYMBOLS:
            contributions.append({"candidate":candidate,"symbol":s,"gross_pnl_per_initial_NAV":pnl[s],
                                  "allocated_fees":float(costs.get(s,0)),"net_pnl_per_initial_NAV":pnl[s]-costs.get(s,0),
                                  "held_periods":exposure[s],"total_periods":len(periods)})
        expected = float(info.total_return)
        np.testing.assert_allclose(sum(pnl.values())-trades.cost.sum(),expected,rtol=0,atol=1e-11)
    pd.DataFrame(rows).to_csv(OUTPUT/"schedule_cost_exclusion.csv",index=False)
    pd.DataFrame(contributions).to_csv(OUTPUT/"stock_contributions.csv",index=False)
    equity = pd.read_csv(runner.OUTPUT/"equity_all92.csv",index_col="Date",parse_dates=["Date"],float_precision="round_trip")
    returns = _returns_from_initial_cash(equity)
    candidates = sorted(set(equity.columns)-{"benchmark_equal","benchmark_spy"})
    active = returns[candidates].sub(returns.benchmark_equal,axis=0)
    bootstrap = []
    for length in (5,20,60):
        result = _simultaneous_lower_bounds(active.to_numpy(),block_length=length)
        for i,name in enumerate(candidates):
            bootstrap.append({"candidate":name,"block_sessions":length,"critical_max_t":result["critical_max_t"],
                              "simultaneous_lower_daily":result["lower"][i],"positive":bool(result["lower"][i]>0),
                              "primary_selection_block":length==20})
    pd.DataFrame(bootstrap).to_csv(OUTPUT/"block_sensitivity.csv",index=False)
    runner.save_json(OUTPUT/"completion.json",{"diagnostic_candidates":names,"main_selection_changed":False,
                                             "2026_market_data_read":False,"completed_at_utc":datetime.now(timezone.utc).isoformat()})
    print(pd.DataFrame(rows)[["candidate","diagnostic","value","cagr","max_drawdown","matched_equal_cagr"]].to_string(index=False))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
