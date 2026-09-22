"""Durable, unitized accounting for ONE explicitly identified strategy fund.

This is a local event ledger, not a broker connection or a whole-account claim.
Creation is explicit. Opening never initializes a missing/corrupt fund. Each
event batch, valuation, risk state and strategy checkpoint commits together.
"""
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3


class FundJournalError(ValueError):
    """Fail closed; caller must not add risk after this error."""


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def timestamp(value):
    dt = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(dt, datetime) or dt.tzinfo is None:
        raise FundJournalError("Timezone-aware event/valuation time required")
    return dt.astimezone(timezone.utc).isoformat(timespec="microseconds")


def finite(value, name):
    result = float(value)
    if not math.isfinite(result):
        raise FundJournalError("Non-finite " + name)
    return result


def normalize_scope(scope):
    result = json.loads(canonical(scope))
    for key in ("scope_id", "owner", "currency"):
        if not isinstance(result.get(key), str) or not result[key].strip():
            raise FundJournalError("Missing fund scope identity: " + key)
    symbols = result.get("universe")
    if (not isinstance(symbols, list) or not symbols or
            any(not isinstance(s, str) or not s for s in symbols) or
            len(symbols) != len(set(symbols))):
        raise FundJournalError("Scope requires a unique, explicit symbol universe")
    if any(k in result for k in ("model_version", "run_id")):
        raise FundJournalError("Model version and process run ID are not fund identities")
    result["universe"] = sorted(symbols)
    return result


