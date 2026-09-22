r"""Inspect existing pre-2026 Yahoo snapshots; never fetch or print price values.

Run from the repository: .venv\Scripts\python.exe tools/check_v14_price_coverage.py
Raw files are read-only. Only the v14 JSON/Markdown check summaries are written.
"""

from __future__ import annotations

import hashlib
import json
import os
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd
import pandas_market_calendars as mcal


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw"
OUT = ROOT / "data/experiments/historical_data_sample_v14"
START, END = "2020-01-01", "2025-12-31"
LIMIT = pd.Timestamp("2026-01-01")
SYMBOLS = ("AAPL", "META")
ABSENT_CANDIDATES = ("TSLA", "SIVB", "SIVBQ", "TWTR", "ATVI")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def price_filename_inventory() -> dict[str, list[str]]:
    """Names only: prune any directory/file containing 2026, including SEC facts."""
    result = {symbol: [] for symbol in ABSENT_CANDIDATES}
    for directory, children, files in os.walk(RAW):
        children[:] = sorted(name for name in children if "2026" not in name)
        for name in sorted(files):
            path = Path(directory) / name
            if "2026" in name or path.suffix.lower() not in {".csv", ".parquet", ".feather"}:
                continue
            for symbol in result:
                if path.stem.upper() == symbol:
                    result[symbol].append(relative(path))
    return result


def inspect(symbol: str, sessions: pd.DatetimeIndex) -> dict:
    path = RAW / "extended_2012_2025" / f"{symbol}.csv"
    metadata_path = path.with_suffix(".json")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

    # Inspect only dates before opening price columns. Refuse mixed/2026 files.
    dates = pd.to_datetime(pd.read_csv(path, usecols=["Date"])["Date"], errors="raise")
    if dates.isna().any() or (dates >= LIMIT).any():
        raise ValueError(f"{relative(path)} has missing or disallowed observation dates")
    frame = pd.read_csv(path)
    frame["Date"] = dates
    sample = frame.loc[dates.between(START, END)].copy()
    observed = pd.DatetimeIndex(sample["Date"].unique()).sort_values()
    numeric = sample.drop(columns="Date").apply(pd.to_numeric, errors="raise")
    ohlc = numeric[["Open", "High", "Low", "Close"]]
    bad_ohlc = (
        (ohlc["High"] + 1e-10 < ohlc[["Open", "Close", "Low"]].max(axis=1))
        | (ohlc["Low"] - 1e-10 > ohlc[["Open", "Close", "High"]].min(axis=1))
    )
    missing = sessions.difference(observed).strftime("%Y-%m-%d").tolist()
    unexpected = observed.difference(sessions).strftime("%Y-%m-%d").tolist()
    digest = sha256(path)
    checks = {
        "csv_sha256_matches_metadata": digest == metadata["sha256"],
        "symbol_matches_metadata": metadata["symbol"] == symbol,
        "all_file_dates_before_2026": bool((dates < LIMIT).all()),
        "all_file_rows_match_metadata": len(frame) == metadata["rows"],
        "columns_match_metadata": frame.columns.tolist() == ["Date", *metadata["columns"]],
        "auto_adjust_false": metadata["parameters"]["auto_adjust"] is False,
        "back_adjust_false": metadata["parameters"]["back_adjust"] is False,
        "sample_dates_unique": not sample["Date"].duplicated().any(),
        "sample_dates_increasing": sample["Date"].is_monotonic_increasing,
        "sample_no_missing": not sample.isna().any().any(),
        "sample_numeric_finite": bool(np.isfinite(numeric.to_numpy()).all()),
        "sample_prices_positive": bool((numeric[["Open", "High", "Low", "Close", "Adj Close"]] > 0).all().all()),
        "sample_volume_nonnegative": bool((numeric["Volume"] >= 0).all()),
        "sample_ohlc_relations_valid": not bool(bad_ohlc.any()),
        "sample_matches_nyse_sessions": not missing and not unexpected,
    }
    return {
        "symbol": symbol,
        "csv_path": relative(path),
        "csv_bytes": path.stat().st_size,
        "csv_sha256": digest,
        "metadata_path": relative(metadata_path),
        "metadata_sha256": sha256(metadata_path),
        "source": metadata["source"],
        "downloaded_at_utc": metadata["downloaded_at_utc"],
        "parameters": metadata["parameters"],
        "source_timezone": metadata["source_timezone"],
        "all_file_rows": len(frame),
        "all_file_date_min": dates.min().strftime("%Y-%m-%d"),
        "all_file_date_max": dates.max().strftime("%Y-%m-%d"),
        "sample_rows": len(sample),
        "sample_date_min": sample["Date"].min().strftime("%Y-%m-%d"),
        "sample_date_max": sample["Date"].max().strftime("%Y-%m-%d"),
        "columns": frame.columns.tolist(),
        "duplicate_date_rows": int(sample["Date"].duplicated().sum()),
        "missing_by_column": {key: int(value) for key, value in sample.isna().sum().items()},
        "invalid_ohlc_rows": int(bad_ohlc.sum()),
        "missing_expected_session_dates": missing,
        "unexpected_session_dates": unexpected,
        "checks": {key: bool(value) for key, value in checks.items()},
        "format_checks_pass": all(checks.values()),
        "ticker_boundary_rows_present": {
            date: bool((sample["Date"] == pd.Timestamp(date)).any())
            for date in ("2022-06-08", "2022-06-09")
        } if symbol == "META" else None,
    }


