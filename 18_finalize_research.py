"""无损重读冻结评分，合并两个 Huber 补充实验；不重训、不访问新行情。"""

import hashlib
import importlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

batch = importlib.import_module("15_run_research_batch")
supplement = importlib.import_module("16_huber_scale_followup")
ORIGINAL = batch.OUTPUT
EXTRA = ORIGINAL / "huber_scale_followup"
OUTPUT = ORIGINAL / "final_evaluation"


def main():
    OUTPUT.mkdir(exist_ok=True)
    plan = {
        "purpose": "Correct CSV floating-point round-trip, preserving the original trained models and scores. No training or strategy changes.",
        "reason": "Default CSV parsing changed some scores by about 1e-16, altering near-tied rank-combination selections in the supplemental evaluation.",
        "inputs": {str(path.relative_to(ORIGINAL)): hashlib.sha256(path.read_bytes()).hexdigest()
                   for path in [ORIGINAL / "all_development_scores.csv", EXTRA / "extra_scores.csv"]},
        "csv_float_precision": "round_trip",
        "candidate_count": 32,
        "gate": "Unchanged original gate and joint bootstrap across all 32 candidates.",
        "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    plan_path = OUTPUT / "plan.json"
    if plan_path.exists():
        old = json.loads(plan_path.read_text(encoding="utf-8"))
        old.pop("registered_at_utc")
        assert old == plan, "Plan changed: preserve prior output and use a new directory."
    else:
        batch.save_json(plan_path, {**plan, "registered_at_utc": datetime.now(timezone.utc).isoformat()})

    original = pd.read_csv(ORIGINAL / "all_development_scores.csv", float_precision="round_trip",
                           parse_dates=["Date", "entry_date", "exit_date"])
    extra = pd.read_csv(EXTRA / "extra_scores.csv", float_precision="round_trip", parse_dates=["Date"])
    combined = original.merge(extra, on=["Date", "symbol"], validate="one_to_one", how="left")
    original_names = [item["id"] for item in batch.CANDIDATES]
    np.testing.assert_array_equal(combined[original_names].to_numpy(), original[original_names].to_numpy())
    assert combined[[item["id"] for item in supplement.EXTRAS]].notna().all().all()
    combined.to_csv(OUTPUT / "all_development_scores.csv", index=False, date_format="%Y-%m-%d")
    saved = pd.read_csv(OUTPUT / "all_development_scores.csv", float_precision="round_trip")
    all_names = original_names + [item["id"] for item in supplement.EXTRAS]
    np.testing.assert_array_equal(saved[all_names].to_numpy(), combined[all_names].to_numpy())
    batch.OUTPUT = OUTPUT
    batch.CANDIDATES = batch.CANDIDATES + supplement.EXTRAS
    batch.evaluate_batch(combined)

    checks = {}
    for filename in ["cost_metrics.json", "stress_metrics.json"]:
        old = json.loads((ORIGINAL / filename).read_text(encoding="utf-8"))
        new = json.loads((OUTPUT / filename).read_text(encoding="utf-8"))
        for name in original_names + ["benchmark_equal", "benchmark_spy"]:
            for field in ["cagr", "total_return", "max_drawdown", "total_cost", "final_equity"]:
                np.testing.assert_allclose(new[name][field], old[name][field], rtol=0, atol=1e-12)
        checks[filename] = "All original 30 candidates and two benchmarks reproduce within absolute 1e-12."
    old_ranking = pd.read_csv(ORIGINAL / "ranking_metrics.csv", float_precision="round_trip").set_index("candidate")
    new_ranking = pd.read_csv(OUTPUT / "ranking_metrics.csv", float_precision="round_trip").set_index("candidate")
    np.testing.assert_allclose(new_ranking.loc[original_names].to_numpy(), old_ranking.loc[original_names].to_numpy(), rtol=0, atol=1e-12)
    checks["ranking_metrics.csv"] = "All original ranking metrics reproduce within absolute 1e-12."
    checks["score_csv_round_trip"] = "All 32 saved score arrays round-trip exactly."
    checks["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
    batch.save_json(OUTPUT / "reproduction_checks.json", checks)
    print("冻结评分与原30结果重现检查全部通过；final_evaluation 是最终32联合评价。", flush=True)


if __name__ == "__main__":
    __import__("sys").stdout.reconfigure(encoding="utf-8")
    main()
