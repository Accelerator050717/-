from AlgorithmImports import *
from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
import ast
import base64
import hashlib
import json
import math
MONTH_FIELDS = ('month', 'input', 'no_fundamental_coverage', 'not_common_stock', 'common_stock_coverage', 'invalid_numeric', 'price_or_volume_filter', 'eligible', 'selected', 'added', 'removed', 'cumulative_ids', 'observation_time', 'engine_available_time', 'selection_callback', 'decision_time', 'member_sid_sha256', 'history_calls', 'history_rows', 'momentum_history_insufficient', 'momentum_unknown_calendar_gap', 'decision_missing_current_price', 'momentum_eligible', 'target_count', 'unknown_price_excluded_from_order_only')

def executable_ast_sha256(source):
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.body and isinstance(node.body[0], ast.Expr):
                value = node.body[0].value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    node.body.pop(0)
    portable = ast.dump(tree, include_attributes=False).replace(', type_params=[]', '')
    return hashlib.sha256(portable.encode()).hexdigest()

def stable_top(rows, count):
    return sorted(rows, key=lambda x: (-x[0], x[1]))[:count]

def whole_share_targets(symbols, prices, equity, budget=0.9):
    if not symbols:
        return {}
    dollars = max(0.0, equity) * budget / len(symbols)
    return {s: int(dollars / prices[s]) for s in symbols if prices.get(s, 0) > 0}

class PilotFeeModel(FeeModel):

    def __init__(self, bps):
        self.rate = bps / 10000.0

    def get_order_fee(self, parameters):
        security, order = (parameters.security, parameters.order)
        price = float(security.price)
        bar = security.cache.get_data[TradeBar]()
        if bar is not None and order.type == OrderType.MARKET_ON_OPEN:
            price = float(bar.open)
        return OrderFee(CashAmount(abs(float(order.quantity)) * price * self.rate, 'USD'))

