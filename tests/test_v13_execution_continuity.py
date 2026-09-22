"""Fictitious offline integration: actual old executor facts and durable fund state."""
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from h60_execution import ExecutionConfig, ExecutionBlocked, H60Executor, VirtualBroker
from h60_fund_risk_bridge import FundRiskBridge
from h60_global_control import GlobalRisk
from strategy_fund_journal import FundJournal


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2025, 1, 6, 15, tzinfo=timezone.utc)
SCOPE = dict(scope_id='test-continuous-fund', owner='fixture', currency='USD', universe=['AAPL'],
             execution_strategy_id='h60-v8-engineering')
RECORD = dict(mode='record_only', allow_new_risk=True)


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.client = H60Executor(self.root / 'execution.sqlite', ExecutionConfig(), 'model-A', ['AAPL'])
        self.broker = VirtualBroker(self.root / 'broker.sqlite')
        self.fund = FundJournal.create(self.root / 'fund.sqlite', scope=SCOPE, initial_cash='10000', at=NOW.isoformat())
        self.bridge = FundRiskBridge(self.client, self.fund, self.broker, run_id='process-1')
        self.quotes = {'AAPL': dict(bid='100', ask='100', asof=NOW.isoformat(),
            basis='synthetic_unadjusted_quote', regular_session=True,
            quantity_step_confirmed=True, corporate_action_pending=False)}
        self.bridge.sync(NOW, {'AAPL': '100'}, risk_state=RECORD)

    def tearDown(self):
        self.client.journal.close()
        self.broker.journal.close()
        self.fund.close()
        self.temp.cleanup()

    def test_execution_checkpoint_gap_blocks_then_replays_exact_facts(self):
        key = self.bridge.plan_targets('first', {'AAPL': .1}, self.quotes, NOW)[0]
        self.bridge.submit_virtual(key, self.quotes, NOW)
        self.broker.fill(key, 3, 100, NOW, execution_id='BUY-001')
        self.assertTrue(self.client.reconcile(self.broker, NOW))
        with self.assertRaisesRegex(ExecutionBlocked, 'checkpoint gap'):
            self.bridge.require_ready()
        state = self.bridge.sync(NOW, {'AAPL': '100'})
        self.assertEqual(float(state['cash']), 9699.7)
        self.assertEqual(float(state['positions']['AAPL']), 3.)
        self.assertEqual(float(state['unit_nav']), .99997)
        before = state['event_cursor']
        again = self.bridge.sync(NOW, {'AAPL': '100'})
        self.assertEqual(again['event_cursor'], before)
        self.assertEqual(again['equity'], state['equity'])

    def test_unknown_submit_never_repeats_and_requires_reconciliation(self):
        key = self.bridge.plan_targets('timeout', {'AAPL': .1}, self.quotes, NOW)[0]
        self.broker.timeout_after_accept = True
        self.assertFalse(self.bridge.submit_virtual(key, self.quotes, NOW))
        with self.assertRaises(ExecutionBlocked):
            self.bridge.require_ready()
        self.bridge.sync(NOW, {'AAPL': '100'})
        self.assertFalse(self.bridge.submit_virtual(key, self.quotes, NOW))
        self.assertEqual(len(self.broker.journal.read()['orders']), 1)

    def test_risk_halt_does_not_erase_partial_position_or_authorize_buy(self):
        key = self.bridge.plan_targets('entry', {'AAPL': .1}, self.quotes, NOW)[0]
        self.bridge.submit_virtual(key, self.quotes, NOW)
        self.broker.fill(key, 3, 100, NOW)
        self.bridge.sync(NOW, {'AAPL': '100'})
        stop = self.client.plan_protection({'AAPL': 85}, self.quotes, NOW)[0]
        self.bridge.sync(NOW, {'AAPL': '100'})
        self.bridge.submit_virtual(stop, self.quotes, NOW)
        self.broker.fill(stop, 1, 70, NOW)
        state = self.bridge.sync(NOW, {'AAPL': '70'},
            risk_state=GlobalRisk(mode='HALTED', pending_flat=True).as_dict())
        self.assertEqual(float(state['positions']['AAPL']), 2.)
        self.assertAlmostEqual(float(state['equity']), 9909.63)
        self.assertLess(float(state['unit_nav']), 1.)
        self.assertEqual(self.broker.journal.read()['orders'][key]['status'], 'PendingCancel')
        gap_quotes = {'AAPL': dict(self.quotes['AAPL'], bid='70', ask='70')}
        with self.assertRaisesRegex(ExecutionBlocked, 'authorize'):
            self.bridge.plan_targets('bad-restart', {'AAPL': .2}, gap_quotes, NOW)
        cancellation = self.bridge.cancel_stopped_buy_remainders([key], gap_quotes, NOW)
        self.assertEqual(cancellation['status'], 'protection_triggered_cancel_buy_remainder')
        self.assertEqual(self.broker.journal.read()['orders'][key]['status'], 'PendingCancel')
        cash_reserved, sell_reserved = self.client.reservations()
        self.assertGreater(cash_reserved, 0)
        self.assertEqual(sell_reserved['AAPL'], 2)

    def test_same_research_controller_caps_targets_and_rejects_stale_buy(self):
        self.bridge.sync(NOW, {'AAPL': '100'}, risk_state=GlobalRisk(mode='REDUCED').as_dict())
        capped = self.bridge.gate_targets({'AAPL': .8})
        self.assertEqual(capped, {'AAPL': .4})
        key = self.bridge.plan_targets('capped', {'AAPL': .8}, self.quotes, NOW)[0]
        self.assertLessEqual(float(self.client.journal.read()['orders'][key]['state']['quantity']), 40.)
        self.bridge.sync(NOW, {'AAPL': '100'}, risk_state=GlobalRisk(mode='HALTED').as_dict())
        with self.assertRaisesRegex(ExecutionBlocked, 'authorize'):
            self.bridge.submit_virtual(key, self.quotes, NOW)

    def test_unexplained_cash_is_not_profit_and_blocks_risk(self):
        with self.broker.journal.change() as state:
            state['cash'] = '11000'
        with self.assertRaisesRegex(ExecutionBlocked, 'cash_mismatch'):
            self.bridge.sync(NOW, {'AAPL': '100'})
        self.assertEqual(float(self.fund.read()['unit_nav']), 1.)
        with self.assertRaises(ExecutionBlocked):
            self.bridge.require_ready()

    def test_existing_executor_model_switch_not_silently_supported(self):
        self.client.journal.close()
        with self.assertRaises(ExecutionBlocked):
            H60Executor(self.root / 'execution.sqlite', ExecutionConfig(), 'model-B', ['AAPL'])
        self.client = H60Executor(self.root / 'execution.sqlite', ExecutionConfig(), 'model-A', ['AAPL'])
        self.assertEqual(self.fund.read()['model_version'], 'model-A')

    def test_real_subprocess_crashes_before_and_after_commit_match(self):
        output = self.root / 'process_evidence'
        result = subprocess.run([sys.executable, str(ROOT / '56_check_fund_continuity.py'),
            '--output', str(output)], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((output / 'CONTINUITY_REPORT.json').exists())

    def test_changed_quotes_need_new_fund_valuation(self):
        changed = {'AAPL': dict(self.quotes['AAPL'], bid='90', ask='90')}
        with self.assertRaisesRegex(ExecutionBlocked, 'new fund valuation'):
            self.bridge.plan_targets('changed-price', {'AAPL': .1}, changed, NOW)

    def test_missing_risk_mode_or_recovery_anchor_cannot_default_to_normal(self):
        state = self.fund.read()
        for risk in ({}, {'mode': 'RECOVERY'}):
            with self.assertRaises(ExecutionBlocked):
                self.bridge.gross_cap(dict(state, risk_state=risk))

    def test_fresh_scope_cannot_adopt_old_execution_and_reset_high_water(self):
        self.bridge.plan_targets('persisted-history', {'AAPL': .1}, self.quotes, NOW)
        second_scope = dict(SCOPE, scope_id='accidentally-new-fund')
        second = FundJournal.create(self.root / 'new-fund.sqlite', scope=second_scope,
                                    initial_cash='10000', at=NOW.isoformat())
        try:
            bridge = FundRiskBridge(self.client, second, self.broker, run_id='wrong-fresh-process')
            with self.assertRaisesRegex(ExecutionBlocked, 'Fresh fund cannot adopt'):
                bridge.sync(NOW, {'AAPL': '100'}, risk_state=RECORD)
        finally:
            second.close()

    def test_other_strategy_cannot_adopt_same_scope_with_same_budget_and_symbols(self):
        wrong = H60Executor(self.root / 'wrong-strategy.sqlite',
            ExecutionConfig(strategy_id='different-strategy'), 'model-A', ['AAPL'])
        try:
            with self.assertRaisesRegex(ExecutionBlocked, 'scope'):
                FundRiskBridge(wrong, self.fund, self.broker, run_id='wrong-owner')
        finally:
            wrong.journal.close()

    def test_record_only_targets_equal_frozen_runtime_without_bridge(self):
        from h60_execution_cycle import plan_open_cycle
        spec = importlib.util.spec_from_file_location('v13_fixture', ROOT / '56_check_fund_continuity.py')
        fixture = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fixture)
        manifest, day, now, quotes, risk, scores = fixture.context()
        clients, brokers, fund = [], [], None
        try:
            for name in ('baseline', 'record_only'):
                folder = self.root / name
                clients.append(H60Executor(folder / 'execution.sqlite',
                    ExecutionConfig(strategy_id=manifest['strategy_id']), fixture.MODEL, manifest['symbols']))
                brokers.append(VirtualBroker(folder / 'broker.sqlite'))
            baseline = plan_open_cycle(clients[0], brokers[0], manifest, day, scores, risk, quotes, now)
            fund = FundJournal.create(self.root / 'paired-fund.sqlite', scope=fixture.SCOPE,
                                     initial_cash='10000', at=now.isoformat())
            bridge = FundRiskBridge(clients[1], fund, brokers[1], run_id='recording')
            bridge.sync(now, {'AAPL': '100', 'MSFT': '100'}, risk_state=RECORD)
            recorded = bridge.record_only_open_cycle(manifest, day, scores, risk, quotes, now)
            self.assertEqual(recorded, baseline)
            self.assertEqual(clients[0].journal.read()['orders'], clients[1].journal.read()['orders'])
            self.assertEqual(clients[0].journal.read()['runtime'], clients[1].journal.read()['runtime'])
        finally:
            for client in clients:
                client.journal.close()
            for broker in brokers:
                broker.journal.close()
            if fund is not None:
                fund.close()


if __name__ == '__main__':
    unittest.main()
