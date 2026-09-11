"""Invented fixtures for information-time and terminal-cash accounting invariants."""
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest

from historical_universe import (load_package, membership_asof, eligibility_asof,
    combined_return, TerminalLedger, validate_events)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT/'data/fixtures/universe_delisting_v9'


class HistoricalUniverseTests(unittest.TestCase):
    def setUp(self):
        self.meta, self.members, self.events = load_package(FIXTURE)

    def test_future_effective_and_late_information_do_not_leak(self):
        before = membership_asof(self.members, 'SIM_INDEX', '2023-10-03T16:00:00-04:00')
        self.assertEqual(before, {'SIM_A': True, 'SIM_B': True})
        fourth = membership_asof(self.members, 'SIM_INDEX', '2023-10-04T16:00:00-04:00')
        self.assertEqual(fourth, {'SIM_A': True, 'SIM_B': True, 'SIM_C': True})
        sixth = membership_asof(self.members, 'SIM_INDEX', '2023-10-06T16:00:00-04:00')
        self.assertFalse(sixth['SIM_B'])  # Late October 3 removal becomes known only now.

    def test_dynamic_groups_and_unknown_trading_status(self):
        sizes = []
        for day in range(2, 7):
            state = eligibility_asof(self.members, self.events, 'SIM_INDEX', f'2023-10-{day:02}T23:59:59-04:00')
            sizes.append(sum(r['can_open'] for r in state.values()))
        self.assertEqual(sizes, [2, 2, 3, 2, 1])
        state = eligibility_asof(self.members, [], 'SIM_INDEX', '2023-10-02T16:00:00-04:00')
        self.assertFalse(any(r['can_open'] for r in state.values()))

    def test_stable_ids_do_not_merge_reused_ticker_identities(self):
        # The module never joins on a display ticker.
        row = deepcopy(self.members[0]); row.update(event_id='another', security_id='DIFFERENT_A')
        state = membership_asof([self.members[0], row], 'SIM_INDEX', '2023-10-02T16:00:00-04:00')
        self.assertEqual(set(state), {'SIM_A', 'DIFFERENT_A'})

    def test_cash_entitlement_is_not_available_cash_and_replays_once(self):
        ledger = TerminalLedger('2023-10-02T16:00:00-04:00', {'SIM_A': 10}, '1000')
        before = ledger.apply(self.events, '2023-10-04T16:00:00-04:00')
        self.assertEqual(before['receivable_cash'], '0')
        result = ledger.apply(self.events, '2023-10-05T16:00:00-04:00')
        self.assertEqual(result['available_cash'], '1000')
        self.assertEqual(result['receivable_cash'], '500')
        self.assertEqual(result['holdings']['SIM_A'], '0')
        restored = TerminalLedger(**json.loads(json.dumps(ledger.to_state())))
        self.assertEqual(restored.apply(self.events, '2023-10-05T16:00:00-04:00'), result)
        self.assertIsNone(result['investment_return'])

    def test_explicit_payment_and_duplicate_receipts(self):
        ledger = TerminalLedger('2023-10-02T16:00:00-04:00', {'SIM_A': 10}, '1000')
        ledger.apply(self.events, '2023-10-05T16:00:00-04:00')
        args = ('sim_a_cash', 500, 'fictional_receipt', '2023-10-06T10:00:00-04:00', '2023-10-06T16:00:00-04:00')
        ledger.settle(*args); ledger.settle(*args)
        self.assertEqual(ledger.snapshot()['available_cash'], '1500')
        self.assertEqual(ledger.snapshot()['receivable_cash'], '0')
        with self.assertRaises(ValueError):
            ledger.settle(args[0], 500, 'duplicate_other_id', args[3], args[4])

    def test_unknown_terminal_does_not_erase_shares_or_invent_zero_return(self):
        ledger = TerminalLedger('2023-10-02T16:00:00-04:00', {'SIM_B': 5})
        result = ledger.apply(self.events, '2023-10-06T16:00:00-04:00')
        self.assertEqual(result['holdings']['SIM_B'], '5')
        self.assertEqual(result['unresolved'], ['SIM_B'])
        self.assertIsNone(result['investment_return'])
        self.assertIsNone(combined_return('-.1', None, 'separate'))

    def test_return_convention_prevents_double_counting(self):
        self.assertEqual(combined_return('-.1', '-.5', 'separate'), Decimal('-.55'))
        self.assertEqual(combined_return('-.55', None, 'already_included'), Decimal('-.55'))
        with self.assertRaises(ValueError):
            combined_return('-.55', '-.5', 'already_included')
        with self.assertRaises(ValueError):
            combined_return(0, '-1.01', 'separate')

    def test_observation_cannot_precede_holdings_or_reverse_payment_clock(self):
        ledger = TerminalLedger('2023-10-02T16:00:00-04:00', {'SIM_A': 10})
        with self.assertRaises(ValueError):
            ledger.apply([], '2023-10-01T16:00:00-04:00')
        ledger.apply(self.events, '2023-10-06T16:00:00-04:00')
        original = ledger.to_state()
        with self.assertRaises(ValueError):
            ledger.settle('sim_a_cash', 500, 'future_knowledge', '2023-10-05T10:00:00-04:00', '2023-10-05T12:00:00-04:00')
        self.assertEqual(ledger.to_state(), original)

    def test_holdings_after_entitlement_cannot_claim_it(self):
        ledger = TerminalLedger('2023-10-06T16:00:00-04:00', {'SIM_A': 10})
        with self.assertRaises(ValueError):
            ledger.apply(self.events, '2023-10-06T17:00:00-04:00')
        self.assertEqual(ledger.available_cash, '0')
        self.assertEqual(ledger.applied, {})

    def test_conflicting_or_repeated_cash_events_are_rejected(self):
        cash = next(r for r in self.events if r['kind'] == 'cash_entitlement')
        conflict = dict(cash, event_id='conflict', cash_per_share='100')
        with self.assertRaises(ValueError):
            validate_events([cash, conflict])
        active = self.events[0]
        halt = dict(active, event_id='halt', kind='halt', effective_at='2023-10-02T13:30:00+00:00')
        with self.assertRaises(ValueError):
            validate_events([active, halt])

    def test_applied_event_correction_is_not_silently_rebooked(self):
        ledger = TerminalLedger('2023-10-02T16:00:00-04:00', {'SIM_A': 10})
        ledger.apply(self.events, '2023-10-05T16:00:00-04:00')
        changed = deepcopy(self.events)
        next(r for r in changed if r['kind'] == 'cash_entitlement')['cash_per_share'] = '51'
        original = ledger.to_state()
        with self.assertRaises(ValueError):
            ledger.apply(changed, '2023-10-06T16:00:00-04:00')
        self.assertEqual(ledger.to_state(), original)

    def test_incremental_duplicate_cash_with_new_id_is_rejected_after_restore(self):
        cash = next(r for r in self.events if r['kind'] == 'cash_entitlement')
        ledger = TerminalLedger('2023-10-02T16:00:00-04:00', {'SIM_A': 10})
        ledger.apply([cash], '2023-10-05T16:00:00-04:00')
        restored = TerminalLedger(**json.loads(json.dumps(ledger.to_state())))
        original = restored.to_state()
        with self.assertRaisesRegex(ValueError, 'another event id'):
            restored.apply([dict(cash, event_id='new_id', cash_per_share='100')], '2023-10-06T16:00:00-04:00')
        self.assertEqual(restored.to_state(), original)

    def test_hash_tampering_and_2026_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            for name in ('manifest.json', 'events.csv', 'memberships.csv'):
                (path/name).write_bytes((FIXTURE/name).read_bytes())
            with (path/'events.csv').open('a') as handle:
                handle.write('\n')
            with self.assertRaisesRegex(ValueError, 'hash'):
                load_package(path)
        with self.assertRaises(ValueError):
            membership_asof(self.members, 'SIM_INDEX', '2026-01-05T16:00:00-05:00')


if __name__ == '__main__':
    unittest.main()
