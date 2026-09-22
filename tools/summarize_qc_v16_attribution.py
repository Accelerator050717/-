"""Decode permitted v16 financial aggregates; never requests market data.

Usage: python tools/summarize_qc_v16_attribution.py --input <cloud-log-or-json>
  --out data/experiments/momentum_loss_attribution_v16
Optional SPY CSV columns: month, net_return (decimal), source, valuation_basis.
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import math
from pathlib import Path
import zlib
import lzma


ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "data/experiments/dynamic_universe_pilot_v15/runs/B10.json"
FIELDS = ("price_pnl", "dividends", "split_cash", "fees", "net_pnl")


def decode(text):
    if "V16_ATTRIBUTION " in text:
        start = text.index("V16_ATTRIBUTION ") + len("V16_ATTRIBUTION ")
        obj, _ = json.JSONDecoder().raw_decode(text[start:].lstrip())
    else:
        obj = json.loads(text)
    receipt = {}
    if "encoding" in obj:
        if obj["encoding"] not in ("zlib-base64-derived-financial-records", "lzma-base64-derived-financial-records"):
            raise ValueError("Unrecognized encoding")
        compressed = base64.b64decode(obj["data"], validate=True)
        raw = lzma.decompress(compressed) if obj["encoding"].startswith("lzma") else zlib.decompress(compressed)
        digest = hashlib.sha256(raw).hexdigest()
        if digest != obj["sha256"] or len(raw) != obj["bytes"]:
            raise ValueError("Cloud aggregate transport hash/size mismatch")
        receipt = {"decoded_sha256": digest, "decoded_bytes": len(raw), "transport_verified": True}
        obj = json.loads(raw)
    if obj.get("schema") != "v16-compact-1":
        raise ValueError("Not a v16 compact financial artifact")
    return obj, receipt


def restore_monthly_runtime(payload, runtime, allow_missing_expected_hash=False):
    """Read24 ordinary financial display strings and verify exact-string hash."""
    runtime = runtime.get("runtime_stats", runtime)
    keys = [f"v16 M{y}-{m:02d}" for y in (2022, 2023) for m in range(1, 13)]
    selected = {k: " ".join(str(runtime[k]).split()) for k in keys}
    digest = hashlib.sha256(json.dumps(selected, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    expected = payload.get("monthly_runtime_sha256")
    if expected is None and not allow_missing_expected_hash:
        raise ValueError("Expected runtime hash missing; explicit partial-evidence mode required")
    if expected is not None and digest != expected:
        raise ValueError("Readable monthly runtime financial data hash mismatch")
    rows, spy = [], []
    previous = 100000.0
    for key in keys:
        amounts = {k: float(v) for k, v in (word.split("=", 1) for word in selected[key].split())}
        if set(amounts) != set("BCFDSR"):
            raise ValueError("Monthly runtime fields incomplete")
        net = amounts["B"] - previous
        price = net - amounts["D"] - amounts["S"] + amounts["F"] - amounts["R"]
        rows.append([key[-7:], previous, amounts["B"], price, amounts["D"], amounts["S"], amounts["F"], net, amounts["R"]])
        spy.append([key[-7:], amounts["C"]])
        previous = amounts["B"]
    payload["month_fields"] = ["month", "begin_equity", "end_equity", "price_pnl", "dividends", "split_cash", "fees", "net_pnl", "residual"]
    payload["months"] = rows
    payload.setdefault("spy_reference", {"original_backtest": "0d921feb058a7e18dac120f1d27097b8", "all_checks_pass": None,
        "metadata_status": "Original C10 identity from frozen reference source; final cloud metadata not recovered"})
    payload["spy_reference"]["month_fields"] = ["month", "end_equity"]
    payload["spy_reference"]["months"] = spy
    payload["monthly_price_derivation"] = "NAV change + fees - dividends - split cash - recorded residual; all input money full precision"
    return {"monthly_runtime_verified": expected is not None, "monthly_runtime_sha256": digest, "rows": 24,
            "expected_hash_status": "matched" if expected is not None else "missing in truncated log; independent money checks required"}


def restore_rankings(payload):
    if payload.get("rankings", {}).get("all", {}).get("worst_from_priority_entries"):
        priority = expand(payload, "priority_entries", "priority_entry_fields")
        worst = sorted(priority, key=lambda r: (r["net_pnl"], r["sid"], r["episode_id"]))[:10]
        payload["rankings"]["all"]["worst"] = [[r["episode_id"], r["sid_index"], r["entry"], r["exit"], r["net_pnl"]] for r in worst]


def expand(payload, name, schema):
    fields = payload.get(schema, [])
    rows = payload.get(name, [])
    result = []
    for row in rows:
        if len(row) != len(fields):
            raise ValueError(f"{name} row differs from its schema")
        record = dict(zip(fields, row))
        if "sid_index" in record:
            sid, ticker = payload["ids"][record["sid_index"]]
            record.update(sid=sid, latest_observed_ticker=ticker, engine_symbol_value=ticker)
        result.append(record)
    return result


def assert_close(a, b, context, tolerance=1e-7):
    if not math.isfinite(a) or not math.isfinite(b) or abs(a - b) > tolerance:
        raise ValueError(f"{context}: {a!r} vs {b!r}")


def csv_write(path, rows):
    if not rows:
        return
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def summarize(payload, baseline):
    monthly = expand(payload, "months", "month_fields")
    securities = expand(payload, "securities", "security_fields")
    corporate = {(r["sid_index"], r["year"]): r for r in expand(payload, "corporate_by_security", "corporate_fields")}
    for row in securities:
        cash = corporate.get((row["sid_index"], row["year"]), {})
        row.setdefault("dividends", cash.get("dividends", 0.0))
        row.setdefault("split_cash", cash.get("split_cash", 0.0))
        row.setdefault("net_pnl", row["price_pnl"] + row["dividends"] + row["split_cash"] - row["fees"])
    if len(monthly) != 24 or [r["month"] for r in monthly] != [f"{y}-{m:02d}" for y in (2022, 2023) for m in range(1, 13)]:
        raise ValueError("Full 24-month sequence not preserved")
    previous = 100000.0
    for row in monthly:
        row.setdefault("begin_equity", previous)
        row.setdefault("net_pnl", row["end_equity"] - row["begin_equity"])
        assert_close(row["begin_equity"], previous, "month continuity")
        assert_close(row["end_equity"] - row["begin_equity"], row["net_pnl"], "month NAV/P&L")
        assert_close(row["price_pnl"] + row["dividends"] + row["split_cash"] - row["fees"] + row["residual"], row["net_pnl"], "month components")
        row["net_return"] = row["end_equity"] / row["begin_equity"] - 1
        previous = row["end_equity"]
    total_by_sid = {}
    for row in securities:
        assert_close(row["price_pnl"] + row["dividends"] + row["split_cash"] - row["fees"], row["net_pnl"], "security components")
        agg = total_by_sid.setdefault(row["sid"], {"sid": row["sid"], "latest_observed_ticker": row["latest_observed_ticker"], **{f: 0.0 for f in FIELDS}})
        for f in FIELDS:
            agg[f] += row[f]
    totals = {f: sum(row[f] for row in securities) for f in FIELDS}
    residual = sum(row["residual"] for row in monthly)
    assert_close(totals["net_pnl"] + residual, previous - 100000, "complete account P&L")
    assert_close(totals["fees"], payload["summary"]["fees"], "fees")
    assert_close(totals["dividends"], payload["comparison"]["dividends"], "dividends")
    assert_close(totals["split_cash"], payload["comparison"]["split_cash"], "fraction cash")
    annual = []
    concentrations = []
    for period in ("2022", "2023", "all"):
        month_rows = monthly if period == "all" else [r for r in monthly if r["month"].startswith(period)]
        observations = list(total_by_sid.values()) if period == "all" else [r for r in securities if r["year"] == period]
        profit = sum(r["net_pnl"] for r in month_rows)
        cumulative = math.prod(1 + r["net_return"] for r in month_rows) - 1
        assert_close(cumulative, month_rows[-1]["end_equity"] / month_rows[0]["begin_equity"] - 1, "monthly compounding")
        if period != "all":
            assert_close(cumulative, payload["comparison"]["annual"][period], "annual replay NAV")
        annual.append({"period": period, "begin_equity": month_rows[0]["begin_equity"], "end_equity": month_rows[-1]["end_equity"],
                       "net_pnl": profit, "net_return": cumulative, "negative_months": sum(r["net_pnl"] < 0 for r in month_rows), "months": len(month_rows)})
        losses = sorted([r for r in observations if r["net_pnl"] < 0], key=lambda r: (r["net_pnl"], r["sid"]))
        gross_loss = -sum(r["net_pnl"] for r in losses)
        for count in (1, 5, 10):
            contribution = -sum(r["net_pnl"] for r in losses[:count])
            concentrations.append({"period": period, "source_scope": "security period net P&L including fees/dividends",
                "top_n": count, "loss_dollars": contribution, "account_net_loss_denominator": -profit if profit < 0 else None,
                "share_of_account_net_loss": contribution / -profit if profit < 0 else None,
                "gross_losing_security_pnl_denominator": gross_loss,
                "share_of_gross_losing_security_pnl": contribution / gross_loss if gross_loss else None,
                "losing_securities": len(losses), "securities": len(observations)})
    original = baseline["summary"][0]
    comparisons = {}
    for key, observed in (("final_equity", previous), ("fees_paid", payload["summary"]["fees"]),
                          ("traded_notional", payload["comparison"]["notional"]),
                          ("dividend_cash_engine_proxy", payload["comparison"]["dividends"]),
                          ("split_fraction_cash_engine_proxy", payload["comparison"]["split_cash"])):
        comparisons[key] = {"original": original[key], "diagnostic": observed, "difference": observed - original[key]}
    comparisons["fills"] = {"original": original["stats"]["fills"], "diagnostic": payload["summary"]["fills"],
                             "difference": payload["summary"]["fills"] - original["stats"]["fills"]}
    comparisons["annual_returns"] = {y: {"original": original["annual_returns"][y], "diagnostic": payload["comparison"]["annual"][y],
                                        "difference": payload["comparison"]["annual"][y] - original["annual_returns"][y]} for y in ("2022", "2023")}
    comparisons["month_hash_matches"] = payload["comparison"]["month_sha256"] == baseline["month_check"][0]["packed_sha256"]
    comparisons["base_executable_hash_matches"] = payload["identity"]["base_ast_sha256"] == baseline["identity"][0]["executable_ast_sha256"]
    comparisons["all_available_comparisons_match"] = (all(abs(v["difference"]) <= 1e-7 for k, v in comparisons.items() if isinstance(v, dict) and "difference" in v)
        and all(abs(v["difference"]) <= 1e-12 for v in comparisons["annual_returns"].values())
        and comparisons["month_hash_matches"] and comparisons["base_executable_hash_matches"])
    verification = {"schema": "v16-attribution-verification-1", "monetary_totals": totals,
        "final_equity": previous, "net_pnl": previous - 100000, "unexplained_account_residual": residual,
        "max_daily_cash_residual": payload["summary"]["max_cash_residual"],
        "observer_checks": payload["summary"]["checks"], "original_comparison": comparisons,
        "omitted_due_free_log_budget": payload.get("omitted_due_free_log_budget"),
        "unavailable_detail_keys": [k for k in ("episodes", "focus_fills", "focus_decisions", "events") if k not in payload],
        "ticker_column_limit": "latest_observed_ticker is retained as a compatibility name for engine Symbol.Value; it can be an old mapped ticker. Use stable SID and documented date-specific aliases.",
        "boundary": "matches are actual compared aggregates, not proof every original fill/close equals replay"}
    return monthly, securities, list(total_by_sid.values()), annual, concentrations, verification


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--spy-monthly", type=Path)
    parser.add_argument("--runtime-stats", type=Path, help="JSON dictionary of exact24 v16 MYYYY-MM financial runtime strings")
    parser.add_argument("--partial-evidence", action="store_true", help="Explicitly allow strictly recovered complete fields whose full transport footer/hash is missing")
    args = parser.parse_args()
    payload, receipt = decode(args.input.read_text(encoding="utf-8-sig"))
    if "monthly_runtime_sha256" in payload or args.partial_evidence:
        if not args.runtime_stats:
            raise ValueError("This diagnostic requires its24 readable runtime monthly records")
        runtime = json.loads(args.runtime_stats.read_text(encoding="utf-8-sig"))
        receipt.update(restore_monthly_runtime(payload, runtime, allow_missing_expected_hash=args.partial_evidence))
    if args.partial_evidence:
        receipt["transport_verified"] = False
        receipt["partial_evidence"] = "Only complete JSON values recovered from a truncated LZMA prefix; full payload SHA/footer unavailable"
    restore_rankings(payload)
    outputs = summarize(payload, json.loads(BASELINE.read_text()))
    monthly, securities, totals, annual, concentrations, verification = outputs
    if "spy_reference" in payload:
        reference = payload["spy_reference"]
        spy_rows = {}
        previous_spy = 100000.0
        for values in reference["months"]:
            row = dict(zip(reference["month_fields"], values))
            row.setdefault("begin_equity", previous_spy)
            spy_rows[row["month"]] = row
            previous_spy = row["end_equity"]
        for row in monthly:
            spy = spy_rows.get(row["month"])
            row["spy_net_return"] = spy["end_equity"] / spy["begin_equity"] - 1 if spy else None
            row["spy_source"] = reference["original_backtest"]
            row["spy_valuation_basis"] = "Original C10 executions on observed regular closes; LEAN dividend cash"
            row["spy_parity_checks_pass"] = reference["all_checks_pass"]
        verification["spy_reference"] = {k: v for k, v in reference.items() if k != "months"}
    if args.spy_monthly:
        with args.spy_monthly.open(encoding="utf-8-sig", newline="") as stream:
            spy = {r["month"]: r for r in csv.DictReader(stream)}
        for row in monthly:
            reference = spy.get(row["month"])
            row["spy_net_return"] = float(reference["net_return"]) if reference else None
            row["spy_source"] = reference.get("source") if reference else None
            row["spy_valuation_basis"] = reference.get("valuation_basis") if reference else None
    args.out.mkdir(parents=True, exist_ok=True)
    csv_write(args.out / "monthly_pnl.csv", monthly)
    csv_write(args.out / "security_year_pnl.csv", securities)
    csv_write(args.out / "security_total_pnl.csv", sorted(totals, key=lambda r: (r["net_pnl"], r["sid"])))
    csv_write(args.out / "annual_pnl.csv", annual)
    csv_write(args.out / "loss_concentration.csv", concentrations)
    security_rankings = []
    for period in ("2022", "2023", "all"):
        candidates = totals if period == "all" else [r for r in securities if r["year"] == period]
        for direction, sign in (("worst", 1), ("best", -1)):
            selected = sorted(candidates, key=lambda r: (sign * r["net_pnl"], r["sid"]))[:10]
            for rank, row in enumerate(selected, 1):
                security_rankings.append({"period": period, "direction": direction, "rank": rank, **row})
    csv_write(args.out / "security_rankings.csv", security_rankings)
    for name, schema, filename in (("episodes", "episode_fields", "focus_episodes.csv"),
                                   ("focus_fills", "focus_fill_fields", "focus_fills.csv"),
                                   ("focus_decisions", "decision_fields", "focus_decisions.csv"),
                                   ("priority_entries", "priority_entry_fields", "priority_entries.csv")):
        csv_write(args.out / filename, expand(payload, name, schema))
    rank_rows = []
    episode_concentration = []
    for period, ranking in payload.get("rankings", {}).items():
        for direction in ("worst", "best"):
            for rank, values in enumerate(ranking.get(direction, []), 1):
                row = dict(zip(ranking["row_fields"], values))
                sid, ticker = payload["ids"][row["sid_index"]]
                row.update(period=period, direction=direction, rank=rank, sid=sid, latest_observed_ticker=ticker)
                rank_rows.append(row)
        pnl_index = ranking["row_fields"].index("net_pnl")
        account_net = next(r["net_pnl"] for r in annual if r["period"] == period)
        for count in (1, 5, 10):
            loss = -sum(min(0, r[pnl_index]) for r in ranking["worst"][:count])
            gross_losses = ranking["negative_episode_pnl_sum"]
            episode_concentration.append({"period": period, "source_scope": "flat-to-flat episode period net P&L including fees/dividends",
                "top_n": count, "loss_dollars": loss,
                "account_net_loss_denominator": -account_net if account_net < 0 else None,
                "share_of_account_net_loss": loss / -account_net if account_net < 0 else None,
                "gross_losing_episode_pnl_denominator": gross_losses,
                "share_of_gross_losing_episode_pnl": loss / gross_losses if gross_losses else None,
                "negative_episode_count": ranking["negative_count"], "episodes": ranking["episode_count"]})
    csv_write(args.out / "episode_rankings.csv", rank_rows)
    csv_write(args.out / "episode_loss_concentration.csv", episode_concentration)
    verification["transport"] = receipt
    (args.out / "DIAGNOSTIC_ATTRIBUTION.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.out / "ATTRIBUTION_VERIFICATION.json").write_text(json.dumps(verification, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(verification, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