class FundJournal:
    SCHEMA = 1

    @classmethod
    def create(cls, path, scope, initial_cash, at):
        path = Path(path)
        marker = Path(str(path) + ".scope.json")
        scope = normalize_scope(scope)
        cash, at = finite(initial_cash, "initial cash"), timestamp(at)
        if cash <= 0:
            raise FundJournalError("Positive initial funding required")
        if path.exists() or marker.exists():
            raise FundJournalError("Fund already exists or initialization is incomplete; never reset")
        path.parent.mkdir(parents=True, exist_ok=True)
        identity = dict(schema=cls.SCHEMA, scope=scope, initial_cash=cash, created_at=at)
        identity["identity_sha256"] = digest(identity)
        # Marker precedes database creation. Interrupted creation requires review.
        with marker.open("x", encoding="utf-8") as handle:
            handle.write(canonical(identity))
            handle.flush()
            os.fsync(handle.fileno())
        db = sqlite3.connect(path)
        try:
            db.execute("PRAGMA synchronous=FULL")
            db.executescript("""
                CREATE TABLE metadata (id INTEGER PRIMARY KEY CHECK(id=1), document TEXT NOT NULL);
                CREATE TABLE state (id INTEGER PRIMARY KEY CHECK(id=1), document TEXT NOT NULL, sha256 TEXT NOT NULL);
                CREATE TABLE records (sequence INTEGER PRIMARY KEY, batch_id TEXT NOT NULL UNIQUE,
                    request_sha256 TEXT NOT NULL, previous_sha256 TEXT NOT NULL,
                    record_sha256 TEXT NOT NULL, document TEXT NOT NULL);
                CREATE TABLE events (event_id TEXT PRIMARY KEY, event_cursor INTEGER UNIQUE NOT NULL,
                    payload_sha256 TEXT NOT NULL, document TEXT NOT NULL, batch_id TEXT NOT NULL);
            """)
            initial = dict(schema=cls.SCHEMA, scope=scope, cash=cash,
                positions={s: 0.0 for s in scope["universe"]}, equity=cash,
                fund_shares=cash, unit_nav=1.0, high_water_nav=1.0,
                current_drawdown=0.0, max_drawdown=0.0,
                event_cursor=0, record_cursor=0, valuation_cursor=0,
                last_event_at=at, last_event_ids={}, last_valuation_at=at,
                model_version=None, model_history=[], last_run_id=None,
                risk_state={"mode": "observe", "reason": None, "recovery": {}},
                risk_mode="observe", blocked=None, checkpoint={},
                last_prices={}, last_batch_id=None,
                external_flows_total=0.0, income_total=0.0, fill_fees_total=0.0)
            db.execute("INSERT INTO metadata VALUES(1,?)", (canonical(identity),))
            db.execute("INSERT INTO state VALUES(1,?,?)", (canonical(initial), digest(initial)))
            db.commit()
        finally:
            db.close()
        return cls(path, scope)

    def __init__(self, path, expected_scope):
        self.path = Path(path)
        self.scope = normalize_scope(expected_scope)
        marker = Path(str(self.path) + ".scope.json")
        self.db = None
        if not self.path.is_file() or not marker.is_file():
            raise FundJournalError("Fund database/identity marker missing; explicit review required")
        try:
            self.db = sqlite3.connect(self.path.resolve().as_uri() + "?mode=rw", uri=True, timeout=10)
            self.db.execute("PRAGMA synchronous=FULL")
            if self.db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise FundJournalError("Fund database integrity check failed")
            identity = json.loads(self.db.execute("SELECT document FROM metadata WHERE id=1").fetchone()[0])
            check = dict(identity)
            stored_hash = check.pop("identity_sha256")
            if (digest(check) != stored_hash or identity != json.loads(marker.read_text(encoding="utf-8"))
                    or identity["scope"] != self.scope or identity["schema"] != self.SCHEMA):
                raise FundJournalError("Fund scope/creation identity mismatch")
            self.identity = identity
            self.verify()
        except Exception as exc:
            if self.db is not None:
                self.db.close()
            if isinstance(exc, FundJournalError):
                raise
            raise FundJournalError("Missing/corrupt fund state; cannot initialize: " + type(exc).__name__) from exc

    def close(self):
        self.db.close()

    def read(self):
        row = self.db.execute("SELECT document,sha256 FROM state WHERE id=1").fetchone()
        if row is None:
            raise FundJournalError("Current fund state missing")
        value = json.loads(row[0])
        if digest(value) != row[1] or value["scope"] != self.scope:
            raise FundJournalError("Current fund state corrupted")
        return value

    def history(self):
        """Yield ordered committed records; checkpoints include session outputs."""
        for row in self.db.execute("SELECT document FROM records ORDER BY sequence"):
            yield json.loads(row[0])

    def verify(self):
        """Check durable state, chain and event index once at process opening."""
        state = self.read()
        previous, cursor, event_cursor, last_state = self.identity["identity_sha256"], 0, 0, None
        for row in self.db.execute("SELECT sequence,previous_sha256,record_sha256,document,batch_id,request_sha256 FROM records ORDER BY sequence"):
            sequence, prev_hash, record_hash, document, batch_id, request_hash = row
            record = json.loads(document)
            if (sequence != cursor + 1 or prev_hash != previous or
                    digest(dict(previous_sha256=prev_hash, record=record)) != record_hash or
                    record["batch_id"] != batch_id or
                    (record["kind"] == "commit" and digest(record["request"]) != request_hash)):
                raise FundJournalError("Fund event/checkpoint chain is corrupt")
            for event in record.get("new_events", []):
                event_cursor += 1
                indexed = self.db.execute("SELECT event_cursor,payload_sha256,document,batch_id FROM events WHERE event_id=?", (event["id"],)).fetchone()
                if (indexed is None or indexed[0] != event_cursor or indexed[1] != digest(event)
                        or json.loads(indexed[2]) != event or indexed[3] != record["batch_id"]):
                    raise FundJournalError("Event deduplication index does not match checkpoint chain")
            previous, cursor, last_state = record_hash, sequence, record["state"]
        if (state["record_cursor"] != cursor or state["event_cursor"] != event_cursor or
                self.db.execute("SELECT COUNT(*) FROM events").fetchone()[0] != event_cursor or
                (last_state is not None and state != last_state)):
            raise FundJournalError("Latest fund state and processed-event cursors disagree")
        if cursor == 0 and (state["equity"] != self.identity["initial_cash"] or state["checkpoint"]):
            raise FundJournalError("Unexpected mutation of initial fund state")
        return dict(records=cursor, events=event_cursor, final_chain_sha256=previous,
                    state_sha256=digest(state), scope_sha256=digest(self.scope))

    def _mark(self, state, prices):
        total = state["cash"]
        for symbol, quantity in state["positions"].items():
            if abs(quantity) > 1e-12:
                if symbol not in prices:
                    raise FundJournalError("Missing current valuation for held symbol " + symbol)
                price = finite(prices[symbol], "valuation price")
                if price <= 0:
                    raise FundJournalError("Valuation prices must be positive")
                total += quantity * price
        if state["fund_shares"] <= 0:
            raise FundJournalError("No positive fund shares; closed-fund review required")
        state["equity"] = total
        state["unit_nav"] = total / state["fund_shares"]
        state["high_water_nav"] = max(state["high_water_nav"], state["unit_nav"])
        state["current_drawdown"] = state["unit_nav"] / state["high_water_nav"] - 1.0
        state["max_drawdown"] = min(state["max_drawdown"], state["current_drawdown"])

    def _write_record(self, state, batch_id, request_hash, record):
        last = self.db.execute("SELECT record_sha256 FROM records ORDER BY sequence DESC LIMIT 1").fetchone()
        previous = last[0] if last else self.identity["identity_sha256"]
        state["record_cursor"] += 1
        record.update(state=state, checkpoint=state["checkpoint"], risk_state=state["risk_state"])
        record_hash = digest(dict(previous_sha256=previous, record=record))
        self.db.execute("INSERT INTO records VALUES(?,?,?,?,?,?)", (
            state["record_cursor"], batch_id, request_hash, previous, record_hash, canonical(record)))
        self.db.execute("UPDATE state SET document=?,sha256=? WHERE id=1", (canonical(state), digest(state)))

    def quarantine(self, reason, details=None):
        """Persist an unresolved discrepancy. Recording later facts cannot clear it."""
        self.db.execute("BEGIN IMMEDIATE")
        try:
            state = self.read()
            state["blocked"] = state["blocked"] or str(reason)
            state["risk_mode"] = "review_required"
            batch_id = "__quarantine__:" + str(state["record_cursor"] + 1)
            record = dict(kind="quarantine", batch_id=batch_id, at=state["last_valuation_at"],
                          reason=str(reason), details=details, new_events=[])
            self._write_record(state, batch_id, digest(record), record)
            self.db.commit()
            return state
        except BaseException:
            self.db.rollback()
            raise

    def commit(self, batch_id, at, events, prices, checkpoint, model_version, run_id,
               expected_cash=None, expected_positions=None, risk_state=None):
        """Record actual facts; this method never submits or assumes an order fill.

        ``prices`` value the fund at ``at``. An external cash flow at an earlier
        instant must provide its own ``prices`` and equal ``valuation_at``.
        Expected broker balances are reconciliation assertions, not overrides.
        """
        if not isinstance(batch_id, str) or not batch_id or batch_id.startswith("__quarantine__:"):
            raise FundJournalError("Nonempty unique batch identity required")
        at = timestamp(at)
        clean_events = []
        for source in events:
            event = json.loads(canonical(source))
            if not isinstance(event.get("id"), str) or not event["id"]:
                raise FundJournalError("Every fact requires a stable event ID")
            event["at"] = timestamp(event["at"])
            clean_events.append(event)
        prices = {s: finite(v, "price") for s, v in prices.items()}
        if not model_version or not run_id:
            raise FundJournalError("Separate model and process identities required")
        request = dict(batch_id=batch_id, at=at, events=clean_events, prices=prices,
                       checkpoint=checkpoint, model_version=model_version,
                       expected_cash=expected_cash, expected_positions=expected_positions,
                       risk_state=risk_state)
        request_hash = digest(request)  # run_id may legitimately change after restart.
        self.db.execute("BEGIN IMMEDIATE")
        try:
            prior = self.db.execute("SELECT request_sha256 FROM records WHERE batch_id=?", (batch_id,)).fetchone()
            if prior is not None:
                if prior[0] != request_hash:
                    raise FundJournalError("Repeated batch ID has changed payload")
                state = self.read()
                self.db.rollback()
                return state
            state = self.read()
            if at < state["last_valuation_at"]:
                raise FundJournalError("Valuation order conflict")
            new_events = []
            for event in clean_events:
                indexed = self.db.execute("SELECT payload_sha256 FROM events WHERE event_id=?", (event["id"],)).fetchone()
                if indexed is not None:
                    if indexed[0] != digest(event):
                        raise FundJournalError("Repeated event ID has changed payload")
                    continue
                if event["at"] < max(state["last_event_at"], state["last_valuation_at"]) or event["at"] > at:
                    raise FundJournalError("Event order conflict; late facts require explicit reconstruction/review")
                kind = event["kind"]
                if kind == "fill":
                    symbol = event["symbol"]
                    if symbol not in state["positions"]:
                        raise FundJournalError("Fill is outside this fund's instrument scope")
                    quantity, price = finite(event["quantity"], "fill quantity"), finite(event["price"], "fill price")
                    fee = finite(event.get("fee", 0), "fill fee")
                    if price <= 0 or quantity == 0 or fee < 0:
                        raise FundJournalError("Invalid actual fill")
                    state["positions"][symbol] += quantity
                    state["cash"] -= quantity * price + fee
                    state["fill_fees_total"] += fee
                elif kind == "cashflow":
                    amount = finite(event["amount"], "external cash flow")
                    if "prices" in event and timestamp(event.get("valuation_at")) != event["at"]:
                        raise FundJournalError("External flow prices require a matching valuation timestamp")
                    if event["at"] == at:
                        flow_prices = event.get("prices", prices)
                    else:
                        if timestamp(event.get("valuation_at")) != event["at"] or "prices" not in event:
                            raise FundJournalError("External flow requires a contemporaneous pre-flow valuation")
                        flow_prices = event["prices"]
                    self._mark(state, flow_prices)
                    if state["unit_nav"] <= 0 or state["equity"] + amount <= 0 or state["cash"] + amount < -1e-9:
                        raise FundJournalError("Cash flow exhausts units or unavailable cash; review required")
                    state["fund_shares"] += amount / state["unit_nav"]
                    state["cash"] += amount
                    state["external_flows_total"] += amount
                elif kind == "income":
                    amount = finite(event["amount"], "investment income")
                    if event.get("reason") not in ("fee", "dividend", "interest") or (event["reason"] == "fee" and amount > 0):
                        raise FundJournalError("Income requires a known investment cash reason; fee is negative")
                    state["cash"] += amount
                    state["income_total"] += amount
                else:
                    raise FundJournalError("Unknown financial event kind; never infer an external flow")
                state["event_cursor"] += 1
                state["last_event_at"] = event["at"]
                state["last_event_ids"][kind] = event["id"]
                self.db.execute("INSERT INTO events VALUES(?,?,?,?,?)", (
                    event["id"], state["event_cursor"], digest(event), canonical(event), batch_id))
                new_events.append(event)
            self._mark(state, prices)
            scale = max(abs(state["equity"]), 1.0)
            if state["cash"] < -1e-9 * scale or any(q < -1e-9 for q in state["positions"].values()):
                state["blocked"] = state["blocked"] or "Actual ledger has negative cash or a short position"
            if expected_cash is not None and not math.isclose(state["cash"], finite(expected_cash, "expected cash"), rel_tol=1e-9, abs_tol=1e-9):
                state["blocked"] = state["blocked"] or "Unexplained cash reconciliation mismatch"
            if expected_positions is not None:
                actual = state["positions"]
                for symbol in set(actual) | set(expected_positions):
                    if not math.isclose(actual.get(symbol, 0), finite(expected_positions.get(symbol, 0), "expected quantity"), rel_tol=1e-9, abs_tol=1e-9):
                        state["blocked"] = state["blocked"] or "Unexplained position reconciliation mismatch"
            if state["model_version"] != model_version:
                state["model_history"].append(dict(at=at, version=model_version, valuation_cursor=state["valuation_cursor"] + 1))
            state.update(last_valuation_at=at, valuation_cursor=state["valuation_cursor"] + 1,
                         last_prices=prices, last_batch_id=batch_id, model_version=model_version,
                         last_run_id=run_id, checkpoint=json.loads(canonical(checkpoint)))
            if risk_state is not None:
                state["risk_state"] = json.loads(canonical(risk_state))
            state["risk_mode"] = "review_required" if state["blocked"] else state["risk_state"].get("mode", "observe")
            record = dict(kind="commit", batch_id=batch_id, at=at, new_events=new_events,
                          request=request, model_version=model_version, run_id=run_id)
            self._write_record(state, batch_id, request_hash, record)
            self.db.commit()
            return state
        except (FundJournalError, ValueError, KeyError, TypeError) as exc:
            self.db.rollback()
            self.quarantine(str(exc), {"batch_id": batch_id, "request_sha256": request_hash})
            if isinstance(exc, FundJournalError):
                raise
            raise FundJournalError("Invalid financial event: " + str(exc)) from exc
        except BaseException:
            self.db.rollback()
            raise
