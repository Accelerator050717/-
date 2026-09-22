"""Prepared fixed cloud Research checks, not run by import.

Three historical entry cases only. No orders, backtests, training, ObjectStore,
or 2026 data. Provider bars remain in the cloud; return derived ratios/checks.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import statistics

from AlgorithmImports import (
    DataNormalizationMode, Market, QuantBook, Resolution,
    SecurityIdentifier, Symbol, TimeZones, TradeBar,
)


CASES = (
    ("TOP", "2023-05-01", "2023-04-28"),
    ("KALA", "2023-01-03", "2022-12-30"),
    ("NTRB", "2022-01-03", "2021-12-31"),
)


def describe_bars(bars, symbol, cutoff):
    ends = [b.end_time for b in bars]
    invalid = 0
    for bar in bars:
        o, h, low, c, v = map(float, (bar.open, bar.high, bar.low, bar.close, bar.volume))
        invalid += int(not all(math.isfinite(x) for x in (o, h, low, c, v))
                       or not (0 < low <= min(o, c) <= max(o, c) <= h and v >= 0))
    return {"rows": len(bars), "first_observation": str(bars[0].time) if bars else None,
            "last_end_time": str(ends[-1]) if ends else None,
            "duplicate_end_times": len(ends) - len(set(ends)),
            "strictly_increasing": all(a < b for a, b in zip(ends, ends[1:])),
            "future_rows": sum(t > cutoff or t.year > 2025 for t in ends),
            "sid_mismatches": sum(str(b.symbol.id) != str(symbol.id) for b in bars),
            "fill_forward_rows": sum(bool(b.is_fill_forward) for b in bars),
            "invalid_ohlcv_rows": invalid}


def usable(check):
    return (check["strictly_increasing"] and not any(check[k] for k in
            ("duplicate_end_times", "future_rows", "sid_mismatches", "fill_forward_rows", "invalid_ohlcv_rows")))


def check_v16_fixed_entries():
    qb = QuantBook()
    qb.set_time_zone(TimeZones.NEW_YORK)
    qb.set_start_date(2025, 12, 31)
    qb.set_end_date(2025, 12, 31)
    qb.settings.seed_initial_prices = False
    qb.settings.daily_precise_end_time = True
    spy = qb.add_equity("SPY", Resolution.DAILY, fill_forward=False,
                        extended_market_hours=False,
                        data_normalization_mode=DataNormalizationMode.RAW).symbol
    output = {"schema": "v16-fixed-entry-research-1", "requested_history_calls": 9,
              "completed_history_calls": 0, "cases": [],
              "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
              "market_data_after_2025_requested": False, "orders_or_backtests": 0,
              "raw_bars_exported": False, "new_model_fits": 0,
              "scope": "Present-day fixed historical queries, not the original immutable data snapshot",
              "volume_definition": "RAW daily close times daily volume; proxy for the original Fundamental dollar-volume field, not an assertion of field equality",
              "momentum_definition": "Last21 valid SplitAdjusted closes through decision-day16:05; compare actual last EndTime and date to original observer signal"}
    for ticker, decision_day, observed_day in CASES:
        decision = datetime.fromisoformat(decision_day).replace(hour=16, minute=5)
        observation = datetime.fromisoformat(observed_day).replace(hour=16, minute=5)
        start = observation.replace(hour=0, minute=0) - timedelta(days=65)
        if not (datetime(2021, 1, 1) <= start < observation < decision < datetime(2026, 1, 1)):
            raise ValueError("Outside fixed historical query boundaries")
        item = {"ticker_at_decision": ticker, "decision_local": str(decision),
                "universe_observation_day": observed_day,
                "raw_request_start": str(start), "raw_request_end": str(observation),
                "momentum_request_end": str(decision)}
        output["cases"].append(item)
        try:
            sid = SecurityIdentifier.generate_equity(ticker, Market.USA,
                                                     mapping_resolve_date=decision)
            earlier_sid = SecurityIdentifier.generate_equity(ticker, Market.USA,
                                                             mapping_resolve_date=observation)
            symbol = Symbol(sid, ticker)
            item.update(sid=str(sid), sid_namespace="QuantConnect SecurityIdentifier equity usa",
                        historical_mapping_resolve_date=decision_day,
                        mapping_same_at_observation_and_decision=str(sid) == str(earlier_sid),
                        sid_sha256=hashlib.sha256(str(sid).encode()).hexdigest())
            if str(sid) != str(earlier_sid):
                raise ValueError("Security mapping changed across the fixed decision boundary")
            qb.add_security(symbol, Resolution.DAILY, fill_forward=False,
                            extended_market_hours=False,
                            data_normalization_mode=DataNormalizationMode.RAW)
            calendar = list(qb.history[TradeBar](spy, start, decision, Resolution.DAILY,
                fill_forward=False, data_normalization_mode=DataNormalizationMode.RAW))
            output["completed_history_calls"] += 1
            raw = list(qb.history[TradeBar](symbol, start, observation, Resolution.DAILY,
                fill_forward=False, data_normalization_mode=DataNormalizationMode.RAW))
            output["completed_history_calls"] += 1
            adjusted = list(qb.history[TradeBar](symbol, start, decision, Resolution.DAILY,
                fill_forward=False, data_normalization_mode=DataNormalizationMode.SPLIT_ADJUSTED))
            output["completed_history_calls"] += 1
            item["calendar_check"] = describe_bars(calendar, spy, decision)
            item["raw_check"] = describe_bars(raw, symbol, observation)
            item["adjusted_check"] = describe_bars(adjusted, symbol, decision)
            calendar_days = [b.end_time.date().isoformat() for b in calendar]
            dv_days = [d for d in calendar_days if d <= observed_day][-21:]
            momentum_days = calendar_days[-21:]
            raw_by_day = {b.end_time.date().isoformat(): b for b in raw}
            adjusted_by_day = {b.end_time.date().isoformat(): b for b in adjusted}
            missing_raw = [d for d in dv_days if d not in raw_by_day]
            missing_adjusted = [d for d in momentum_days if d not in adjusted_by_day]
            item.update(dv_expected_count=len(dv_days), momentum_expected_count=len(momentum_days),
                        dv_expected_first=dv_days[0] if dv_days else None,
                        dv_expected_last=dv_days[-1] if dv_days else None,
                        momentum_expected_first=momentum_days[0] if momentum_days else None,
                        momentum_expected_last=momentum_days[-1] if momentum_days else None,
                        missing_raw_expected_days=missing_raw,
                        missing_adjusted_expected_days=missing_adjusted,
                        decision_close_in_history=bool(momentum_days and momentum_days[-1] == decision_day),
                        observation_is_prior_reference_session=bool(len(calendar_days) > 1 and calendar_days[-2] == observed_day))
            checks_ok = all(usable(item[name]) for name in ("calendar_check", "raw_check", "adjusted_check"))
            item["volume_ratio"] = None
            if checks_ok and len(dv_days) == 21 and dv_days[-1] == observed_day and not missing_raw:
                values = [float(raw_by_day[d].close) * float(raw_by_day[d].volume) for d in dv_days]
                median = statistics.median(values[:-1])
                item["positive_prior_dv_days"] = sum(v > 0 for v in values[:-1])
                if median > 0 and item["positive_prior_dv_days"] == 20:
                    item["volume_ratio"] = values[-1] / median
            item["momentum_20"] = None
            if checks_ok and len(momentum_days) == 21 and momentum_days[-1] == decision_day and not missing_adjusted:
                first, last = adjusted_by_day[momentum_days[0]], adjusted_by_day[momentum_days[-1]]
                item["momentum_20"] = float(last.close) / float(first.close) - 1
                item["momentum_actual_first_time"] = str(first.time)
                item["momentum_actual_last_end_time"] = str(last.end_time)
            item["status"] = "complete" if checks_ok and item["volume_ratio"] is not None and item["momentum_20"] is not None else "limited_missing_or_boundary"
        except Exception as error:
            item["status"] = "unavailable"
            item["error_type"] = type(error).__name__
    print(json.dumps(output, separators=(",", ":")))
    return output
