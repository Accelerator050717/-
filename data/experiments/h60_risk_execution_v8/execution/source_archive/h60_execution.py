"""Durable paper/virtual execution ledger. No live-account execution mode.

SQLite stores one small versioned journal atomically; OrderState remains the
per-order event merger. The broker is a separate source of facts. An uncertain
submission is NEVER retried, even when absent from an open-order snapshot.
"""
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
import hashlib
import json
import os
from pathlib import Path
import sqlite3

import numpy as np

from execution_order_state import OrderState
from research_backtest import _rebalance, reduce_only


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def intent_prefix(strategy_id):
    return 'H60V8-'+digest(strategy_id)[:5]+'-'


def number(value):
    x = Decimal(str(value))
    if not x.is_finite():
        raise ValueError('Non-finite execution value')
    return x


def utc(value):
    result = datetime.fromisoformat(value) if isinstance(value, str) else value
    if result.tzinfo is None:
        raise ValueError('Execution timestamps must include timezone')
    return result.astimezone(timezone.utc)


class ExecutionBlocked(ValueError):
    pass


@dataclass(frozen=True)
class ExecutionConfig:
    strategy_id: str = 'h60-v8-engineering'
    mode: str = 'virtual'
    budget: str = '10000'
    quantity_step: str = '1'
    fee_reserve_rate: str = '.002'
    max_quote_age_seconds: int = 30
    paper_budget_isolated: bool = False
    paper_identity_confirmed: bool = False

    def validate(self):
        if self.mode not in ('virtual','paper'):
            raise ExecutionBlocked('Live account execution is not implemented')
        if (not self.strategy_id or number(self.budget) <= 0 or number(self.quantity_step) != 1
                or not 0 <= number(self.fee_reserve_rate) <= Decimal('.05')
                or not 0 < self.max_quote_age_seconds <= 60):
            raise ExecutionBlocked('Invalid config; initial implementation supports whole shares only')
        if self.mode == 'paper' and (not self.paper_budget_isolated or not self.paper_identity_confirmed
                                     or number(self.budget) > 1000):
            raise ExecutionBlocked('Paper requires confirmed identity and isolated budget <= USD 1000')