class DynamicUniversePilot(QCAlgorithm):

    def initialize(self):
        if self.live_mode:
            raise RuntimeError('v15 is restricted to historical cloud backtests')
        self.mode = self.get_parameter('mode') or 'audit'
        self.bps = int(self.get_parameter('cost_bps') or '10')
        if self.mode not in ('audit', 'A', 'B', 'C') or self.bps not in (10, 20):
            raise ValueError('Only the registered mode and costs are allowed')
        self.set_start_date(2021, 12, 31)
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
        self.spy = self.add_equity('SPY', Resolution.MINUTE, fill_forward=False, extended_market_hours=True, data_normalization_mode=DataNormalizationMode.RAW).symbol
        self.universe_settings.schedule.on(self.date_rules.month_start(self.spy))
        self.add_universe(self.select_universe)
        self.pool, self.seen, self.previous_pool = ([], set(), set())
        self.universe_month = None
        self.latest, self.last_ends, self.last_raw = ({}, {}, {})
        self.prior_close_quantities, self.pending_splits = ({}, {})
        self.pending_fill_quantities = Counter()
        self.issues = {}
        self.regular_sessions = {}
        self.split_today, self.terminal = ({}, {})
        self.stats = Counter()
        self.months, self.nav, self.events, self.orders = ([], [], [], [])
        self.packed_months = []
        self.current_month = None
        self.frozen_targets, self.buy_after = ({}, None)
        self.finalizing = False
        self.notional = self.fees = self.fee_difference = 0.0
        self.trade_cash = self.dividend_cash = self.split_cash = 0.0
        self.peak, self.max_dd, self.max_cash_error = (100000.0, 0.0, 0.0)
        self.min_cash, self.max_gross = (100000.0, 0.0)
        self.year_start, self.annual = (100000.0, {})
        self.schedule.on(self.date_rules.every_day(self.spy), self.time_rules.at(16, 5), self.after_close)
        source = Path(__file__).read_text()
        self.log('V15_IDENTITY ' + json.dumps({'schema': 'v15log3', 'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'executable_ast_sha256': executable_ast_sha256(source), 'mode': self.mode, 'cost_bps': self.bps, 'start': '2022-01-01', 'end': '2023-12-31', 'engine_warmup_start': '2021-12-31', 'initial_cash': 100000, 'budget': 0.9, 'model_fits': 0, 'engine': 'native EquityFillModel', 'settlement': 'Immediate research assumption', 'object_store': False}, separators=(',', ':')))

    def initialize_security(self, security):
        security.set_leverage(1)
        security.set_data_normalization_mode(DataNormalizationMode.RAW)
        security.set_fee_model(PilotFeeModel(self.bps))
        security.set_settlement_model(ImmediateSettlementModel())

    def select_universe(self, fundamental):
        if self.time.year not in (2022, 2023):
            return Universe.UNCHANGED
        hours = self.securities[self.spy].exchange.hours
        if not hours.is_date_open(self.time, False):
            return Universe.UNCHANGED
        previous_session = hours.get_previous_trading_day(self.time).date()
        month = self.time.strftime('%Y-%m')
        if month == self.universe_month:
            return Universe.UNCHANGED
        rows, counts, ids = ([], Counter(), set())
        max_observed = max_available = None
        for f in fundamental:
            counts['input'] += 1
            sid = str(f.symbol.id)
            if sid in ids:
                counts['duplicate_sid'] += 1
                continue
            ids.add(sid)
            if f.end_time > self.time or f.time >= f.end_time:
                counts['invalid_information_time'] += 1
                continue
            if not f.has_fundamental_data:
                counts['no_fundamental_coverage'] += 1
                continue
            if f.security_reference.security_type != 'ST00000001':
                counts['not_common_stock'] += 1
                continue
            counts['common_stock_coverage'] += 1
            price, dollar_volume = (float(f.price), float(f.dollar_volume))
            if not math.isfinite(price) or not math.isfinite(dollar_volume):
                counts['invalid_numeric'] += 1
                continue
            if price <= 5 or dollar_volume <= 0:
                counts['price_or_volume_filter'] += 1
                continue
            self.stats['universe_freshness_checks'] += 1
            if f.time.date() != previous_session:
                self.stats['stale_universe'] += 1
                raise ValueError('Stale universe observation: ' + str(f.time.date()) + ' expected ' + str(previous_session))
            counts['eligible'] += 1
            rows.append((dollar_volume, sid, f.symbol))
            max_observed = max(max_observed or f.time, f.time)
            max_available = max(max_available or f.end_time, f.end_time)
        if counts['duplicate_sid'] or counts['invalid_information_time'] or (not rows):
            raise ValueError('Universe identity/time gate failed: ' + str(dict(counts)))
        selected = stable_top(rows, 100)
        self.pool = [r[2] for r in selected]
        selected_ids = {r[1] for r in selected}
        added, removed = (selected_ids - self.previous_pool, self.previous_pool - selected_ids)
        self.seen.update(selected_ids)
        item = dict(counts)
        item.update(month=month, selected=len(selected), added=len(added), removed=len(removed), cumulative_ids=len(self.seen), observation_time=str(max_observed), engine_available_time=str(max_available), selection_callback=str(self.time), member_sid_sha256=hashlib.sha256('\n'.join(sorted(selected_ids)).encode()).hexdigest())
        self.current_month = item
        self.months.append(item)
        self.previous_pool, self.universe_month = (selected_ids, month)
        return self.pool

    def on_data(self, data):
        for symbol, dividend in data.dividends.items():
            amount = float(dividend.distribution) * self.prior_close_quantities.get(str(symbol.id), 0.0)
            self.dividend_cash += amount
            self.stats['dividend_events'] += 1
            self.events.append({'kind': 'dividend', 'sid': str(symbol.id), 'engine_time': str(self.time), 'cash_credit_proxy': amount, 'not_actual_pay_date': True})
        for symbol, split in data.splits.items():
            self.stats['split_events'] += 1
            if split.type == SplitType.SPLIT_OCCURRED:
                self.split_today[str(symbol.id), self.time.date()] = float(split.split_factor)
                self.stats['splits_occurred'] += 1
                sid = str(symbol.id)
                self.pending_splits[sid] = self.pending_splits.get(sid, 1.0) * float(split.split_factor)
                adjusted = Decimal(str(self.prior_close_quantities.get(sid, 0.0))) / Decimal(str(split.split_factor))
                remainder = adjusted - int(adjusted)
                if remainder:
                    cached = self.securities[symbol].get_last_data()
                    adjusted_price = float(cached.price) if cached is not None else float(split.reference_price) * float(split.split_factor)
                    credit = float(remainder) * adjusted_price
                    self.split_cash += credit
                    self.issue('split_fraction_cash_proxy', symbol, credit, engine_cash_proxy=credit)
                if symbol in self.frozen_targets:
                    self.frozen_targets[symbol] = int(Decimal(self.frozen_targets[symbol]) / Decimal(str(split.split_factor)))
                    self.stats['frozen_target_split_adjustments'] += 1
        for symbol, change in data.symbol_changed_events.items():
            self.stats['symbol_changes'] += 1
        for symbol, event in data.delistings.items():
            kind = 'warning' if event.type == DelistingType.WARNING else 'delisted'
            self.stats['delisting_' + kind] += 1
            holding = float(self.portfolio[symbol].quantity)
            self.events.append({'kind': kind, 'sid': str(symbol.id), 'ticker': symbol.value, 'engine_time': str(self.time), 'quantity_seen': holding, 'holding_value_seen': float(self.portfolio[symbol].holdings_value), 'settlement': 'unverified; engine event is not a payment record'})
            if kind == 'delisted':
                self.terminal[str(symbol.id)] = str(self.time)
        for symbol, bar in data.bars.items():
            sid = str(symbol.id)
            if symbol == self.spy:
                day = bar.end_time.date()
                if day not in self.regular_sessions:
                    midnight = datetime(day.year, day.month, day.day)
                    hours = self.securities[symbol].exchange.hours
                    self.regular_sessions[day] = (hours.get_next_market_open(midnight, False), hours.get_next_market_close(midnight, False))
                opened, closed = self.regular_sessions[day]
                if bar.time < opened or bar.end_time > closed:
                    continue
            previous_end = self.last_ends.get(sid)
            if previous_end == bar.end_time:
                self.stats['duplicate_bars'] += 1
            self.last_ends[sid] = bar.end_time
            o, h, l, c, v = map(float, (bar.open, bar.high, bar.low, bar.close, bar.volume))
            if not all((math.isfinite(x) for x in (o, h, l, c, v))) or not (0 < l <= min(o, c) <= max(o, c) <= h and v >= 0):
                self.stats['invalid_bars'] += 1
                raise ValueError('Invalid native bar: ' + symbol.value + ' ' + str(bar.end_time))
            if symbol != self.spy:
                previous = self.last_raw.get(sid)
                if previous and abs(c / previous - 1) > 0.4:
                    factor = self.split_today.get((sid, bar.end_time.date()), 1.0)
                    next_open = self.securities[symbol].exchange.hours.get_next_market_open(previous_end + timedelta(microseconds=1), False) if previous_end else None
                    consecutive = next_open is not None and next_open.date() == bar.end_time.date()
                    key = ('raw_jump_with_split' if factor != 1 else 'raw_jump_unexplained') if consecutive else 'raw_change_across_subscription_gap'
                    self.stats[key] += 1
                    details = {'split_adjusted_step': c / previous / factor - 1} if consecutive else {'gap_calendar_days': (bar.end_time - previous_end).days if previous_end else None}
                    self.issue(key, symbol, abs(float(self.portfolio[symbol].holdings_value)), **details)
                self.last_raw[sid] = c
            self.latest[sid] = (bar.end_time, c)

    def close_equity(self):
        cash = float(self.portfolio.cash)
        values = []
        for holding in self.portfolio.values():
            if holding.invested:
                mark = self.latest.get(str(holding.symbol.id))
                price = mark[1] if mark else float(holding.price)
                values.append(float(holding.quantity) * price)
        return (cash + sum(values), sum((abs(v) for v in values)), cash)

    def issue(self, kind, symbol, held_value=0, **details):
        key = kind + ':' + str(symbol.id)
        item = self.issues.setdefault(key, {'kind': kind, 'ticker': symbol.value, 'first_date': str(self.time.date()), 'last_date': str(self.time.date()), 'observations': 0, 'max_held_value': 0.0})
        item['observations'] += 1
        item['last_date'] = str(self.time.date())
        item['max_held_value'] = max(item['max_held_value'], held_value)
        item.update(details)

    def after_close(self):
        if self.time.year == 2021:
            return
        if self.time.year not in (2022, 2023):
            raise ValueError('Outside frozen observation boundary')
        today = self.time.date()
        equity, gross, cash = self.close_equity()
        expected_cash = 100000 + self.trade_cash + self.dividend_cash + self.split_cash
        error = abs(cash - expected_cash)
        self.max_cash_error = max(self.max_cash_error, error)
        self.min_cash, self.max_gross = (min(self.min_cash, cash), max(self.max_gross, gross / equity if equity > 0 else 999))
        if cash < -0.01 or gross > equity + 0.01:
            self.stats['cash_or_leverage_breaches'] += 1
            raise ValueError('Negative cash or leverage; no strategy continuation')
        if error > 0.05:
            self.stats['cash_reconciliation_days'] += 1
        for holding in self.portfolio.values():
            sid = str(holding.symbol.id)
            expected_quantity = int(Decimal(str(self.prior_close_quantities.get(sid, 0.0))) / Decimal(str(self.pending_splits.get(sid, 1.0)))) + self.pending_fill_quantities[sid]
            difference = abs(float(holding.quantity) - expected_quantity)
            if difference > 1e-06:
                self.stats['quantity_reconciliation_errors'] += 1
                raise ValueError('Unexplained share quantity: ' + holding.symbol.value)
        monitored = set(self.pool) | {h.symbol for h in self.portfolio.values() if h.invested}
        for symbol in monitored:
            sid, mark = (str(symbol.id), self.latest.get(str(symbol.id)))
            self.stats['expected_security_days'] += 1
            if mark and mark[0].date() == today:
                self.stats['observed_security_days'] += 1
                continue
            key = 'known_terminated_missing' if sid in self.terminal else 'unknown_missing'
            self.stats[key] += 1
            value = abs(float(self.portfolio[symbol].holdings_value))
            self.issue(key, symbol, value)
            if value:
                self.stats['missing_held_days'] += 1
                self.stats['missing_held_value_sum'] += value
                self.stats['max_missing_held_value'] = max(self.stats['max_missing_held_value'], value)
                self.events.append({'kind': key, 'sid': sid, 'ticker': symbol.value, 'date': str(today), 'held_value': value})
        self.peak = max(self.peak, equity)
        self.max_dd = max(self.max_dd, 1 - equity / self.peak)
        self.nav.append((str(today), equity, gross, cash))
        self.prior_close_quantities = {str(h.symbol.id): float(h.quantity) for h in self.portfolio.values() if h.invested}
        self.pending_fill_quantities.clear()
        self.pending_splits.clear()
        if today.month == 12 and today.day == 29 and (today.year == 2023) or today == datetime(2022, 12, 30).date():
            self.annual[str(today.year)] = equity / self.year_start - 1
            self.year_start = equity
        if today == datetime(2023, 12, 28).date():
            self.finalizing = True
            self.frozen_targets = {}
            self.buy_after = None
            if self.mode != 'audit':
                self.reduce_to_targets({}, 'terminal')
        elif not self.finalizing and self.current_month and (not self.current_month.get('decision_time')):
            self.make_decision()
        elif not self.finalizing and self.buy_after and (today > self.buy_after):
            self.fund_buys()

    def make_decision(self):
        item = self.current_month
        item['decision_time'] = str(self.time)
        if datetime.fromisoformat(item['engine_available_time']) > self.time:
            raise ValueError('Universe arrived after decision')
        prices, ranked, count = ({}, [], Counter())
        calendar = list(self.history[TradeBar](self.spy, 21, Resolution.DAILY, fill_forward=False, data_normalization_mode=DataNormalizationMode.SPLIT_ADJUSTED))
        expected_dates = [b.end_time.date() for b in calendar]
        if len(expected_dates) != 21 or any((b.end_time > self.time for b in calendar)):
            raise ValueError('SPY reference trading calendar history failed')
        for symbol in self.pool:
            bars = list(self.history[TradeBar](symbol, 21, Resolution.DAILY, fill_forward=False, data_normalization_mode=DataNormalizationMode.SPLIT_ADJUSTED))
            ends = [b.end_time for b in bars]
            if any((t > self.time or t.year > 2025 for t in ends)) or len(ends) != len(set(ends)):
                raise ValueError('Momentum history time/identity gate failed')
            count['history_calls'] += 1
            count['history_rows'] += len(bars)
            if len(bars) < 21:
                count['momentum_history_insufficient'] += 1
                continue
            if [t.date() for t in ends] != expected_dates:
                count['momentum_unknown_calendar_gap'] += 1
                continue
            closes = [float(b.close) for b in bars]
            if not all((math.isfinite(p) and p > 0 for p in closes)):
                raise ValueError('Invalid split-adjusted momentum history')
            mark = self.latest.get(str(symbol.id))
            if not mark or mark[0].date() != self.time.date():
                count['decision_missing_current_price'] += 1
                continue
            prices[symbol] = mark[1]
            ranked.append((closes[-1] / closes[0] - 1, str(symbol.id), symbol))
        item.update(dict(count))
        item['momentum_eligible'] = len(ranked)
        if self.mode in ('audit', 'A'):
            targets = list(self.pool)
            prices.update({s: self.latest[str(s.id)][1] for s in targets if self.latest.get(str(s.id), (datetime.min, 0))[0].date() == self.time.date()})
        elif self.mode == 'B':
            targets = [r[2] for r in stable_top(ranked, 10)]
        else:
            targets = [self.spy]
            prices[self.spy] = self.latest[str(self.spy.id)][1]
        item['target_count'] = len(targets)
        item['unknown_price_excluded_from_order_only'] = len(self.pool) - sum((str(s.id) in self.latest and self.latest[str(s.id)][0].date() == self.time.date() for s in self.pool))
        equity = self.close_equity()[0]
        self.frozen_targets = whole_share_targets(targets, prices, equity)
        for holding in self.portfolio.values():
            if holding.invested and self.latest.get(str(holding.symbol.id), (datetime.min, 0))[0].date() != self.time.date():
                self.frozen_targets[holding.symbol] = int(holding.quantity)
        self.buy_after = self.time.date()
        if self.mode != 'audit':
            self.reduce_to_targets(self.frozen_targets, 'monthly')
        packed = []
        for key in MONTH_FIELDS:
            value = item.get(key, 0)
            if key.endswith('_time') or key == 'selection_callback':
                value = int((datetime.fromisoformat(value) - datetime(2022, 1, 1)).total_seconds())
            elif key == 'member_sid_sha256':
                value = base64.b64encode(bytes.fromhex(value)).decode()
            packed.append(value)
        self.packed_months.append(packed)
        if self.mode == 'audit':
            self.log('V15_MONTH ' + json.dumps(packed, separators=(',', ':')))

    def reduce_to_targets(self, targets, label):
        for holding in sorted(self.portfolio.values(), key=lambda h: str(h.symbol.id)):
            if not holding.invested:
                continue
            quantity = int(holding.quantity)
            reduction = quantity - targets.get(holding.symbol, 0)
            if self.latest.get(str(holding.symbol.id), (datetime.min, 0))[0].date() != self.time.date():
                self.issue('reduction_blocked_unknown_current_price', holding.symbol, abs(float(holding.holdings_value)))
                continue
            if reduction > 0 and (not self.transactions.get_open_orders(holding.symbol)):
                self.market_on_open_order(holding.symbol, -reduction, tag='v15:' + label + ':reduce')

    def fund_buys(self):
        if self.mode == 'audit':
            self.buy_after = None
            return
        if self.transactions.get_open_orders():
            self.stats['execution_wait_days'] += 1
            return
        cash = max(0, float(self.portfolio.cash))
        equity = self.close_equity()[0]
        available = max(0, cash - 0.1 * equity)
        wishes = []
        for symbol, target in sorted(self.frozen_targets.items(), key=lambda x: str(x[0].id)):
            quantity = target - int(self.portfolio[symbol].quantity)
            mark = self.latest.get(str(symbol.id))
            if quantity <= 0 or not mark or mark[0].date() != self.time.date():
                continue
            unit_cost = mark[1] * (1 + self.bps / 10000)
            wishes.append((symbol, quantity, unit_cost))
        required = sum((q * p for _, q, p in wishes))
        factor = min(1.0, available / required) if required else 0
        for symbol, quantity, unit_cost in wishes:
            amount = min(int(quantity * factor), int(available / unit_cost))
            if amount > 0:
                self.market_on_open_order(symbol, amount, tag='v15:monthly:buy')
                available -= amount * unit_cost
        self.buy_after = None

    def on_order_event(self, event):
        self.stats['order_events'] += 1
        if event.status == OrderStatus.INVALID:
            self.stats['invalid_orders'] += 1
            self.issue('invalid_order', event.symbol, abs(float(self.portfolio[event.symbol].holdings_value)), reason=str(event.message)[:240])
        if event.fill_quantity == 0:
            return
        order = self.transactions.get_order_by_id(event.order_id)
        quantity, price = (float(event.fill_quantity), float(event.fill_price))
        fee = float(event.order_fee.value.amount)
        notional = abs(quantity * price)
        self.notional += notional
        self.fees += fee
        self.trade_cash -= quantity * price + fee
        sid = str(event.symbol.id)
        self.pending_fill_quantities[sid] += quantity
        own = str(order.tag).startswith('v15:')
        expected = notional * self.bps / 10000
        difference = fee - expected
        if own:
            self.fee_difference += difference
            if abs(difference) > 0.01:
                self.stats['fee_mismatch_fills'] += 1
        else:
            self.stats['native_nonstrategy_fills'] += 1
            self.stats['native_liquidation_notional'] += notional
            self.stats['native_liquidation_fees'] += fee
        self.stats['fills'] += 1
        self.stats['buy_fills' if quantity > 0 else 'sell_fills'] += 1
        self.orders.append({'id': int(event.order_id), 'sid': str(event.symbol.id), 'engine_receipt': str(self.time), 'event_utc': str(event.utc_time), 'submitted_utc': str(order.time), 'type': str(order.type), 'modeled_open_local': str(self.time.replace(hour=9, minute=30, second=0)) if order.type == OrderType.MARKET_ON_OPEN else None, 'quantity': quantity, 'fill_price': price, 'fee': fee, 'own': own, 'native_terminal_value_not_proven': not own})
        if self.time.year > 2025 or (own and order.time >= event.utc_time):
            self.stats['fill_timing_violations'] += 1
        if not own:
            self.issue('native_terminal_liquidation', event.symbol, notional, engine_cash_credit=-quantity * price - fee, ordinary_fee_not_applied=expected - fee)

    def on_end_of_algorithm(self):
        if not self.nav:
            return
        equity, gross, cash = self.close_equity()
        elapsed_years = (datetime(2024, 1, 1) - datetime(2022, 1, 1)).days / 365.25
        returns = [self.nav[i][1] / self.nav[i - 1][1] - 1 for i in range(1, len(self.nav))]
        mean = sum(returns) / len(returns) if returns else 0
        volatility = math.sqrt(sum(((r - mean) ** 2 for r in returns)) / max(1, len(returns) - 1) * 252)
        avg_equity = sum((row[1] for row in self.nav)) / len(self.nav)
        unresolved = [e for e in self.events if e['kind'] in ('delisted', 'unknown_missing') and (e.get('holding_value_seen', 0) or e.get('held_value', 0))]
        summary = {'mode': self.mode, 'cost_bps': self.bps, 'complete_months': len(self.months), 'daily_close_rows': len(self.nav), 'cumulative_security_ids': len(self.seen), 'net_cumulative': equity / 100000 - 1, 'net_cagr': (equity / 100000) ** (1 / elapsed_years) - 1, 'max_drawdown': self.max_dd, 'annualized_volatility': volatility, 'annual_returns': self.annual, 'average_exposure': sum((r[2] / r[1] for r in self.nav)) / len(self.nav), 'turnover_gross_notional_over_average_equity': self.notional / avg_equity, 'traded_notional': self.notional, 'fees_paid': self.fees, 'own_fee_difference_from_fill_bps': self.fee_difference, 'final_equity': equity, 'final_cash': cash, 'final_gross_holdings': gross, 'dividend_cash_engine_proxy': self.dividend_cash, 'split_fraction_cash_engine_proxy': self.split_cash, 'max_cash_reconciliation_error': self.max_cash_error, 'minimum_cash': self.min_cash, 'maximum_exposure': self.max_gross, 'unresolved_held_events': len(unresolved) + self.stats['native_nonstrategy_fills'], 'stats': dict(self.stats), 'unverified_terminal_gross_cash': self.stats['native_liquidation_notional'], 'training_count': 0, 'native_orders_only': True, 'object_store_written': False, 'terminal_assumption': 'engine liquidation; unverified recovery; no warning exit signal', 'scope': '2022-2023 development pilot, not independent or 2016-2025 validation'}
        summary['first_close_date'], summary['last_close_date'] = (self.nav[0][0], self.nav[-1][0])
        summary['open_orders_at_end'] = len(self.transactions.get_open_orders())
        complete = len(self.months) == 24 and self.nav[0][0] == '2022-01-03' and (self.nav[-1][0] == '2023-12-29') and (set(self.annual) == {'2022', '2023'})
        flat = self.mode == 'audit' or (gross < 0.01 and summary['open_orders_at_end'] == 0)
        summary['gate_pass'] = complete and flat and (not any((self.stats[k] for k in ('duplicate_bars', 'invalid_bars', 'cash_or_leverage_breaches', 'fill_timing_violations', 'cash_reconciliation_days', 'quantity_reconciliation_errors', 'fee_mismatch_fills', 'invalid_orders', 'stale_universe'))))
        target_index = MONTH_FIELDS.index('target_count')
        pool_rows = [row[:target_index] + row[target_index + 1:] for row in self.packed_months]
        digest = lambda rows: hashlib.sha256(json.dumps(rows, separators=(',', ':')).encode()).hexdigest()
        self.log('V15_MONTH_CHECK ' + json.dumps({'rows': len(self.packed_months), 'packed_sha256': digest(self.packed_months), 'pool_sha256': digest(pool_rows), 'target_counts': [row[target_index] for row in self.packed_months], 'pool_excludes_only': 'target_count'}, separators=(',', ':')))
        material = [i for i in self.issues.values() if i['max_held_value'] > 0 or i['kind'] in ('unknown_missing', 'known_terminated_missing', 'invalid_order', 'raw_jump_unexplained')]
        summary['issue_detail_emitted'] = len(material)
        summary['unheld_jump_details_omitted'] = len(self.issues) - len(material)
        self.log('V15_SUMMARY ' + json.dumps(summary, separators=(',', ':')))
        for item in material:
            base = ('kind', 'ticker', 'first_date', 'last_date', 'observations', 'max_held_value')
            packed = [item[k] for k in base] + [{k: v for k, v in item.items() if k not in base}]
            self.log('V15_ISSUE ' + json.dumps(packed, separators=(',', ':')))
        for key in ('net_cagr', 'max_drawdown', 'average_exposure', 'fees_paid', 'gate_pass'):
            self.set_runtime_statistic('v15_' + key, str(summary[key]))