def main() -> None:
    plan = json.loads((OUT / "plan.json").read_text(encoding="utf-8"))
    assert plan["observation_start"] == START and plan["observation_end"] == END
    schedule = mcal.get_calendar("NYSE").schedule(start_date=START, end_date=END)
    sessions = pd.DatetimeIndex(schedule.index).tz_localize(None).normalize()
    results = [inspect(symbol, sessions) for symbol in SYMBOLS]
    report = {
        "kind": "existing_local_price_snapshot_coverage_not_a_return_backtest",
        "plan_sha256": sha256(OUT / "plan.json"),
        "script_sha256": sha256(Path(__file__)),
        "read_network": False,
        "read_2026_observations": False,
        "observation_start": START,
        "observation_end": END,
        "calendar": "pandas_market_calendars NYSE session dates (New York trading calendar)",
        "calendar_package_version": version("pandas_market_calendars"),
        "expected_sessions": len(sessions),
        "sample_security_count": len(plan["sample"]),
        "price_snapshots_checked": len(results),
        "historical_price_filename_matches": price_filename_inventory(),
        "securities": results,
        "both_snapshots_have_same_complete_sample_dates": all(item["checks"]["sample_matches_nyse_sessions"] for item in results),
        "format_checks_pass": all(item["format_checks_pass"] for item in results),
        "coverage_is_complete": False,
        "historical_ticker_identity_verified_by_prices_alone": False,
        "terminal_return_or_cash_receipt_verified": False,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "PRICE_COVERAGE.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Existing local historical price coverage",
        "",
        f"Read-only inputs; no downloads, training, return backtests, broker connections or 2026 observations. Checked window: {START} through {END}; NYSE calendar: {len(sessions)} sessions.",
        "",
        "| Snapshot | Whole-file dates / rows | Checked sample rows | Hash / format | Missing sessions / duplicates / invalid OHLC |",
        "|---|---|---:|---|---|",
    ]
    for item in results:
        lines.append(f"| {item['symbol']} | {item['all_file_date_min']} to {item['all_file_date_max']} / {item['all_file_rows']} | {item['sample_rows']} | {'PASS' if item['format_checks_pass'] else 'FAIL'} | {len(item['missing_expected_session_dates'])} / {item['duplicate_date_rows']} / {item['invalid_ohlc_rows']} |")
    lines.extend([
        "",
        "Only AAPL and META snapshots were opened. The five-name filename-only search (TSLA, SIVB, SIVBQ, TWTR, ATVI) prunes all 2026-named directories/files and reads no matching contents. Results are recorded explicitly in JSON; an absent local file does not mean the security lacked historical trading.",
        "",
        f"META boundary-record presence: {results[1]['ticker_boundary_rows_present']}. The JSON date-alignment checks determine whether the period has a session gap. This is a current-META-labelled vendor series, not proof that the old FB ticker, share class and legal security identity were correctly mapped historically. Independent identity evidence is still required. AAPL/META are Nasdaq listings; the NYSE calendar is a US session-date alignment proxy here, not a claim about their listing venue or intraday tradeability.",
        "",
        "Metadata records Yahoo/yfinance snapshots obtained in September 2026 with auto_adjust=False and back_adjust=False; the maximum observed date in each file is still 2025-12-31. The acquisition timestamp is not an information-availability timestamp for every historical observation. These settings do not guarantee untouched, original-vintage executable quotations: Yahoo historical OHLC can incorporate split conventions, and Adj Close incorporates vendor adjustment/revision history. Never mix adjusted prices with an independently applied identical dividend or terminal return.",
        "",
        "Neither snapshot provides the missing sample securities' final market prices, delisting returns, takeover receivables or actual reusable cash receipt dates. Unknown terminal proceeds stay unknown; no terminal return is imputed and no final-bar liquidation is assumed. Passing schema and date alignment does not make this six-security lifecycle sample sufficient for return research or eliminate the original 30-stock survivorship bias.",
        "",
        "Reproduce: `.venv\\Scripts\\python.exe tools/check_v14_price_coverage.py`. Only PRICE_COVERAGE.json and this summary are written. No price values are exported in either summary. SHA256, acquisition metadata, missing-date lists and check outcomes are in the JSON.",
    ])
    (OUT / "PRICE_COVERAGE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"format_checks_pass": report["format_checks_pass"], "checked_prices": len(results), "expected_sessions": len(sessions), "sample_rows": {item["symbol"]: item["sample_rows"] for item in results}, "other_price_filename_matches": report["historical_price_filename_matches"]}))
    if not report["format_checks_pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
