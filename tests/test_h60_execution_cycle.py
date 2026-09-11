"""Fictitious quotes: restart a persisted H60 batch and handle stop/cancel races."""
from dataclasses import asdict,replace
from datetime import datetime,timezone
from pathlib import Path
import tempfile
import unittest

from h60_execution import H60Executor,VirtualBroker,ExecutionConfig,number,ExecutionBlocked
from h60_execution_cycle import plan_open_cycle,submit_next
from h60_strategy_runtime import H60Runtime
import profit_priority_strategy as strategy
from test_robust_strategy import fixture


class CycleTests(unittest.TestCase):
    def test_budget_mismatch_stops_before_broker_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            client=H60Executor(Path(directory)/'client.sqlite',ExecutionConfig(),'fictitious-budget',['AAPL'])
            manifest=dict(strategy_id=client.config.strategy_id,budget='1000')
            with self.assertRaisesRegex(ExecutionBlocked,'budget/identity differ'):
                plan_open_cycle(client,None,manifest,None,None,None,None,None)
            self.assertEqual(client.journal.read()['orders'],{})
            client.journal.close()

    def test_protection_fill_cancels_partial_entry_remainder_across_restart(self):
        # All quotes/fills are deliberately fictitious. 9-share entry: fill 3,
        # stop 1, cancel entry remainder, then race a buy 1 and stop 1.
        now=datetime(2025,1,6,15,tzinfo=timezone.utc)
        q={'AAPL':dict(bid='100',ask='100',asof=now.isoformat(),basis='synthetic_unadjusted_quote',
            regular_session=True,quantity_step_confirmed=True,corporate_action_pending=False)}
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);config=ExecutionConfig()
            client=H60Executor(root/'client.sqlite',config,'fictitious-partial-entry',['AAPL'])
            broker=VirtualBroker(root/'broker.sqlite')
            self.assertTrue(client.reconcile(broker,now))
            keys=client.plan_targets('entry',{'AAPL':.1},q,now)
            buy=keys[0]
            self.assertEqual(client.journal.read()['orders'][buy]['state']['quantity'],'9')
            self.assertEqual(submit_next(client,broker,keys,q,now)['status'],'submitted_reconcile_before_next')
            broker.fill(buy,3,100,now);self.assertTrue(client.reconcile(broker,now))
            stop=client.plan_protection({'AAPL':85},q,now)[0]
            client.submit(stop,broker,q,now);self.assertTrue(client.reconcile(broker,now))
            broker.fill(stop,1,85,now)
            result=submit_next(client,broker,keys,q,now)
            self.assertEqual(result['status'],'protection_triggered_cancel_buy_remainder')
            self.assertEqual(broker.journal.read()['orders'][buy]['status'],'PendingCancel')
            cash_reserved,sell_reserved=client.reservations()
            self.assertGreater(cash_reserved,600)
            self.assertEqual(sell_reserved['AAPL'],2)
            client.journal.close()
            client=H60Executor(root/'client.sqlite',config,'fictitious-partial-entry',['AAPL'])
            broker.fill(buy,1,100,now);broker.fill(stop,1,85,now)
            broker.confirm_cancel(buy)
            self.assertEqual(submit_next(client,broker,keys,q,now)['status'],'batch_terminal')
            self.assertEqual(client.balances()[1]['AAPL'],2)
            topup=client.plan_protection({'AAPL':85},q,now)
            self.assertEqual(len(topup),1)
            self.assertEqual(client.journal.read()['orders'][topup[0]]['state']['quantity'],'1')
            client.submit(topup[0],broker,q,now);self.assertTrue(client.reconcile(broker,now))
            self.assertEqual(client.reservations()[0],0)
            self.assertEqual(client.reservations()[1]['AAPL'],2)
            self.assertEqual(sum(e['kind']=='submit' and e['key']==buy for e in broker.journal.read()['events']),1)
            client.journal.close();broker.journal.close()

    def test_restart_same_batch_and_recompute_after_cancel_stop_fill(self):
        dates,bars,spy,scores,groups=fixture()
        symbols=list(scores.columns)
        manifest=dict(calendar=[str(d.date()) for d in dates],observations=[str(dates[i].date()) for i in (250,255)],
                      risk_policy=asdict(replace(strategy.Policy(),soft_enabled=False)),symbols=symbols,
                      groups=groups,budget='10000',strategy_id='cycle-test')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); config=ExecutionConfig(strategy_id='cycle-test')
            client=H60Executor(root/'client.sqlite',config,'fictitious-cycle',symbols)
            broker=VirtualBroker(root/'broker.sqlite')
            def context(index):
                day=str(dates[index].date());obs=str(dates[index-1].date())
                now=datetime.fromisoformat(day+'T15:00:00+00:00')
                quotes={s:dict(bid='100',ask='100',asof=now.isoformat(),basis='synthetic_unadjusted_quote',
                    regular_session=True,quantity_step_confirmed=True,corporate_action_pending=False) for s in symbols}
                risk=strategy.risk_inputs({k:v.loc[:obs] for k,v in bars.items()},spy.loc[:obs])
                return day,obs,now,quotes,risk
            day,obs,now,q,risk=context(251)
            cycle=plan_open_cycle(client,broker,manifest,day,scores.loc[obs],risk,q,now)
            self.assertEqual(cycle['status'],'intents_persisted')
            keys=cycle['intents']; count=len(client.journal.read()['orders'])
            client.journal.close()
            client=H60Executor(root/'client.sqlite',config,'fictitious-cycle',symbols)
            resumed=plan_open_cycle(client,broker,manifest,day,scores.loc[obs],risk,q,now)
            self.assertEqual(resumed['intents'],keys)
            self.assertEqual(resumed['status'],'resume_persisted_batch')
            self.assertEqual(len(client.journal.read()['orders']),count)
            for _ in keys:
                step=submit_next(client,broker,keys,q,now)
                self.assertEqual(step['status'],'submitted_reconcile_before_next')
                order=broker.journal.read()['orders'][step['intent']]
                broker.fill(step['intent'],order['quantity'],100,now)
                self.assertTrue(client.reconcile(broker,now))
            runtime=H60Runtime(manifest,client.journal.read()['runtime'])
            runtime.apply_fills(client.journal.read(),day)
            protections=client.plan_protection(runtime.state['floors'],q,now)
            for key in protections:
                client.submit(key,broker,q,now);self.assertTrue(client.reconcile(broker,now))
            cash,positions=client.balances()
            runtime.close(day,positions,cash,{s:100. for s in symbols});client.save_runtime(runtime.state)
            day,obs,now,q,risk=context(256)
            waiting=plan_open_cycle(client,broker,manifest,day,scores.loc[obs],risk,q,now)
            self.assertEqual(waiting['status'],'await_cancel_reconciliation')
            stopped=next(k for k in protections if broker.journal.read()['orders'][k]['symbol']=='AAPL')
            quantity=broker.journal.read()['orders'][stopped]['quantity']
            broker.fill(stopped,quantity,80,now)
            for k in protections:
                broker.confirm_cancel(k)
            decision=plan_open_cycle(client,broker,manifest,day,scores.loc[obs],risk,q,now)
            self.assertEqual(decision['status'],'intents_persisted')
            self.assertEqual(decision['decision']['weights']['AAPL'],0.)
            self.assertFalse(any(client.journal.read()['orders'][k]['state']['symbol']=='AAPL' and
                                 client.journal.read()['orders'][k]['state']['side']=='BUY' for k in decision['intents']))
            client.journal.close();broker.journal.close()

    def test_delayed_fill_processing_uses_execution_day_for_cooldown(self):
        dates,bars,spy,scores,groups=fixture()
        manifest=dict(calendar=[str(d.date()) for d in dates],observations=[],symbols=list(scores.columns),
                      risk_policy=asdict(strategy.Policy()),groups=groups,budget='10000',strategy_id='test')
        runtime=H60Runtime(manifest)
        ledger={'orders':{'stop':{'reason':'stock_protection','state':{'symbol':'AAPL','side':'SELL','executions':{'E':{'price':'80'}}},
                                 'fill_times':{'E':str(dates[251].date())+'T15:00:00+00:00'}}}}
        runtime.apply_fills(ledger,str(dates[256].date()))
        self.assertEqual(runtime.state['blocked_until']['AAPL'],256)


if __name__=='__main__':
    unittest.main()
