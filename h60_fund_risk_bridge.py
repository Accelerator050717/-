"""Offline-only bridge from durable H60 execution facts to a strategy-fund NAV ledger.

The two SQLite files are NOT a distributed transaction. The fund transaction
atomically saves processed fill/fee IDs and the complete execution checkpoint.
Before any further risk, a crash gap is recovered from reconciled execution facts.
The scope is the assigned strategy budget/owned symbols, never an IBKR account.
Existing paper adapters are deliberately not accepted by this entry point.
"""
from copy import deepcopy

from h60_execution import ExecutionBlocked, VirtualBroker, digest, number, utc
from h60_execution_cycle import plan_open_cycle as original_plan_open_cycle, submit_next
from h60_global_control import GlobalRisk


class FundRiskBridge:
    def __init__(self, client, fund, broker, *, run_id):
        if client.config.mode != 'virtual' or type(broker) is not VirtualBroker:
            raise ExecutionBlocked('v13 bridge supports fictitious VirtualBroker only')
        self.client, self.fund, self.broker = client, fund, broker
        self.run_id = run_id
        if not run_id:
            raise ExecutionBlocked('A process/run identity is required')
        if (fund.read()['scope']['currency'] != 'USD'
                or fund.read()['scope'].get('execution_strategy_id') != client.config.strategy_id
                or set(fund.read()['scope']['universe']) != set(client.symbols)
                or number(fund.identity['initial_cash']) != number(client.config.budget)):
            raise ExecutionBlocked('Fund scope/universe/initial allocation differs from execution ledger')

    @staticmethod
    def stopped_buy_remainders(source, keys=None):
        stopped = []
        for key in keys if keys is not None else source['orders']:
            row = source['orders'][key]
            if row.get('terminal_reconciled') or row['state']['side'] != 'BUY':
                continue
            if any(other['reason'] == 'stock_protection'
                   and other['state']['symbol'] == row['state']['symbol']
                   and any(utc(t) >= utc(row['created_at']) for t in other.get('fill_times', {}).values())
                   for other in source['orders'].values()):
                stopped.append(key)
        return stopped

    @staticmethod
    def facts(document):
        events = []
        for row in document['orders'].values():
            order = row['state']
            for eid, fill in order['executions'].items():
                if eid not in document['commissions'] or eid not in row.get('fill_times', {}):
                    raise ExecutionBlocked('Actual fill time and commission must be reconciled')
                moment = row['fill_times'][eid]
                signed = str(number(fill['quantity']) * (1 if order['side'] == 'BUY' else -1))
                events.append(dict(id='fill:' + eid, at=moment, kind='fill',
                                   symbol=order['symbol'], quantity=signed, price=fill['price']))
                fee = document['commissions'][eid]
                if fee['currency'] != 'USD':
                    raise ExecutionBlocked('Unsupported fee currency')
                events.append(dict(id='commission:' + eid, at=moment, kind='income',
                                   amount=str(-number(fee['fee'])), reason='fee'))
        return sorted(events, key=lambda event: (event['at'], event['kind'] != 'fill', event['id']))

    def _check_source_continuity(self, document):
        previous = self.fund.read().get('checkpoint') or {}
        old = previous.get('execution_document')
        if old is None:
            if document['orders'] or document.get('runtime') is not None:
                raise ExecutionBlocked('Fresh fund cannot adopt an existing strategy history; restore its original fund ledger')
            return
        if old['spec'] != document['spec']:
            raise ExecutionBlocked('Execution identity changed; model handoff needs a separate reviewed adapter')
        if document['version'] < old['version'] or not set(old['orders']).issubset(document['orders']):
            raise ExecutionBlocked('Execution ledger rolled back or lost persisted order intents')
        current_facts = {event['id']: event for event in self.facts(document)}
        if any(current_facts.get(event['id']) != event for event in self.facts(old)):
            raise ExecutionBlocked('Previously checkpointed execution facts changed or disappeared')

    def sync(self, now, prices, *, risk_state=None):
        """Reconcile first, then publish actual balances + all facts in one fund commit.

        A partial/unfilled exit remains an actual position. Commission-pending,
        missing history, unexplained cash and stale facts never authorize risk.
        """
        if not self.client.reconcile(self.broker, now):
            raise ExecutionBlocked('Source reconciliation failed: ' + str(self.client.journal.read()['blocked']))
        document = self.client.journal.read()
        self._check_source_continuity(document)
        stopped = [key for key in self.stopped_buy_remainders(document)
                   if not document['orders'][key]['state']['cancel_requested']]
        if stopped:
            # Stop fills must cancel the old entry remainder even in HALTED mode.
            # This path can only cancel: submit_next returns before submission.
            result = submit_next(self.client, self.broker, stopped, {}, now)
            if result['status'] != 'protection_triggered_cancel_buy_remainder':
                raise ExecutionBlocked('Unexpected stop/cancel reconciliation result')
            if not self.client.reconcile(self.broker, now):
                raise ExecutionBlocked('Cancellation facts require reconciliation')
            document = self.client.journal.read()
        cash, positions = self.client.balances(document)
        old_state = self.fund.read()
        checkpoint = dict(execution_document=deepcopy(document), execution_digest=digest(document),
                          source_version=document['version'], run_id=self.run_id,
                          scope_boundary='allocated strategy cash plus strategy-owned symbols only')
        state = self.fund.commit(
            batch_id='execution:' + digest([document, str(now), prices, risk_state]),
            at=utc(now).isoformat(), events=self.facts(document), prices=prices,
            checkpoint=checkpoint, model_version=document['spec']['strategy_manifest_hash'],
            run_id=self.run_id, expected_cash=str(cash),
            expected_positions={symbol: str(value) for symbol, value in positions.items()},
            risk_state=risk_state if risk_state is not None else old_state.get('risk_state'))
        if state.get('blocked'):
            raise ExecutionBlocked('Fund accounting needs review: ' + str(state['blocked']))
        return state

    def require_ready(self, *, increasing_risk=True, now=None, prices=None):
        state = self.fund.read()
        checkpoint = state.get('checkpoint') or {}
        document = self.client.journal.read()
        if state.get('blocked') or document.get('blocked'):
            raise ExecutionBlocked('Accounting/reconciliation block prevents new decisions')
        if checkpoint.get('execution_digest') != digest(document):
            raise ExecutionBlocked('Execution/fund checkpoint gap: reconcile and replay facts first')
        if now is not None and not 0 <= (utc(now)-utc(state['last_valuation_at'])).total_seconds() <= 30:
            raise ExecutionBlocked('Fresh fund valuation required before execution')
        if prices is not None and any(number(state['last_prices'][s]) != number(prices[s]) for s in self.client.symbols):
            raise ExecutionBlocked('Changed execution quotes require a new fund valuation')
        if increasing_risk and self.gross_cap(state) <= 0:
            raise ExecutionBlocked('Risk state does not authorize additional exposure')
        return state

    @staticmethod
    def gross_cap(state):
        risk = state.get('risk_state') or {}
        if risk.get('mode') == 'record_only':
            return 1. if risk.get('allow_new_risk') is True else 0.
        if risk.get('mode') not in ('NORMAL', 'REDUCED', 'HALTED', 'RECOVERY', 'REVIEW_LOCKED'):
            raise ExecutionBlocked('Missing/invalid continuous risk state')
        if risk['mode'] == 'RECOVERY' and (risk.get('resume_unit_nav') is None or risk.get('recovery_floor') is None):
            raise ExecutionBlocked('Recovery anchors missing from continuous risk state')
        try:
            # Same policy/controller used by the fixed research comparison.
            return GlobalRisk(**risk).cap(float(state['unit_nav']), float(state['high_water_nav']))
        except (TypeError, ValueError) as exc:
            raise ExecutionBlocked('Missing/invalid continuous risk state') from exc

    def gate_targets(self, weights, *, reduction=False, now=None, prices=None):
        state = self.require_ready(increasing_risk=not reduction, now=now, prices=prices)
        cap = self.gross_cap(state)
        gross = sum(float(value) for value in weights.values())
        multiplier = min(1., cap / gross) if gross > 0 else 1.
        return {symbol: float(value) * multiplier for symbol, value in weights.items()}

    def plan_targets(self, decision_id, weights, quotes, now, *, reduction=False,
                     reason='scheduled', runtime_after=None):
        weights = self.gate_targets(weights, reduction=reduction, now=now,
                                    prices={s: quotes[s]['bid'] for s in self.client.symbols})
        keys = self.client.plan_targets(decision_id, weights, quotes, now,
            reduction=reduction, reason=reason, runtime_after=runtime_after)
        self.sync(now, {symbol: quotes[symbol]['bid'] for symbol in self.client.symbols})
        return keys

    def record_only_open_cycle(self, manifest, day, scores, risk, quotes, now):
        """Existing shared runtime unchanged; record-only mode must be explicit.

        Global-control order transformation is not silently applied here. This
        offline method proves checkpoint/target parity of the frozen runtime.
        """
        state = self.require_ready(now=now, prices={s: quotes[s]['bid'] for s in self.client.symbols})
        if (state.get('risk_state') or {}).get('mode') != 'record_only':
            raise ExecutionBlocked('This entry only verifies record-only runtime parity')
        result = original_plan_open_cycle(self.client, self.broker, manifest, day,
                                         scores, risk, quotes, now)
        self.sync(now, {symbol: quotes[symbol]['bid'] for symbol in self.client.symbols})
        return result

    def submit_virtual(self, key, quotes, now):
        source = self.client.journal.read()
        order = source['orders'][key]['state']
        state = self.require_ready(increasing_risk=order['side'] == 'BUY' and not order['attempted'],
                                  now=now, prices={s: quotes[s]['bid'] for s in self.client.symbols})
        if order['side'] == 'BUY' and not order['attempted']:
            cash, positions = self.client.balances(source)
            gross = sum(positions[s] * number(quotes[s]['ask']) for s in self.client.symbols)
            nav = cash + gross
            additional = number(0)
            for other_key, row in source['orders'].items():
                other = self.client.order(row)
                if (other.side == 'BUY' and not row.get('terminal_reconciled')
                        and (other.attempted or other_key == key)):
                    additional += (number(other.quantity) - other.filled) * number(quotes[other.symbol]['ask'])
            if float((gross + additional) / nav) > self.gross_cap(state) + 1e-12:
                raise ExecutionBlocked('Outstanding buys exceed the current continuous-risk gross cap')
        accepted = self.client.submit(key, self.broker, quotes, now)
        # No fund publication on ambiguity. Source attempted=True already durable;
        # the next call to sync must reconcile and can never repeat this attempt.
        if accepted or not self.client.journal.read()['blocked']:
            self.sync(now, {symbol: quotes[symbol]['bid'] for symbol in self.client.symbols})
        return accepted

    def cancel_stopped_buy_remainders(self, keys, quotes, now):
        """Preserve v8's stop/entry race handling even while global risk is halted."""
        self.require_ready(increasing_risk=False, now=now,
                           prices={s: quotes[s]['bid'] for s in self.client.symbols})
        source = self.client.journal.read()
        stopped = self.stopped_buy_remainders(source, keys)
        if not stopped:
            return dict(status='no_stopped_buy_remainder', intents=[])
        # Existing coordinator returns after these cancellations, before submits.
        result = submit_next(self.client, self.broker, stopped, quotes, now)
        if result['status'] != 'protection_triggered_cancel_buy_remainder':
            raise ExecutionBlocked('Unexpected stop/cancel reconciliation result')
        self.sync(now, {symbol: quotes[symbol]['bid'] for symbol in self.client.symbols})
        return result
