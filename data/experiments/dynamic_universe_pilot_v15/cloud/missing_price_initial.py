"""Prepared v15 cloud Research diagnostic; NOT executed merely by importing.

Call check_v15_missing_prices() in the permitted QuantConnect Research cloud.
Eight fixed <=2023 cases only. No model, orders, downloads or Object Store.
Returned counts/timestamps do not prove when the original stream delivered data.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math

from AlgorithmImports import (
    DataNormalizationMode, Market, QuantBook, Resolution,
    SecurityIdentifier, Symbol, TimeZones, TradeBar,
)


CASES = (
    ("WDAY", "2022-06-15"),
    ("MDT", "2022-09-23"),
    ("QCOM", "2022-09-28"),
    ("QCOM", "2022-10-03"),
    ("CSCO", "2022-10-21"),
    ("MSFT", "2022-12-02"),
    ("GOOG", "2023-04-13"),
    ("AMZN", "2023-06-28"),
)


def check_v15_missing_prices():
    qb = QuantBook()
    qb.set_time_zone(TimeZones.NEW_YORK)
    qb.set_start_date(2025, 12, 31)
    qb.set_end_date(2025, 12, 31)
    qb.settings.seed_initial_prices = False
    qb.settings.daily_precise_end_time = True
    qb.universe_settings.fill_forward = False
    qb.universe_settings.data_normalization_mode = DataNormalizationMode.RAW
    output = {
        "mode": "Research history lookup; not an original stream delivery replay",
        "requested_calls": len(CASES), "completed_calls": 0,
        "daily_precise_end_time": True, "normalization": "RAW",
        "fill_forward": False, "provider_raw_prices_exported": False,
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(), "cases": [],
    }
    for ticker, date in CASES:
        start = datetime.fromisoformat(date)
        end, decision = start + timedelta(days=1), start.replace(hour=16, minute=5)
        if not datetime(2022, 1, 1) <= start < end < datetime(2026, 1, 1):
            raise ValueError("Outside the fixed diagnostic dates")
        item = {"ticker": ticker, "date": date, "request_start": str(start),
                "request_end_boundary": str(end), "pilot_decision_local": str(decision)}
        output["cases"].append(item)
        try:
            sid = SecurityIdentifier.generate_equity(ticker, Market.USA, mapping_resolve_date=start)
            symbol = Symbol(sid, ticker)
            qb.add_security(symbol, Resolution.DAILY, fill_forward=False,
                            extended_market_hours=False,
                            data_normalization_mode=DataNormalizationMode.RAW)
            item["resolved_sid_sha256"] = hashlib.sha256(str(sid).encode()).hexdigest()
            bars = list(qb.history[TradeBar](symbol, start, end, Resolution.DAILY,
                        fill_forward=False, data_normalization_mode=DataNormalizationMode.RAW))
            output["completed_calls"] += 1
            item["status"], item["rows"] = "completed", len(bars)
            item["bar_observation_times"] = [str(bar.time) for bar in bars]
            item["bar_end_times"] = [str(bar.end_time) for bar in bars]
            matching = [bar for bar in bars if bar.time.date() == start.date()]
            item["matching_observation_date_rows"] = len(matching)
            item["matching_rows_end_by_pilot_decision"] = sum(bar.end_time <= decision for bar in matching)
            item["duplicate_end_times"] = len(bars) - len({bar.end_time for bar in bars})
            item["unexpected_post_2025_rows"] = sum(bar.time.year > 2025 or bar.end_time.year > 2025 for bar in bars)
            item["fill_forward_rows"] = sum(bool(bar.is_fill_forward) for bar in bars)
            invalid = 0
            for bar in bars:
                o, h, l, c, v = map(float, (bar.open, bar.high, bar.low, bar.close, bar.volume))
                invalid += (not all(math.isfinite(value) for value in (o, h, l, c, v))
                            or not (0 < l <= min(o, c) <= max(o, c) <= h and v >= 0))
            item["invalid_ohlcv_rows"] = invalid
        except Exception as error:
            item["status"] = "unavailable"
            item["error_type"] = type(error).__name__
    print(json.dumps(output, separators=(",", ":")))
    return output
