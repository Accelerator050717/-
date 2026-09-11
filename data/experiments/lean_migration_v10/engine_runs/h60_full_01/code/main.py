"""Run the frozen H60 daily research proxy through the real LEAN engine.

OPEN 09:30, RANGE 12:00 and CLOSE 16:00 are artificial event clocks. The RANGE
record is the entire session's actual daily low, not a noon market observation.
This adapter is deliberately incapable of live trading and consumes no quote API.
"""
from AlgorithmImports import *

import hashlib
import json
import math
from pathlib import Path
import sys


class H60Phase(PythonData):
    sources = {}
    traced_sources = set()
    traced_readers = set()

    def get_source(self, config, date, is_live_mode):
        if is_live_mode:
            raise ValueError("Historical daily proxy cannot run live")
        if config.symbol.value not in self.traced_sources:
            self.traced_sources.add(config.symbol.value)
            print(f"H60 SOURCE {config.symbol.value}: {self.sources[config.symbol.value]}", flush=True)
        return SubscriptionDataSource(self.sources[config.symbol.value],
                                      SubscriptionTransportMedium.LOCAL_FILE)

    def reader(self, config, line, date, is_live_mode):
        if is_live_mode:
            raise ValueError("Historical daily proxy cannot run live")
        if not line or line.startswith("datetime") or line.startswith("timestamp"):
            return None
        if config.symbol.value not in self.traced_readers:
            self.traced_readers.add(config.symbol.value)
            print(f"H60 READER {config.symbol.value}: {line.strip()}", flush=True)
        timestamp, phase, price = line.strip().split(",")
        point = H60Phase()
        point.symbol = config.symbol
        point.time = datetime.fromisoformat(timestamp)
        point.end_time = point.time
        point.value = float(price)
        point["phase"] = phase
        return point


class H60ProxyFeeModel(FeeModel):
    def __init__(self, algorithm):
        super().__init__()
        self.algorithm = algorithm

    def get_order_fee(self, parameters):
        order = parameters.order
        if order.tag in self.algorithm.intents:
            price = self.algorithm.intent(order)["price"]
        elif int(order.id) == 0:
            # LEAN values unrealized P&L by asking for the estimated fee of an
            # unsubmitted hypothetical close order (Extensions.GetMarketOrderFees).
            # This estimate never creates an intent or debits account cash.
            price = float(parameters.security.price)
        else:
            raise ValueError("Fee requested for an unknown submitted order")
        amount = float(order.absolute_quantity) * price * self.algorithm.fee_rate
        return OrderFee(CashAmount(amount, "USD"))


class H60ProxyFillModel(FillModel):
    def __init__(self, algorithm):
        super().__init__()
        self.algorithm = algorithm

    def market_fill(self, asset, order):
        intent = self.algorithm.intent(order)
        if intent["phase"] != self.algorithm.current_phase:
            raise ValueError("Proxy order escaped the phase that created it")
        event = OrderEvent(order, self.algorithm.utc_time, OrderFee.ZERO)
        event.status = OrderStatus.FILLED
        event.fill_quantity = order.quantity
        event.fill_price = intent["price"]
        event.message = "Historical adjusted daily proxy; not a broker execution"
        return event


class LeanLedger:
    """Read LEAN balances and submit real engine orders; no parallel cash ledger."""
    def __init__(self, algorithm):
        self.algorithm = algorithm

    def quantities(self, names):
        return [float(self.algorithm.portfolio[self.algorithm.symbols[name]].quantity) for name in names]

    def cash(self):
        return float(self.algorithm.portfolio.cash_book["USD"].amount)

    def equity(self):
        return float(self.algorithm.portfolio.total_portfolio_value)

    def cumulative_fees(self):
        return float(self.algorithm.portfolio.total_fees)

    def execute(self, name, quantity, price, reason, observation, threshold, risk_action):
        algo = self.algorithm
        current = float(algo.portfolio[algo.symbols[name]].quantity)
        if quantity < 0 and abs(quantity) > current + 1e-8:
            raise ValueError("Proxy order would sell more than engine holdings")
        if quantity > 0 and quantity * price * (1 + algo.fee_rate) > self.cash() + 1e-5:
            raise ValueError("Proxy order would spend unavailable cash")
        key = f"h60-{len(algo.intents) + 1}"
        intent = dict(key=key, Date=algo.current_date, symbol=name,
                      phase=algo.current_phase, price=float(price), reason=reason,
                      observation_date=observation,
                      stop_threshold=threshold if math.isfinite(threshold) else None,
                      risk_action=risk_action,
                      session_open=float(algo.controller.opened[algo.controller.names.index(name)]))
        algo.intents[key] = intent
        if len(algo.intents) == 1:
            print(f"H60 FIRST ORDER entering: {name} qty={quantity} price={price}", flush=True)
        # Exact requested quantity is rounded only by LEAN's declared proxy lot size.
        ticket = algo.market_order(algo.symbols[name], float(quantity), False, key)
        if len(algo.intents) == 1:
            print(f"H60 FIRST ORDER returned: {ticket.status}", flush=True)
        if ticket.status != OrderStatus.FILLED:
            raise RuntimeError(f"LEAN did not synchronously fill {key}: {ticket.status}; {ticket.get_most_recent_order_response()}")
        if abs(float(ticket.quantity_filled) - quantity) > 1e-8:
            raise RuntimeError("Unexpected LEAN quantity rounding; parity cannot continue")


