"""Read-only verification of saved v15 cloud evidence; no market/API/model calls."""
import argparse
import ast
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import subprocess

from prepare_qc_v15_source import portable_ast, stripped_tree

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "data/experiments/dynamic_universe_pilot_v15"
BASE = "a3f9a5f221bb36258e7453a6e2b0b3a1f476dfbe"
PAIRS = {f"{mode}{bps}": (mode, bps) for mode in "ABC" for bps in (10, 20)}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(content):
    return hashlib.sha256(content).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def only(payload, key):
    require(len(payload.get(key, [])) == 1, f"Expected one {key}")
    return payload[key][0]


def digest(rows):
    return sha(json.dumps(rows, separators=(",", ":")).encode())


def fnv(text):
    value = 0xcbf29ce484222325
    # Browser capture uses ASCII JSON. Do not silently change non-ASCII encoding.
    require(text.isascii(), "Non-ASCII transfer needs an explicitly matching browser hash protocol")
    for byte in text.encode("ascii"):
        value = ((value ^ byte) * 0x100000001b3) & 0xffffffffffffffff
    return f"{value:016x}"


def verify_payload(payload, mode, bps, expected_ast):
    identity, summary = only(payload, "identity"), only(payload, "summary")
    for key, expected in {"mode": mode, "cost_bps": bps, "start": "2022-01-01",
                          "end": "2023-12-31", "initial_cash": 100000, "budget": .9,
                          "model_fits": 0, "object_store": False}.items():
        require(identity.get(key) == expected, f"{mode}{bps}: identity {key}")
    require(identity.get("executable_ast_sha256") == expected_ast, "Cloud/source AST mismatch")
    for key, expected in {"mode": mode, "cost_bps": bps, "complete_months": 24,
                          "daily_close_rows": 501, "first_close_date": "2022-01-03",
                          "last_close_date": "2023-12-29", "training_count": 0,
                          "open_orders_at_end": 0, "gate_pass": True}.items():
        require(summary.get(key) == expected, f"{mode}{bps}: summary {key}")
    require(summary["native_orders_only"] is True and summary["object_store_written"] is False,
            "Unexpected execution/storage mode")
    require(abs(summary["final_gross_holdings"]) < .01, "Non-flat ending")
    require(abs(summary["final_equity"] - summary["final_cash"]) < .01, "Ending cash mismatch")
    require(summary["minimum_cash"] >= -.01 and summary["maximum_exposure"] <= 1.000001,
            "Cash/leverage violation")
    require(summary["max_cash_reconciliation_error"] <= .05, "Unreconciled cash")
    require(abs(summary["own_fee_difference_from_fill_bps"]) <= .01, "Fee mismatch")
    hard_errors = ("duplicate_bars", "invalid_bars", "cash_or_leverage_breaches", "fill_timing_violations",
                   "cash_reconciliation_days", "quantity_reconciliation_errors", "fee_mismatch_fills",
                   "invalid_orders", "stale_universe")
    require(not any(summary["stats"].get(key, 0) for key in hard_errors), "Hard gate errors recorded")
    require(len(payload.get("issue", [])) == summary["issue_detail_emitted"], "Issue output truncated")
    for issue in payload.get("issue", []):
        require(len(issue) == 7 and isinstance(issue[6], dict), "Invalid issue schema")
    annual = summary["annual_returns"]
    require(set(annual) == {"2022", "2023"}, "Missing annual result")
    ratio = summary["final_equity"] / 100000
    years = (datetime(2024, 1, 1) - datetime(2022, 1, 1)).days / 365.25
    for actual, expected in ((math.prod(1 + r for r in annual.values()), ratio),
                             (summary["net_cumulative"], ratio - 1),
                             (summary["net_cagr"], ratio ** (1 / years) - 1)):
        require(math.isfinite(actual) and math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-10),
                "Return arithmetic mismatch")
    return summary


