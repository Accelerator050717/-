"""Fictitious broker: real subprocess crashes/restarts, no network or training."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

from panel_config import ROOT
from h60_execution import H60Executor, VirtualBroker, ExecutionConfig, number
from h60_research_inputs import save, sha

OUT=ROOT/'data/experiments/h60_risk_execution_v8/execution_faults_v2'
NOW=datetime(2025,1,6,15,tzinfo=timezone.utc)


def worker(phase):
    client=H60Executor(OUT/'client.sqlite',ExecutionConfig(strategy_id='h60-v8-fault-fixture'),'fictitious-fault-manifest',['AAPL'])
    broker=VirtualBroker(OUT/'broker.sqlite',outside_positions={'FOREIGN_TEST':'17'})
    q={'AAPL':dict(bid='100',ask='100',asof=NOW.isoformat(),basis='synthetic_unadjusted_quote',
                   regular_session=True,quantity_step_confirmed=True,corporate_action_pending=False)}
    if phase=='crash_after_timeout':
        assert client.reconcile(broker,NOW)
        key=client.plan_targets('same-fixed-decision',{'AAPL':.1},q,NOW)[0]
        broker.timeout_after_accept=True
        assert not client.submit(key,broker,q,NOW)
        save(OUT/'phase1.json',dict(attempt_persisted=client.journal.read()['orders'][key]['state']['attempted'],broker_order_count=1))
        os._exit(73)  # Deliberately skip normal shutdown AFTER durable commits.
    assert client.reconcile(broker,NOW)
    key=client.plan_targets('same-fixed-decision',{'AAPL':.1},q,NOW)[0]
    assert not client.submit(key,broker,q,NOW)
    if phase=='recover_then_crash_during_cancel':
        assert len(broker.journal.read()['orders'])==1
        broker.fill(key,3,100,NOW)
        assert client.reconcile(broker,NOW)
        stop=client.plan_protection({'AAPL':'85'},q,NOW)[0]
        client.submit(stop,broker,q,NOW)
        assert client.reconcile(broker,NOW)
        client.cancel(stop,broker,NOW)
        broker.fill(stop,1,80,NOW)  # Fill competes with a pending cancellation.
        save(OUT/'phase2.json',dict(duplicate_submit_prevented=True,stop_key=stop,client_quantity_before_recovery='3',broker_quantity_after_race='2'))
        os._exit(74)
    assert phase=='final_recovery'
    assert client.balances()[1]['AAPL']==2
    assert client.reservations()[1]['AAPL']==2
    stop=json.loads((OUT/'phase2.json').read_text(encoding='utf-8'))['stop_key']
    broker.confirm_cancel(stop)
    assert client.reconcile(broker,NOW)
    assert client.reservations()[1]['AAPL']==0
    quantity=number(client.journal.read()['orders'][key]['state']['quantity'])
    broker.fill(key,quantity-3,100,NOW)
    assert client.reconcile(broker,NOW)
    keys=client.plan_protection({'AAPL':'85'},q,NOW)
    for item in keys:
        client.submit(item,broker,q,NOW)
        assert client.reconcile(broker,NOW)
    assert client.reservations()[1]['AAPL']==client.balances()[1]['AAPL']==quantity-1
    client.export(OUT/'recovered_state.json')
    save(OUT/'phase3.json',dict(partial_fill_and_cancel_race_reconciled=True,
         held=str(client.balances()[1]['AAPL']),protected=str(client.reservations()[1]['AAPL']),
         broker_order_count=len(broker.journal.read()['orders']),original_buy_submit_count=sum(
             e['kind']=='submit' and e['key']==key for e in broker.journal.read()['events']),
         unrelated_positions_untouched=broker.journal.read()['positions']['FOREIGN_TEST']=='17'))
    client.journal.close();broker.journal.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase',choices=('crash_after_timeout','recover_then_crash_during_cancel','final_recovery'))
    args=parser.parse_args()
    OUT.mkdir(exist_ok=True)
    if args.phase:
        worker(args.phase);return
    if (OUT/'completion.json').exists():
        print('Persisted subprocess recovery evidence already exists; preserved.');return
    phases=[('crash_after_timeout',73),('recover_then_crash_during_cancel',74),('final_recovery',0)]
    records=[]
    for phase,expected in phases:
        result=subprocess.run([sys.executable,str(Path(__file__)), '--phase',phase],cwd=ROOT,
             capture_output=True,text=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        (OUT/(phase+'.log')).write_text(result.stdout+result.stderr,encoding='utf-8')
        records.append(dict(phase=phase,process_returncode=result.returncode,expected=expected))
        save(OUT/'process_results.json',records)
        assert result.returncode==expected,phase+': '+result.stderr
    save(OUT/'completion.json',dict(completed_at_utc=datetime.now(timezone.utc).isoformat(),
        fixture='All quotes, broker facts and account balances are fictitious',real_os_processes=3,
        forced_abrupt_exits=2,steps=records,all_checks_passed=True,
        source_sha256={p:sha(ROOT/p) for p in ('h60_execution.py','44_test_h60_recovery.py')},
        real_paper_responses=0,new_fits=0,prices_2026_accessed=False))
    print(json.dumps(json.loads((OUT/'phase3.json').read_text(encoding='utf-8')),indent=2))


if __name__=='__main__':
    main()
