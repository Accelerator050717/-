"""Independent links among saved original UI, recovered fields and CSV money.

No network calls, market data requests, model fitting or simulation. Full log
transport integrity is deliberately separate from numeric cross-checks.
"""
from collections import defaultdict
import csv
from datetime import datetime
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/experiments/momentum_loss_attribution_v16"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(name):
    with (OUT / name).open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def main():
    monthly = read_csv("monthly_pnl.csv")
    lookup = {r["month"]: r for r in monthly}
    original = read_json(OUT / "ORIGINAL_B10_MONTHLY_UI.json")
    monthly_comparisons = []
    for row in original["rows"]:
        day = datetime.strptime(row[0], "%m/%d/%Y")
        if day.year not in (2022, 2023):
            continue
        month = day.strftime("%Y-%m")
        displayed = Decimal(row[1])
        recovered = Decimal(lookup[month]["end_equity"])
        diff = recovered - displayed
        monthly_comparisons.append({"month": month, "original_displayed_equity": str(displayed),
            "diagnostic_runtime_equity": str(recovered), "difference": str(diff),
            "within_four_decimal_display_rounding": abs(diff) <= Decimal("0.00005001")})
    baseline_c = read_json(ROOT / "data/experiments/dynamic_universe_pilot_v15/runs/C10.json")["summary"][0]
    runtime = read_json(OUT / "DIAGNOSTIC_RUNTIME_STATS.json")
    reference = {month: {k: Decimal(v) for k, v in (token.split("=", 1) for token in runtime["v16 M" + month].split())}["C"] for month in lookup}
    c2022 = Decimal(100000) * (1 + Decimal(str(baseline_c["annual_returns"]["2022"])))
    cfinal = Decimal(str(baseline_c["final_equity"]))
    cchecks = {"runtime_2022_end": str(reference["2022-12"]), "original_2022_regular_close_end": str(c2022),
        "runtime_final": str(reference["2023-12"]), "original_final": str(cfinal),
        "2022_end_matches": abs(reference["2022-12"] - c2022) < Decimal("0.0000001"),
        "final_matches": abs(reference["2023-12"] - cfinal) < Decimal("0.0000001"),
        "all_cloud_tail_checks_observed": False,
        "scope": "These are observed runtime values vs original monetary controls; missing final cloud C10 metadata is not filled in."}
    compound = []
    for period in ("2022", "2023", "all"):
        rows = monthly if period == "all" else [r for r in monthly if r["month"].startswith(period)]
        ratio = float(rows[-1]["end_equity"]) / float(rows[0]["begin_equity"]) - 1
        chained = math.prod(1 + float(r["net_return"]) for r in rows) - 1
        cchained = math.prod(1 + float(r["spy_net_return"]) for r in rows) - 1
        cstart = 100000.0 if period in ("2022", "all") else float(reference["2022-12"])
        cratio = float(reference[rows[-1]["month"]]) / cstart - 1
        compound.append({"period": period, "B10_monthly_compound": chained, "B10_boundary_return": ratio,
            "C10_monthly_compound": cchained, "C10_boundary_return": cratio,
            "B10_match": abs(chained - ratio) < 1e-12, "C10_match": abs(cchained - cratio) < 1e-12})
    annual_rows = read_csv("security_year_pnl.csv")
    all_rows = read_csv("security_total_pnl.csv")
    sums = defaultdict(lambda: defaultdict(Decimal))
    fields = ("price_pnl", "dividends", "split_cash", "fees", "net_pnl")
    for row in annual_rows:
        for field in fields:
            sums[row["sid"]][field] += Decimal(row[field])
    max_differences = {f: Decimal(0) for f in fields}
    for row in all_rows:
        for field in fields:
            max_differences[field] = max(max_differences[field], abs(sums[row["sid"]][field] - Decimal(row[field])))
    joins = []
    priority = read_csv("priority_entries.csv")
    for case in read_json(OUT / "ENTRY_DIAGNOSTICS_RESULTS.json")["cases"]:
        matches = [r for r in priority if r["sid"] == case["sid"] and r["entry"][:7] == case["decision_local"][:7]]
        if len(matches) != 1:
            raise ValueError("Entry diagnostic cannot match one priority interval")
        row = matches[0]
        error = abs(float(row["momentum_20"]) - case["momentum_20"])
        joins.append({"ticker_at_decision": case["ticker_at_decision"], "sid": case["sid"],
            "entry": row["entry"], "research_decision": case["decision_local"],
            "sid_hash_matches": hashlib.sha256(row["sid"].encode()).hexdigest() == case["sid_sha256"],
            "observer_momentum_eight_decimals": row["momentum_20"], "research_momentum": case["momentum_20"],
            "absolute_difference": error, "within_declared_eight_decimal_rounding": error <= 5.001e-9,
            "research_prior_day_DV_proxy_over_previous20median": case["volume_ratio"],
            "observer_universe_dollar_volume_rank": row["dollar_volume_rank"],
            "limit": "RAW close*volume proxy is not an equality check of Fundamental.DollarVolume; three loss-selected cases do not estimate universe-wide failure probability."})
    numeric_pass = (len(monthly_comparisons) == 24 and all(r["within_four_decimal_display_rounding"] for r in monthly_comparisons)
        and cchecks["2022_end_matches"] and cchecks["final_matches"] and all(r["B10_match"] and r["C10_match"] for r in compound)
        and len(annual_rows) == 167 and len(all_rows) == 133 and all(v < Decimal("0.0000001") for v in max_differences.values())
        and all(r["sid_hash_matches"] and r["within_declared_eight_decimal_rounding"] for r in joins))
    output = {"schema": "v16-financial-cross-check-1", "available_numeric_checks_pass": numeric_pass,
        "full_payload_transport_integrity_verified": False,
        "transport_reason": "Only a strict prefix of the one diagnostic log was obtained; LZMA EOF/full SHA and final runtime expected hash not available.",
        "B10_original_months": monthly_comparisons, "C10_reference_money_controls": cchecks,
        "monthly_compounding": compound, "security_aggregation": {"year_rows": len(annual_rows), "SIDs": len(all_rows),
            "max_year_to_total_difference": {k: str(v) for k, v in max_differences.items()}}, "entry_signal_links": joins}
    (OUT / "FINANCIAL_CROSS_CHECK.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"numeric_checks_pass": numeric_pass, "B10_months": len(monthly_comparisons),
        "B10_max_UI_difference": str(max(abs(Decimal(r["difference"])) for r in monthly_comparisons)),
        "C10_controls": cchecks, "security_aggregation": output["security_aggregation"], "entry_links": joins}, ensure_ascii=False, indent=2))
    if not numeric_pass:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
