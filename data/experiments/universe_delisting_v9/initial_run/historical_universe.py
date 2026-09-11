"""Small, source-neutral historical membership and terminal-event data boundary.

This module neither downloads nor trades. Timestamps are information boundaries,
not reconstructed intraday release times. Cash rights are not spendable cash.
"""
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path

import pandas as pd


MEMBERSHIP_COLUMNS = ['event_id', 'security_id', 'universe', 'effective_at',
                      'available_at', 'member', 'source_id']
EVENT_COLUMNS = ['event_id', 'security_id', 'kind', 'effective_at',
                 'available_at', 'cash_per_share', 'source_id']
KINDS = {'active', 'halt', 'cash_entitlement', 'unknown_terminal'}
CUTOFF = datetime(2026, 1, 1, tzinfo=timezone.utc)


def instant(value):
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        raise ValueError('Timezone is required; do not guess an intraday timestamp')
    return moment.astimezone(timezone.utc)


def amount(value):
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError('Non-finite number')
    return result


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def event_key(row):
    return (max(instant(row['effective_at']), instant(row['available_at'])),
            instant(row['effective_at']), row['event_id'])


def visible(rows, asof):
    now = instant(asof)
    if now >= CUTOFF:
        raise ValueError('This data-check step is restricted to observations before 2026')
    return [r for r in rows if instant(r['effective_at']) <= now
            and instant(r['available_at']) <= now]


def validate_events(rows):
    """This small contract has no implicit correction/duplicate-source protocol."""
    ids, moments, cash_securities = set(), set(), set()
    for row in rows:
        if row['event_id'] in ids or row['kind'] not in KINDS:
            raise ValueError('Duplicate id or unsupported event kind')
        ids.add(row['event_id'])
        kind = row['kind']
        domain = 'trading' if kind in ('active', 'halt') else kind
        key = (row['security_id'], instant(row['effective_at']), instant(row['available_at']), domain)
        if key in moments:
            raise ValueError('Ambiguous same-time security events')
        moments.add(key)
        if kind == 'cash_entitlement':
            if row['security_id'] in cash_securities:
                raise ValueError('Multiple full cash terminations need an explicit correction protocol')
            if row['cash_per_share'] == '' or amount(row['cash_per_share']) < 0:
                raise ValueError('Cash consideration must be explicitly known and nonnegative')
            cash_securities.add(row['security_id'])
        elif row['cash_per_share'] != '':
            raise ValueError('Noncash events cannot carry consideration')


def load_package(directory):
    """Validate two explicit CSV schemas and their snapshot hashes. No raw export."""
    directory = Path(directory)
    meta = json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    if meta['schema_version'] != 1 or meta['evidence_kind'] not in {
            'synthetic_fixture', 'public_event_case', 'licensed_local_export'}:
        raise ValueError('Unrecognized package identity')
    if meta['evidence_kind'] == 'licensed_local_export' and not meta.get('local_use_confirmed'):
        raise ValueError('Confirm the local export use before reading vendor records')
    tables = {}
    for name, columns in [('memberships.csv', MEMBERSHIP_COLUMNS), ('events.csv', EVENT_COLUMNS)]:
        path = directory/name
        if sha(path) != meta['file_sha256'][name]:
            raise ValueError('Input snapshot hash differs: '+name)
        frame = pd.read_csv(path, dtype=str, keep_default_na=False)
        if list(frame.columns) != columns:
            raise ValueError('Unexpected columns: '+name)
        if frame.event_id.duplicated().any():
            raise ValueError('Duplicate event id: '+name)
        for row in frame.to_dict('records'):
            if any(not row[c] for c in columns if c != 'cash_per_share'):
                raise ValueError('Required field missing: '+name)
            if row['source_id'] not in meta['sources']:
                raise ValueError('Source provenance missing')
            if any(instant(row[c]) >= CUTOFF for c in ('effective_at', 'available_at')):
                raise ValueError('2026 event/information boundary outside this step')
            if name == 'memberships.csv' and row['member'] not in ('0', '1'):
                raise ValueError('Membership must be explicit 0 or 1')
            if name == 'events.csv':
                if row['kind'] not in KINDS:
                    raise ValueError('Unsupported security event')
                if row['kind'] == 'cash_entitlement':
                    if row['cash_per_share'] == '' or amount(row['cash_per_share']) < 0:
                        raise ValueError('Cash consideration must be explicitly known')
                elif row['cash_per_share'] != '':
                    raise ValueError('Unknown/noncash events cannot carry fabricated consideration')
        if name == 'memberships.csv':
            keys = [(r.security_id, r.universe, instant(r.effective_at), instant(r.available_at))
                    for r in frame.itertuples()]
            if len(keys) != len(set(keys)):
                raise ValueError('Ambiguous membership facts at the same time')
        else:
            validate_events(frame.to_dict('records'))
        tables[name] = frame.to_dict('records')
    return meta, tables['memberships.csv'], tables['events.csv']


def membership_asof(rows, universe, asof):
    """Latest effective known fact; missing history remains absent, not false."""
    state = {}
    ordered = sorted(visible(rows, asof), key=lambda r:
                     (instant(r['effective_at']), instant(r['available_at']), r['event_id']))
    for row in ordered:
        if row['universe'] == universe:
            state[row['security_id']] = row['member'] == '1'
    return state


