"""Prepare a compact v15 cloud source file without executing the algorithm.

Only comments/formatting and leading module/class/function docstrings are removed.
This is a local upload artifact, never evidence of what actually ran in the cloud.
"""
import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tools/qc_v15_dynamic_pilot.py"
OUTPUT = ROOT / "data/experiments/dynamic_universe_pilot_v15/cloud/main.py"
IDENTITY = OUTPUT.with_name("PREPARED_SOURCE_IDENTITY.json")
LIMIT = 32768


def stripped_tree(text):
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.body and isinstance(node.body[0], ast.Expr):
                value = node.body[0].value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    node.body.pop(0)
    return tree


def portable_ast(text):
    # Matches the algorithm's cloud identity helper across Python 3.11/3.12.
    return ast.dump(stripped_tree(text), include_attributes=False).replace(", type_params=[]", "")


def sha256(content):
    return hashlib.sha256(content).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true", help="Read-only check of prepared files")
    args = parser.parse_args()
    source_bytes = SOURCE.read_bytes()
    source = source_bytes.decode("utf-8-sig")
    compact = (ast.unparse(stripped_tree(source)) + "\n").encode("utf-8")
    if len(compact) >= LIMIT:
        raise ValueError(f"Prepared source is {len(compact)} bytes; must be below {LIMIT}")
    compact_text = compact.decode("utf-8")
    if ast.dump(stripped_tree(source), include_attributes=False) != ast.dump(
            stripped_tree(compact_text), include_attributes=False):
        raise ValueError("Prepared executable AST differs from canonical source")
    compile(compact_text, str(OUTPUT), "exec")  # Syntax only; no imports/execution.
    details = {
        "status": "prepared_local_upload_artifact_not_cloud_execution_evidence",
        "canonical_path": SOURCE.relative_to(ROOT).as_posix(),
        "canonical_bytes": len(source_bytes),
        "canonical_sha256": sha256(source_bytes),
        "prepared_path": OUTPUT.relative_to(ROOT).as_posix(),
        "prepared_bytes": len(compact),
        "prepared_sha256": sha256(compact),
        "portable_executable_ast_sha256": sha256(portable_ast(source).encode()),
        "byte_limit_exclusive": LIMIT,
        "algorithm_imported_or_executed": False,
    }
    if args.verify:
        recorded = json.loads(IDENTITY.read_text(encoding="utf-8"))
        if OUTPUT.read_bytes() != compact:
            raise ValueError("Prepared source is stale or differs from deterministic generation")
        if any(recorded.get(key) != value for key, value in details.items()):
            raise ValueError("Prepared source identity does not match current inputs")
    else:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_bytes(compact)
        IDENTITY.write_text(json.dumps({**details,
            "prepared_at_utc": datetime.now(timezone.utc).isoformat(),
            "preparer_python": sys.version.split()[0],
        }, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"action": "verified" if args.verify else "prepared", **details}, indent=2))


if __name__ == "__main__":
    main()
