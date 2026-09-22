"""Observer-only B10 replay. Upload unchanged v15 as v15_core.py in QC.

All strategy calls and their return values are preserved. Raw provider bars are
not exported; only derived attribution records are emitted within Free logs.
No additional History requests are made by the observer.
"""
from AlgorithmImports import *
import v15_core as v15
import qc_v16_c10_reference as c10
from collections import Counter, defaultdict, deque
from datetime import datetime
import hashlib
import json
from pathlib import Path
import statistics
import base64
import zlib
import lzma


def mark_to_market_pnl(previous_value, ending_value, signed_fill_notional,
                       dividends, split_cash, fees):
    price = ending_value - previous_value - signed_fill_notional
    return price, price + dividends + split_cash - fees


def packed_log(core):
    payload = json.dumps(core, separators=(",", ":"))
    envelope = {"encoding": "lzma-base64-derived-financial-records",
        "sha256": hashlib.sha256(payload.encode()).hexdigest(), "bytes": len(payload.encode()),
        "data": base64.b64encode(lzma.compress(payload.encode(), preset=6)).decode()}
    return "V16_ATTRIBUTION " + json.dumps(envelope, separators=(",", ":")), envelope


class V16Attribution(v15.DynamicUniversePilot):
    def initialize(self):
        self._base_logs = []
        super().initialize()
        if self.mode != "B" or self.bps != 10:
            raise ValueError("Only the unchanged B10 diagnostic replay is registered")
        self._a = {"schema": "v16-attribution-1", "original_backtest":
                   "549882ad625e8d4d5a4c149d8f943cd0", "fills": [],
                   "decisions": [], "daily_account": [], "daily_security": [],
                   "events": [], "episodes": [], "checks": Counter()}
        self._flows = defaultdict(Counter)
        self._previous_values = {}
        self._previous_equity = self._previous_cash = 100000.0
        self._symbols, self._active, self._day_episode = {}, {}, {}
        self._universe_scores, self._momentum_scores = {}, {}
        self._bars = defaultdict(lambda: deque(maxlen=23))
        self._decision_by_sid = {}
        self._seen_fill_events = set()
        self._c10 = c10.C10Reference()
        self._episode_id = 0
        self._original_top = v15.stable_top

        def observed_top(rows, count):
            result = self._original_top(rows, count)
            if count == 100:
                self._universe_scores = {sid: {"dollar_volume_rank": i + 1,
                    "dollar_volume": float(score)}
                    for i, (score, sid, symbol) in enumerate(result)}
            elif count == 10:
                ordered = self._original_top(rows, len(rows))
                self._momentum_scores = {sid: {"momentum_rank": i + 1,
                    "momentum_20": float(score)}
                    for i, (score, sid, symbol) in enumerate(ordered)}
            return result

        v15.stable_top = observed_top
        self._a["identity"] = {"observer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "observer_ast_sha256": v15.executable_ast_sha256(Path(__file__).read_text()),
            "base_sha256": hashlib.sha256(Path(v15.__file__).read_bytes()).hexdigest(),
            "base_ast_sha256": v15.executable_ast_sha256(Path(v15.__file__).read_text()),
            "c10_reference_sha256": hashlib.sha256(Path(c10.__file__).read_bytes()).hexdigest(),
            "start": "2022-01-01", "end": "2023-12-31", "mode": "B", "cost_bps": 10,
            "additional_history_requests": 0, "training_count": 0,
            "daily_pnl": "end holding value - prior holding value - signed fill notional + dividends + split cash - fees",
            "episodes": "flat to flat; additions and reductions remain in the same episode",
            "fill_time": "native engine receipt and submitted UTC; MOO date models regular open, not independently observed auction time"}

    def log(self, message):
        # Logging only: preserve original financial summary for comparison while
        # avoiding duplicate v15 detail output consuming the Free 10KB limit.
        text = str(message)
        if text.startswith("V15_"):
            self._base_logs.append(text)
        else:
            super().log(message)

    def on_data(self, data):
        for symbol, dividend in data.dividends.items():
            if symbol == self.spy:
                self._c10.observe_dividend(str(self.time.date()), float(dividend.distribution))
            sid = str(symbol.id)
            amount = float(dividend.distribution) * self.prior_close_quantities.get(sid, 0.0)
            if amount:
                self._symbols[sid] = symbol
                self._flows[sid]["dividends"] += amount
                self._a["events"].append({"kind": "dividend", "date": str(self.time),
                    "sid": sid, "ticker": symbol.value, "cash": amount,
                    "per_share": float(dividend.distribution), "prior_quantity": self.prior_close_quantities.get(sid, 0),
                    "payment_status": "engine proxy, not actual pay date"})
        for symbol, split in data.splits.items():
            if split.type == SplitType.SPLIT_OCCURRED:
                sid = str(symbol.id)
                if self.prior_close_quantities.get(sid, 0) or float(self.portfolio[symbol].quantity):
                    self._a["events"].append({"kind": "split", "date": str(self.time),
                        "sid": sid, "ticker": symbol.value, "factor": float(split.split_factor),
                        "reference_price": float(split.reference_price),
                        "previous_close_quantity": self.prior_close_quantities.get(sid, 0),
                        "engine_quantity_seen": float(self.portfolio[symbol].quantity)})
        for symbol, change in data.symbol_changed_events.items():
            self._a["events"].append({"kind": "symbol_change", "date": str(self.time),
                "sid": str(symbol.id), "old": str(change.old_symbol), "new": str(change.new_symbol)})
        for symbol, event in data.delistings.items():
            if self.prior_close_quantities.get(str(symbol.id), 0) or float(self.portfolio[symbol].quantity):
                self._a["events"].append({"kind": "delisting", "date": str(self.time),
                    "sid": str(symbol.id), "ticker": symbol.value, "type": str(event.type),
                    "price": float(event.price), "quantity_seen": float(self.portfolio[symbol].quantity),
                    "known_public_at_time": "unverified; not used as a signal"})
        super().on_data(data)
        for symbol, bar in data.bars.items():
            if symbol != self.spy:
                self._bars[str(symbol.id)].append((str(bar.end_time.date()), float(bar.close * bar.volume)))

    def issue(self, kind, symbol, held_value=0, **details):
        super().issue(kind, symbol, held_value, **details)
        if kind == "split_fraction_cash_proxy":
            sid = str(symbol.id)
            credit = float(details["engine_cash_proxy"])
            self._flows[sid]["split_cash"] += credit
            self._symbols[sid] = symbol
            self._a["events"].append({"kind": kind, "date": str(self.time), "sid": sid,
                "ticker": symbol.value, "cash": credit})
        if kind in ("unknown_missing", "known_terminated_missing", "reduction_blocked_unknown_current_price"):
            self._a["events"].append({"kind": kind, "date": str(self.time), "sid": str(symbol.id),
                "ticker": symbol.value, "held_value": held_value,
                "quantity": float(self.portfolio[symbol].quantity),
                "selected_current_month": str(symbol.id) in self._decision_by_sid,
                "open_orders": len(self.transactions.get_open_orders(symbol))})

    def make_decision(self):
        super().make_decision()
        equity = self.close_equity()[0]
        observed = self.current_month["observation_time"][:10]
        month = self.current_month["month"]
        self._decision_by_sid = {}
        selected = []
        for symbol, quantity in self.frozen_targets.items():
            sid = str(symbol.id)
            mark = self.latest.get(sid)
            row = {"month": month, "sid": sid, "ticker": symbol.value,
                "decision_time": str(self.time), "observation_time": self.current_month["observation_time"],
                "available_time": self.current_month["engine_available_time"],
                "decision_price": mark[1] if mark else None, "decision_equity": equity,
                "held_quantity": float(self.portfolio[symbol].quantity), "target_quantity": quantity,
                "target_weight_at_decision": quantity * mark[1] / equity if mark else None,
                **self._universe_scores.get(sid, {}), **self._momentum_scores.get(sid, {})}
            past = [(d, dv) for d, dv in self._bars[sid] if d <= observed]
            previous = past[:-1] if past and past[-1][0] == observed else []
            row["available_prior_dollar_volume_days"] = len(previous)
            row["dollar_volume_vs_available_observations"] = (row["dollar_volume"] / statistics.median([dv for d, dv in previous[-20:]])
                if len(previous) >= 20 and row.get("dollar_volume") and statistics.median([dv for d, dv in previous[-20:]]) > 0 else None)
            row["volume_comparison_limit"] = "median of up to20 available prior observations may cross subscription gaps; not certified last20 sessions; missing is not zero"
            self._decision_by_sid[sid] = row
            selected.append(row)
        self._a["decisions"].append({"month": month, "account_equity": equity,
            "selected": selected, "momentum_eligible": len(self._momentum_scores),
            "top10_ids": [sid for sid, x in sorted(self._momentum_scores.items(), key=lambda kv: kv[1]["momentum_rank"])[:10]],
            "pool_sid_sha256": self.current_month["member_sid_sha256"]})

    def on_order_event(self, event):
        super().on_order_event(event)
        if not event.fill_quantity:
            return
        record = dict(self.orders[-1])
        sid = record["sid"]
        self._symbols[sid] = event.symbol
        order = self.transactions.get_order_by_id(event.order_id)
        record.update(ticker=event.symbol.value, tag=str(order.tag),
            event_id=int(event.id), status=str(event.status),
            engine_quantity_after=float(self.portfolio[event.symbol].quantity),
            cash_after=float(self.portfolio.cash), decision=self._decision_by_sid.get(sid))
        receipt_equity = float(self.portfolio.total_portfolio_value)
        record["fill_notional_weight_at_receipt"] = abs(record["quantity"] * record["fill_price"]) / receipt_equity if receipt_equity else None
        d = record["decision"]
        record["decision_to_fill_price_change"] = record["fill_price"] / d["decision_price"] - 1 if d and d.get("decision_price") else None
        key = (record["id"], record["event_id"])
        if key in self._seen_fill_events:
            self._a["checks"]["duplicate_fill_events"] += 1
        self._seen_fill_events.add(key)
        if sid not in self._active:
            self._episode_id += 1
            self._active[sid] = self._episode_id
            self._a["episodes"].append({"id": self._episode_id, "sid": sid, "ticker": event.symbol.value,
                "entry": record["engine_receipt"], "exit": None, "price_pnl": 0.0,
                "dividends": 0.0, "split_cash": 0.0, "fees": 0.0, "net_pnl": 0.0,
                "fill_indexes": [], "years": {}, "max_close_value": 0.0, "max_close_weight": 0.0})
        eid = self._active[sid]
        if sid in self._day_episode and self._day_episode[sid] != eid:
            self._a["checks"]["multiple_episodes_same_sid_close_interval"] += 1
        self._day_episode[sid] = eid
        record["episode_id"] = eid
        episode = self._a["episodes"][eid - 1]
        episode["fill_indexes"].append(len(self._a["fills"]))
        self._a["fills"].append(record)
        self._flows[sid]["signed_fill_notional"] += record["quantity"] * record["fill_price"]
        self._flows[sid]["fees"] += record["fee"]
        if not float(self.portfolio[event.symbol].quantity):
            episode["exit"] = record["engine_receipt"]
            self._active.pop(sid)

    def after_close(self):
        super().after_close()
        if self.time.year not in (2022, 2023):
            return
        date = str(self.time.date())
        spy_mark = self.latest.get(str(self.spy.id))
        self._c10.close(date, spy_mark[1], str(spy_mark[0].date()))
        equity, gross, cash = self.close_equity()
        current = {}
        quantities = {}
        tickers = {}
        for h in self.portfolio.values():
            if h.invested:
                sid = str(h.symbol.id)
                mark = self.latest.get(sid)
                current[sid] = float(h.quantity) * (mark[1] if mark else float(h.price))
                quantities[sid] = float(h.quantity)
                tickers[sid] = h.symbol.value
        total = Counter()
        for sid in sorted(set(current) | set(self._previous_values) | set(self._flows)):
            flow = self._flows[sid]
            price, net = mark_to_market_pnl(self._previous_values.get(sid, 0), current.get(sid, 0),
                flow["signed_fill_notional"], flow["dividends"], flow["split_cash"], flow["fees"])
            eid = self._day_episode.get(sid, self._active.get(sid))
            if eid is None and abs(net) > 1e-7:
                self._a["checks"]["pnl_without_episode"] += 1
            row = {"date": date, "sid": sid, "ticker": tickers.get(sid, self._symbols[sid].value),
                "episode_id": eid, "previous_value": self._previous_values.get(sid, 0),
                "ending_value": current.get(sid, 0), "quantity": quantities.get(sid, 0),
                "price_pnl": price, "dividends": flow["dividends"], "split_cash": flow["split_cash"],
                "fees": flow["fees"], "net_pnl": net, "signed_fill_notional": flow["signed_fill_notional"],
                "weight": current.get(sid, 0) / equity}
            self._a["daily_security"].append(row)
            for k in ("price_pnl", "dividends", "split_cash", "fees", "net_pnl", "signed_fill_notional"):
                total[k] += row[k]
            if eid is not None:
                ep = self._a["episodes"][eid - 1]
                for k in ("price_pnl", "dividends", "split_cash", "fees", "net_pnl"):
                    ep[k] += row[k]
                ep["max_close_value"] = max(ep["max_close_value"], row["ending_value"])
                ep["max_close_weight"] = max(ep["max_close_weight"], row["weight"])
                yr = ep["years"].setdefault(date[:4], {k: 0.0 for k in ("price_pnl", "dividends", "split_cash", "fees", "net_pnl")})
                for k in yr:
                    yr[k] += row[k]
        cash_expected = self._previous_cash - total["signed_fill_notional"] + total["dividends"] + total["split_cash"] - total["fees"]
        self._a["daily_account"].append({"date": date, "equity": equity, "cash": cash, "gross": gross,
            "begin_equity": self._previous_equity, "net_pnl": equity - self._previous_equity,
            "attributed_net_pnl": total["net_pnl"], "residual": equity - self._previous_equity - total["net_pnl"],
            "cash_residual": cash - cash_expected, **{k: total[k] for k in ("price_pnl", "dividends", "split_cash", "fees")}})
        self._previous_values, self._previous_equity, self._previous_cash = current, equity, cash
        self._flows.clear()
        self._day_episode = dict(self._active)

    def on_end_of_algorithm(self):
        super().on_end_of_algorithm()
        v15.stable_top = self._original_top
        self._a["baseline_summary"] = {"final_equity": self.close_equity()[0], "annual_returns": self.annual,
            "fees": self.fees, "traded_notional": self.notional, "dividends": self.dividend_cash,
            "split_cash": self.split_cash, "fills": self.stats["fills"], "month_rows": self.packed_months}
        rows = self._a["daily_account"]
        summary = {"final_equity": self.close_equity()[0], "net_pnl": self.close_equity()[0] - 100000,
            "attributed_net_pnl": sum(r["attributed_net_pnl"] for r in rows),
            "residual": sum(r["residual"] for r in rows),
            "max_cash_residual": max(abs(r["cash_residual"]) for r in rows),
            "fees": self.fees, "fills": len(self._a["fills"]), "episodes": len(self._a["episodes"]),
            "daily_close_rows": len(rows), "checks": dict(self._a["checks"])}
        core = self.compact_attribution(summary)
        spy = self._c10.summary()
        core["spy_reference"] = {k: v for k, v in spy.items() if k != "months"}
        spy_months = {r["month"]: r for r in spy["months"]}
        runtime = {}
        for values in core.pop("months"):
            r = dict(zip(core["month_fields"], values))
            value = " ".join(k + "=" + repr(v) for k, v in (
                ("B", r["end_equity"]), ("C", spy_months[r["month"]]["end_equity"]),
                ("F", r["fees"]), ("D", r["dividends"]), ("S", r["split_cash"]), ("R", r["residual"])))
            if len(value) > 200:
                raise ValueError("Readable monthly financial statistic exceeds Free value limit")
            key = "v16 M" + r["month"]
            self.set_runtime_statistic(key, value)
            runtime[key] = value
        core.pop("month_fields", None)
        core["monthly_runtime_sha256"] = hashlib.sha256(json.dumps(runtime, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        core["monthly_runtime_format"] = "24 keys v16 MYYYY-MM: B=end NAV C=C10 NAV F=fees D=dividends S=split cash R=unexplained residual; full-precision numbers"
        text, envelope = packed_log(core)
        omitted = []
        for field in ("focus_fills", "focus_decisions", "episodes", "events"):
            if len(text.encode()) <= 9000:
                break
            core.pop(field, None)
            omitted.append(field)
            core["omitted_due_free_log_budget"] = omitted
            text, envelope = packed_log(core)
        if len(text.encode()) > 9000:
            for ranking in core["rankings"].values():
                ranking.pop("best", None)
            omitted.append("best_episode_rankings; winners remain in full security table")
            core["omitted_due_free_log_budget"] = omitted
            text, envelope = packed_log(core)
        if len(text.encode()) > 9000:
            core.pop("retention", None)
            core.pop("sparse_semantics", None)
            for key in ("daily_pnl", "episodes", "fill_time"):
                core["identity"].pop(key, None)
            for key in ("source", "limitations", "execution_fields", "execution_static_check"):
                core["spy_reference"].pop(key, None)
            core["rankings"]["all"].pop("worst", None)
            core["rankings"]["all"]["worst_from_priority_entries"] = True
            text, envelope = packed_log(core)
        self.set_runtime_statistic("v16_payload_sha256", envelope["sha256"])
        self.set_runtime_statistic("v16_log_bytes", str(len(text.encode())))
        if len(text.encode()) > 9200:
            self.log("V16_OUTPUT_LIMIT " + json.dumps({"bytes": len(text.encode()), "summary": summary}, separators=(",", ":")))
            return
        self.log(text)

    def compact_attribution(self, summary):
        fields = ("price_pnl", "dividends", "split_cash", "fees", "net_pnl")
        ids = sorted({r["sid"] for r in self._a["daily_security"]})
        index = {sid: i for i, sid in enumerate(ids)}
        securities, months = {}, {}
        for row in self._a["daily_security"]:
            key = (row["sid"], row["date"][:4])
            agg = securities.setdefault(key, Counter())
            for f in fields:
                agg[f] += row[f]
        for row in self._a["daily_account"]:
            month = row["date"][:7]
            agg = months.setdefault(month, {"begin": row["begin_equity"], "end": 0.0, **{f: 0.0 for f in fields}, "residual": 0.0})
            agg["end"] = row["equity"]
            for f in fields:
                agg[f] += row[f]
            agg["residual"] += row["residual"]
        rankings, focus = {}, set()
        episodes = self._a["episodes"]
        for period in ("all", "2022", "2023"):
            eligible = [ep for ep in episodes if period == "all" or period in ep["years"]]
            value = lambda ep: ep["net_pnl"] if period == "all" else ep["years"][period]["net_pnl"]
            worst = sorted(eligible, key=lambda ep: (value(ep), ep["sid"], ep["id"]))[:10]
            best = sorted(eligible, key=lambda ep: (-value(ep), ep["sid"], ep["id"]))[:10]
            loss = sum(-value(ep) for ep in eligible if value(ep) < 0)
            rank_row = lambda ep: [ep["id"], index[ep["sid"]], ep["entry"][:10], ep["exit"][:10] if ep["exit"] else None, value(ep)]
            rankings[period] = {"row_fields": ["episode_id", "sid_index", "entry", "exit", "net_pnl"],
                "worst": [rank_row(ep) for ep in worst], "best": [rank_row(ep) for ep in best], "negative_episode_pnl_sum": loss,
                "negative_count": sum(value(ep) < 0 for ep in eligible), "episode_count": len(eligible)}
            focus.update(ep["id"] for ep in worst + best)
        focus.update(ep["id"] for ep in episodes if ep["ticker"] in ("TOP", "TWTR"))
        focus_ep = [ep for ep in episodes if ep["id"] in focus]
        fill_indexes = {i for ep in focus_ep for i in ep["fill_indexes"]}
        fills = [self._a["fills"][i] for i in sorted(fill_indexes)]
        decisions = {}
        for fill in fills:
            d = fill.get("decision")
            if d and fill["quantity"] > 0:
                decisions[(d["month"], d["sid"])] = d
        priority_ids = {ep["id"] for ep in sorted(episodes, key=lambda ep: (ep["net_pnl"], ep["sid"], ep["id"]))[:10]}
        priority_ids.update(ep["id"] for ep in episodes if ep["ticker"] in ("TOP", "TWTR"))
        priority_entries = []
        for ep in episodes:
            if ep["id"] not in priority_ids:
                continue
            ep_fills = [self._a["fills"][i] for i in ep["fill_indexes"]]
            buys = [f for f in ep_fills if f["quantity"] > 0]
            sells = [f for f in ep_fills if f["quantity"] < 0]
            first = buys[0] if buys else {}
            d = first.get("decision") or {}
            sold = -sum(f["quantity"] for f in sells)
            derived = lambda value: round(value, 8) if value is not None else None
            priority_entries.append([ep["id"], index[ep["sid"]], ep["ticker"], ep["entry"][:10],
                ep["exit"][:10] if ep["exit"] else None, first.get("quantity"), first.get("fill_price"),
                sold, -sum(f["quantity"] * f["fill_price"] for f in sells) / sold if sold else None,
                ep["net_pnl"], ep["fees"], derived(d.get("momentum_20")), d.get("momentum_rank"),
                d.get("dollar_volume_rank"), derived(d.get("target_weight_at_decision")),
                derived(first.get("fill_notional_weight_at_receipt")), derived(first.get("decision_to_fill_price_change")),
                derived(ep["max_close_weight"])])
        # Compact arrays are fully documented schemas, not hidden data fields.
        return {"schema": "v16-compact-1", "identity": self._a["identity"], "summary": summary,
            "comparison": {"annual": self.annual, "notional": self.notional, "fees": self.fees,
                "dividends": self.dividend_cash, "split_cash": self.split_cash,
                "stats": {k: self.stats[k] for k in ("fills", "buy_fills", "sell_fills", "order_events", "native_nonstrategy_fills",
                    "invalid_orders", "quantity_reconciliation_errors", "fill_timing_violations", "fee_mismatch_fills")},
                "month_sha256": hashlib.sha256(json.dumps(self.packed_months, separators=(",", ":")).encode()).hexdigest()},
            "ids": [[sid, self._symbols[sid].value] for sid in ids],
            "security_fields": ["sid_index", "year", "price_pnl", "fees"],
            "securities": [[index[sid], year, agg["price_pnl"], agg["fees"]] for (sid, year), agg in sorted(securities.items())],
            "corporate_fields": ["sid_index", "year", "dividends", "split_cash"],
            "corporate_by_security": [[index[sid], year, agg["dividends"], agg["split_cash"]]
                for (sid, year), agg in sorted(securities.items()) if agg["dividends"] or agg["split_cash"]],
            "sparse_semantics": "Absent corporate row means zero observed cash; net=price+dividends+split-fees. Month beginning=prior ending, first beginning=100000. All monetary numbers preserve float precision; priority signal/weight/change ratios rounded to8 decimals only for output.",
            "month_fields": ["month", "end_equity", "price_pnl", "dividends", "split_cash", "fees", "residual"],
            "months": [[m, a["end"], *[a[f] for f in ("price_pnl", "dividends", "split_cash", "fees")], a["residual"]] for m, a in sorted(months.items())],
            "rankings": rankings,
            "priority_entry_fields": ["episode_id", "sid_index", "entry_ticker", "entry", "exit", "first_buy_quantity", "first_buy_price",
                "total_sold_quantity", "weighted_exit_price", "net_pnl", "fees", "momentum_20", "momentum_rank", "dollar_volume_rank",
                "target_weight_at_decision", "fill_notional_weight_at_receipt", "decision_to_fill_price_change", "max_close_weight"],
            "priority_entries": priority_entries,
            "episode_fields": ["id", "sid_index", "entry_ticker", "entry", "exit", *fields, "max_close_weight"],
            "episodes": [[ep["id"], index[ep["sid"]], ep["ticker"], ep["entry"][:10], ep["exit"][:10] if ep["exit"] else None,
                *[ep[f] for f in fields], ep["max_close_weight"]] for ep in focus_ep],
            "focus_fill_fields": ["order_id", "episode_id", "ticker", "receipt", "submitted_utc", "quantity", "price", "fee", "own", "fill_notional_weight_at_receipt", "decision_to_fill_price_change"],
            "focus_fills": [[f["id"], f["episode_id"], f["ticker"], f["engine_receipt"], f["submitted_utc"], f["quantity"],
                f["fill_price"], f["fee"], f["own"], f["fill_notional_weight_at_receipt"], f["decision_to_fill_price_change"]] for f in fills],
            "decision_fields": ["month", "sid_index", "momentum_20", "momentum_rank", "dollar_volume_rank",
                "target_quantity", "decision_equity", "target_weight_at_decision", "available_prior_dollar_volume_days", "dollar_volume_vs_available_observations"],
            "focus_decisions": [[d["month"], index[d["sid"]], *[d.get(k) for k in ("momentum_20", "momentum_rank", "dollar_volume_rank",
                "target_quantity", "decision_equity", "target_weight_at_decision", "available_prior_dollar_volume_days", "dollar_volume_vs_available_observations")]] for key, d in sorted(decisions.items())],
            "events": [{k: v for k, v in e.items() if k not in ("per_share", "reference_price", "price", "factor")}
                for e in self._a["events"] if e["kind"] not in ("known_terminated_missing", "unknown_missing") or e.get("held_value", 0)],
            "retention": "native Orders/Trades retained by QC; full auxiliary daily records only in run memory; derived subset in Free log; no ObjectStore write"}
