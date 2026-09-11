"""Fictitious SDK contract responses only; no TWS connection is made."""
from datetime import datetime,timezone
from types import SimpleNamespace as N
import unittest
from unittest.mock import patch

from h60_ibkr_paper import IBKRPaperAdapter
from h60_execution import ExecutionBlocked,intent_prefix


class FakeIB:
    def __init__(self,accounts):
        self.accounts=accounts; self.client=N(isReady=lambda:True); self.cancelled=[]
    def isConnected(self): return True
    def managedAccounts(self): return self.accounts
    def cancelOrder(self,order): self.cancelled.append(order)


def configuration():
    return dict(mode='paper',enable_paper_orders=True,paper_budget_isolated=True,budget='1000',
                strategy_id='synthetic-test',host='127.0.0.1',port=7497,client_id=9032,
                currency='USD',symbols=['AAPL'],corporate_actions_checked_through='2025-01-06')


class PaperAdapterTests(unittest.TestCase):
    def test_quote_receipt_uses_post_request_clock_and_rejects_stale_ticks(self):
        # Fictitious response arrives after request-start. It is not a future tick.
        fake=FakeIB(['DU123']);config=configuration()
        contract=N(conId=123)
        ticker=N(marketDataType=1,time=datetime(2025,1,6,15,0,2,tzinfo=timezone.utc),
                 bid=100.,ask=100.01,contract=contract)
        fake.reqTickers=lambda *contracts:[ticker]
        adapter=IBKRPaperAdapter(config,'DU123',client=fake)
        adapter.contracts['AAPL']=contract
        adapter.details['AAPL']=N(liquidSessions=lambda:[N(start=datetime(2025,1,6,14,30,tzinfo=timezone.utc),
                                                         end=datetime(2025,1,6,21,tzinfo=timezone.utc))])
        with patch('h60_ibkr_paper.datetime') as clock:
            clock.now.return_value=datetime(2025,1,6,15,0,3,tzinfo=timezone.utc)
            quotes=adapter.quotes(['AAPL'],datetime(2025,1,6,15,tzinfo=timezone.utc))
            self.assertEqual(quotes['AAPL']['asof'],'2025-01-06T15:00:02+00:00')
            ticker.time=datetime(2025,1,6,14,59,tzinfo=timezone.utc)
            with self.assertRaisesRegex(ExecutionBlocked,'stale'):
                adapter.quotes(['AAPL'],datetime(2025,1,6,15,tzinfo=timezone.utc))

    def test_unknown_live_or_mixed_accounts_never_reach_order_code(self):
        for accounts in (['U123'],['DU123','U123'],[]):
            adapter=IBKRPaperAdapter(configuration(),'DU123',client=FakeIB(accounts))
            with self.assertRaises(ExecutionBlocked):
                adapter.submit({},datetime.now(timezone.utc))

    def test_other_order_reference_or_client_cannot_be_cancelled(self):
        fake=FakeIB(['DU123'])
        adapter=IBKRPaperAdapter(configuration(),'DU123',client=fake)
        key=intent_prefix('synthetic-test')+'test'
        adapter.references[key]=N(order=N(account='DU123',clientId=99))
        with self.assertRaises(ExecutionBlocked):
            adapter.cancel(key,datetime.now(timezone.utc))
        with self.assertRaises(ExecutionBlocked):
            adapter.cancel('foreign-order',datetime.now(timezone.utc))
        self.assertEqual(fake.cancelled,[])

    def test_snapshot_normalizes_partial_execution_and_commission(self):
        fake=FakeIB(['DU123']); config=configuration()
        key=intent_prefix(config['strategy_id'])+'test'
        order=N(account='DU123',orderRef=key,clientId=9032,action='BUY',permId=101,totalQuantity=2)
        trade=N(order=order,contract=N(symbol='AAPL'),orderStatus=N(status='Submitted',filled=1))
        execution=N(acctNumber='DU123',clientId=9032,orderRef=key,permId=101,side='BOT',execId='fixture.1',shares=1,price=100,
                    time=datetime(2025,1,6,15,tzinfo=timezone.utc))
        fill=N(execution=execution,contract=N(symbol='AAPL'),commissionReport=N(execId='fixture.1',commission=.1,currency='USD'))
        fake.reqAllOpenOrders=lambda:[trade]
        fake.reqCompletedOrders=lambda apiOnly:[]
        fake.reqExecutions=lambda filter:[fill]
        fake.reqPositions=lambda:[N(account='DU123',contract=N(symbol='AAPL'),position=1)]
        fake.reqAccountSummaryAsync=lambda:None
        fake._run=lambda arg:None
        fake.accountSummary=lambda account:[N(account='DU123',tag=t,value='899.9',currency='USD') for t in ('TotalCashValue','SettledCash','AvailableFunds')]
        adapter=IBKRPaperAdapter(config,'DU123',client=fake)
        fact=adapter.snapshot(datetime(2025,1,6,15,tzinfo=timezone.utc))
        self.assertTrue(fact['complete'] and fact['identity_confirmed'])
        self.assertEqual(fact['orders'][key]['fills'][0]['id'],'fixture.1')
        self.assertEqual(fact['commissions']['fixture.1']['fee'],'0.1')
        self.assertEqual(fact['positions'],{'AAPL':'1'})
        self.assertNotIn('DU123',str(fact))


if __name__=='__main__':
    unittest.main()
