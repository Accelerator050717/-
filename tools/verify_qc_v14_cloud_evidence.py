"""Verify saved cloud diagnostics offline; never query QC or import trading code."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "data/experiments/historical_data_sample_v14/cloud_free_20260922"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def definitions_hash(source):
    tree = ast.parse(source)
    # Cloud cells omit the module docstring and append a function invocation.
    tree.body = [node for node in tree.body if not isinstance(node, ast.Expr)]
    # Python 3.12 added an empty type_params field; cloud uses Python 3.11.
    canonical = ast.dump(tree, include_attributes=False).replace(", type_params=[]", "")
    return hashlib.sha256(canonical.encode()).hexdigest()


def transfer_fingerprint(payload):
    # Same compact JSON / UTF-8 FNV-1a used on the browser's copied output.
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    value = 14695981039346656037
    for byte in raw:
        value = ((value ^ byte) * 1099511628211) & ((1 << 64) - 1)
    return {"compact_utf8_bytes": len(raw), "fnv1a64": f"{value:016x}"}


def main():
    identity = read_json(RUN / "CLOUD_EVIDENCE_IDENTITY.json")
    for entry in identity["files"]:
        path = ROOT / entry["path"]
        require(path.is_file(), f"Missing evidence: {entry['path']}")
        raw = path.read_bytes()
        require(len(raw) == entry["bytes"], f"Size changed: {entry['path']}")
        require(hashlib.sha256(raw).hexdigest() == entry["sha256"],
                f"Hash changed: {entry['path']}")

    runtime = read_json(RUN / "RUN_IDENTITY.json")
    package = read_json(RUN / "v14_readonly_checks.ipynb")
    code_cells = [cell for cell in package["cells"] if cell["cell_type"] == "code"]
    require(len(code_cells) == 4, "Prepared notebook must have two source/call pairs")
    for cell in code_cells:
        require(not cell["outputs"] and cell["execution_count"] is None,
                "Local package must not impersonate an executed notebook")
    for mapping, cell, invocation, executed in zip(identity["source_mapping"], code_cells[::2],
                                      code_cells[1::2],
                                      runtime["executed_cells"], strict=True):
        source = (ROOT / mapping["path"]).read_text(encoding="utf-8-sig")
        require("".join(cell["source"]) == source, "Prepared cell/source mismatch")
        require("".join(invocation["source"]) == mapping["invoke"] + "\n",
                "Prepared invocation mismatch")
        require(definitions_hash(source) == executed["definitions_ast_sha256"],
                f"Cloud/local AST mismatch: {mapping['path']}")
    for filename, expected in identity["browser_transfer"].items():
        require(transfer_fingerprint(read_json(RUN / filename)) == expected,
                f"Copied browser output differs: {filename}")

    original = read_json(RUN / "ORIGINAL_RESULTS.json")
    supplement = read_json(RUN / "SUPPLEMENT_RESULTS.json")
    status = read_json(RUN / "RUN_STATUS.json")
    queries, bars, events = [], 0, 0
    for case in original["cases"].values():
        require(case["requested_end_exclusive"] < "2026-01-01", "Date boundary changed")
        queries.extend([case["prices"], case["research_universe"],
                        *case["lifecycle"].values()])
        bars += case["prices"]["rows"]
        events += sum(item["rows"] for item in case["lifecycle"].values())
    corporate = supplement["aapl_corporate_actions"]
    queries.extend([corporate["dividends"], corporate["splits"]])
    events += corporate["dividends"]["rows"] + corporate["splits"]["rows"]
    universe = supplement["historical_fundamental_universe"]
    queries.extend(universe.values())
    candidate_rows = sum(call["candidate_rows"] for item in universe.values()
                         for call in item["filter_calls"])
    require(all(item["query"] == "completed" for item in queries), "Incomplete query")
    require((len(queries), bars, events, candidate_rows) ==
            (status["history_queries_completed"], status["price_rows"],
             status["event_rows"], status["historical_filter_input_rows"]),
            "Run summary does not match returned diagnostics")
    current_head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    print(json.dumps({
        "status": "verified_offline_saved_cloud_evidence",
        "generation_base_commit": identity["generation_base_commit"],
        "verification_commit": current_head,
        "head_change_alone_invalidates_evidence": False,
        "files_verified": len(identity["files"]),
        "cloud_source_ast_matches": 2,
        "browser_result_transfer_matches": 2,
        "history_queries_completed": len(queries), "price_rows": bars,
        "event_rows": events, "historical_filter_input_rows": candidate_rows,
        "new_cloud_queries": 0,
        "meaning": "Saved-output integrity, not a fresh service run or full data certification",
    }, indent=2))


if __name__ == "__main__":
    main()
