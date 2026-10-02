"""Verify visible v17 RuntimeStats captured as JSON, without contacting QC.

Input: {"v17_summary": "{...}", ...}, or
{"runtime_statistics": {...}, "run_identity": {...}}. Values must be the
unmodified visible cell strings (JSON objects already decoded are also accepted).
Run: python tools/summarize_v17_cloud.py --input capture.json --output run_dir
This only verifies derived artifacts. It cannot authenticate vendor prices,
turn monthly equity into daily drawdown, or prove a raw-data snapshot complete.
"""
import argparse
import csv
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import statistics

from qc_v17_features import FEATURE_NAMES, stable_digest, decode_runtime_payload, continuous_drawdown


def decoded(value):
    return json.loads(value) if isinstance(value, str) else value


def verify_runtime(capture):
    runtime = capture.get("runtime_statistics", capture)
    if not isinstance(runtime, dict):
        raise ValueError("Input must map RuntimeStats keys to visible cell values")
    checks, artifacts = [], {}

    def check(name, passed, detail=None):
        checks.append({"check": name, "passed": bool(passed), "detail": detail})

    # Revision03 transmits exact ASCII JSON text in <=180-character cells.
    # Reconstruct and authenticate before parsing; do not JSON-parse each part.
    runtime = dict(runtime)
    for key in sorted(list(runtime)):
        if not key.startswith("v17_payload_") or not key.endswith("_meta"):
            continue
        meta = decoded(runtime[key])
        prefix = key[:-5]
        parts = [runtime[prefix + "_" + str(i)] for i in range(meta["chunks"])]
        value = decode_runtime_payload(meta, parts)
        original_name = "v17_" + prefix.removeprefix("v17_payload_")
        runtime[original_name] = value
        check(original_name + "_text_transport", True,
              {"chunks": meta["chunks"], "characters": meta["characters"], "sha256": meta["sha256"]})

    summary = decoded(runtime["v17_summary"])
    months = decoded(runtime["v17_months"])
    expected_months = [f"{year}-{month:02d}" for year in (2022, 2023) for month in range(1, 13)]
    check("registered_evaluation_months", sorted(months) == expected_months, sorted(months))
    check("engine_gate_pass", summary.get("gate_pass") is True)
    check("evaluation_identity", summary.get("evaluation") == "2022-2023 development")
    check("year_2026_not_used", summary.get("2026_market_data_used") is False)
    check("training_mode_count", summary.get("training_count") == (2 if str(summary.get("mode")).startswith("ridge") else 0))
    monthly, prior, prior_fees, peak, monthly_dd = [], 100000.0, 0.0, 100000.0, 0.0
    for month in sorted(months):
        date, equity, gross, cash, fees = months[month]
        check("month_end_identity_" + month, date.startswith(month) and date <= "2023-12-31", date)
        check("monthly_cash_mark_" + month, abs(cash + gross - equity) < .05,
              {"difference": cash + gross - equity})
        check("nondecreasing_fees_" + month, fees + 1e-7 >= prior_fees)
        monthly.append({"month": month, "last_close_date": date, "begin_equity": prior,
                        "end_equity": equity, "net_pnl": equity - prior,
                        "net_return": equity / prior - 1, "fees": fees - prior_fees,
                        "closing_gross": gross, "closing_cash": cash})
        prior, prior_fees = equity, fees
        peak = max(peak, equity)
        monthly_dd = max(monthly_dd, 1 - equity / peak)
    if months:
        final = monthly[-1]["end_equity"]
        years = (datetime(2024, 1, 1) - datetime(2022, 1, 1)).days / 365.25
        derived_cagr = (final / 100000) ** (1 / years) - 1
        check("final_equity_matches", abs(final - summary["final_equity"]) < .01)
        check("cumulative_return_matches", abs(final / 100000 - 1 - summary["net_cumulative"]) < 1e-10)
        check("two_year_cagr_matches", abs(derived_cagr - summary["net_cagr"]) < 1e-10)
        check("final_fee_total_matches", abs(prior_fees - summary["fees_paid"]) < .01)
        check("reported_daily_drawdown_not_smaller_than_monthly", summary["max_drawdown"] + 1e-10 >= monthly_dd)
        check("final_flat", abs(summary["final_gross_holdings"]) < .01 and summary["open_orders_at_end"] == 0)
    if "2022-12" in months and "2023-12" in months:
        annual_2022 = months["2022-12"][1] / 100000 - 1
        annual_2023 = months["2023-12"][1] / months["2022-12"][1] - 1
        for year, value in (("2022", annual_2022), ("2023", annual_2023)):
            check("annual_return_" + year, abs(value - summary["annual_returns"][year]) < 1e-10)
    for key in sorted(runtime):
        if not key.startswith("v17_") or not key.endswith("_index"):
            continue
        index = decoded(runtime[key])
        prefix, rows, missing = key[:-6], [], []
        for i in range(index["chunks"]):
            chunk_key = prefix + "_" + str(i)
            if chunk_key not in runtime:
                missing.append(chunk_key)
                continue
            rows.extend(decoded(runtime[chunk_key]))
        check(prefix + "_chunks_present", not missing, missing)
        check(prefix + "_row_count", len(rows) == index["rows"], {"observed": len(rows), "expected": index["rows"]})
        check(prefix + "_sha256", stable_digest(rows) == index["sha256"])
        artifacts[prefix] = rows
    # New text transport carries a whole list per payload; old row chunks are
    # retained above solely to validate original, untruncated old observations.
    for key, value in runtime.items():
        if key.startswith(("v17_predictions_", "v17_security_pnl")) or key in (
                "v17_labels", "v17_unresolved_labels", "v17_held_issues", "v17_daily_nav"):
            if isinstance(value, list):
                artifacts[key] = value
    check("all_monthly_prediction_indices", all("v17_predictions_" + m in artifacts for m in expected_months))
    fits = []
    for year in (2022, 2023):
        key = "v17_fit_" + str(year)
        if key not in runtime:
            continue
        fit = decoded(runtime[key])
        parameters = fit["parameters"]
        payload = {"parameters": parameters, "features": list(FEATURE_NAMES), "input_sha256": fit["input_sha256"]}
        boundary = datetime(year, 1, 1)
        check(key + "_model_hash", stable_digest(payload) == fit["model_sha256"])
        check(key + "_feature_order", fit["feature_order"] == list(FEATURE_NAMES))
        check(key + "_observations_before_boundary", datetime.fromisoformat(fit["observed_last"]) < boundary)
        check(key + "_labels_matured_before_boundary", datetime.fromisoformat(fit["label_end_last"]) < boundary)
        check(key + "_parameter_dimensions", all(len(parameters[k]) == len(FEATURE_NAMES) for k in ("mean", "scale", "coefficient")))
        check(key + "_positive_scales", all(math.isfinite(v) and v > 0 for v in parameters["scale"]))
        fits.append(fit)
    check("fit_artifact_count", len(fits) == summary["training_count"])
    check("model_hash_list_matches", [r["model_sha256"] for r in fits] == summary["model_hashes"])
    if "v17_security_pnl" in artifacts:
        pnl = sum(row[1] for row in artifacts["v17_security_pnl"])
        split_cash = summary["stats"].get("attribution_split_cash", 0)
        residual = summary["final_equity"] - 100000 - pnl - split_cash
        check("security_pnl_reconciles", abs(residual) < .05, {"residual": residual})
    else:
        check("security_pnl_artifact_available", False)
    daily_independent = False
    if "v17_daily_nav" in artifacts:
        daily = artifacts["v17_daily_nav"]
        check("daily_dates", len(daily) == 501 and daily[0][0] == "2022-01-03" and daily[-1][0] == "2023-12-29"
              and [r[0] for r in daily] == sorted({r[0] for r in daily}))
        values = [r[1] for r in daily]
        drawdown = continuous_drawdown(values)
        exposure = statistics.mean(r[2] / r[1] for r in daily)
        returns = [values[0] / 100000 - 1] + [values[i] / values[i-1] - 1 for i in range(1, len(values))]
        volatility = statistics.stdev(returns) * math.sqrt(252)
        check("daily_drawdown_recomputed", abs(drawdown - summary["max_drawdown"]) < 1e-10)
        check("daily_exposure_recomputed", abs(exposure - summary["average_exposure"]) < 1e-10)
        check("daily_volatility_recomputed", abs(volatility - summary["annualized_volatility"]) < 1e-10)
        check("daily_turnover_denominator", abs(summary["traded_notional"] / statistics.mean(values)
              - summary["turnover_gross_notional_over_average_equity"]) < 1e-10)
        check("daily_cash_and_holdings", all(abs(r[1] - r[2] - r[3]) < .05 for r in daily))
        monthly_from_daily = {}
        for row in daily:
            monthly_from_daily[row[0][:7]] = row
        check("daily_to_monthly_alignment", all(m in months and months[m][:4] == list(r) for m, r in monthly_from_daily.items())
              and sorted(monthly_from_daily) == expected_months)
        daily_independent = True
    verification = {
        "passed": all(r["passed"] for r in checks), "checks": checks,
        "monthly_drawdown_lower_bound": monthly_dd,
        "daily_drawdown_independently_recomputed": daily_independent,
        "evidence": "visible cloud derived RuntimeStats; no provider quote authentication or independent validation",
        "run_identity": capture.get("run_identity", {}),
    }
    return summary, monthly, fits, artifacts, verification


