"""Read-only comparison of actually captured v17 cloud cases; no QC requests.

Reads cases/*/{SUMMARY,VERIFICATION,FITS}.json and optional monthly.csv.
Selection waits for all seven registered10bp configurations. A selected research
candidate is not a validated profitable strategy;20bp confirmation is separate.
"""
import argparse
import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path


MODES = ("eq", "mom20", "trend63", "ridge", "trend63_risk", "ridge_risk", "spy")
CANDIDATES = ("mom20", "trend63", "ridge", "trend63_risk", "ridge_risk")
METRICS = ("net_cumulative", "net_cagr", "max_drawdown", "annualized_volatility", "average_exposure",
           "maximum_single_close_weight", "fees_paid", "traded_notional", "turnover_gross_notional_over_average_equity", "final_equity")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_cases(root):
    cases, omitted = [], []
    for path in sorted(root.glob("*/SUMMARY.json")):
        directory = path.parent
        verification_path = directory / "VERIFICATION.json"
        if not verification_path.exists():
            omitted.append({"case": str(directory), "reason": "missing_verification"})
            continue
        summary, verified = read_json(path), read_json(verification_path)
        if not verified.get("passed") or not summary.get("gate_pass"):
            omitted.append({"case": str(directory), "reason": "verification_or_engine_gate_failed"})
            continue
        if summary.get("mode") not in MODES or summary.get("cost_bps") not in (10, 20):
            raise ValueError("Unregistered mode/cost in " + str(path))
        if summary.get("evaluation") != "2022-2023 development" or summary.get("daily_close_rows") != 501:
            raise ValueError("Different evaluation interval in " + str(path))
        fits = read_json(directory / "FITS.json") if (directory / "FITS.json").exists() else []
        monthly = []
        if (directory / "monthly.csv").exists():
            with (directory / "monthly.csv").open(encoding="utf-8", newline="") as stream:
                monthly = list(csv.DictReader(stream))
        cases.append({"directory": str(directory), "summary": summary, "verification": verified,
                      "fits": fits, "monthly": monthly})
    return cases, omitted


