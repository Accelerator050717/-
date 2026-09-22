"""Paste into QuantConnect cloud Research; call check_cloud_supplement() separately.

Fixed v14 access checks only. Provider rows stay in memory in the cloud. Output
contains counts/booleans, never prices, amounts, provider IDs or member lists.
No local invocation, orders, files, Object Store, training or external requests.
"""
from datetime import datetime, timedelta
import json

from AlgorithmImports import (
    DataNormalizationMode, Dividend, Market, QuantBook, Resolution,
    SecurityIdentifier, Split, SplitType, Symbol, TimeZones,
)


def check_cloud_supplement():
    """Inspect fixed pre-2026 corporate actions and historical universe inputs."""
    qb = QuantBook()
    qb.set_time_zone(TimeZones.NEW_YORK)
    qb.set_start_date(2025, 12, 31)
    qb.set_end_date(2025, 12, 31)
    qb.settings.seed_initial_prices = False
    qb.universe_settings.fill_forward = False
    qb.universe_settings.data_normalization_mode = DataNormalizationMode.RAW
    cutoff = datetime(2026, 1, 1)
    output = {"mode": "cloud read-only supplemental metadata inspection"}

    # Public issuer dates are comparison inputs, not inferred settlement data.
    # https://www.apple.com/newsroom/2020/07/apple-reports-third-quarter-results/
    start, end = datetime(2020, 8, 3), datetime(2020, 9, 4)
    assert start < end < cutoff
    corporate = output["aapl_corporate_actions"] = {
        "requested_start": start.isoformat(), "requested_end_boundary": end.isoformat(),
        "public_payable_date": "2020-08-13", "public_split_trading_date": "2020-08-31",
        "interpretation": "Engine events do not prove original announcement receipt or actual cash settlement",
    }
    try:
        sid = SecurityIdentifier.generate_equity("AAPL", Market.USA, mapping_resolve_date=start)
        symbol = Symbol(sid, "AAPL")
        qb.add_security(symbol, Resolution.DAILY, fill_forward=False,
                        extended_market_hours=False,
                        data_normalization_mode=DataNormalizationMode.RAW)
        for label, data_type, fields in (
            ("dividends", Dividend, ("symbol", "time", "end_time", "distribution", "reference_price")),
            ("splits", Split, ("symbol", "time", "end_time", "type", "split_factor", "reference_price")),
        ):
            try:
                events = list(qb.history[data_type](symbol, start, end))
                item = {"query": "completed", "rows": len(events),
                        "fields_present_in_all_rows": {
                            field: all(hasattr(e, field) for e in events) if events else None
                            for field in fields},
                        "unexpected_year_rows": sum(e.end_time.year > 2025 for e in events)}
                if data_type is Dividend:
                    item["any_event_matches_public_payable_date"] = (
                        any((e.end_time.year, e.end_time.month, e.end_time.day) == (2020, 8, 13)
                            for e in events) if events else None)
                else:
                    occurred = [e for e in events if e.type == SplitType.SPLIT_OCCURRED]
                    item["warning_rows"] = sum(e.type == SplitType.WARNING for e in events)
                    item["occurred_rows"] = len(occurred)
                    item["occurred_event_matches_public_split_trading_date"] = (
                        any((e.end_time.year, e.end_time.month, e.end_time.day) == (2020, 8, 31)
                            for e in occurred) if occurred else None)
                    del occurred
                corporate[label] = item
                del events
            except Exception as exc:
                corporate[label] = {"query": "unavailable", "error_type": type(exc).__name__}
    except Exception as exc:
        corporate["identity_query"] = {"query": "unavailable", "error_type": type(exc).__name__}

    # These are fixed request intervals, not a current list of survivors. LEAN's
    # history time filter uses start < EndTime <= end. Fundamental observations
    # normally have EndTime on the next date; this delivery convention is not
    # proof of original vendor receipt/announcement time. Do not label all input
    # observations as known at the requested day's opening.
    # Fundamental universe coverage is not an index or the complete OTC market.
    windows = (
        ("twtr_before", "TWTR", datetime(2022, 10, 24)),
        ("twtr_after", "TWTR", datetime(2022, 11, 2)),
        ("sivb_before", "SIVB", datetime(2023, 3, 6)),
        ("sivb_after", "SIVB", datetime(2023, 4, 3)),
    )
    universe_output = output["historical_fundamental_universe"] = {}
    wanted, identity_errors = {}, {}
    for ticker, as_of in (("TWTR", datetime(2022, 10, 24)), ("SIVB", datetime(2023, 3, 6))):
        try:
            sid = SecurityIdentifier.generate_equity(ticker, Market.USA, mapping_resolve_date=as_of)
            wanted[ticker] = str(sid)
        except Exception as exc:
            identity_errors[ticker] = type(exc).__name__

    # Only transient sets are retained for membership/difference checks. They
    # never enter output, files, the Object Store, or external requests.
    selected_ids = set(wanted.values())
    capture = {"calls": [], "ids": set(), "start": None, "end": None}

    def capture_filter(facts):
        rows = list(facts)
        ids = {str(f.symbol.id) for f in rows}
        first, last = capture["start"], capture["end"]
        capture["ids"].update(ids)
        capture["calls"].append({
            "candidate_rows": len(rows), "unique_sid_count": len(ids),
            "duplicate_sid_rows": len(rows) - len(ids),
            "case_present": {name: value in ids if ids else None for name, value in wanted.items()},
            "unexpected_year_rows": sum(f.end_time.year > 2025 for f in rows),
            "time_boundary_counts": {
                "observation_time_before_start": sum(f.time < first for f in rows),
                "observation_time_start_through_before_end": sum(first <= f.time < last for f in rows),
                "observation_time_at_or_after_end": sum(f.time >= last for f in rows),
                "end_time_at_or_before_start": sum(f.end_time <= first for f in rows),
                "end_time_after_start_through_end": sum(first < f.end_time <= last for f in rows),
                "end_time_after_end": sum(f.end_time > last for f in rows),
                "observation_date_before_own_end_time_date": sum(
                    (f.time.year, f.time.month, f.time.day) <
                    (f.end_time.year, f.end_time.month, f.end_time.day) for f in rows),
                "prior_observation_delivered_in_request": sum(
                    f.time < first < f.end_time <= last for f in rows),
            },
        })
        return [f.symbol for f in rows if str(f.symbol.id) in selected_ids]

    sets_by_window = {}
    try:
        universe = qb.add_universe(capture_filter)
        for label, ticker, first in windows:
            last = first + timedelta(days=1)
            assert first < last < cutoff
            item = universe_output[label] = {
                "requested_start": first.isoformat(), "requested_end_boundary": last.isoformat(),
                "target_identity_error_type": identity_errors.get(ticker),
            }
            capture["calls"], capture["ids"] = [], set()
            capture["start"], capture["end"] = first, last
            try:
                series = qb.universe_history(universe, first, last)
                item.update({"query": "completed", "selection_records": len(series),
                             "filter_calls": capture["calls"],
                             "case_present_in_any_filter_input": (
                                 wanted[ticker] in capture["ids"]
                                 if ticker in wanted and capture["ids"] else None)})
                if capture["ids"]:
                    sets_by_window[label] = capture["ids"]
                del series
            except Exception as exc:
                item.update({"query": "unavailable", "error_type": type(exc).__name__})
    except Exception as exc:
        universe_output["setup"] = {"query": "unavailable", "error_type": type(exc).__name__}

    differences = output["universe_input_set_differences"] = {}
    for ticker, before, after in (("TWTR", "twtr_before", "twtr_after"),
                                 ("SIVB", "sivb_before", "sivb_after")):
        if before in sets_by_window and after in sets_by_window:
            old, new = sets_by_window[before], sets_by_window[after]
            differences[ticker] = {"query": "completed", "same_sid_set": old == new,
                                   "removed_sid_count": len(old - new),
                                   "added_sid_count": len(new - old)}
        else:
            differences[ticker] = {"query": "unavailable", "reason": "missing_nonempty_filter_observations"}
    output["time_interpretation"] = (
        "Requested boundaries are compared with each observation's Time and EndTime; "
        "LEAN history uses start < EndTime <= end. A later EndTime models delivery "
        "after the observation date, not independently verified announcement or receipt time."
    )
    output["not_established"] = [
        "full historical universe coverage", "index membership", "original vendor receipt/vintage",
        "announcement availability", "halt cause", "OTC continuation", "terminal recovery", "cash settlement",
    ]
    print(json.dumps(output, indent=2))


# Intentionally no automatic run. Execute check_cloud_supplement() in Research.
