"""Run only as a QuantConnect cloud Research notebook cell after login.

DOCUMENTED API, NOT CLOUD-EXECUTED during v14. No orders, training, file writes,
Object Store, external requests, raw-data export, or 2026 history requests.
See data/experiments/historical_data_sample_v14/QC_CLOUD_CHECK.md.
"""
from datetime import datetime
import json
import math

from AlgorithmImports import (
    DataNormalizationMode, Delisting, DelistingType, Market, QuantBook,
    Resolution, SecurityIdentifier, Symbol, SymbolChangedEvent, TimeZones,
    TradeBar,
)


# Purposefully selected interface cases, not an investable universe or index.
# End is exclusive; every requested observation window ends before 2026.
CASES = (
    ("AAPL", "AAPL", "2020-12-14", "2020-12-24"),
    ("TSLA", "TSLA", "2020-12-14", "2020-12-24"),
    ("META", "FB", "2022-06-06", "2022-06-14"),
    ("TWTR", "TWTR", "2022-10-24", "2022-11-04"),
    ("SIVB", "SIVB", "2023-03-06", "2023-04-04"),
    ("ATVI", "ATVI", "2023-10-09", "2023-10-20"),
)


def historical_symbol(ticker, as_of):
    sid = SecurityIdentifier.generate_equity(
        ticker, Market.USA, mapping_resolve_date=as_of
    )
    return Symbol(sid, ticker)


def check_cloud_sample():
    qb = QuantBook()
    qb.set_time_zone(TimeZones.NEW_YORK)
    qb.set_start_date(2025, 12, 31)
    qb.set_end_date(2025, 12, 31)
    qb.settings.seed_initial_prices = False
    qb.universe_settings.fill_forward = False
    qb.universe_settings.data_normalization_mode = DataNormalizationMode.RAW
    symbols, output = {}, {}

    for name, ticker, first, last in CASES:
        start, end = datetime.fromisoformat(first), datetime.fromisoformat(last)
        if not start < end < datetime(2026, 1, 1):
            raise ValueError("Only fixed pre-2026 windows are allowed")
        item = output[name] = {"requested_start": first, "requested_end_exclusive": last}
        try:
            symbol = historical_symbol(ticker, start)
            qb.add_security(
                symbol, Resolution.DAILY, fill_forward=False,
                extended_market_hours=False,
                data_normalization_mode=DataNormalizationMode.RAW,
            )
            symbols[name] = symbol
            item["identity"] = "date-resolved SID; presence requires history evidence"
        except Exception as exc:
            item["identity"] = "unavailable"
            item["error_type"] = type(exc).__name__  # never dump provider payloads
            continue

        try:
            bars = list(qb.history[TradeBar](symbol, start, end, Resolution.DAILY,
                                           fill_forward=False,
                                           data_normalization_mode=DataNormalizationMode.RAW))
            ends = [bar.end_time for bar in bars]
            bad_finite = bad_order = 0
            for bar in bars:
                o, h, l, c, v = map(float, (bar.open, bar.high, bar.low, bar.close, bar.volume))
                bad_finite += not all(math.isfinite(x) for x in (o, h, l, c, v))
                bad_order += not (0 < l <= min(o, c) <= max(o, c) <= h and v >= 0)
            item["prices"] = {
                "query": "completed", "rows": len(bars),
                "duplicate_end_times": len(ends) - len(set(ends)),
                "nonfinite_rows": bad_finite, "invalid_ohlcv_rows": bad_order,
                "unexpected_year_rows": sum(t.year > 2025 for t in ends),
                "interpretation": "No fill forward; empty does not prove a halt or delisting",
            }
            del bars, ends
        except Exception as exc:
            item["prices"] = {"query": "unavailable", "error_type": type(exc).__name__}

        item["lifecycle"] = {}
        for label, data_type in (("symbol_changes", SymbolChangedEvent), ("delistings", Delisting)):
            try:
                events = list(qb.history[data_type](symbol, start, end))
                summary = {"query": "completed", "rows": len(events),
                           "interpretation": "Empty is unknown; engine time is not announcement evidence"}
                if data_type is Delisting:
                    summary["warning_rows"] = sum(e.type == DelistingType.WARNING for e in events)
                    summary["delisted_rows"] = sum(e.type == DelistingType.DELISTED for e in events)
                item["lifecycle"][label] = summary
                del events
            except Exception as exc:
                item["lifecycle"][label] = {"query": "unavailable", "error_type": type(exc).__name__}

    # Compare mapping continuity in memory; do not print raw provider SID/map rows.
    try:
        before = historical_symbol("FB", datetime(2022, 6, 8))
        after = historical_symbol("META", datetime(2022, 6, 10))
        mapping_check = {"query": "completed", "fb_meta_same_sid": before.id == after.id}
    except Exception as exc:
        mapping_check = {"query": "unavailable", "error_type": type(exc).__name__}

    # Research universe selection, not S&P index membership. Official QuantBook
    # universe_history applies this filter; no complete universe table is exported.
    wanted = {str(symbol.id) for symbol in symbols.values()}
    try:
        universe = qb.add_universe(lambda facts: [f.symbol for f in facts if str(f.symbol.id) in wanted])
        for name, _, first, last in CASES:
            if name not in symbols:
                continue
            try:
                series = qb.universe_history(universe, datetime.fromisoformat(first),
                                             datetime.fromisoformat(last))
                matched = sum(any(f.symbol.id == symbols[name].id for f in row)
                              for row in series.values)
                output[name]["research_universe"] = {
                    "query": "completed", "selection_records": len(series),
                    "records_containing_case_sid": matched,
                    "meaning": "Trading-stock universe coverage, not index membership",
                }
                del series
            except Exception as exc:
                output[name]["research_universe"] = {"query": "unavailable", "error_type": type(exc).__name__}
    except Exception as exc:
        for item in output.values():
            item["research_universe"] = {"query": "unavailable", "error_type": type(exc).__name__}

    print(json.dumps({
        "mode": "cloud read-only metadata inspection; not a return study",
        "price_mode": "RAW", "fill_forward": False,
        "scope": "six deliberately selected cases, not complete history",
        "cases": output, "mapping_check": mapping_check,
        "not_established": ["announcement availability", "original received vintage",
                            "OTC continuation", "terminal recovery", "cash settlement",
                            "index membership", "complete universe coverage"],
    }, indent=2))


# Intentionally no automatic run. In the cloud notebook, call:
# check_cloud_sample()