def compare(cases):
    groups, duplicate_checks, conflicts = {}, [], []
    for case in cases:
        s = case["summary"]
        key = (s["mode"], s["cost_bps"])
        if key in groups:
            old = groups[key]["summary"]
            equal = all(abs(s[k] - old[k]) <= 1e-8 for k in METRICS)
            models = s["model_hashes"] == old["model_hashes"]
            duplicate_checks.append({"mode": key[0], "cost_bps": key[1], "metrics_agree": equal,
                                     "model_hashes_agree": models, "case": case["directory"]})
            if not equal or not models:
                conflicts.append(key)
        else:
            groups[key] = case
    rows, annual_rows, monthly_rows, identity_rows = [], [], [], []
    for (mode, cost), case in sorted(groups.items()):
        s, v = case["summary"], case["verification"]
        row = {"mode": mode, "cost_bps": cost, **{k: s[k] for k in METRICS},
               "training_count_this_run": s["training_count"], "meets_cagr_20pct": s["net_cagr"] >= .20,
               "above_cagr_30pct": s["net_cagr"] > .30, "within_preferred_dd_20pct": s["max_drawdown"] <= .20,
               "within_dd_budget_30pct": s["max_drawdown"] <= .30,
               "meets_minimum_numeric_targets": s["net_cagr"] >= .20 and s["max_drawdown"] <= .30,
               "daily_drawdown_independently_recomputed": v.get("daily_drawdown_independently_recomputed", False),
               "full_predictions_archived": v.get("full_predictions_archived", False),
               "case": case["directory"]}
        for control in ("eq", "spy"):
            baseline = groups.get((control, cost))
            row["cagr_delta_vs_" + control + "_pp"] = (s["net_cagr"] - baseline["summary"]["net_cagr"]) * 100 if baseline else None
            row["drawdown_delta_vs_" + control + "_pp"] = (s["max_drawdown"] - baseline["summary"]["max_drawdown"]) * 100 if baseline else None
        rows.append(row)
        for year, value in s["annual_returns"].items():
            annual_rows.append({"mode": mode, "cost_bps": cost, "year": year, "net_return": value})
        monthly_rows += [{"mode": mode, "cost_bps": cost, **r} for r in case["monthly"]]
        identity = v.get("source_identity") or {}
        identity_rows.append({"mode": mode, "cost_bps": cost, "source_identity": identity,
                              "cumulative_security_ids": s["cumulative_security_ids"],
                              "pool_membership_hashes_exported": False})
    identity_fields = ("strategy_sha256", "core_sha256", "features_sha256", "features", "training_start", "evaluation", "label", "model")
    identity_projection = lambda r: {k: r["source_identity"].get(k) for k in identity_fields}
    source_versions = {json.dumps(identity_projection(r), sort_keys=True) for r in identity_rows}
    identities_complete = bool(identity_rows) and all(all(r["source_identity"].get(k) for k in identity_fields) for r in identity_rows)
    common_source = identities_complete and len(source_versions) == 1
    missing = [mode for mode in MODES if (mode, 10) not in groups]
    selection = {"status": "pending", "missing_10bp_modes": missing, "selected_research_candidate": None,
                 "rule": "among fixed non-control candidates with fullDD<=30%, highestnetCAGR; if none, leastDD as rejected diagnostic only",
                 "independent_validation": False, "forward_run": False}
    selection["pending_reasons"] = (["missing_registered_10bp_modes"] if missing else []) + (["conflicting_duplicate_configurations"] if conflicts else []) + (["source_identity_incomplete_or_different"] if not common_source else [])
    if not missing and not conflicts and common_source:
        pool = [groups[(m, 10)]["summary"] for m in CANDIDATES]
        eligible = [s for s in pool if s["max_drawdown"] <= .30]
        selected = sorted(eligible, key=lambda s: (-s["net_cagr"], s["max_drawdown"], s["mode"]))[0] if eligible else sorted(pool, key=lambda s: (s["max_drawdown"], -s["net_cagr"], s["mode"]))[0]
        mode = selected["mode"]
        selection.update(status="selected_for_registered_cost_check" if eligible else "all_candidates_rejected_risk_diagnostic_only",
                         selected_research_candidate=mode, selected_10bp_cagr=selected["net_cagr"],
                         selected_10bp_drawdown=selected["max_drawdown"],
                         meets_minimum_numeric_targets=selected["net_cagr"] >= .20 and selected["max_drawdown"] <= .30,
                         required_20bp_modes=[mode, "eq", "spy"],
                         remaining_20bp_modes=[m for m in (mode, "eq", "spy") if (m, 20) not in groups])
        all_budget = [groups[(m, 10)]["summary"] for m in MODES if groups[(m, 10)]["summary"]["max_drawdown"] <= .30]
        selection["best_including_controls_under_budget"] = sorted(all_budget, key=lambda s: (-s["net_cagr"], s["mode"]))[0]["mode"] if all_budget else None
    paired = []
    def same_signal(a, b):
        left, right = a.get("prediction_panel_sha256"), b.get("prediction_panel_sha256")
        return isinstance(left, str) and len(left) == 64 and left == right

    for base, overlay in (("trend63", "trend63_risk"), ("ridge", "ridge_risk")):
        if (base, 10) in groups and (overlay, 10) in groups:
            a, b = groups[(base, 10)]["summary"], groups[(overlay, 10)]["summary"]
            paired.append({"kind": "fixed_risk_overlay", "base": base, "candidate": overlay,
                           "cagr_delta_pp": 100*(b["net_cagr"]-a["net_cagr"]),
                           "drawdown_delta_pp": 100*(b["max_drawdown"]-a["max_drawdown"]),
                           "exposure_delta_pp": 100*(b["average_exposure"]-a["average_exposure"]),
                           "signal_hash_matches": same_signal(a, b),
                           "model_hashes_match": a["model_hashes"] == b["model_hashes"]})
    for mode in MODES:
        if (mode, 10) in groups and (mode, 20) in groups:
            a, b = groups[(mode, 10)]["summary"], groups[(mode, 20)]["summary"]
            paired.append({"kind": "ordinary_cost_10_to_20bp", "base": mode, "candidate": mode,
                           "cagr_delta_pp": 100*(b["net_cagr"]-a["net_cagr"]),
                           "drawdown_delta_pp": 100*(b["max_drawdown"]-a["max_drawdown"]),
                           "signal_hash_matches": same_signal(a, b),
                           "model_hashes_match": a["model_hashes"] == b["model_hashes"]})
    evidence = {"validated_case_count": len(cases), "unique_mode_cost_count": len(groups),
                "validated_case_fit_count_not_total_cloud_attempt_fits": sum(c["summary"]["training_count"] for c in cases),
                "duplicate_checks": duplicate_checks, "conflicting_duplicate_configs": conflicts,
                "common_source_configuration": common_source,
                "source_identities": identity_rows,
                "exact_monthly_universe_membership_cross_run_verified": False,
                "universe_identity_limit": "Frozen same source, parameters, coverage/counts; full per-month membership hashes were not exported. This is not exact membership hash proof.",
                "comparison_scope": "2022-2023 development; equity vs concentrated signals also changes holdings/concentration; risk overlay changes budget intentionally",
                "selection": selection, "paired_checks": paired}
    return rows, annual_rows, monthly_rows, evidence


