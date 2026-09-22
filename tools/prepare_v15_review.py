"""Inventory only explicitly scoped v15 review materials; never stage or upload."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "data/experiments/dynamic_universe_pilot_v15"
DEST = ROOT / "review_upload/sync_v15_20260922"
MANIFEST = DEST / "files.json"
BASE = "a3f9a5f221bb36258e7453a6e2b0b3a1f476dfbe"


def current_head():
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def collect():
    paths = set((ROOT / "tools").glob("qc_v15*"))
    paths.update((ROOT / "tests").glob("test_qc_v15*"))
    paths.update(EXP.rglob("*"))
    paths.update(ROOT / path for path in (
        "tools/prepare_qc_v15_source.py", "tools/verify_qc_v15_pilot.py",
        "tools/summarize_qc_v15_pilot.py", "tools/prepare_v15_review.py",
        "REVIEW_INDEX.md", "review_upload/sync_v15_20260922/README.md"))
    entries = []
    for path in sorted((p for p in paths if p.is_file()), key=lambda p: p.as_posix()):
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        content = path.read_bytes()
        entries.append({"path": path.relative_to(ROOT).as_posix(), "absolute_path": str(path.resolve()),
                        "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()})
    return entries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--preview", action="store_true", help="Read paths and hashes; write nothing")
    mode.add_argument("--verify", action="store_true", help="Read-only comparison with final manifest")
    args = parser.parse_args()
    entries = collect()
    runs = json.loads((EXP / "RUN_IDENTITIES.json").read_text(encoding="utf-8"))
    if len(runs["runs"]) != 6 or runs["generation_base_commit"] != BASE:
        raise ValueError("Expected the six actual fixed run identities")
    cloud_runs = [{"file": r["file"], "backtest_id": r["backtest_id"], "name": r["name"],
                   "engine_version": r["engine_version"]} for r in runs["runs"]]
    large = [r["path"] for r in entries if r["bytes"] >= 10 * 1024 * 1024]
    archives = [r["path"] for r in entries if Path(r["path"]).suffix.lower() == ".zip"]
    details = {"generation_base_commit": BASE, "project_id": 36834914,
               "files": entries, "file_count": len(entries), "total_bytes": sum(r["bytes"] for r in entries),
               "large_file_threshold_bytes": 10 * 1024 * 1024, "new_large_materials": large,
               "new_review_zips": archives, "cloud_runs": cloud_runs,
               "cloud_only": {"project_url": "https://www.quantconnect.com/project/36834914",
                              "native_code_order_fill_log_results": "retained by native cloud backtest",
                              "provider_source_records": "not exported; no original snapshot backup claimed",
                              "full_auxiliary_in_memory_event_tables": "not a permanent backup",
                              "object_store_written": False}}
    if args.verify:
        recorded = json.loads(MANIFEST.read_text(encoding="utf-8"))
        if any(recorded.get(key) != value for key, value in details.items()):
            raise ValueError("Scoped v15 materials changed; regenerate final manifest after edits finish")
    elif not args.preview:
        DEST.mkdir(parents=True, exist_ok=True)
        MANIFEST.write_text(json.dumps({**details, "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                                      "head_at_generation": current_head()}, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8")
    print(json.dumps({"action": "preview_only" if args.preview else "verified" if args.verify else "generated",
                      "file_count": len(entries), "total_bytes": details["total_bytes"],
                      "new_large_materials": len(large), "new_review_zips": len(archives),
                      "main_cloud_runs": len(cloud_runs), "current_verification_head": current_head(),
                      "manifest_written": not args.verify and not args.preview}, ensure_ascii=False))


if __name__ == "__main__":
    main()
