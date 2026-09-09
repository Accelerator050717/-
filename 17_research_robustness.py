"""冻结评分的调仓相位和禁止持有单股诊断：不重训、不选最佳相位。

这是已见历史上的回顾性稳定性检查，不构成独立验证，不改变选拔门槛。
必须先完成第 18 步，证明无损评分能够重现原 30 个候选的结果。
"""

import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import research_features as rf
from panel_config import ROOT, SYMBOLS, RAW_DIR
from research_backtest import run_backtest

ORIGINAL = ROOT / "data" / "experiments" / "auto_research_45m_v1"
FINAL = ORIGINAL / "final_evaluation"
OUTPUT = ORIGINAL / "robustness"
METRIC_FIELDS = ["cagr", "total_return", "max_drawdown", "total_cost", "final_equity"]


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value, exclusive=False):
    with path.open("x" if exclusive else "w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)


def metric_row(candidate, kind, phase, result, equal=None, spy=None, excluded=None):
    row = {"candidate": candidate, "kind": kind, "phase": phase, "excluded_symbol": excluded}
    row.update(result["metrics"])
    if equal is not None:
        row["cagr_advantage_vs_equal"] = row["cagr"] - equal["metrics"]["cagr"]
        if not result["daily_equity"].index.equals(equal["daily_equity"].index):
            raise AssertionError("候选与对应等权基准的实际持有区间不一致。")
        active = result["daily_equity"]["daily_return"] - equal["daily_equity"]["daily_return"]
        sigma = active.std(ddof=1)
        row["information_ratio_vs_equal"] = float(active.mean() / sigma * np.sqrt(252)) if sigma > 0 else None
    if spy is not None:
        row["cagr_advantage_vs_spy"] = row["cagr"] - spy["metrics"]["cagr"]
        if not result["daily_equity"].index.equals(spy["daily_equity"].index):
            raise AssertionError("候选与对应 SPY 基准的实际持有区间不一致。")
    return row


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    started = time.perf_counter()
    check_path = FINAL / "reproduction_checks.json"
    if not check_path.exists():
        raise FileNotFoundError("先完成 18_finalize_research.py 并生成 reproduction_checks.json，再运行本诊断。")
    reproduction = read_json(check_path)
    required_checks = {"cost_metrics.json", "stress_metrics.json", "ranking_metrics.csv", "score_csv_round_trip", "completed_at_utc"}
    if not required_checks.issubset(reproduction):
        raise ValueError("原结果重现记录不完整。")

    old_plan = read_json(ORIGINAL / "plan.json")
    extra_plan_path = ORIGINAL / "huber_scale_followup" / "plan.json"
    extra_plan = read_json(extra_plan_path)
    names = [item["id"] for item in old_plan["candidates"] + extra_plan["candidates"]]
    assert len(names) == len(set(names)) == 32
    original_names = [item["id"] for item in old_plan["candidates"]]
    comparison = pd.read_csv(ORIGINAL / "comparison.csv", float_precision="round_trip")
    chosen = str(comparison.sort_values(["information_ratio", "candidate"], ascending=[False, True]).iloc[0]["candidate"])
    if chosen != "m16_elastic_rank":
        raise ValueError("原 30 候选最高 IR 与预定诊断对象不一致，不自动更换对象。")

    score_path = FINAL / "all_development_scores.csv"
    rows = pd.read_csv(score_path, float_precision="round_trip", parse_dates=["Date"])
    old = pd.read_csv(ORIGINAL / "all_development_scores.csv", float_precision="round_trip", parse_dates=["Date"])
    pd.testing.assert_frame_equal(rows[["Date", "symbol", *original_names]], old[["Date", "symbol", *original_names]], check_exact=True)
    assert rows.Date.min().year == 2020 and rows.Date.max() < pd.Timestamp("2026-01-01")
    assert not rows.duplicated(["Date", "symbol"]).any()
    assert np.isfinite(rows[names].to_numpy()).all()
    assert rows.groupby("Date").symbol.nunique().eq(len(SYMBOLS)).all()
    dates = pd.DatetimeIndex(sorted(rows.Date.unique()))
    matrices = {name: rows.pivot(index="Date", columns="symbol", values=name).reindex(columns=SYMBOLS) for name in names}

    # 保持原评价所用价格解析口径；评分单独使用 round_trip 保留同分关系。
    raw, _ = rf.load_inputs()
    opens = pd.DataFrame({name: raw[name].Open * raw[name]["Adj Close"] / raw[name].Close for name in SYMBOLS})
    spy_open = raw["SPY"].Open * raw["SPY"]["Adj Close"] / raw["SPY"].Close
    assert opens.index.max() < pd.Timestamp("2026-01-01")
    equal_scores = pd.DataFrame(0.0, index=dates, columns=SYMBOLS)
    spy_scores = pd.DataFrame(0.0, index=dates, columns=["SPY"])
    phase_starts = [day.strftime("%Y-%m-%d") for day in dates[:5]]
    source_paths = [score_path, ORIGINAL / "all_development_scores.csv", ORIGINAL / "comparison.csv",
                    ORIGINAL / "plan.json", extra_plan_path, FINAL / "plan.json", check_path,
                    FINAL / "cost_metrics.json", Path(__file__), ROOT / "research_backtest.py"]
    source_paths += [RAW_DIR / f"{symbol}.csv" for symbol in (*SYMBOLS, "SPY")]
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in source_paths}
    plan = {
        "purpose": "Retrospective robustness diagnostics on frozen 2020-2025 scores; not independent validation or candidate selection.",
        "candidates": names, "source_sha256": hashes,
        "required_reproduction_completed_at_utc": reproduction["completed_at_utc"],
        "score_parser": "pandas float_precision=round_trip; original30 score arrays must match exactly",
        "price_parser": "unchanged rf.load_inputs default pandas parsing, matching original/final backtests",
        "phase_diagnostic": {"offset_sessions": [0, 1, 2, 3, 4], "first_observation_dates": phase_starts,
                             "selection": "Report all phases; never select the best phase.", "equal_and_spy_match_each_phase": True},
        "leave_one_out_diagnostic": {"candidate": chosen, "reason": "Highest original30 development information ratio, fixed before this diagnosis",
                                     "excluded_symbols": list(SYMBOLS), "training_universe_size": 30,
                                     "investment_universe_size": 29, "retrain": False, "recompute_features_or_scores": False,
                                     "benchmark": "matching 29-stock equal weight for each exclusion", "phase": 0},
        "trading": {"top_k": 5, "rebalance_every": 5, "entry": "next_open", "end_exclusive": "2026-01-01", "cost_bps_per_side": 10},
        "annual_active_definition": "strategy CAGR minus matched benchmark CAGR, not CAGR of a tradable long-short strategy",
        "no_gate_changes": True, "no_2026_access": True, "no_downloads_or_training": True,
    }
    OUTPUT.mkdir(exist_ok=True)
    plan_path = OUTPUT / "plan.json"
    if plan_path.exists():
        previous = read_json(plan_path)
        registered = previous.pop("registered_at_utc")
        if previous != plan:
            raise ValueError("已有诊断计划不同，不允许覆盖。")
        if (OUTPUT / "completion.json").exists():
            print("诊断已完成，计划及输入未变；复用保存结果。", flush=True)
            return
    else:
        registered = datetime.now(timezone.utc).isoformat()
        write_json(plan_path, {**plan, "registered_at_utc": registered}, exclusive=True)
    if datetime.fromisoformat(registered) < datetime.fromisoformat(reproduction["completed_at_utc"]):
        raise AssertionError("诊断注册必须晚于原结果重现完成时间。")
    print(f"固定诊断计划已注册 {registered}；32 候选 × 5 相位，不选最佳相位。", flush=True)

    final_reference = read_json(FINAL / "cost_metrics.json")
    phase_rows = []
    for phase, start in enumerate(phase_starts):
        equal = run_backtest(equal_scores, opens, spy_open, start=start, top_k=None, cost_bps=10)
        spy = run_backtest(spy_scores, spy_open.to_frame("SPY"), spy_open, start=start, top_k=None, cost_bps=10)
        phase_rows.append(metric_row("benchmark_equal", "benchmark", phase, equal, equal, spy))
        phase_rows.append(metric_row("benchmark_spy", "benchmark", phase, spy, equal, spy))
        for name in names:
            result = run_backtest(matrices[name], opens, spy_open, start=start, top_k=5, cost_bps=10)
            if phase == 0:
                for key in METRIC_FIELDS:
                    np.testing.assert_allclose(result["metrics"][key], final_reference[name][key], rtol=0, atol=1e-12)
            phase_rows.append(metric_row(name, "candidate", phase, result, equal, spy))
        if phase == 0:
            for name, value in (("benchmark_equal", equal), ("benchmark_spy", spy)):
                for key in METRIC_FIELDS:
                    np.testing.assert_allclose(value["metrics"][key], final_reference[name][key], rtol=0, atol=1e-12)
        pd.DataFrame(phase_rows).to_csv(OUTPUT / "phase_metrics.csv", index=False)
        print(f"相位 {phase}（{start}）完成，累计 {len(phase_rows)} 行；耗时 {time.perf_counter()-started:.1f}s。", flush=True)
    phase_frame = pd.DataFrame(phase_rows)
    assert len(phase_frame) == (32 + 2) * 5
    summary_rows = []
    for name in names:
        selected = phase_frame.loc[phase_frame.candidate.eq(name)]
        delta = selected.cagr_advantage_vs_equal
        summary_rows.append({
            "candidate": name, "phases": len(selected),
            "cagr_advantage_vs_equal_min": float(delta.min()),
            "cagr_advantage_vs_equal_median": float(delta.median()),
            "cagr_advantage_vs_equal_max": float(delta.max()),
            "phases_beating_equal": int(delta.gt(0).sum()),
            "phases_beating_spy": int(selected.cagr_advantage_vs_spy.gt(0).sum()),
            "max_drawdown_worst": float(selected.max_drawdown.min()),
        })
    pd.DataFrame(summary_rows).to_csv(OUTPUT / "phase_summary.csv", index=False)

    loo_rows = []
    for number, excluded in enumerate(SYMBOLS, start=1):
        allowed = [symbol for symbol in SYMBOLS if symbol != excluded]
        equal = run_backtest(equal_scores[allowed], opens[allowed], spy_open, start=phase_starts[0], top_k=None, cost_bps=10)
        result = run_backtest(matrices[chosen][allowed], opens[allowed], spy_open, start=phase_starts[0], top_k=5, cost_bps=10)
        assert not result["trades"].symbol.eq(excluded).any()
        loo_rows.append(metric_row("benchmark_equal29", "benchmark", 0, equal, equal, excluded=excluded))
        loo_rows.append(metric_row(chosen, "candidate", 0, result, equal, excluded=excluded))
        if number % 5 == 0:
            pd.DataFrame(loo_rows).to_csv(OUTPUT / "leave_one_out_metrics.csv", index=False)
            print(f"禁止单股持有诊断完成 {number}/30（无重训）；耗时 {time.perf_counter()-started:.1f}s。", flush=True)
    assert len(loo_rows) == 60
    for path in source_paths:
        if digest(path) != hashes[str(path.relative_to(ROOT))]:
            raise AssertionError(f"运行期间源文件改变: {path}")
    output_files = [OUTPUT / name for name in ("phase_metrics.csv", "phase_summary.csv", "leave_one_out_metrics.csv")]
    write_json(OUTPUT / "completion.json", {
        "completed_at_utc": datetime.now(timezone.utc).isoformat(), "seconds": time.perf_counter()-started,
        "phase_metric_rows": len(phase_rows), "phase_summary_rows": len(summary_rows), "leave_one_out_metric_rows": len(loo_rows),
        "phase0_reproduces_final32_and_benchmarks_atol": 1e-12,
        "original_sources_unchanged": True,
        "output_sha256": {path.name: digest(path) for path in output_files},
        "interpretation": "All retrospective diagnostics; no best-phase selection, no retraining, no gate update, no independent holdout consumed.",
    })
    print(f"全部诊断完成：{OUTPUT}", flush=True)


if __name__ == "__main__":
    main()