def eligibility_asof(memberships, events, universe, asof):
    """Membership alone is insufficient. Unknown or terminated trading blocks entry."""
    validate_events(events)
    members = membership_asof(memberships, universe, asof)
    status, terminated = {}, set()
    for row in sorted(visible(events, asof), key=lambda r:
                      (instant(r['effective_at']), instant(r['available_at']), r['event_id'])):
        security = row['security_id']
        status[security] = row['kind']
        if row['kind'] in ('cash_entitlement', 'unknown_terminal'):
            terminated.add(security)
    return {s: dict(member=member, trading_status=status.get(s, 'unknown'),
                    can_open=member and status.get(s) == 'active' and s not in terminated)
            for s, member in sorted(members.items())}


def combined_return(regular_return, terminal_return, representation):
    """Return-series check, never a tradable price or a cash-settlement instruction.

    Separate legacy terminal return: (1+r)*(1+d)-1. An already-inclusive vendor
    return must NOT receive an additional d. Missing terminal data stays unknown.
    """
    r = None if regular_return is None else amount(regular_return)
    d = None if terminal_return is None else amount(terminal_return)
    if any(v is not None and v < -1 for v in (r, d)):
        raise ValueError('Long-only unlevered return cannot be below -100%')
    if representation in ('ordinary', 'already_included'):
        if d is not None:
            raise ValueError('Do not add terminal return to an inclusive/ordinary series')
        return r
    if representation == 'separate':
        return None if r is None or d is None else (1+r)*(1+d)-1
    if representation == 'unknown':
        return None
    raise ValueError('Explicit return representation required')


@dataclass
class TerminalLedger:
    """Hypothetical fixed holdings only; no purchases, pricing model or broker calls.

    Full USD cash consideration supported. Stock-for-stock, tax, fees, split
    entitlements and partial settlements require separate implementation.
    """
    holdings_asof: str
    holdings: dict
    available_cash: str = '0'
    receivables: dict = field(default_factory=dict)
    applied: dict = field(default_factory=dict)
    receipts: dict = field(default_factory=dict)
    unresolved: list = field(default_factory=list)
    last_asof: str | None = None

    def __post_init__(self):
        instant(self.holdings_asof)
        if amount(self.available_cash) < 0 or any(amount(q) < 0 for q in self.holdings.values()):
            raise ValueError('Only nonnegative hypothetical cash/shares supported')
        self.holdings = {s: str(amount(q)) for s, q in self.holdings.items()}

    def apply(self, events, asof):
        validate_events(events)
        # A rejected event must not partially change a previous valid snapshot.
        staged = TerminalLedger(**self.to_state())
        result = staged._apply(events, asof)
        self.__dict__.update(staged.__dict__)
        return result

    def _check_clock(self, asof):
        if instant(asof) < instant(self.holdings_asof):
            raise ValueError('Observation precedes the seeded holdings snapshot')
        if self.last_asof and instant(asof) < instant(self.last_asof):
            raise ValueError('Use a fresh ledger to inspect an earlier information time')

    def _apply(self, events, asof):
        self._check_clock(asof)
        for row in sorted(visible(events, asof), key=event_key):
            if row['kind'] not in ('cash_entitlement', 'unknown_terminal'):
                continue
            event_id, security = row['event_id'], row['security_id']
            fingerprint = hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()
            if event_id in self.applied:
                if self.applied[event_id] != fingerprint:
                    raise ValueError('Previously applied event was changed')
                continue
            quantity = amount(self.holdings.get(security, 0))
            if quantity and instant(self.holdings_asof) >= instant(row['effective_at']):
                raise ValueError('Cannot claim entitlement for shares seeded after the event')
            if row['kind'] == 'unknown_terminal':
                if quantity and security not in self.unresolved:
                    self.unresolved.append(security)  # Do not erase value or fill zero.
            else:
                cash = quantity*amount(row['cash_per_share'])
                self.receivables[event_id] = dict(security_id=security,amount=str(cash),
                    effective_at=row['effective_at'],available_at=row['available_at'])
                self.holdings[security] = '0'
                self.unresolved = [s for s in self.unresolved if s != security]
            self.applied[event_id] = fingerprint
        self.last_asof = asof
        return self.snapshot()

    def settle(self, event_id, cash, receipt_id, paid_at, asof):
        """Only an explicit confirmed receipt releases cash; never infer a pay date."""
        self._check_clock(asof)
        if instant(paid_at) > instant(asof) or instant(asof) >= CUTOFF:
            raise ValueError('Receipt is not yet available or outside the allowed period')
        receipt = dict(event_id=event_id,cash=str(amount(cash)),paid_at=paid_at)
        if receipt_id in self.receipts:
            if self.receipts[receipt_id] != receipt:
                raise ValueError('Receipt id changed')
            return
        if any(r['event_id'] == event_id for r in self.receipts.values()):
            raise ValueError('Entitlement already paid under another receipt id')
        receivable = self.receivables[event_id]
        if instant(asof) < instant(receivable['available_at']):
            raise ValueError('Entitlement is not known at this information time')
        if instant(paid_at) < instant(receivable['effective_at']):
            raise ValueError('Cash receipt precedes entitlement')
        if amount(cash) != amount(receivable['amount']):
            raise ValueError('Partial/withheld/corrected payment needs explicit reconciliation')
        self.available_cash = str(amount(self.available_cash)+amount(cash))
        receivable['amount'] = '0'
        self.receipts[receipt_id] = receipt
        self.last_asof = asof

    def snapshot(self):
        return dict(holdings=deepcopy(self.holdings),available_cash=self.available_cash,
                    receivable_cash=str(sum((amount(r['amount']) for r in self.receivables.values()), Decimal(0))),
                    unresolved=sorted(self.unresolved),investment_return=None,
                    reason='No acquisition prices/real holdings/complete price history; no return computed')

    def to_state(self):
        return asdict(self)