class Journal:
    def __init__(self, path, initial):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        marker = self.path.with_suffix(self.path.suffix+'.initialized')
        if marker.exists():
            if not self.path.exists() or marker.read_text(encoding='utf-8') != digest(initial):
                raise ExecutionBlocked('Previously initialized ledger missing or initialization identity changed')
        else:
            if self.path.exists():
                raise ExecutionBlocked('Existing ledger has no initialization identity; do not adopt it')
            with marker.open('x',encoding='utf-8') as handle:
                handle.write(digest(initial)); handle.flush(); os.fsync(handle.fileno())
        self.db = sqlite3.connect(self.path, timeout=3)
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS journal (id INTEGER PRIMARY KEY CHECK(id=1), document TEXT NOT NULL)')
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO journal VALUES(1,?)', (json.dumps(initial, allow_nan=False),))

    def read(self):
        return json.loads(self.db.execute('SELECT document FROM journal WHERE id=1').fetchone()[0])

    @contextmanager
    def change(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            state = self.read()
            yield state
            state['version'] += 1
            self.db.execute('UPDATE journal SET document=? WHERE id=1', (json.dumps(state, allow_nan=False),))
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def close(self):
        self.db.close()


class H60Executor:
    def __init__(self, path, config, manifest_hash, symbols):
        config.validate()
        self.config, self.symbols = config, list(symbols)
        spec = dict(config=asdict(config), strategy_manifest_hash=manifest_hash, symbols=self.symbols)
        self.journal = Journal(path, dict(version=1,spec=spec,orders={},batches={},commissions={},events=[],
            reconciliation=None,blocked='initial_reconciliation_required',account_cash_offset=None,runtime=None))
        if self.journal.read()['spec'] != spec:
            raise ExecutionBlocked('Persisted strategy/model/config identity differs; cannot reset or adopt ledger')

    @staticmethod
    def order(row):
        return OrderState.from_json(json.dumps(row['state']))

    @staticmethod
    def set_order(row, order):
        row['state'] = asdict(order)

    def balances(self, state=None):
        state = state or self.journal.read()
        cash = number(self.config.budget)
        positions = {s:Decimal(0) for s in self.symbols}
        for row in state['orders'].values():
            order = self.order(row)
            cash += order.cash_delta_before_fees
            positions[order.symbol] += order.filled * (1 if order.side == 'BUY' else -1)
        cash -= sum((number(c['fee']) for c in state['commissions'].values()), Decimal(0))
        if cash < 0 or any(q < 0 for q in positions.values()):
            raise ExecutionBlocked('Ledger is overdrawn or short; reconciliation required')
        return cash, positions

    def reservations(self, state=None):
        state = state or self.journal.read()
        cash, sells = Decimal(0), {s:Decimal(0) for s in self.symbols}
        for row in state['orders'].values():
            order = self.order(row)
            # Cancel request/status alone does not release anything. A complete
            # authoritative reconciliation must first confirm the terminal fact.
            if row.get('terminal_reconciled'):
                continue
            remaining = number(order.quantity) - order.filled
            if order.side == 'BUY':
                # Unsubmitted buys are deferred behind actual sale receipts. The
                # batch excludes other decisions; submit checks cash before each
                # attempt. Once attempted, reserve through timeout/cancel races.
                if order.attempted:
                    cash += remaining * number(row['limit_price']) * (1 + number(self.config.fee_reserve_rate))
            else:
                sells[order.symbol] += remaining
        return cash, sells

    def block(self, reason):
        with self.journal.change() as state:
            state['blocked'] = reason
            state['events'].append(dict(kind='blocked',reason=reason))

    def reconcile(self, broker, now):
        """Merge facts, deduplicate fills/fees, then compare cash and own positions.

        Unrelated positions are never adopted. Other-account cash changes block
        this isolated budget until explained; they are not silently assigned.
        """
        try:
            snapshot = broker.snapshot(now)
        except Exception as exc:
            self.block('snapshot_failed_'+type(exc).__name__)
            return False
        okay = True
        with self.journal.change() as state:
            state['blocked'] = None
            if (broker.mode != self.config.mode or not snapshot.get('identity_confirmed')
                    or not snapshot.get('complete') or snapshot.get('corporate_actions_pending')
                    or not 0 <= (utc(now)-utc(snapshot['asof'])).total_seconds() <= 30):
                state['blocked'] = 'untrusted_or_incomplete_broker_snapshot'
                state['reconciliation'] = snapshot
                return False
            known_refs = set(state['orders'])
            for ref, fact in snapshot['orders'].items():
                if fact.get('strategy_id') == self.config.strategy_id and ref not in known_refs:
                    state['blocked'] = 'orphan_owned_order_requires_review'
            execution_owner = {eid:key for key,row in state['orders'].items() for eid in row['state']['executions']}
            for key,row in state['orders'].items():
                order = self.order(row)
                fact = snapshot['orders'].get(key)
                if not order.attempted:
                    if fact:
                        state['blocked'] = 'broker_order_without_persisted_attempt'
                    continue
                if not fact:
                    if not row.get('terminal_reconciled'):
                        order.mark_disconnected()
                        state['blocked'] = 'attempted_order_missing_from_available_broker_history'
                    self.set_order(row,order)
                    continue
                try:
                    if (fact['strategy_id'] != self.config.strategy_id or fact['symbol'] != order.symbol
                            or fact['side'] != order.side or number(fact['quantity']) != number(order.quantity)):
                        raise ExecutionBlocked('broker_intent_identity_conflict')
                    order.acknowledge(fact['reference'])
                    for fill in fact['fills']:
                        if fill['id'] in execution_owner and execution_owner[fill['id']] != key:
                            raise ExecutionBlocked('execution_id_owned_by_other_intent')
                        order.record_execution(fill['id'],fact['reference'],fill['quantity'],fill['price'],correction=fill.get('correction',False))
                        execution_owner[fill['id']] = key
                        commission = snapshot['commissions'].get(fill['id'])
                        if commission is None or commission['currency'] != 'USD' or number(commission['fee']) < 0:
                            state['blocked'] = 'commission_pending_or_unsupported_currency'
                        elif fill['id'] in state['commissions'] and state['commissions'][fill['id']] != commission:
                            raise ExecutionBlocked('commission_correction_requires_review')
                        else:
                            state['commissions'][fill['id']] = commission
                    order.observe_status(fact['reference'],fact['status'],fact['filled'])
                    terminal = fact['status'] in ('Filled','Cancelled','ApiCancelled')
                    verified = order.reconcile(snapshot_complete=True,
                        open_references=[] if terminal else [fact['reference']],
                        terminal_reference=fact['reference'] if terminal else None,
                        terminal_status=fact['status'] if terminal else None,total_executed=fact['filled'])
                    if not verified:
                        state['blocked'] = 'order_status_execution_mismatch'
                    row['terminal_reconciled'] = bool(terminal and verified)
                except (ValueError, KeyError) as exc:
                    state['blocked'] = 'order_reconciliation_'+str(exc)
                    order.uncertain = True
                self.set_order(row,order)
            try:
                cash, positions = self.balances(state)
                actual = {s:number(snapshot['positions'].get(s,0)) for s in self.symbols}
                if actual != positions:
                    state['blocked'] = 'own_symbol_position_mismatch_or_foreign_overlap'
                if state['account_cash_offset'] is None:
                    if state['orders'] or any(actual.values()) or number(snapshot['cash']) < cash:
                        state['blocked'] = 'cannot_initialize_nonflat_or_insufficient_isolated_budget'
                    else:
                        state['account_cash_offset'] = str(number(snapshot['cash'])-cash)
                if state['account_cash_offset'] is not None and abs(number(snapshot['cash'])-number(state['account_cash_offset'])-cash) > Decimal('.02'):
                    state['blocked'] = 'cash_mismatch_or_unexplained_external_cashflow'
                reserve, sells = self.reservations(state)
                if reserve > cash or any(sells[s] > positions[s] for s in sells):
                    state['blocked'] = 'reservation_exceeds_own_cash_or_positions'
            except ValueError as exc:
                state['blocked'] = str(exc)
            state['reconciliation'] = snapshot
            state['events'].append(dict(kind='reconciliation',asof=snapshot['asof'],blocked=state['blocked']))
            okay = state['blocked'] is None
        return okay

    def _quotes(self, quotes, now, symbols):
        for s in symbols:
            q = quotes[s]
            age = (utc(now)-utc(q['asof'])).total_seconds()
            expected_basis = 'synthetic_unadjusted_quote' if self.config.mode=='virtual' else 'broker_unadjusted_quote'
            if (q['basis'] != expected_basis or q.get('corporate_action_pending') or not q.get('regular_session')
                    or not 0 <= age <= self.config.max_quote_age_seconds
                    or not 0 < number(q['bid']) <= number(q['ask']) or not q.get('quantity_step_confirmed')):
                raise ExecutionBlocked('stale_or_untrusted_quote_'+s)

    def plan_targets(self, decision_id, weights, quotes, now, *, reduction=False, reason='scheduled', runtime_after=None):
        """Persist the decision and all order intents in ONE transaction, before any submission."""
        signature = dict(weights=weights,reduction=reduction,reason=reason)
        with self.journal.change() as state:
            if decision_id in state['batches']:
                prior = state['batches'][decision_id]
                if prior['signature'] != signature:
                    raise ExecutionBlocked('same_decision_id_with_different_targets')
                return prior['intents']
            if state['blocked'] or state['reconciliation'] is None:
                raise ExecutionBlocked('new_intent_blocked_until_reconciliation')
            self._quotes(quotes, now, self.symbols)
            if set(weights) != set(self.symbols) or any(not np.isfinite(v) or v<0 for v in weights.values()) or sum(weights.values()) > 1+1e-10:
                raise ExecutionBlocked('invalid_target_weights')
            cash, positions = self.balances(state)
            reserved_cash, reserved_sells = self.reservations(state)
            active = [self.order(row) for row in state['orders'].values() if not row.get('terminal_reconciled')]
            if active:
                raise ExecutionBlocked('cancel_and_reconcile_existing_orders_before_new_target_batch')
            # Use ask for budget-conservative target sizing; sells use a bid limit.
            prices = np.array([float(quotes[s]['ask']) for s in self.symbols])
            units = np.array([float(positions[s]) for s in self.symbols])
            sizing = reduce_only if reduction else _rebalance
            target,_,_,_ = sizing(units*prices,float(cash-reserved_cash),np.array([weights[s] for s in self.symbols]),float(self.config.fee_reserve_rate))
            desired = {s:(number(target[j]/prices[j])/number(self.config.quantity_step)).to_integral_value(rounding=ROUND_DOWN)*number(self.config.quantity_step) for j,s in enumerate(self.symbols)}
            if reduction and any(desired[s] > positions[s] for s in self.symbols):
                raise AssertionError('Risk reduction attempted to buy')
            intents=[]
            # Persist sell and buy intents, but submit checks enforce sell-first and
            # actual available cash. Unfilled sale proceeds are never spendable.
            for s in sorted(self.symbols,key=lambda n:(desired[n]-positions[n],n)):
                delta=desired[s]-positions[s]
                if delta == 0:
                    continue
                side='BUY' if delta>0 else 'SELL'
                price=quotes[s]['ask' if delta>0 else 'bid']
                key=intent_prefix(self.config.strategy_id)+digest([state['spec']['strategy_manifest_hash'],decision_id,s,side])[:18]
                order=OrderState(key,s,side,str(abs(delta)))
                state['orders'][key]=dict(state=asdict(order),decision=decision_id,kind='LMT',
                    limit_price=str(price),stop_price=None,reason=reason,terminal_reconciled=False,created_at=utc(now).isoformat())
                intents.append(key)
            state['batches'][decision_id]=dict(signature=signature,intents=intents,quotes=quotes,created_at=utc(now).isoformat())
            if runtime_after is not None:
                state['runtime']=runtime_after
            state['events'].append(dict(kind='intents_persisted',decision=decision_id,count=len(intents)))
            return intents

    def submit(self, key, broker, quotes, now):
        with self.journal.change() as state:
            row=state['orders'][key]; order=self.order(row)
            if order.attempted:
                return False  # Idempotent: never resubmit, including unknown attempts.
            if state['blocked'] or broker.mode!=self.config.mode:
                raise ExecutionBlocked('submission_blocked')
            self._quotes(quotes,now,[order.symbol])
            if not 0 <= (utc(now)-utc(row['created_at'])).total_seconds() <= 300:
                raise ExecutionBlocked('unsubmitted_intent_expired_reconcile_and_cancel_locally')
            if (utc(now)-utc(state['reconciliation']['asof'])).total_seconds()>30:
                raise ExecutionBlocked('broker_snapshot_stale')
            cash,positions=self.balances(state)
            reserve,sells=self.reservations(state)
            if order.side=='BUY':
                # Exclude unattempted other buys here; persist-all batches may need
                # prior sells to fill. Each actual submit is checked sequentially.
                other=sum((number(r['state']['quantity'])-self.order(r).filled)*number(r['limit_price'])*(1+number(self.config.fee_reserve_rate))
                          for k,r in state['orders'].items() if k!=key and r['state']['side']=='BUY' and r['state']['attempted'] and not r.get('terminal_reconciled'))
                required=number(order.quantity)*number(row['limit_price'])*(1+number(self.config.fee_reserve_rate))
                available=min(cash,number(state['reconciliation']['available_cash']))
                if required+other>available:
                    raise ExecutionBlocked('insufficient_settled_available_cash')
            elif sells[order.symbol]>positions[order.symbol]:
                raise ExecutionBlocked('sell_or_stop_reservations_exceed_actual_position')
            order.begin_attempt()  # This transaction commits BEFORE calling broker.
            self.set_order(row,order)
            state['events'].append(dict(kind='submit_attempt_persisted',intent=key))
            payload=dict(key=key,strategy_id=self.config.strategy_id,symbol=order.symbol,side=order.side,
                         quantity=order.quantity,kind=row['kind'],limit_price=row['limit_price'],stop_price=row['stop_price'])
        try:
            reference=broker.submit(payload,now)
        except Exception as exc:
            self.block('submit_outcome_unknown_'+type(exc).__name__)
            return False
        with self.journal.change() as state:
            row=state['orders'][key]; order=self.order(row)
            order.acknowledge(reference)
            self.set_order(row,order)
            state['events'].append(dict(kind='submit_acknowledged_reconciliation_required',intent=key))
            state['blocked']='post_submit_reconciliation_required'
        return True

    def cancel(self, key, broker, now):
        with self.journal.change() as state:
            row=state['orders'][key]; order=self.order(row)
            if row.get('terminal_reconciled'):
                return False
            if not order.attempted:
                row['terminal_reconciled']=True
                order.terminal_status='CANCELLED'
                self.set_order(row,order)
                return True
            if not order.broker_reference or broker.mode!=self.config.mode:
                raise ExecutionBlocked('unknown_order_must_be_reconciled_before_cancellation')
            if not order.cancel_requested:
                order.request_cancel_locally()
            self.set_order(row,order)
            state['events'].append(dict(kind='cancel_requested_reservation_retained',intent=key))
        broker.cancel(key,now)
        return True

    def plan_protection(self, floors, quotes, now):
        """Protect only filled, strategy-owned shares. Existing sell reservations count.

        Incremental fills can add incremental protection, avoiding overlapping full
        position stops. To raise an old stop, first cancel it and reconcile its
        terminal state; never replace an unconfirmed cancelled order.
        """
        with self.journal.change() as state:
            if state['blocked']:
                raise ExecutionBlocked('protection_requires_trustworthy_positions')
            cash,positions=self.balances(state)
            _,reserved=self.reservations(state)
            intents=[]
            for s in self.symbols:
                unprotected=positions[s]-reserved[s]
                if unprotected<=0:
                    continue
                self._quotes(quotes,now,[s])
                if s not in floors or number(floors[s])<=0:
                    raise ExecutionBlocked('missing_protection_floor')
                # Filled quantity and existing protection keys identify this revision.
                revision=sorted(k for k,r in state['orders'].items() if r['state']['symbol']==s)
                key=intent_prefix(self.config.strategy_id)+digest(['protect',s,str(positions[s]),str(floors[s]),revision])[:18]
                order=OrderState(key,s,'SELL',str(unprotected))
                state['orders'][key]=dict(state=asdict(order),decision='protection',kind='STP',
                    limit_price=str(quotes[s]['bid']),stop_price=str(floors[s]),reason='stock_protection',terminal_reconciled=False,
                    created_at=utc(now).isoformat())
                intents.append(key)
            state['events'].append(dict(kind='protection_intents_persisted',count=len(intents)))
            return intents

    def save_runtime(self, runtime):
        with self.journal.change() as state:
            state['runtime']=runtime

    def export(self, path):
        state=self.journal.read()
        cash,positions=self.balances(state)
        reserve,sells=self.reservations(state)
        state['derived']=dict(cash=str(cash),positions={s:str(v) for s,v in positions.items()},
                              reserved_cash=str(reserve),reserved_sells={s:str(v) for s,v in sells.items()})
        Path(path).write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')


class VirtualBroker:
    """Persistent fictitious broker, separate from client journal. Never uses historical adjusted prices."""
    mode='virtual'

    def __init__(self,path,budget='10000',outside_positions=None):
        self.journal=Journal(path,dict(version=1,cash=str(budget),positions=outside_positions or {},orders={},commissions={},events=[],identity_confirmed=True,corporate_actions_pending=False))
        self.timeout_after_accept=False
        self.snapshot_complete=True

    def submit(self,payload,now):
        with self.journal.change() as state:
            if payload['key'] in state['orders']:
                raise ExecutionBlocked('Duplicate broker submit: caller must reconcile')
            state['orders'][payload['key']]=dict(payload,reference='virtual:'+payload['key'],status='Submitted',filled='0',fills=[])
            state['events'].append(dict(kind='submit',key=payload['key']))
        if self.timeout_after_accept:
            self.timeout_after_accept=False
            raise TimeoutError('Synthetic network failure after broker acceptance')
        return 'virtual:'+payload['key']

    def fill(self,key,quantity,price,now,*,execution_id=None,commission=True):
        with self.journal.change() as state:
            row=state['orders'][key]
            quantity,price=number(quantity),number(price)
            if row['status'] in ('Filled','Cancelled','ApiCancelled') or quantity<=0 or price<=0 or quantity+number(row['filled'])>number(row['quantity']):
                raise ExecutionBlocked('Invalid fictitious fill')
            if row['kind']=='LMT' and ((row['side']=='BUY' and price>number(row['limit_price'])) or (row['side']=='SELL' and price<number(row['limit_price']))):
                raise ExecutionBlocked('Fictitious fill violates order limit')
            qty=number(state['positions'].get(row['symbol'],0))
            fee=quantity*price*Decimal('.001')
            new_qty=qty+quantity*(1 if row['side']=='BUY' else -1)
            new_cash=number(state['cash'])+quantity*price*(-1 if row['side']=='BUY' else 1)-fee
            if new_qty<0 or new_cash<0:
                raise ExecutionBlocked('Virtual broker refuses short or overdraft')
            eid=execution_id or 'SIM-'+digest([key,len(row['fills'])])[:20]
            if any(eid==f['id'] for r in state['orders'].values() for f in r['fills']):
                raise ExecutionBlocked('Duplicate virtual execution id')
            row['fills'].append(dict(id=eid,quantity=str(quantity),price=str(price)))
            row['filled']=str(number(row['filled'])+quantity)
            row['status']='Filled' if number(row['filled'])==number(row['quantity']) else 'Submitted'
            state['positions'][row['symbol']]=str(new_qty)
            state['cash']=str(new_cash)
            if commission:
                state['commissions'][eid]=dict(fee=str(fee),currency='USD')
            state['events'].append(dict(kind='fill',key=key,id=eid,asof=utc(now).isoformat()))
            return eid

    def cancel(self,key,now):
        with self.journal.change() as state:
            row=state['orders'][key]
            if row['status']!='Filled':
                row['status']='PendingCancel'
            state['events'].append(dict(kind='cancel_requested',key=key))

    def confirm_cancel(self,key):
        with self.journal.change() as state:
            row=state['orders'][key]
            if row['status']!='Filled':
                row['status']='Cancelled'

    def snapshot(self,now):
        state=self.journal.read()
        return dict(asof=utc(now).isoformat(),complete=self.snapshot_complete,
            identity_confirmed=state['identity_confirmed'],corporate_actions_pending=state['corporate_actions_pending'],
            cash=state['cash'],available_cash=state['cash'],positions=state['positions'],
            orders=state['orders'],commissions=state['commissions'])
