"""v17 cloud research. Upload with qc_v15_dynamic_pilot.py and qc_v17_features.py.

Parameters: research_mode=eq/mom20/trend63/ridge/trend63_risk/ridge_risk/spy;
cost_bps=10/20. No live mode, broker connection, 2026 data, or provider export.
Native execution/accounting methods are inherited from the frozen v15 source.
"""
from AlgorithmImports import *
from collections import Counter, deque
from datetime import datetime, timedelta
from pathlib import Path
import hashlib
import json
import math
import statistics
import time
import warnings

import qc_v15_dynamic_pilot as core
import qc_v17_features as features


class DynamicResearchV17(core.DynamicUniversePilot):
    def runtime_rows(self, prefix, rows, maximum_characters=3500):
        """Bounded derived-result chunks, never provider OHLCV records.

        Counts and a digest identify completeness; a clipped/missing UI value
        must be reported as an incomplete artifact rather than reconstructed.
        """
        chunks, chunk = [], []
        for row in rows:
            candidate = chunk + [row]
            if chunk and len(json.dumps(candidate, separators=(",", ":"))) > maximum_characters:
                chunks.append(chunk)
                chunk = [row]
            else:
                chunk = candidate
        if chunk:
            chunks.append(chunk)
        for i, values in enumerate(chunks):
            self.set_runtime_statistic(prefix + "_" + str(i), json.dumps(values, separators=(",", ":")))
        self.set_runtime_statistic(prefix + "_index", json.dumps({
            "rows": len(rows), "chunks": len(chunks), "sha256": features.stable_digest(rows)
        }, separators=(",", ":")))

    def initialize(self):
        if self.live_mode:
            raise RuntimeError("v17 is historical research only")
        self.research_mode = self.get_parameter("research_mode") or "eq"
        self.bps = int(self.get_parameter("cost_bps") or "10")
        if self.research_mode not in ("eq", "mom20", "trend63", "ridge", "trend63_risk", "ridge_risk", "spy") or self.bps not in (10, 20):
            raise ValueError("Unregistered strategy or cost")
        # Core methods use B to permit orders and their unchanged v15 tags.
        self.mode = "B"
        self.set_start_date(2018, 12, 1)
        self.set_end_date(2023, 12, 31)
        self.set_cash(100000)
        self.set_time_zone(TimeZones.NEW_YORK)
        self.set_brokerage_model(BrokerageName.QUANT_CONNECT_BROKERAGE, AccountType.CASH)
        self.settings.daily_precise_end_time = True
        self.settings.seed_initial_prices = False
        self.add_security_initializer(self.initialize_security)
        self.universe_settings.resolution = Resolution.DAILY
        self.universe_settings.fill_forward = False
        self.universe_settings.extended_market_hours = False
        self.universe_settings.data_normalization_mode = DataNormalizationMode.RAW
        self.universe_settings.leverage = 1
        self.universe_settings.asynchronous = False
        self.spy = self.add_equity("SPY", Resolution.MINUTE, fill_forward=False,
                                   extended_market_hours=True,
                                   data_normalization_mode=DataNormalizationMode.RAW).symbol
        self.universe_settings.schedule.on(self.date_rules.every_day(self.spy))
        self.add_universe(self.select_universe)
        # The following are the original v15 accounting/execution state fields.
        self.pool, self.seen, self.previous_pool = [], set(), set()
        self.universe_month = None
        self.latest, self.last_ends, self.last_raw = {}, {}, {}
        self.prior_close_quantities, self.pending_splits = {}, {}
        self.pending_fill_quantities = Counter()
        self.issues, self.regular_sessions, self.split_today, self.terminal = {}, {}, {}, {}
        self.stats = Counter()
        self.months, self.nav, self.events, self.orders, self.packed_months = [], [], [], [], []
        self.current_month = None
        self.frozen_targets, self.buy_after, self.finalizing = {}, None, False
        self.notional = self.fees = self.fee_difference = 0.0
        self.trade_cash = self.dividend_cash = self.split_cash = 0.0
        self.peak, self.max_dd, self.max_cash_error = 100000.0, 0.0, 0.0
        self.min_cash, self.max_gross = 100000.0, 0.0
        self.year_start, self.annual = 100000.0, {}
        self.dv_history, self.pool_liquidity = {}, {}
        self.observation_days = deque(maxlen=20)
        self.last_universe_observation = None
        self.pending_features, self.training_rows = [], []
        self.model, self.model_year = None, None
        self.fits, self.decisions, self.label_checks = [], [], []
        self.feature_cache, self.current_history_calendar = {}, []
        self.month_end, self.sid_net_pnl, self.sid_year_pnl = {}, Counter(), {}
        self.last_values, self.daily_signed_trade, self.daily_cash_income, self.daily_fees = {}, Counter(), Counter(), Counter()
        self.maximum_single_weight = 0.0
        self.prediction_checks, self.unresolved_labels = [], []
        self.schedule.on(self.date_rules.every_day(self.spy), self.time_rules.at(16, 5), self.after_close)
        self.source_identity = {
            "strategy_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "core_sha256": hashlib.sha256(Path(core.__file__).read_bytes()).hexdigest(),
            "features_sha256": hashlib.sha256(Path(features.__file__).read_bytes()).hexdigest(),
            "features": list(features.FEATURE_NAMES), "research_mode": self.research_mode,
            "cost_bps": self.bps, "training_start": "2019-01-01", "evaluation": ["2022-01-01", "2023-12-31"],
            "label": "next monthly decision close price-return cross-sectional average rank minus0.5",
            "model": "StandardScaler + Ridge(alpha=100, solver=svd)",
        }
        self.log("V17_IDENTITY " + json.dumps(self.source_identity, separators=(",", ":")))

    def select_universe(self, fundamental):
        if self.time.year > 2023:
            raise ValueError("Frozen observation boundary exceeded")
        hours = self.securities[self.spy].exchange.hours
        if not hours.is_date_open(self.time, False):
            return Universe.UNCHANGED
        previous = hours.get_previous_trading_day(self.time).date()
        if previous == self.last_universe_observation:
            return Universe.UNCHANGED
        self.observation_days.append(previous)
        self.last_universe_observation = previous
        counts, seen_today, current = Counter(), set(), {}
        max_observed = max_available = None
        for f in fundamental:
            counts["input"] += 1
            sid = str(f.symbol.id)
            if sid in seen_today:
                raise ValueError("Duplicate Fundamental SID")
            seen_today.add(sid)
            if f.end_time > self.time or f.time >= f.end_time:
                raise ValueError("Fundamental information is not yet available")
            if not f.has_fundamental_data or f.security_reference.security_type != "ST00000001":
                counts["outside_common_stock_coverage"] += 1
                continue
            if f.time.date() != previous:
                counts["stale_observation"] += 1
                continue
            price, dv = float(f.price), float(f.dollar_volume)
            if not all(math.isfinite(v) and v > 0 for v in (price, dv)):
                counts["invalid_numeric"] += 1
                continue
            history = self.dv_history.setdefault(sid, deque(maxlen=20))
            history.append((previous, dv))
            # Low-price observations remain in the trailing liquidity measure;
            # the current >$5 eligibility test is applied only at selection.
            current[sid] = (f.symbol, price, dv)
            max_observed = max(max_observed or f.time, f.time)
            max_available = max(max_available or f.end_time, f.end_time)
        month = self.time.strftime("%Y-%m")
        if self.time.year < 2019 or month == self.universe_month:
            return Universe.UNCHANGED
        rows, liquidity = [], {}
        expected = list(self.observation_days)
        for sid, (symbol, price, last_dv) in current.items():
            if price <= 5:
                counts["price_filter"] += 1
                continue
            history = list(self.dv_history[sid])
            if len(expected) != 20 or [r[0] for r in history] != expected:
                counts["liquidity_history_incomplete"] += 1
                continue
            median_dv = statistics.median(r[1] for r in history)
            rows.append((median_dv, sid, symbol))
            liquidity[sid] = (median_dv, last_dv)
        if len(rows) < 100:
            raise ValueError("Fewer than100 contemporaneous persistent-liquidity candidates")
        selected = core.stable_top(rows, 100)
        self.pool = [r[2] for r in selected]
        self.pool_liquidity = {r[1]: liquidity[r[1]] for r in selected}
        ids = {r[1] for r in selected}
        counts.update(eligible=len(rows), selected=len(selected), added=len(ids - self.previous_pool), removed=len(self.previous_pool - ids))
        item = dict(counts)
        item.update(month=month, observation_time=str(max_observed), engine_available_time=str(max_available),
                    selection_callback=str(self.time), member_sid_sha256=features.stable_digest(sorted(ids)))
        self.current_month = item
        if self.time.year >= 2022:
            self.months.append(item)
            self.seen.update(ids)
        self.previous_pool, self.universe_month = ids, month
        return self.pool

    def history_closes(self, symbol):
        sid = str(symbol.id)
        if sid not in self.feature_cache:
            bars = list(self.history[TradeBar](symbol, 127, Resolution.DAILY,
                        fill_forward=False, data_normalization_mode=DataNormalizationMode.SPLIT_ADJUSTED))
            ends = [b.end_time for b in bars]
            if any(t > self.time or t.year > 2025 for t in ends) or len(ends) != len(set(ends)):
                raise ValueError("History duplicate or future endpoint")
            if any(not math.isfinite(float(b.close)) or float(b.close) <= 0 for b in bars):
                raise ValueError("Invalid historical close")
            self.feature_cache[sid] = [(b.end_time, float(b.close)) for b in bars]
        return self.feature_cache[sid]

    def resolve_labels(self):
        if not self.pending_features:
            return
        valid, reasons = [], Counter()
        for row in self.pending_features:
            points = dict((t.date(), p) for t, p in self.history_closes(row["symbol"]))
            start, end = row["observed"].date(), self.time.date()
            if start not in points or end not in points:
                reason = "terminal_endpoint_unresolved" if row["sid"] in self.terminal else "missing_endpoint_unresolved"
                reasons[reason] += 1
                self.unresolved_labels.append({"sid": row["sid"], "start": str(start), "end": str(end), "reason": reason})
                continue
            # Both endpoints use the same request/adjustment anchor. No zero
            # recovery, forward-filled price, or future-completeness selection.
            result = dict(row, label_end=self.time, price_return=points[end] / points[start] - 1)
            valid.append(result)
        if len(valid) >= 2:
            for row, rank in zip(valid, features.centered_ranks([r["price_return"] for r in valid])):
                row["y"] = rank
                self.training_rows.append(row)
            scored = [r for r in valid if r.get("prediction") is not None]
            if len(scored) >= 2:
                pred_rank = features.centered_ranks([r["prediction"] for r in scored])
                true_rank = features.centered_ranks([r["price_return"] for r in scored])
                denom = math.sqrt(sum(v*v for v in pred_rank) * sum(v*v for v in true_rank))
                self.prediction_checks.append(sum(a*b for a, b in zip(pred_rank, true_rank)) / denom if denom else 0)
        self.label_checks.append({"month": self.time.strftime("%Y-%m"), "input": len(self.pending_features), "resolved": len(valid), "unresolved": dict(reasons)})
        self.pending_features = []

    def fit_annual(self):
        if not self.research_mode.startswith("ridge") or self.model_year == self.time.year:
            return
        import numpy as np
        from sklearn.linear_model import Ridge
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
        rows = features.eligible_training_rows(self.training_rows, self.time.year)
        if len(rows) < 1000 or len({r["observed"].strftime("%Y-%m") for r in rows}) < 12:
            raise ValueError("Insufficient matured training history")
        identity = [[str(r["observed"]), r["sid"], r["x"], str(r["label_end"]), r["y"]] for r in rows]
        started = time.perf_counter()
        with warnings.catch_warnings(record=True) as recorded:
            warnings.simplefilter("always")
            model = make_pipeline(StandardScaler(), Ridge(alpha=100.0, solver="svd"))
            model.fit(np.asarray([r["x"] for r in rows]), np.asarray([r["y"] for r in rows]))
        scaler, ridge = model.steps[0][1], model.steps[1][1]
        parameters = {"mean": scaler.mean_.tolist(), "scale": scaler.scale_.tolist(),
                      "coefficient": ridge.coef_.tolist(), "intercept": float(ridge.intercept_)}
        record = {
            "year": self.time.year, "rows": len(rows), "feature_order": list(features.FEATURE_NAMES),
            "observed_first": str(min(r["observed"] for r in rows)), "observed_last": str(max(r["observed"] for r in rows)),
            "label_end_last": str(max(r["label_end"] for r in rows)),
            "boundary_exclusive": str(datetime(self.time.year, 1, 1)),
            "input_sha256": features.stable_digest(identity), "parameters": parameters,
            "model_sha256": features.stable_digest({"parameters": parameters, "features": list(features.FEATURE_NAMES), "input_sha256": features.stable_digest(identity)}),
            "fit_seconds": time.perf_counter() - started,
            "warnings": [str(w.message)[:200] for w in recorded],
            "unresolved_labels_so_far": len(self.unresolved_labels),
        }
        self.fits.append(record)
        self.model, self.model_year = model, self.time.year
        # These are derived model parameters, not downloaded provider records.
        self.set_runtime_statistic("v17_fit_" + str(self.time.year), json.dumps(record, separators=(",", ":")))
        self.log("V17_FIT " + json.dumps({k: v for k, v in record.items() if k not in ("parameters", "feature_order")}, separators=(",", ":")))

    def make_decision(self):
        item = self.current_month
        item["decision_time"] = str(self.time)
        if datetime.fromisoformat(item["engine_available_time"]) > self.time:
            raise ValueError("Universe arrived after decision")
        self.feature_cache = {}
        calendar = self.history_closes(self.spy)
        expected = [t.date() for t, _ in calendar]
        if len(expected) != 127 or expected[-1] != self.time.date():
            raise ValueError("127-session benchmark calendar incomplete")
        self.resolve_labels()
        rows, prices, counts = [], {}, Counter()
        for symbol in self.pool:
            sid = str(symbol.id)
            mark = self.latest.get(sid)
            if mark and mark[0].date() == self.time.date():
                prices[symbol] = mark[1]
            history = self.history_closes(symbol)
            if len(history) != 127:
                counts["feature_history_insufficient"] += 1
                continue
            if [t.date() for t, _ in history] != expected:
                counts["feature_calendar_gap"] += 1
                continue
            if symbol not in prices:
                counts["feature_missing_current_price"] += 1
                continue
            median_dv, latest_dv = self.pool_liquidity[sid]
            x = features.feature_vector([p for _, p in history], median_dv, latest_dv)
            rows.append({"symbol": symbol, "sid": sid, "observed": self.time, "x": x, "prediction": None})
        self.pending_features = rows
        item.update(counts)
        item["feature_ready"] = len(rows)
        if self.time.year < 2022:
            return
        self.fit_annual()
        if self.model is not None:
            for row, value in zip(rows, self.model.predict([r["x"] for r in rows])):
                row["prediction"] = float(value)
        base_mode = self.research_mode.replace("_risk", "")
        if base_mode == "eq":
            targets = list(self.pool)
            scored = []
        elif base_mode == "spy":
            targets, scored = [self.spy], []
            prices[self.spy] = self.latest[str(self.spy.id)][1]
        else:
            # All non-equal stock signals share the exact feature-ready range;
            # no subsequent outcome or unresolved-label status filters it.
            scored = [(r["prediction"] if base_mode == "ridge" else r["x"][1 if base_mode == "mom20" else 2], r["sid"], r["symbol"]) for r in rows]
            targets = [r[2] for r in core.stable_top(scored, 10)]
        budget = .90
        if self.research_mode.endswith("_risk"):
            spy_bars = list(self.history[TradeBar](self.spy, 200, Resolution.DAILY, fill_forward=False,
                            data_normalization_mode=DataNormalizationMode.SPLIT_ADJUSTED))
            if len(spy_bars) != 200 or any(b.end_time > self.time for b in spy_bars):
                raise ValueError("SPY200 risk input incomplete or future")
            budget = .45 if float(spy_bars[-1].close) < statistics.mean(float(b.close) for b in spy_bars) else .90
        equity = self.close_equity()[0]
        self.frozen_targets = core.whole_share_targets(targets, prices, equity, budget)
        for holding in self.portfolio.values():
            if holding.invested and self.latest.get(str(holding.symbol.id), (datetime.min, 0))[0].date() != self.time.date():
                self.frozen_targets[holding.symbol] = int(holding.quantity)
        self.buy_after = self.time.date()
        self.reduce_to_targets(self.frozen_targets, "monthly")
        decision = {"month": item["month"], "budget": budget, "pool_sha256": item["member_sid_sha256"],
                    "feature_ready": len(rows), "target_count": len(targets),
                    "prediction_sha256": features.stable_digest([[r[1], r[0]] for r in sorted(scored, key=lambda v: v[1])]),
                    "target_sha256": features.stable_digest([[str(s.id), q] for s, q in sorted(self.frozen_targets.items(), key=lambda v: str(v[0].id))]),
                    "selected": [str(s.id) for s in targets]}
        self.decisions.append(decision)
        # Predicted scores are derived signals; no original bars or volume
        # records are exported. Each bounded chunk must survive UI readback.
        self.runtime_rows("v17_predictions_" + item["month"],
                          [[r[1], r[0]] for r in sorted(scored, key=lambda v: v[1])])
        self.set_runtime_statistic("v17_decision_" + item["month"], json.dumps(decision, separators=(",", ":")))

    def on_data(self, data):
        if self.time.year >= 2022:
            for symbol, dividend in data.dividends.items():
                self.daily_cash_income[str(symbol.id)] += float(dividend.distribution) * self.prior_close_quantities.get(str(symbol.id), 0.0)
            before = self.split_cash
        super().on_data(data)
        if self.time.year >= 2022 and self.split_cash != before:
            # Fractional cash is uncommon and remains explicitly unattributed
            # to a SID rather than guessed; it is included in account equity.
            self.stats["attribution_split_cash"] += self.split_cash - before

    def on_order_event(self, event):
        if self.time.year < 2022 and event.fill_quantity != 0:
            raise ValueError("Warm-up must not trade")
        super().on_order_event(event)
        if event.fill_quantity != 0:
            sid = str(event.symbol.id)
            self.daily_signed_trade[sid] += float(event.fill_quantity) * float(event.fill_price)
            self.daily_fees[sid] += float(event.order_fee.value.amount)

    def after_close(self):
        if self.time.year < 2022:
            if self.current_month and not self.current_month.get("decision_time"):
                self.make_decision()
            return
        super().after_close()
        equity, gross, cash = self.close_equity()
        values = {str(h.symbol.id): float(h.quantity) * self.latest.get(str(h.symbol.id), (None, float(h.price)))[1]
                  for h in self.portfolio.values() if h.invested}
        self.maximum_single_weight = max(self.maximum_single_weight, max(values.values(), default=0.0) / equity)
        annual = self.sid_year_pnl.setdefault(str(self.time.year), Counter())
        for sid in set(values) | set(self.last_values) | set(self.daily_signed_trade) | set(self.daily_cash_income) | set(self.daily_fees):
            pnl = values.get(sid, 0) - self.last_values.get(sid, 0) - self.daily_signed_trade[sid] + self.daily_cash_income[sid] - self.daily_fees[sid]
            self.sid_net_pnl[sid] += pnl
            annual[sid] += pnl
        self.last_values = values
        self.daily_signed_trade.clear()
        self.daily_cash_income.clear()
        self.daily_fees.clear()
        self.month_end[self.time.strftime("%Y-%m")] = [str(self.time.date()), equity, gross, cash, self.fees]

    def on_end_of_algorithm(self):
        if not self.nav:
            self.log("V17_INCOMPLETE no evaluation rows")
            return
        equity, gross, cash = self.close_equity()
        rets = [self.nav[0][1] / 100000 - 1] + [self.nav[i][1] / self.nav[i-1][1] - 1 for i in range(1, len(self.nav))]
        elapsed = (datetime(2024, 1, 1) - datetime(2022, 1, 1)).days / 365.25
        avg_equity = statistics.mean(r[1] for r in self.nav)
        blocked = ("duplicate_bars", "invalid_bars", "cash_or_leverage_breaches", "fill_timing_violations",
                   "cash_reconciliation_days", "quantity_reconciliation_errors", "fee_mismatch_fills", "invalid_orders")
        complete = len(self.months) == 24 and self.nav[0][0] == "2022-01-03" and self.nav[-1][0] == "2023-12-29"
        attribution_residual = equity - 100000 - sum(self.sid_net_pnl.values()) - self.stats["attribution_split_cash"]
        summary = {
            "mode": self.research_mode, "cost_bps": self.bps, "evaluation": "2022-2023 development",
            "training_count": len(self.fits), "model_hashes": [r["model_sha256"] for r in self.fits],
            "complete_months": len(self.months), "daily_close_rows": len(self.nav), "cumulative_security_ids": len(self.seen),
            "net_cumulative": equity/100000 - 1, "net_cagr": (equity/100000)**(1/elapsed) - 1,
            "max_drawdown": self.max_dd, "annualized_volatility": statistics.stdev(rets)*math.sqrt(252),
            "annual_returns": self.annual, "average_exposure": statistics.mean(r[2]/r[1] for r in self.nav),
            "maximum_single_close_weight": self.maximum_single_weight,
            "turnover_gross_notional_over_average_equity": self.notional/avg_equity,
            "traded_notional": self.notional, "fees_paid": self.fees, "final_equity": equity,
            "final_cash": cash, "final_gross_holdings": gross,
            "dividend_cash_engine_proxy": self.dividend_cash, "split_fraction_cash_engine_proxy": self.split_cash,
            "max_cash_reconciliation_error": self.max_cash_error, "attribution_residual": attribution_residual,
            "maximum_exposure": self.max_gross, "minimum_cash": self.min_cash,
            "training_rows_resolved": len(self.training_rows), "unresolved_training_labels": len(self.unresolved_labels),
            "training_label_scope": "rank conditional on observed endpoint; unresolved lifecycle cases prevent a complete-lifecycle/survivorship-free claim",
            "mean_monthly_rank_ic": statistics.mean(self.prediction_checks) if self.prediction_checks else None,
            "rank_ic_months": len(self.prediction_checks), "stats": dict(self.stats),
            "open_orders_at_end": len(self.transactions.get_open_orders()),
            "gate_pass": complete and gross < .01 and not self.transactions.get_open_orders()
                         and abs(attribution_residual) < .05 and not any(self.stats[k] for k in blocked),
            "native_orders_only": True, "object_store_written": False,
            "raw_provider_records_exported": False, "2026_market_data_used": False,
            "economic_rights_limit": "LEAN dividend/terminal cash proxy; not verified real payment dates or complete spinoff rights",
        }
        self.log("V17_SUMMARY " + json.dumps(summary, separators=(",", ":")))
        self.set_runtime_statistic("v17_summary", json.dumps(summary, separators=(",", ":")))
        self.set_runtime_statistic("v17_months", json.dumps(self.month_end, separators=(",", ":")))
        self.runtime_rows("v17_labels", self.label_checks)
        self.runtime_rows("v17_unresolved_labels", self.unresolved_labels)
        self.runtime_rows("v17_security_pnl", sorted(self.sid_net_pnl.items()))
        for year, values in self.sid_year_pnl.items():
            self.runtime_rows("v17_security_pnl_" + year, sorted(values.items()))
        material = [v for v in self.issues.values() if v["max_held_value"] > 0]
        self.runtime_rows("v17_held_issues", material)
        for k in ("net_cagr", "max_drawdown", "training_count", "gate_pass"):
            self.set_runtime_statistic("v17_"+k, str(summary[k]))