class H60MigrationAlgorithm(QCAlgorithm):
    def initialize(self):
        if self.live_mode:
            raise ValueError("H60 migration is historical-only, no live or paper connectivity")
        self.output = Path(self.get_parameter("h60-output-dir"))
        self.output.mkdir(parents=True, exist_ok=True)
        package_path = Path(self.get_parameter("h60-package-path"))
        identity = json.loads(package_path.with_name("EXPORT_IDENTITY.json").read_text(encoding="utf-8-sig"))
        for name, digest in identity["exported_sha256"].items():
            path = (package_path.parent / name).resolve()
            if not path.is_relative_to(package_path.parent.resolve()):
                raise ValueError("Export identity path escaped the local package")
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError(f"Exported input hash mismatch: {name}")
        if "package.json" not in identity["exported_sha256"]:
            raise ValueError("Frozen export has no package identity")
        package = json.loads(package_path.read_text(encoding="utf-8-sig"))
        if not package.get("research_only") or package.get("live_mode_allowed"):
            raise ValueError("Package must explicitly forbid live trading")
        self.package_sha256 = hashlib.sha256(package_path.read_bytes()).hexdigest()
        shared = package_path.parent / package.get("shared_directory", "shared")
        for name, digest in package.get("shared_source_sha256", {}).items():
            path = shared / Path(name).name
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError(f"Shared strategy source hash mismatch: {name}")
        for name, digest in package["data_sha256"].items():
            path = (package_path.parent / name).resolve()
            if not path.is_relative_to(package_path.parent.resolve()):
                raise ValueError("Market-data path escaped the frozen package")
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError(f"Phase input hash mismatch: {name}")
        sys.path.insert(0, str(shared))
        sys.path.insert(0, str(Path(__file__).parent))
        from decision import H60Decision
        self.controller = H60Decision(package)
        first = datetime.fromisoformat(package["first_date"])
        final = datetime.fromisoformat(package["final_date"])
        if final.year >= 2026:
            raise ValueError("2026 holdout is not authorized for this migration")
        self.set_time_zone(TimeZones.NEW_YORK)
        self.set_start_date(first.year, first.month, first.day)
        self.set_end_date(final.year, final.month, final.day)
        self.set_cash(float(package["initial_cash"]))
        self.set_brokerage_model(BrokerageName.DEFAULT, AccountType.MARGIN)
        self.settings.free_portfolio_value_percentage = 0
        self.fee_rate = float(package["cost_bps"]) / 10000
        self.symbols, self.intents, self.trades, self.order_events = {}, {}, [], []
        self.current_phase, self.current_date = None, None
        self._phase_packets = {}
        for name in package["names"]:
            # Base securities intentionally represent fractional adjusted-price
            # research units, not IBKR-share contracts or raw corporate actions.
            props = SymbolProperties("H60 adjusted proxy", "USD", 1, 1e-12, 1e-12, name)
            source = (package_path.parent / package["data_files"][name]).resolve()
            if not source.is_file():
                raise ValueError(f"Missing local phase input: {name}")
            H60Phase.sources[name] = str(source)
            # Official custom-data overload registers the type-qualified symbol
            # properties and explicit proxy clock together.
            security = self.add_data(H60Phase, name, props,
                SecurityExchangeHours.always_open(TimeZones.NEW_YORK),
                Resolution.MINUTE, False, 1)
            H60Phase.sources[security.symbol.value] = str(source)
            if float(security.symbol_properties.lot_size) > 1e-10:
                raise ValueError(f"LEAN proxy lot size is too coarse: {security.symbol_properties.lot_size}")
            security.set_leverage(1)
            security.set_fee_model(H60ProxyFeeModel(self))
            security.set_fill_model(H60ProxyFillModel(self))
            self.symbols[name] = security.symbol
        self.ledger = LeanLedger(self)
        self.set_benchmark(lambda time: float(package["initial_cash"]))
        self.log("Historical-only H60 proxy: actual daily prices; artificial OPEN/RANGE/CLOSE order.")

    def intent(self, order):
        if order.tag not in self.intents:
            raise ValueError("Unknown order outside fixed H60 proxy")
        return self.intents[order.tag]

    def on_data(self, data):
        if not hasattr(self, "first_data_traced"):
            self.first_data_traced = True
            print(f"H60 FIRST ON_DATA {self.time}", flush=True)
        packet = {}
        phase, date = None, None
        for name, symbol in self.symbols.items():
            if not data.contains_key(symbol):
                continue
            point = data[symbol]
            point_phase = str(point["phase"])
            point_date = point.time.date().isoformat()
            if phase is not None and (phase != point_phase or date != point_date):
                raise ValueError("Cross-section mixes dates or daily proxy phases")
            phase, date = point_phase, point_date
            packet[name] = float(point.value)
        if not packet:
            return
        if len(packet) != len(self.symbols):
            raise ValueError("Incomplete daily phase cross-section; no forward filling")
        self.current_phase, self.current_date = phase, date
        self.controller.process(phase, date, [packet[s] for s in self.controller.names], self.ledger)

    def on_order_event(self, event):
        order = self.transactions.get_order_by_id(event.order_id)
        intent = self.intent(order)
        self.order_events.append(dict(order_id=int(event.order_id), event_id=int(event.id),
            utc_time=event.utc_time.isoformat(), status=str(event.status),
            fill_quantity=float(event.fill_quantity), fill_price=float(event.fill_price),
            fee=float(event.order_fee.value.amount), intent_key=intent["key"]))
        if event.status not in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED):
            return
        quantity, price = float(event.fill_quantity), float(event.fill_price)
        fee = float(event.order_fee.value.amount)
        self.trades.append(dict(Date=intent["Date"], observation_date=intent["observation_date"],
            symbol=intent["symbol"], reason=intent["reason"], risk_action=intent["risk_action"],
            signed_units=quantity, proxy_fill=price, signed_notional=quantity * price,
            fee=fee, cash_change=-quantity * price - fee,
            stop_threshold=intent["stop_threshold"], session_open=intent["session_open"],
            stop_extra_bps=self.controller.stop_extra_bps if intent["reason"].startswith("stop_") else 0,
            lean_order_id=int(event.order_id), lean_event_id=int(event.id),
            phase=intent["phase"]))

    def on_end_of_algorithm(self):
        if not hasattr(self, "ledger"):
            return
        import pandas as pd
        for filename, records in (("daily.csv", self.controller.daily),
                                  ("trades.csv", self.trades),
                                  ("positions.csv", self.controller.positions),
                                  ("targets.csv", self.controller.targets),
                                  ("events.csv", self.controller.events),
                                  ("order_events.csv", self.order_events),
                                  ("observation_audit.csv", self.controller.observation_audit)):
            pd.DataFrame(records).to_csv(self.output / filename, index=False)
        status = self.controller.status()
        runtime_error = str(self.run_time_error) if self.run_time_error else None
        status.update(engine="LEAN", live_mode=False,
                      status="completed" if self.controller.completed and not runtime_error else "incomplete",
                      package_sha256=self.package_sha256,
                      lean_order_count=len(self.intents), lean_fill_count=len(self.trades),
                      final_engine_cash=self.ledger.cash(),
                      final_engine_equity=self.ledger.equity(),
                      final_engine_quantities=dict(zip(self.controller.names,
                                                self.ledger.quantities(self.controller.names))),
                      ledger_source="LEAN SecurityPortfolioManager and OrderEvent callbacks",
                      engine_runtime_error=runtime_error)
        (self.output / "completion.json").write_text(
            json.dumps(status, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