def write_csv(path, rows):
    if not rows:
        return
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def candidate_diagnostics(cases, evidence):
    """Descriptive development attribution; no deletion/re-optimization."""
    selected = evidence["selection"].get("selected_research_candidate")
    if selected is None:
        return {"status": "pending_complete_registered_comparison"}
    lookup = {(c["summary"]["mode"], c["summary"]["cost_bps"]): c for c in cases}
    case = lookup[(selected, 10)]
    rows = case["monthly"]
    ordered = sorted(rows, key=lambda r: (float(r["net_pnl"]), r["month"]))
    positive = sum(max(0, float(r["net_pnl"])) for r in rows)
    negative = -sum(min(0, float(r["net_pnl"])) for r in rows)
    comparisons = {}
    for name in ("eq", "spy"):
        baseline = {r["month"]: float(r["net_return"]) for r in lookup[(name, 10)]["monthly"]}
        matched = [r for r in rows if r["month"] in baseline]
        comparisons[name] = {"matched_months": len(matched),
                             "months_with_higher_net_return": sum(float(r["net_return"]) > baseline[r["month"]] for r in matched)}
    compact = lambda r: {"month": r["month"], "net_pnl": float(r["net_pnl"]), "net_return": float(r["net_return"])}
    summary = case["summary"]
    winners = summary.get("top5_winners", [])
    gross_wins = summary.get("gross_positive_security_pnl", 0)
    return {
        "selected_10bp_research_candidate": selected, "status": "descriptive_development_diagnostic",
        "positive_months": sum(float(r["net_return"]) > 0 for r in rows), "total_months": len(rows),
        "monthly_comparisons": comparisons, "three_worst_months": [compact(r) for r in ordered[:3]],
        "three_best_months": [compact(r) for r in ordered[-3:][::-1]],
        "top3_positive_months_share_of_gross_positive_month_pnl": sum(max(0, float(r["net_pnl"])) for r in ordered[-3:]) / positive if positive else None,
        "top3_negative_months_share_of_gross_negative_month_pnl": -sum(min(0, float(r["net_pnl"])) for r in ordered[:3]) / negative if negative else None,
        "top5_winning_securities": winners, "top5_losing_securities": summary.get("top5_losers", []),
        "top_winning_security_share_of_gross_winning_security_pnl": winners[0][1] / gross_wins if gross_wins and winners else None,
        "top5_winning_securities_share_of_gross_winning_security_pnl": sum(r[1] for r in winners) / gross_wins if gross_wins else None,
        "top5_loss_share_of_gross_losses": summary.get("top5_loss_share_of_gross_losses"),
        "no_security_exclusion_or_counterfactual_backtest": True,
        "limitations": "Monthly comparisons are24dependent development observations, not an independent validation. Holdings counts and actual exposure differ. Gross positive/negative contribution denominators are not net profit."
    }


