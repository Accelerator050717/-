"""Read-only byte/hash and CSV/JSON preview. Never trains, downloads or unpickles."""
import argparse
import csv
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", help="Path relative to the project root, or an absolute path")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    path = Path(args.path)
    path = path if path.is_absolute() else root / path
    path = path.resolve(strict=True)
    if not path.is_relative_to(root):
        raise ValueError("Only project artifacts may be inspected.")
    with path.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    result = dict(path=path.as_posix(), size_bytes=path.stat().st_size, sha256=digest)
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            result["columns"] = next(reader, [])
            result["first_record"] = next(reader, [])
    elif path.suffix.lower() == ".json" and path.stat().st_size < 1024*1024:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        result["top_level_keys"] = list(value) if isinstance(value, dict) else None
    else:
        result["preview"] = "Bytes and hash only; serialized models are not loaded."
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
