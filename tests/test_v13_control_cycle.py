"""Automatic v13 control on actual fictional fills, without submitting by the cycle."""
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from h60_execution import ExecutionConfig, ExecutionBlocked, H60Executor, VirtualBroker, digest
from h60_fund_risk_bridge import FundRiskBridge
from h60_fund_control_cycle import FundControlCycle
from profit_priority_strategy import DrawdownState
from strategy_fund_journal import FundJournal


class ControlCycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.days = []
        day = datetime(2025, 1, 6)
        while len(self.days) < 60:
            if day.weekday() < 5:
                self.days.append(day.date().isoformat())
            day += timedelta(days=1)
        self.scope = dict(scope_id='fictional-control-cycle', owner='test-only', currency='USD',
                          universe=['AAPL'], execution_strategy_id='h60-v8-engineering')
        self.config = ExecutionConfig()
        self.manifest = dict(calendar=self.days, observations=self.days[:-1], symbols=['AAPL'],
                             strategy_id=self.config.strategy_id, budget=self.config.budget)
        self.client = H60Executor(self.root / 'execution.sqlite', self.config, digest(self.manifest), ['AAPL'])
        self.broker = VirtualBroker(self.root / 'broker.sqlite')
        self.fund = FundJournal.create(self.root / 'fund.sqlite', self.scope, '10000', self.time(0, False).isoformat())
        self.bridge = FundRiskBridge(self.client, self.fund, self.broker, run_id='first-process')
        self.cycle = FundControlCycle(self.bridge, runtime_manifest=self.manifest)
        self.cycle.initialize(self.time(0, False), {'AAPL': '100'})
        quote = self.quote(0, '100')
        key = self.bridge.plan_targets('fictitious-entry', {'AAPL': .9}, quote, self.time(0, False))[0]
        self.bridge.submit_virtual(key, quote, self.time(0, False))
        qty = self.client.journal.read()['orders'][key]['state']['quantity']
        self.broker.fill(key, qty, 100, self.time(0, False), execution_id='ACTUAL-FICTIONAL-FILL')
        self.assertEqual(qty, '89')
        self.episode = asdict(DrawdownState())
        self.client.save_runtime(dict(drawdown=self.episode))

    def time(self, index, close=True):
        return datetime.fromisoformat(self.days[index] + ('T21:00:00+00:00' if close else 'T14:30:00+00:00'))

    def quote(self, index, price):
        return {'AAPL': dict(bid=price, ask=price, asof=self.time(index, False).isoformat(),
            basis='synthetic_unadjusted_quote', regular_session=True,
            quantity_step_confirmed=True, corporate_action_pending=False)}

    def tearDown(self):
        self.client.journal.close()
        self.broker.journal.close()
        self.fund.close()
        self.tmp.cleanup()

    def test_close_automatically_reduces_then_halts_on_actual_nav(self):
        before_orders = len(self.broker.journal.read()['orders'])
        reduced = self.cycle.close(self.days[0], self.time(0), {'AAPL': '88'})
        self.assertEqual(reduced['mode'], 'REDUCED')
        self.assertAlmostEqual(reduced['gross_cap'], .4)
        halted = self.cycle.close(self.days[1], self.time(1), {'AAPL': '77'})
        self.assertEqual(halted['mode'], 'HALTED')
        self.assertTrue(halted['risk_state']['pending_flat'])
        self.assertEqual(halted['risk_state']['pause_count'], 1)
        self.assertEqual(halted['positions']['AAPL'], '89')
        self.assertEqual(halted['high_water_nav'], 1.)
        self.assertEqual(len(self.broker.journal.read()['orders']), before_orders)

    def test_restart_repeating_same_close_does_not_retrigger_or_reset_high_water(self):
        first = self.cycle.close(self.days[0], self.time(0), {'AAPL': '77'})
        cursor = self.fund.read()['event_cursor']
        self.client.journal.close()
        self.fund.close()
        self.client = H60Executor(self.root / 'execution.sqlite', self.config, digest(self.manifest), ['AAPL'])
        self.fund = FundJournal(self.root / 'fund.sqlite', self.scope)
        bridge = FundRiskBridge(self.client, self.fund, self.broker, run_id='new-process')
        cycle = FundControlCycle(bridge, runtime_manifest=self.manifest)
        again = cycle.close(self.days[0], self.time(0), {'AAPL': '77'})
        self.assertEqual(again, first)
        self.assertEqual(self.fund.read()['event_cursor'], cursor)
        self.assertEqual(self.fund.read()['risk_state']['pause_count'], 1)
        self.assertEqual(self.fund.read()['high_water_nav'], 1.)
        bridge.require_ready(increasing_risk=False)

    def test_existing_position_and_pending_exit_prevent_resume(self):
        halt = self.cycle.close(self.days[0], self.time(0), {'AAPL': '77'})
        self.assertEqual(halt['mode'], 'HALTED')
        result = self.cycle.resume_open(self.days[22], self.time(22, False), {'AAPL': '77'},
            trend_observation=self.days[21], trend=True, episode_input=self.episode)
        self.assertFalse(result['resumed'])
        self.assertEqual(result['positions']['AAPL'], '89')
        self.assertEqual(result['mode'], 'HALTED')

    def test_flat_after_real_exit_can_resume_but_high_water_stays(self):
        self.cycle.close(self.days[0], self.time(0), {'AAPL': '77'})
        # The separate fictional execution fixture provides real exit facts;
        # controller never invents liquidation or sends this order itself.
        now = self.time(1, False)
        quotes = self.quote(1, '77')
        self.bridge.sync(now, {'AAPL': '77'})
        key = self.bridge.plan_targets('actual-exit', {'AAPL': 0.}, quotes, now, reduction=True)[0]
        self.bridge.submit_virtual(key, quotes, now)
        self.broker.fill(key, 89, 77, now, execution_id='ACTUAL-FICTIONAL-EXIT')
        result = self.cycle.resume_open(self.days[22], self.time(22, False), {'AAPL': '77'},
            trend_observation=self.days[21], trend=True, episode_input=self.episode)
        self.assertTrue(result['resumed'])
        self.assertEqual(result['mode'], 'RECOVERY')
        self.assertEqual(result['positions']['AAPL'], '0')
        self.assertEqual(result['high_water_nav'], 1.)
        self.assertLess(result['unit_nav'], .8)
        self.assertEqual(result['risk_state']['resume_count'], 1)
        close = self.cycle.close(self.days[22], self.time(22), {'AAPL': '77'})
        self.assertEqual(close['mode'], 'RECOVERY')
        self.assertEqual(close['risk_state']['pause_count'], 1)

    def test_changed_repeated_close_or_future_trend_rejected(self):
        self.cycle.close(self.days[0], self.time(0), {'AAPL': '88'})
        with self.assertRaisesRegex(ExecutionBlocked, 'previous completed session'):
            self.cycle.resume_open(self.days[1], self.time(1, False), {'AAPL': '88'},
                trend_observation=self.days[1], trend=True, episode_input=self.episode)
        with self.assertRaisesRegex(ExecutionBlocked, 'conflicting facts'):
            self.cycle.close(self.days[0], self.time(0), {'AAPL': '87'})
        self.assertIsNotNone(self.fund.read()['blocked'])

    def test_flat_but_unresolved_order_prevents_resume(self):
        self.cycle.close(self.days[0], self.time(0), {'AAPL': '77'})
        now = self.time(1, False)
        quotes = self.quote(1, '77')
        self.bridge.sync(now, {'AAPL': '77'})
        key = self.bridge.plan_targets('actual-exit', {'AAPL': 0.}, quotes, now, reduction=True)[0]
        self.bridge.submit_virtual(key, quotes, now)
        self.broker.fill(key, 89, 77, now, execution_id='FLAT-EXIT')
        self.assertTrue(self.client.reconcile(self.broker, now))
        # Inject a legacy persisted-but-unsubmitted intent via the frozen old
        # executor; the new risk gate itself would correctly reject this buy.
        self.client.plan_targets('stale-legacy-intent', {'AAPL': .01}, quotes, now)
        result = self.cycle.resume_open(self.days[22], self.time(22, False), {'AAPL': '77'},
            trend_observation=self.days[21], trend=True, episode_input=self.episode)
        self.assertEqual(result['positions']['AAPL'], '0')
        self.assertFalse(result['resumed'])
        self.assertEqual(result['mode'], 'HALTED')

    def test_close_trigger_cannot_be_immediately_resumed_at_same_close(self):
        self.cycle.close(self.days[1], self.time(1), {'AAPL': '77'})
        with self.assertRaisesRegex(ExecutionBlocked, 'regular-session open'):
            self.cycle.resume_open(self.days[1], self.time(1), {'AAPL': '77'},
                trend_observation=self.days[0], trend=True, episode_input=self.episode)

    def test_calendar_origin_must_match_the_actual_runtime_manifest(self):
        with self.assertRaisesRegex(ExecutionBlocked, 'day-index origin'):
            FundControlCycle(self.bridge, runtime_manifest=self.manifest, calendar=self.days[1:])
        changed = dict(self.manifest, calendar=self.days[1:])
        with self.assertRaisesRegex(ExecutionBlocked, 'manifest identity'):
            FundControlCycle(self.bridge, runtime_manifest=changed)

    def test_normal_held_open_is_not_a_matching_research_control_entry(self):
        with self.assertRaisesRegex(ExecutionBlocked, 'halted or locked'):
            self.cycle.resume_open(self.days[1], self.time(1, False), {'AAPL': '110'},
                trend_observation=self.days[0], trend=True, episode_input=self.episode)


if __name__ == '__main__':
    unittest.main()