def plot_month_end(cases, output):
    """One chart, only actual observed month-end balances; no daily invention."""
    lookup = {(c["summary"]["mode"], c["summary"]["cost_bps"]): c for c in cases}
    if any((mode, 10) not in lookup for mode in MODES):
        raise ValueError("Plot waits for all seven registered10bp cases")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter
    colors = {"eq": "#777777", "spy": "#20252B", "mom20": "#D98B2B", "trend63": "#286FB4",
              "ridge": "#9467BD", "trend63_risk": "#15856F", "ridge_risk": "#C84B55"}
    labels = {"eq": "Equal100", "spy": "SPY", "mom20": "Momentum20", "trend63": "Trend63 ex20",
              "ridge": "Annual Ridge", "trend63_risk": "Trend63 + risk", "ridge_risk": "Ridge + risk"}
    fig, ax = plt.subplots(figsize=(11, 6.6), dpi=160)
    manifest = {}
    for mode in MODES:
        case = lookup[(mode, 10)]
        rows = sorted(case["monthly"], key=lambda r: r["month"])
        if len(rows) != 24:
            raise ValueError("Incomplete monthly series: " + mode)
        dates = [datetime(2022, 1, 1)] + [datetime.fromisoformat(r["last_close_date"]) for r in rows]
        values = [100000.0] + [float(r["end_equity"]) for r in rows]
        ax.plot(dates, values, color=colors[mode], linewidth=1.8 if mode not in ("eq", "spy") else 2.2,
                marker="o", markersize=2.7, label=labels[mode])
        csv_path = Path(case["directory"]) / "monthly.csv"
        manifest[mode] = {"source": str(csv_path), "sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest(),
                          "observed_month_end_points": len(rows), "initial_capital_point": 100000}
    ax.axhline(100000, color="#A0A5AA", linewidth=.8, linestyle="--")
    ax.axvline(datetime(2023, 1, 1), color="#C0C4C8", linewidth=.8, linestyle=":")
    ax.set_title("Dynamic universe | 2022-2023 development", loc="left", fontsize=16, pad=18)
    ax.set_ylabel("Account equity (USD)")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda value, position: "$" + format(value / 1000, ".0f") + "k"))
    ax.grid(axis="y", color="#E8EAED", linewidth=.7)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(loc="upper left", ncol=2, frameon=False, fontsize=9)
    fig.text(.09, .035, "Observed month-end balances plus initial cash; connecting lines do not show intramonth drawdown.\n"
             "All seven fixed10bp configurations. Development evidence; no2026 data or forward performance.", fontsize=9, color="#555B62")
    fig.tight_layout(rect=(0, .09, 1, 1))
    fig.savefig(output / "month_end_equity.png", dpi=160)
    plt.close(fig)
    (output / "PLOT_SOURCES.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--plot", action="store_true", help="One actual month-end chart after all seven10bp cases exist")
    args = parser.parse_args()
    cases, omitted = read_cases(args.cases)
    rows, annual, monthly, evidence = compare(cases)
    evidence["omitted_cases"] = omitted
    args.output.mkdir(parents=True, exist_ok=True)
    write_csv(args.output / "results.csv", rows)
    write_csv(args.output / "annual.csv", annual)
    write_csv(args.output / "monthly.csv", monthly)
    (args.output / "COMPARISON.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output / "CANDIDATE_DIAGNOSTICS.json").write_text(json.dumps(candidate_diagnostics(cases, evidence), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.plot:
        plot_month_end(cases, args.output)
    print(json.dumps({"validated_cases": len(cases), "selection": evidence["selection"],
                      "common_source_configuration": evidence["common_source_configuration"],
                      "omitted_cases": omitted}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
