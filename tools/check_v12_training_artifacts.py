"""Independently inspect v12 saved models; never fit, download, or submit orders.

Default is read-only and prints JSON. --output may create a NEW report directly
inside the v12 directory; existing artifacts cannot be overwritten.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "data/experiments/h60_training_cutoff_v12"
PRIOR = ROOT / "data/experiments/extended_history_v5"

import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

import research_features as rf


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify():
    complete = read(OUT / "TRAINING_COMPLETE.json")
    assert complete["new_fits"] == 10 and complete["reused_models"] == 10
    artifact_checks = []
    for name, digest in complete["outputs_sha256"].items():
        actual = sha(OUT / name)
        if actual != digest:
            raise ValueError(f"Frozen output changed: {name}")
        artifact_checks.append({"path": name, "sha256": actual, "matches": True})
    identity = read(OUT / "TRAINING_IDENTITY.json")
    source_checks = []
    for name, digest in identity["source_sha256"].items():
        if sha(ROOT / name) != digest or sha(OUT / "source_snapshot" / name) != digest:
            raise ValueError(f"Frozen training source or snapshot changed: {name}")
        source_checks.append({"path": name, "sha256": digest, "current_and_snapshot_match": True})
    input_identity = read(OUT / "INPUT_IDENTITY.json")
    input_checks = []
    for name in ("panel.csv", "all_scores.csv", "training_summary.csv"):
        path = PRIOR / name
        key = path.relative_to(ROOT).as_posix()
        expected = input_identity["input_files"][key]
        if path.stat().st_size != expected["size_bytes"] or sha(path) != expected["sha256"]:
            raise ValueError(f"Original input changed: {key}")
        input_checks.append({"path": key, **expected, "matches": True})
    assert len(rf.EXTENDED_FEATURES) == 81
    panel = pd.read_csv(PRIOR / "panel.csv", usecols=["Date", "symbol", "rank_60", "exit_60", *rf.EXTENDED_FEATURES],
                        parse_dates=["Date", "exit_60"], float_precision="round_trip")
    baseline = pd.read_csv(PRIOR / "all_scores.csv", usecols=["Date", "symbol", "ridge_h60_price"],
                           parse_dates=["Date"], float_precision="round_trip").rename(columns={"ridge_h60_price": "A"})
    saved = pd.read_csv(OUT / "scores.csv", parse_dates=["Date"], float_precision="round_trip")
    pd.testing.assert_frame_equal(baseline, saved[["Date", "symbol", "A"]], check_exact=True)
    old_summary = pd.read_csv(PRIOR / "training_summary.csv").query("id == 'ridge_h60_price'").set_index("year")
    yearly_checks = []
    for year in range(2016, 2026):
        # Deliberately independent from 53.training_rows/scoring_rows.
        cutoff, old_cutoff = pd.Timestamp(year, 1, 1), pd.Timestamp(year - 1, 1, 1)
        complete_xy = panel[["rank_60", *rf.EXTENDED_FEATURES]].notna().all(axis=1)
        eligible = panel.loc[(panel.Date < cutoff) & (panel.exit_60 < cutoff) & complete_xy].sort_values(["Date", "symbol"])
        old_eligible = panel.loc[(panel.Date < old_cutoff) & (panel.exit_60 < old_cutoff) & complete_xy]
        boundary = eligible.loc[(eligible.Date < old_cutoff) & (eligible.exit_60 >= old_cutoff)]
        assert len(old_eligible) == int(old_summary.loc[year, "train_rows"])
        path = OUT / "models" / f"{year}_mature_rank60.joblib"
        record = read(path.with_suffix(".json"))
        assert sha(path) == record["model_sha256"]
        model = joblib.load(path)["model"]  # Only after frozen hash checks above.
        assert model[-1].alpha == 100 and model[-1].solver == "svd" and model[-1].fit_intercept
        assert model[0].feature_names_in_.tolist() == rf.EXTENDED_FEATURES
        assert model[0].n_samples_seen_ == len(eligible) == record["contract"]["train_rows"]
        expected_mean = eligible[rf.EXTENDED_FEATURES].mean().to_numpy()
        expected_variance = eligible[rf.EXTENDED_FEATURES].var(ddof=0).to_numpy()
        np.testing.assert_allclose(model[0].mean_, expected_mean, rtol=1e-12, atol=1e-12)
        np.testing.assert_allclose(model[0].var_, expected_variance, rtol=1e-12, atol=1e-12)
        keys = saved.loc[saved.Date.dt.year.eq(year)]
        scoring = keys.merge(panel, on=["Date", "symbol"], validate="one_to_one", sort=False)
        with threadpool_limits(limits=2):
            prediction = model.predict(scoring[rf.EXTENDED_FEATURES])
        np.testing.assert_allclose(prediction, keys.B, rtol=0, atol=1e-14)
        assert eligible.exit_60.max() < keys.Date.min()
        assert eligible.Date.min() == pd.Timestamp("2013-05-22")
        key_bytes = eligible[["Date", "symbol"]].to_csv(index=False, date_format="%Y-%m-%d").encode()
        assert hashlib.sha256(key_bytes).hexdigest() == record["contract"]["training_key_sha256"]
        yearly_checks.append({
            "year": year, "B_rows": len(eligible), "A_rows": len(old_eligible),
            "added_rows": len(eligible) - len(old_eligible), "newly_mature_boundary_rows": len(boundary),
            "last_observation": str(eligible.Date.max().date()), "last_label_exit": str(eligible.exit_60.max().date()),
            "scoring_rows": len(scoring), "model_sha256": record["model_sha256"],
            "target": "original rank_60", "feature_order_exact": True,
            "scaler_mean_max_abs_error": float(np.max(np.abs(model[0].mean_ - expected_mean))),
            "scaler_variance_max_abs_error": float(np.max(np.abs(model[0].var_ - expected_variance))),
            "scaler_check_tolerance": {"rtol": 1e-12, "atol": 1e-12},
            "prediction_max_abs_error": float(np.max(np.abs(prediction - keys.B))),
            "scaler_sample_count_exact": True, "training_key_hash_exact": True,
        })
    tail = saved[["Date", "symbol"]].merge(panel[["Date", "symbol", "rank_60"]], on=["Date", "symbol"], validate="one_to_one")
    return {
        "status": "PASS", "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "verification_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "generation_commit": read(OUT / "GENERATION_CONTEXT.json")["git_head"],
        "checker": {"path": Path(__file__).relative_to(ROOT).as_posix(), "sha256": sha(Path(__file__))},
        "scope": "Independent saved-artifact check; no fit calls and no training script invocation",
        "new_fits_during_check": 0, "market_downloads": 0, "broker_orders": 0,
        "frozen_outputs_checked": len(artifact_checks), "frozen_output_checks": artifact_checks,
        "sources_checked": len(source_checks), "source_checks": source_checks, "input_checks": input_checks,
        "prediction_keys_and_A_saved_scores_exact": len(saved),
        "retained_unmatured_prediction_rows": int(tail.rank_60.isna().sum()),
        "years": yearly_checks,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Optional NEW JSON file directly in the v12 experiment directory")
    args = parser.parse_args()
    if args.output is not None:
        output = args.output.resolve()
        if output.parent != OUT.resolve() or output.suffix.lower() != ".json" or output.exists():
            raise ValueError("Output must be a new JSON file in the v12 directory; never overwrite artifacts")
    report = verify()
    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output is not None:
        with output.open("x", encoding="utf-8") as stream:
            stream.write(text)
    print(text, end="")


if __name__ == "__main__":
    main()
