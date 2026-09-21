"""Read-only byte verification of the completed v11 experiment; never train or trade.

The generation commit describes when v11 was produced. A later documentation or
upload commit is allowed, while the recorded generation sources and data must
still match. The uploaded v11 commit anchors the old manifests themselves.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys


ARCHIVE_COMMIT = "8b70778217cc2e0405cd20b68e4a3ba9f51b6cd9"
EXPERIMENT = Path("data/experiments/h60_signal_objectives_v11")
NEW_REPORT_DIRECTORY = Path("data/experiments/h60_training_cutoff_v12")


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def git(root: Path, *arguments: str) -> bytes:
    process = subprocess.run(["git", "-C", str(root), *arguments],
                             capture_output=True, check=False)
    if process.returncode:
        raise ValueError(f"git {' '.join(arguments)} failed: "
                         f"{process.stderr.decode('utf-8', errors='replace').strip()}")
    return process.stdout


def verify_v11(root: Path, archive_commit: str = ARCHIVE_COMMIT) -> dict:
    """Read manifests and hash files without importing training code or models."""
    root = root.resolve()
    verified: dict[str, dict] = {}
    failures: list[dict] = []
    category_counts: dict[str, int] = {}

    def resolve(relative: str | Path) -> Path:
        path = (root / relative).resolve()
        if not path.is_relative_to(root):
            raise ValueError(f"Artifact path escapes project: {relative}")
        return path

    def read_json(relative: str | Path) -> dict:
        return json.loads(resolve(relative).read_text(encoding="utf-8"))

    def check(relative: str | Path, expected: str, category: str,
              size: int | str | None = None) -> None:
        path = resolve(relative)
        name = path.relative_to(root).as_posix()
        category_counts[category] = category_counts.get(category, 0) + 1
        if name not in verified:
            verified[name] = {
                "path": name,
                "size_bytes": path.stat().st_size if path.is_file() else None,
                "sha256": sha256(path) if path.is_file() else None,
                "categories": [],
            }
        actual = verified[name]
        if category not in actual["categories"]:
            actual["categories"].append(category)
        if actual["sha256"] != expected or (size is not None and actual["size_bytes"] != int(size)):
            failures.append({"path": name, "category": category,
                             "expected_sha256": expected, "actual_sha256": actual["sha256"],
                             "expected_size_bytes": int(size) if size is not None else None,
                             "actual_size_bytes": actual["size_bytes"]})

    def check_record(record: dict, category: str) -> None:
        check(record["path"], record["sha256"], category, record.get("size_bytes"))

    # These were committed at upload. Hash anchors cannot silently be replaced
    # with current values and then presented as original generation evidence.
    anchor_names = ["plan.json", "TRAINING_IDENTITY.json", "TRAINING_COMPLETE.json",
                    "INPUT_IDENTITY.json", "EVALUATION_IDENTITY.json",
                    "evaluation_complete.json", "SOURCE_SNAPSHOT.json", "ARTIFACTS.csv"]
    anchors = [EXPERIMENT / name for name in anchor_names]
    for relative in anchors:
        archived_bytes = git(root, "show", f"{archive_commit}:{relative.as_posix()}")
        check(relative, hashlib.sha256(archived_bytes).hexdigest(), "archive_identity", len(archived_bytes))
    if failures:
        raise ValueError("Original v11 identity/manifest differs from the uploaded archive: "
                         + ", ".join(row["path"] for row in failures))

    training = read_json(EXPERIMENT / "TRAINING_IDENTITY.json")
    training_complete = read_json(EXPERIMENT / "TRAINING_COMPLETE.json")
    evaluation = read_json(EXPERIMENT / "EVALUATION_IDENTITY.json")
    evaluation_complete = read_json(EXPERIMENT / "evaluation_complete.json")
    inputs = read_json(EXPERIMENT / "INPUT_IDENTITY.json")
    plan = read_json(EXPERIMENT / "plan.json")
    snapshots = read_json(EXPERIMENT / "SOURCE_SNAPSHOT.json")

    check(EXPERIMENT / "plan.json", training["plan_sha256"], "training_plan")
    check(EXPERIMENT / "plan.json", evaluation["plan_sha256"], "evaluation_plan")
    check(EXPERIMENT / "PLAN.md", plan["design_sha256"], "registered_design")
    for path, expected in training["source_sha256"].items():
        check(path, expected, "generation_training_source")
    for record in evaluation["source_files"]:
        check_record(record, "generation_evaluation_source")
    for path, expected in snapshots["files"].items():
        check(EXPERIMENT / "source_snapshot" / path, expected, "generation_source_copy")

    if plan["input_identity"] != inputs or evaluation["input_identity"] != inputs:
        raise ValueError("Recorded plan/training/evaluation input identities disagree")
    for path, record in inputs["input_files"].items():
        check(path, record["sha256"], "frozen_input", record.get("size_bytes"))
    for record in inputs["models"]:
        check_record(record, "reused_annual_model")
    for path, expected in training_complete["outputs_sha256"].items():
        check(EXPERIMENT / path, expected, "training_output")
    for key in ("score_file", "label_file", "training_file", "training_complete", "training_identity"):
        check_record(evaluation[key], "evaluation_dependency")

    old_manifest = evaluation["old_artifacts"]["manifest"]
    check_record(old_manifest, "reused_result_manifest")
    manifest_counts = {}
    for manifest, category in [(Path(old_manifest["path"]), "v8_frozen_artifact"),
                               (EXPERIMENT / "ARTIFACTS.csv", "v11_frozen_artifact")]:
        with resolve(manifest).open(encoding="utf-8-sig", newline="") as stream:
            records = list(csv.DictReader(stream))
        if not records:
            raise ValueError(f"Empty frozen manifest: {manifest}")
        manifest_counts[category] = len(records)
        for record in records:
            check_record(record, category)
    if manifest_counts["v8_frozen_artifact"] != evaluation["old_artifacts"]["verified_files"]:
        raise ValueError("Reused v8 manifest count differs from recorded evaluation")

    evaluation_hash = evaluation_complete["evaluation_identity_sha256"]
    check(EXPERIMENT / "EVALUATION_IDENTITY.json", evaluation_hash, "evaluation_completion")
    expected_cases = [f"{signal}_{scenario}" for signal in evaluation["new_signals"]
                      for scenario in evaluation["scenarios"]]
    if len(expected_cases) != evaluation_complete["new_strategy_runs"]:
        raise ValueError("Completed evaluation case count differs from identity")
    for case in expected_cases:
        completion = read_json(EXPERIMENT / "backtests" / case / "complete.json")
        if completion["evaluation_identity_sha256"] != evaluation_hash:
            raise ValueError(f"Backtest identity mismatch: {case}")
        for record in completion["files"]:
            check_record(record, "completed_backtest_output")

    head = git(root, "rev-parse", "HEAD").decode("ascii").strip()
    verifier_path = Path(__file__).resolve()
    verifier_sha = sha256(verifier_path)
    try:
        verifier_git_sha = hashlib.sha256(git(root, "show", f"HEAD:{verifier_path.name}")).hexdigest()
    except ValueError:
        verifier_git_sha = None  # A newly added verifier has not been committed yet.
    return {
        "passed": not failures,
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "experiment": EXPERIMENT.name,
        "generation": {
            "git_head": training["git_head"],
            "archived_at_git_commit": archive_commit,
            "training_identity_sha256": sha256(resolve(EXPERIMENT / "TRAINING_IDENTITY.json")),
            "source_sha256": training["source_sha256"],
            "evaluation_source_files": evaluation["source_files"],
            "packages": training["packages"],
            "recorded_new_fits": training_complete["new_fits"],
            "recorded_reused_models": training_complete["reused_models"],
        },
        "verification": {
            "git_head": head,
            "verifier_path": verifier_path.name,
            "verifier_sha256": verifier_sha,
            "verifier_at_current_commit_sha256": verifier_git_sha,
            "verifier_matches_current_commit": verifier_sha == verifier_git_sha,
            "head_changed_since_generation": head != training["git_head"],
            "head_is_informational_not_a_generation_input": True,
            "strict_generation_source_checks": True,
            "new_fits": 0, "strategy_replays": 0, "broker_orders": 0,
            "market_data_downloads": 0, "model_deserializations": 0,
        },
        "counts": {"unique_verified_files": len(verified), "checks_by_category": category_counts,
                   "v8_manifest_files": manifest_counts["v8_frozen_artifact"],
                   "v11_manifest_files": manifest_counts["v11_frozen_artifact"],
                   "completed_new_backtests": len(expected_cases)},
        "failures": failures,
        "verified_files": sorted(verified.values(), key=lambda record: record["path"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        help="Optional new JSON report under data/experiments/h60_training_cutoff_v12; never overwrite")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    try:
        output = (root / args.output).resolve() if args.output else None
        if output and (not output.is_relative_to((root / NEW_REPORT_DIRECTORY).resolve()) or output.exists()):
            raise ValueError("--output must be a new file in the v12 experiment directory")
        report = verify_v11(root)
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("x", encoding="utf-8", newline="\n") as stream:
                json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.write("\n")
        summary = {key: value for key, value in report.items() if key != "verified_files"}
        summary["report_output"] = str(output) if output else None
        print(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False))
        return 0 if report["passed"] else 1
    except (ValueError, OSError, KeyError, json.JSONDecodeError) as error:
        print(json.dumps({"passed": False, "error": str(error)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    sys.exit(main())
