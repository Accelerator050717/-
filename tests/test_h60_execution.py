"""All broker responses and raw quotes in this file are fictitious fault fixtures."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from h60_execution import ExecutionConfig, ExecutionBlocked, H60Executor, VirtualBroker, number

NOW=datetime(2025,1,6,15,0,tzinfo=timezone.utc)


def quotes(symbols=('AAPL','MSFT')):
    return {s:dict(bid='100',ask='100',asof=NOW.isoformat(),basis='synthetic_unadjusted_quote',
                   regular_session=True,quantity_step_confirmed=True,corporate_action_pending=False) for s in symbols}


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.config=ExecutionConfig()
        self.client=H60Executor(self.root/'client.sqlite',self.config,'test-manifest',['AAPL','MSFT'])
        self.broker=VirtualBroker(self.root/'broker.sqlite',outside_positions={'FOREIGN':'17'})
        self.q=quotes()
        self.assertTrue(self.client.reconcile(self.broker,NOW))

    def tearDown(self):
        self.client.journal.close(); self.broker.journal.close(); self.temp.cleanup()

    def buy(self,partial=None):
        key=self.client.plan_targets('first',{'AAPL':.1,'MSFT':0},self.q,NOW)[0]
        self.client.submit(key,self.broker,self.q,NOW)
        qty=number(self.client.journal.read()['orders'][key]['state']['quantity'])
        self.broker.fill(key,partial or qty,100,NOW)
        self.assertTrue(self.client.reconcile(self.broker,NOW))
        return key,qty

    def test_repeat_decision_submit_and_restart_no_duplicates(self):
        key,qty=self.buy()
        prior=self.client.journal.read()
        self.client.journal.close()
        self.client=H60Executor(self.root/'client.sqlite',self.config,'test-manifest',['AAPL','MSFT'])
        self.assertTrue(self.client.reconcile(self.broker,NOW))
        self.assertEqual(self.client.plan_targets('first',{'AAPL':.1,'MSFT':0},self.q,NOW),[key])
        self.assertFalse(self.client.submit(key,self.broker,self.q,NOW))
        self.assertEqual(len(self.broker.journal.read()['orders']),1)
        self.assertEqual(len(self.client.journal.read()['orders']),len(prior['orders']))
        self.assertEqual(self.broker.journal.read()['positions']['FOREIGN'],'17')

    def test_timeout_after_accept_reconcile_instead_of_resend(self):
        key=self.client.plan_targets('timeout',{'AAPL':.1,'MSFT':0},self.q,NOW)[0]
        self.broker.timeout_after_accept=True
        self.assertFalse(self.client.submit(key,self.broker,self.q,NOW))
        self.assertTrue(self.client.journal.read()['orders'][key]['state']['attempted'])
        self.client.journal.close()
        self.client=H60Executor(self.root/'client.sqlite',self.config,'test-manifest',['AAPL','MSFT'])
        self.assertFalse(self.client.submit(key,self.broker,self.q,NOW))
        self.assertTrue(self.client.reconcile(self.broker,NOW))
        self.assertFalse(self.client.submit(key,self.broker,self.q,NOW))
        self.assertEqual(len(self.broker.journal.read()['orders']),1)

    def test_missing_unknown_order_is_not_evidence_for_resubmission(self):
        key=self.client.plan_targets('lost',{'AAPL':.1,'MSFT':0},self.q,NOW)[0]
        self.broker.timeout_after_accept=True
        self.client.submit(key,self.broker,self.q,NOW)
        original=self.broker.snapshot
        self.broker.snapshot=lambda now:dict(original(now),orders={})
        self.assertFalse(self.client.reconcile(self.broker,NOW))
        self.assertFalse(self.client.submit(key,self.broker,self.q,NOW))
        self.assertIn('missing',self.client.journal.read()['blocked'])

    def test_partial_fill_and_cancel_fill_race_reserves_shares(self):
        key,qty=self.buy(partial=3)
        reserved,_=self.client.reservations()
        self.assertGreater(reserved,0)
        protect=self.client.plan_protection({'AAPL':'85'},self.q,NOW)[0]
        self.client.submit(protect,self.broker,self.q,NOW)
        self.assertTrue(self.client.reconcile(self.broker,NOW))
        self.assertEqual(self.client.reservations()[1]['AAPL'],3)
        self.client.cancel(protect,self.broker,NOW)
        self.broker.fill(protect,1,80,NOW)  # Gap stop, filled while cancellation is pending.
        self.assertTrue(self.client.reconcile(self.broker,NOW))
        self.assertEqual(self.client.balances()[1]['AAPL'],2)
        self.assertEqual(self.client.reservations()[1]['AAPL'],2)
        with self.assertRaises(ExecutionBlocked):
            self.client.plan_targets('reduce',{'AAPL':0,'MSFT':0},self.q,NOW,reduction=True)
        self.broker.confirm_cancel(protect)
        self.assertTrue(self.client.reconcile(self.broker,NOW))
        self.assertEqual(self.client.reservations()[1]['AAPL'],0)
        self.assertGreater(self.client.reservations()[0],0)  # Remaining buy still reserved.

    def test_protection_tracks_actual_fills_without_overselling(self):
        key,qty=self.buy(partial=3)
        first=self.client.plan_protection({'AAPL':'85'},self.q,NOW)
        for k in first:
            self.client.submit(k,self.broker,self.q,NOW); self.client.reconcile(self.broker,NOW)
        self.broker.fill(key,qty-3,100,NOW)
        self.assertTrue(self.client.reconcile(self.broker,NOW))
        additional=self.client.plan_protection({'AAPL':'85'},self.q,NOW)
        self.assertEqual(len(additional),1)
        self.assertEqual(self.client.reservations()[1]['AAPL'],qty)
        self.assertEqual(self.client.plan_protection({'AAPL':'85'},self.q,NOW),[])

    def test_missing_commission_and_conflicting_fills_block_new_risk(self):
        key=self.client.plan_targets('fees',{'AAPL':.1,'MSFT':0},self.q,NOW)[0]
        self.client.submit(key,self.broker,self.q,NOW)
        eid=self.broker.fill(key,1,100,NOW,commission=False)
        self.assertFalse(self.client.reconcile(self.broker,NOW))
        with self.broker.journal.change() as state:
            state['commissions'][eid]=dict(fee='.1',currency='USD')
        self.assertTrue(self.client.reconcile(self.broker,NOW))
        old_cash=self.client.balances()[0]
        self.assertTrue(self.client.reconcile(self.broker,NOW))
        self.assertEqual(old_cash,self.client.balances()[0])
        with self.broker.journal.change() as state:
            state['orders'][key]['fills'][0]['price']='101'
        self.assertFalse(self.client.reconcile(self.broker,NOW))

    def test_stale_quotes_wrong_basis_identity_and_cash_mismatch(self):
        bad=quotes(); bad['AAPL']['asof']=(NOW-timedelta(seconds=31)).isoformat()
        with self.assertRaises(ExecutionBlocked):
            self.client.plan_targets('stale',{'AAPL':.1,'MSFT':0},bad,NOW)
        bad=quotes(); bad['AAPL']['basis']='supplier_adjusted_open_return_proxy'
        with self.assertRaises(ExecutionBlocked):
            self.client.plan_targets('adjusted',{'AAPL':.1,'MSFT':0},bad,NOW)
        with self.broker.journal.change() as state:
            state['identity_confirmed']=False
        self.assertFalse(self.client.reconcile(self.broker,NOW))
        with self.broker.journal.change() as state:
            state['identity_confirmed']=True; state['cash']='9900'
        self.assertFalse(self.client.reconcile(self.broker,NOW))
        self.assertEqual(len(self.client.journal.read()['orders']),0)

    def test_foreign_overlap_and_corporate_actions_fail_closed(self):
        with self.broker.journal.change() as state:
            state['positions']['AAPL']='2'
        self.assertFalse(self.client.reconcile(self.broker,NOW))
        with self.broker.journal.change() as state:
            state['positions']['AAPL']='0'; state['corporate_actions_pending']=True
        self.assertFalse(self.client.reconcile(self.broker,NOW))

    def test_live_or_unconfirmed_paper_configuration_refused(self):
        for config in (replace(self.config,mode='live'),replace(self.config,mode='paper'),replace(self.config,quantity_step='.01')):
            with self.assertRaises(ExecutionBlocked):
                config.validate()

    def test_missing_initialized_database_never_resets_capital(self):
        self.client.journal.close()
        (self.root/'client.sqlite').unlink()
        with self.assertRaises(ExecutionBlocked):
            H60Executor(self.root/'client.sqlite',self.config,'test-manifest',['AAPL','MSFT'])


if __name__=='__main__':
    unittest.main()