def write_csv(path, rows, fieldnames):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = args.input.read_bytes()
    capture = json.loads(source)
    summary, monthly, fits, artifacts, verification = verify_runtime(capture)
    verification["capture_sha256"] = hashlib.sha256(source).hexdigest()
    args.output.mkdir(parents=True, exist_ok=True)
    for name, value in (("SUMMARY.json", summary), ("VERIFICATION.json", verification),
                        ("FITS.json", fits), ("DERIVED_ARTIFACTS.json", artifacts)):
        (args.output / name).write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    if monthly:
        write_csv(args.output / "monthly.csv", monthly, list(monthly[0]))
    predictions = [{"month": key.removeprefix("v17_predictions_"), "sid": row[0], "score": row[1]}
                   for key, values in sorted(artifacts.items()) if key.startswith("v17_predictions_") for row in values]
    write_csv(args.output / "predictions.csv", predictions, ["month", "sid", "score"])
    securities = [{"sid": sid, "net_pnl": value} for sid, value in artifacts.get("v17_security_pnl", [])]
    write_csv(args.output / "security_pnl.csv", securities, ["sid", "net_pnl"])
    if "v17_daily_nav" in artifacts:
        daily = [dict(zip(("date", "equity", "gross", "cash"), row)) for row in artifacts["v17_daily_nav"]]
        write_csv(args.output / "daily_nav.csv", daily, ["date", "equity", "gross", "cash"])
    print(json.dumps({"mode": summary["mode"], "cost_bps": summary["cost_bps"],
                      "net_cagr": summary["net_cagr"], "max_drawdown": summary["max_drawdown"],
                      "training_count": summary["training_count"], "verification_passed": verification["passed"],
                      "failed_checks": [r["check"] for r in verification["checks"] if not r["passed"]]}, indent=2))
    raise SystemExit(0 if verification["passed"] else 1)


if __name__ == "__main__":
    main()
