"""Package only v17 local prototype bulky artifacts; never provider raw data.

All original generation artifacts remain untouched. Existing archives are verified,
never silently overwritten. The archive contains complete relative paths and an
internal per-file inventory, so it can be independently extracted into the checkout.
"""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/experiments/adaptive_strategy_research_v17/local_prototype"
ARCHIVE = ROOT / "review_bundles/v17_local_20261002.zip"
INVENTORY = OUT / "LARGE_ARTIFACTS.csv"
MANIFEST = OUT / "ZIP_MANIFEST.json"
LIMIT = 450 * 1024 * 1024


def sha(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def records():
    generation = json.loads((OUT / "GENERATION.json").read_text(encoding="utf-8"))
    expected = json.loads((OUT / "COMPLETE.json").read_text(encoding="utf-8"))["files_sha256"]
    files = [OUT / "predictions.csv", *sorted((OUT / "models").glob("*.joblib"))]
    for folder in sorted((OUT / "backtests").iterdir()):
        if folder.is_dir():
            files.extend(folder / f"{name}.csv" for name in ("trades", "positions", "targets"))
    rows = []
    for path in files:
        relative = path.relative_to(ROOT).as_posix()
        digest = sha(path)
        if digest != expected[relative]:
            raise ValueError(f"Original completed artifact changed: {relative}")
        rows.append(dict(relative_path=relative, size_bytes=path.stat().st_size, sha256=digest,
            experiment="adaptive_strategy_research_v17/local_prototype", generation_head=generation["git_head"],
            generation_command=".\\.venv\\Scripts\\python.exe -B tools/research_v17_local.py",
            read_verify_command=".\\.venv\\Scripts\\python.exe -B tools/research_v17_local.py --verify"))
    if len(rows) != 35:
        raise ValueError(f"Expected ten models, one predictions file, 24 trade/position/target files; got {len(rows)}")
    return sorted(rows, key=lambda r: r["relative_path"])


def csv_bytes(rows):
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def verify_zip(rows):
    with zipfile.ZipFile(ARCHIVE) as archive:
        expected = {r["relative_path"] for r in rows} | {"ZIP_CONTENTS.json"}
        if len(archive.namelist()) != len(expected) or set(archive.namelist()) != expected:
            raise ValueError("Archive member set differs or contains duplicates")
        if json.loads(archive.read("ZIP_CONTENTS.json")) != rows:
            raise ValueError("Internal inventory differs")
        for row in rows:
            content = archive.read(row["relative_path"])
            if len(content) != row["size_bytes"] or hashlib.sha256(content).hexdigest() != row["sha256"]:
                raise ValueError(f"Archive payload differs: {row['relative_path']}")
        if archive.testzip() is not None:
            raise ValueError("Archive CRC failed")
    if ARCHIVE.stat().st_size >= LIMIT:
        raise ValueError("Archive exceeds 450 MiB limit")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    rows = records()
    inventory = csv_bytes(rows)
    if INVENTORY.exists():
        if INVENTORY.read_bytes() != inventory:
            raise ValueError("Existing inventory differs; preserve and investigate")
    elif not args.verify:
        INVENTORY.write_bytes(inventory)
    else:
        raise FileNotFoundError(INVENTORY)
    if not ARCHIVE.exists():
        if args.verify:
            raise FileNotFoundError(ARCHIVE)
        ARCHIVE.parent.mkdir(exist_ok=True)
        with zipfile.ZipFile(ARCHIVE, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for row in rows:
                archive.write(ROOT / row["relative_path"], row["relative_path"])
            archive.writestr("ZIP_CONTENTS.json", json.dumps(rows, ensure_ascii=False, indent=2))
    verify_zip(rows)
    identity = dict(archive_path=ARCHIVE.relative_to(ROOT).as_posix(),
        archive_size_bytes=ARCHIVE.stat().st_size, archive_sha256=sha(ARCHIVE),
        payload_count=len(rows), payload_size_bytes=sum(r["size_bytes"] for r in rows),
        inventory_path=INVENTORY.relative_to(ROOT).as_posix(), inventory_sha256=sha(INVENTORY),
        original_complete_sha256=sha(OUT / "COMPLETE.json"),
        contains_provider_raw_data=False, extract_into=str(ROOT),
        verification="All 35 payload lengths and SHA256 values plus archive CRC checked against original COMPLETE",
        regenerate_command=".\\.venv\\Scripts\\python.exe -B tools/prepare_v17_local_bundle.py",
        verify_command=".\\.venv\\Scripts\\python.exe -B tools/prepare_v17_local_bundle.py --verify")
    if MANIFEST.exists():
        saved = json.loads(MANIFEST.read_text(encoding="utf-8"))
        saved.pop("created_at_utc")
        if saved != identity:
            raise ValueError("Existing ZIP identity differs")
    elif not args.verify:
        MANIFEST.write_text(json.dumps(dict(created_at_utc=datetime.now(timezone.utc).isoformat(), **identity),
                                       ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        raise FileNotFoundError(MANIFEST)
    print(json.dumps(dict(status="verified", **identity), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
