"""Create or verify the v16 review inventory without touching older materials."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "data/experiments/momentum_loss_attribution_v16"
DEST = ROOT / "review_upload/sync_v16_20260922"


def collect():
    paths = set(EXP.rglob("*"))
    paths.update((ROOT / "tools").glob("*v16*.py"))
    paths.update((ROOT / "tests").glob("*v16*.py"))
    paths.update((ROOT / "REVIEW_INDEX.md", DEST / "README.md"))
    result = []
    for path in sorted(paths):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        content = path.read_bytes()
        result.append({"path": path.relative_to(ROOT).as_posix(),
                       "absolute_path": str(path.resolve()), "bytes": len(content),
                       "sha256": hashlib.sha256(content).hexdigest()})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    entries = collect()
    payload = {"baseline_commit": "138d2bf8ddf81f484c95c5e8cffa3dbab66fb07b",
               "files": entries, "total_bytes": sum(x["bytes"] for x in entries),
               "large_files": [x for x in entries if x["bytes"] >= 10 * 1024 * 1024],
               "original_cloud_project": 36834914, "diagnostic_cloud_project": 36839440,
               "provider_raw_data": "Cloud only; no data export or local backup claimed",
               "new_models": 0, "new_review_zips": []}
    manifest = DEST / "files.json"
    if args.verify:
        recorded = json.loads(manifest.read_text(encoding="utf-8"))
        if any(recorded.get(k) != v for k, v in payload.items()):
            raise ValueError("v16 review materials changed after inventory")
    else:
        DEST.mkdir(parents=True, exist_ok=True)
        payload.update(generated_at_utc=datetime.now(timezone.utc).isoformat(),
                       generation_head=subprocess.check_output(
                           ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip())
        manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"verified": args.verify, "files": len(entries),
                      "bytes": payload["total_bytes"], "large_files": len(payload["large_files"])}))


if __name__ == "__main__":
    main()