def verify_missing_price_evidence():
    identity = read(EXP / "MISSING_PRICE_IDENTITY.json")
    initial_path = EXP / "cloud/missing_price_initial.py"
    current_path = ROOT / "tools/qc_v15_missing_price_check.py"
    require(sha(initial_path.read_bytes()) == identity["initial_source_sha256"], "Initial diagnostic source changed")
    require(sha(current_path.read_bytes()) == identity["current_diagnostic_source_sha256"], "Diagnostic source changed")
    initial_cell = initial_path.read_text(encoding="utf-8") + "\nv15_missing_result = check_v15_missing_prices()\n"
    current = current_path.read_text(encoding="utf-8")
    control_node = next(n for n in ast.parse(current).body if isinstance(n, ast.FunctionDef)
                        and n.name == "check_v15_missing_price_controls")
    control_cell = ast.get_source_segment(current, control_node) + "\n\nv15_control_result = check_v15_missing_price_controls()\n"
    for source, record in zip((initial_cell, control_cell), identity["notebook_cells"]):
        require(len(source.encode()) == record["bytes"] and fnv(source) == record["fnv1a64"],
                "Diagnostic notebook/source mismatch")
    for record in identity["outputs"]:
        content = (EXP / record["path"]).read_text(encoding="utf-8").rstrip("\n")
        require(len(content.encode()) == record["bytes_without_final_lf"] and fnv(content) == record["fnv1a64"],
                "Diagnostic output transfer mismatch")
    missing, controls = read(EXP / "MISSING_PRICE_RESULTS.json"), read(EXP / "MISSING_PRICE_CONTROLS.json")
    for payload in (missing, controls):
        require(payload["requested_calls"] == payload["completed_calls"] == len(payload["cases"]) == 8,
                "Incomplete diagnostic requests")
        require(all(c["status"] == "completed" and c["invalid_ohlcv_rows"] == c["duplicate_end_times"]
                    == c["fill_forward_rows"] == c["unexpected_post_2025_rows"] == 0 for c in payload["cases"]),
                "Diagnostic data validity failure")
    require([(c["ticker"], c["date"]) for c in missing["cases"]]
            == [(c["ticker"], c["target_date"]) for c in controls["cases"]], "Different diagnostic cases")
    require(all(c["rows"] == 0 for c in missing["cases"]), "Unexpected single-day findings")
    require(all(c["target_exchange_session_expected"] and c["target_observation_rows"] == 0
                and c["rows"] == c["surrounding_rows"] == 4 and c["surrounding_data_positive_control"]
                for c in controls["cases"]), "Missing positive controls")
    return {"distinct_fixed_queries": 16, "actual_history_calls_including_repeat": 24,
            "missing_target_dates": 8, "surrounding_bars": 32}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-only", action="store_true", help="Verify saved audit only; not six runs")
    args = parser.parse_args()
    registration = read(EXP / "REGISTRATION.json")
    require(registration["baseline_commit"] == BASE, "Registration baseline mismatch")
    require(sha((EXP / "PLAN.md").read_bytes()) == registration["plan_sha256"], "Frozen PLAN changed")
    audit = read(EXP / "AUDIT_RESULTS.json")
    audit_source = (EXP / "cloud/audit_source.py").read_text(encoding="utf-8")
    audit_manifest = read(EXP / "cloud/AUDIT_PREPARED_SOURCE_IDENTITY.json")
    require(sha((EXP / "cloud/audit_source.py").read_bytes()) == audit_manifest["prepared_sha256"],
            "Audit prepared source changed")
    audit_ast = sha(portable_ast(audit_source).encode())
    verify_payload(audit, "audit", 10, audit_ast)
    rows = audit["month"]
    months = [f"{year}-{month:02d}" for year in (2022, 2023) for month in range(1, 13)]
    require([row[0] for row in rows] == months and all(len(row) == 25 for row in rows), "Audit months")
    for row in rows:
        require(row[8] == 100 and row[12] < row[13] <= row[14] <= row[15], "Monthly scope/time")
    result = {"status": "audit_only_verified_main_runs_not_checked", "audit_months": len(rows),
              "audit_days": 501, "generation_base_commit": BASE,
              "current_verification_commit": subprocess.check_output(
                  ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(), "main_runs_verified": 0}
    if not args.audit_only:
        canonical = (ROOT / "tools/qc_v15_dynamic_pilot.py").read_text(encoding="utf-8")
        prepared = (EXP / "cloud/main.py").read_text(encoding="utf-8")
        require(ast.dump(stripped_tree(canonical)) == ast.dump(stripped_tree(prepared)), "Prepared AST")
        main_ast = sha(portable_ast(canonical).encode())
        manifest = read(EXP / "RUN_IDENTITIES.json")
        require(manifest["generation_base_commit"] == BASE, "Run provenance baseline")
        files = {f"runs/{key}.json" for key in PAIRS}
        require({p.relative_to(EXP).as_posix() for p in (EXP / "runs").glob("*.json")} == files,
                "Require exactly six registered run files")
        records = manifest["runs"]
        require(len(records) == 6 and {r["file"] for r in records} == files, "Six run identities")
        require(len({r["backtest_id"] for r in records}) == 6, "Repeated cloud backtest identity")
        require(len({r["engine_version"] for r in records}) == 1, "Different main-run engines")
        results = {}
        for record in records:
            path = EXP / record["file"]
            text = path.read_text(encoding="utf-8").rstrip("\n")
            require(len(text.encode()) == record["transfer_bytes"] and fnv(text) == record["transfer_fnv1a64"],
                    f"Transfer mismatch: {path.name}")
            payload = json.loads(text)
            mode, bps = PAIRS[path.stem]
            summary = verify_payload(payload, mode, bps, main_ast)
            check = only(payload, "month_check")
            require(check["rows"] == 24 and check["pool_excludes_only"] == "target_count"
                    and len(check["target_counts"]) == 24, "Monthly checksum schema")
            reconstructed = [list(row) for row in rows]
            for row, count in zip(reconstructed, check["target_counts"]):
                require(count == {"A": 100, "B": 10, "C": 1}[mode], "Unexpected target count")
                row[23] = count
            require(digest(reconstructed) == check["packed_sha256"], "Monthly observations changed")
            require(digest([r[:23] + r[24:] for r in reconstructed]) == check["pool_sha256"],
                    "Stock pool checksum mismatch")
            results[path.stem] = {k: summary[k] for k in ("net_cumulative", "net_cagr", "max_drawdown", "fees_paid")}
        result.update(status="six_fixed_cloud_runs_verified", main_runs_verified=6, results=results,
                      missing_price_evidence=verify_missing_price_evidence())
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
