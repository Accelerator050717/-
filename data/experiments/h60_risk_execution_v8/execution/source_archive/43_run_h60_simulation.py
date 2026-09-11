"""H60 engineering replay with fictitious raw quotes; optional real IBKR read-only readiness check.

Default never connects a broker. Research scores/risk snapshots are historical;
the separate simulated execution prices are invented and cannot measure alpha.
"""
import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

from panel_config import ROOT, SYMBOLS
import research_features as rf
import profit_priority_strategy as strategy
from h60_research_inputs import load_inputs, sha, save, PRIOR
from h60_execution import H60Executor, VirtualBroker, ExecutionConfig, ExecutionBlocked, digest, number
from h60_strategy_runtime import H60Runtime, score_feature_snapshot, validate_manifest

OUT=ROOT/'data/experiments/h60_risk_execution_v8'
REPLAY=OUT/'execution'


def check_ibkr():
    from ibkr_readonly import check_readiness, ReadonlyConfig
    result=check_readiness(ReadonlyConfig(ports=(7497,4002),expected_environment='paper'))
    save(OUT/'IBKR_READINESS.json',result)
    print(json.dumps({k:result.get(k) for k in ('checked_at_utc','status','blocker','paper_account_confirmed','orders_sent')},indent=2))


def paper_reconcile(config_path):
    """Available recovery check; does not generate new intents or submit orders."""
    import os
    from h60_ibkr_paper import IBKRPaperAdapter
    config=json.loads(Path(config_path).read_text(encoding='utf-8'))
    account=os.environ.get(config['expected_account_environment_variable'])
    adapter=IBKRPaperAdapter(config,account)
    manifest=json.loads((ROOT/config['strategy_manifest']).read_text(encoding='utf-8'))
    validate_manifest(manifest)
    if config['symbols']!=manifest['symbols']:
        raise ExecutionBlocked('Paper symbols do not match strategy manifest')
    client=None
    try:
        adapter.connect()
        policy=ExecutionConfig(mode='paper',budget=config['budget'],strategy_id=config['strategy_id'],
                               paper_budget_isolated=True,paper_identity_confirmed=adapter.confirmed)
        client=H60Executor(OUT/'paper_private/client.sqlite',policy,digest(manifest),manifest['symbols'])
        okay=client.reconcile(adapter,datetime.now(timezone.utc))
        client.export(OUT/'paper_private/state.json')
        save(OUT/'PAPER_RECONCILIATION_STATUS.json',dict(completed_at_utc=datetime.now(timezone.utc).isoformat(),
            paper_identity_confirmed=adapter.confirmed,reconciled=okay,new_orders_submitted=0,
            blocker=client.journal.read()['blocked'],evidence='Real paper facts only if identity+responses actually succeeded'))
        print(json.dumps(dict(paper_confirmed=adapter.confirmed,reconciled=okay,orders_submitted=0)))
    finally:
        adapter.close()
        if client:
            client.journal.close()


def run_virtual():
    bars,_,spy,scores,observations,final,identity=load_inputs()
    model=next(m for m in identity['models'] if m['year']==2025)
    source_files=('profit_priority_strategy.py','research_backtest.py','h60_execution.py','h60_strategy_runtime.py',
                  'h60_ibkr_paper.py','43_run_h60_simulation.py','execution_order_state.py')
    manifest=dict(schema=1,strategy_id='h60-v8-engineering',strategy_role='engineering_only',
        development_candidate='stop_on_soft_off',development_passed=False,
        model=model,model_role='2025 annual engineering replay; not current deployment model',
        symbols=list(SYMBOLS),groups=rf.SECTOR_PROXY,calendar=identity['common_calendar'],
        observations=identity['observations'],risk_policy=asdict(replace(strategy.Policy(),soft_enabled=False)),
        budget='10000',quantity_step='1',reference_commit='9d98008d72f096c2c1fa33a998f000fe62c48bb5',
        source_sha256={p:sha(ROOT/p) for p in source_files},
        code_version='uncommitted v8 working tree identified by per-file SHA256',
        price_boundary='Historical adjusted inputs for model/risk; invented unadjusted quotes for engineering fills',
        corporate_actions='Fail closed for unknown actions; no automatic splits/dividend cash ledger in this adapter',
        independent_validation_protocol='Annual Y model trained through Y-2 with labels mature before Y-1; no 2026 evaluation authorized by a failed development gate')
    path=OUT/'ENGINEERING_STRATEGY_MANIFEST.json'
    if path.exists():
        assert json.loads(path.read_text(encoding='utf-8'))==manifest,'Engineering identity changed; preserve old run, do not silently reset.'
    else:
        save(path,manifest)
    validate_manifest(manifest)
    calendar=pd.DatetimeIndex(manifest['calendar'])
    start=next(d for d in manifest['observations'] if d.startswith('2025'))
    anchor=calendar.get_loc(pd.Timestamp(start))
    days=calendar[anchor+1:anchor+17]
    REPLAY.mkdir(exist_ok=True)
    config=ExecutionConfig()
    client=H60Executor(REPLAY/'client.sqlite',config,digest(manifest),SYMBOLS)
    broker=VirtualBroker(REPLAY/'broker.sqlite',outside_positions={'UNRELATED_TEST_ASSET':'17'})
    before=client.journal.read()
    # One genuine inference from the identified model; compare with original saved
    # prediction, not with any future y. Training count remains zero.
    features=pd.read_csv(PRIOR/'panel.csv',usecols=['Date','symbol',*model['features']],float_precision='round_trip')
    features=features.loc[features.Date.eq(start),['Date','symbol',*model['features']]]
    prediction=score_feature_snapshot(features,start,manifest)
    original=scores.loc[start]
    np.testing.assert_allclose(prediction.reindex(SYMBOLS),original,rtol=0,atol=1e-12)
    save(OUT/'FORWARD_SIGNAL_INTERFACE_CHECK.json',dict(observation=start,rows=len(features),new_fits=0,
        model_sha256=model['sha256'],max_abs_difference=float((prediction.reindex(SYMBOLS)-original).abs().max()),
        features_only=True,scoring_year=2025,forward_2026_performance=False))
    snapshots=[]; new_decisions=0; restarts=0

    def reconcile(now):
        if not client.reconcile(broker,now):
            raise ExecutionBlocked(client.journal.read()['blocked'])

    def fill_intents(keys,q,now):
        for key in keys:
            row=client.journal.read()['orders'][key]
            if row.get('terminal_reconciled'):
                continue
            client.submit(key,broker,q,now)
            reconcile(now)
            actual=broker.journal.read()['orders'][key]
            remaining=number(actual['quantity'])-number(actual['filled'])
            if remaining>0:
                # Separate fill/commission callbacks are represented by broker facts.
                broker.fill(key,remaining,q[actual['symbol']]['ask' if actual['side']=='BUY' else 'bid'],now)
            reconcile(now)

    for offset,stamp in enumerate(days):
        day=str(stamp.date()); now=datetime.fromisoformat(day+'T14:35:00+00:00')
        reconcile(now)
        existing=client.journal.read()
        if existing.get('runtime') and existing['runtime']['last_close'] and day<=existing['runtime']['last_close']:
            continue
        runtime=H60Runtime(manifest,existing.get('runtime'))
        raw={s:round(80+3*j+.15*offset+np.sin(offset*.7+j)*1.5,2) for j,s in enumerate(SYMBOLS)}
        if offset==7:
            held=client.balances()[1]
            stopped=next((s for s in SYMBOLS if held[s]>0 and s in runtime.state['floors']),None)
            if stopped:
                raw[stopped]=round(runtime.state['floors'][stopped]*.90,2)  # Explicit invented gap fixture.
        q={s:dict(bid=str(raw[s]),ask=str(round(raw[s]+.02,2)),asof=now.isoformat(),
            basis='synthetic_unadjusted_quote',regular_session=True,quantity_step_confirmed=True,corporate_action_pending=False) for s in SYMBOLS}
        # Existing protective orders act before a new scheduled target.
        for key,order in list(broker.journal.read()['orders'].items()):
            if order['kind']=='STP' and order['status'] not in ('Filled','Cancelled','ApiCancelled') and number(q[order['symbol']]['bid'])<=number(order['stop_price']):
                broker.fill(key,number(order['quantity'])-number(order['filled']),q[order['symbol']]['bid'],now)
        reconcile(now)
        runtime.apply_fills(client.journal.read(),day)
        obs=manifest['calendar'][manifest['calendar'].index(day)-1]
        risk=strategy.risk_inputs({k:v.loc[:obs] for k,v in bars.items()},spy.loc[:obs],runtime.policy.target_vol)
        cash,positions=client.balances()
        decision=runtime.next_open(day,scores.loc[obs],risk,positions,cash,q)
        if decision:
            # Conservative cancel/reconcile sequence before any position resize.
            # Pending cancellations retain sell reservations; no overlap allowed.
            for key,row in list(client.journal.read()['orders'].items()):
                if not row.get('terminal_reconciled'):
                    client.cancel(key,broker,now)
                    broker.confirm_cancel(key)
            reconcile(now)
            keys=client.plan_targets(decision['decision_id'],decision['weights'],q,now,
                reduction=decision['reduction'],reason=decision['reason'],runtime_after=decision['runtime_after'])
            repeated=client.plan_targets(decision['decision_id'],decision['weights'],q,now,
                reduction=decision['reduction'],reason=decision['reason'],runtime_after=decision['runtime_after'])
            assert repeated==keys
            fill_intents(keys,q,now)
            new_decisions+=1
            runtime=H60Runtime(manifest,client.journal.read()['runtime'])
        else:
            client.save_runtime(runtime.state)
        runtime.apply_fills(client.journal.read(),day)
        protection=client.plan_protection(runtime.state['floors'],q,now)
        for key in protection:
            client.submit(key,broker,q,now);reconcile(now)
        cash,positions=client.balances()
        _,reserved=client.reservations()
        assert reserved==positions,'Total protective sell quantity must equal actual filled holdings'
        runtime.close(day,positions,cash,raw)
        client.save_runtime(runtime.state)
        snapshots.append(dict(day=day,cash=str(cash),positions={s:str(v) for s,v in positions.items()},
                              protective_quantity={s:str(v) for s,v in reserved.items()},quote_fixture=q,
                              runtime=runtime.state))
        # Every simulated day closes the process-side DB connection and reconstructs
        # executor state. The independent broker journal stays authoritative.
        client.journal.close()
        client=H60Executor(REPLAY/'client.sqlite',config,digest(manifest),SYMBOLS)
        reconcile(now);restarts+=1
        print(f'Fictitious execution {day}: decision={decision is not None}, persisted/reconciled',flush=True)
    after=client.journal.read()
    client.export(REPLAY/'state.json')
    if snapshots:
        save(REPLAY/'snapshots.json',snapshots)
    total_fills=sum(len(r['state']['executions']) for r in after['orders'].values())
    old_fills=sum(len(r['state']['executions']) for r in before['orders'].values())
    report=dict(completed_at_utc=datetime.now(timezone.utc).isoformat(),mode='synthetic_quote_engineering_replay',
        real_historical_H60_signal=True,all_execution_quotes_and_fills_fictitious=True,
        new_decisions=new_decisions,new_fills=total_fills-old_fills,total_fills=total_fills,
        total_order_intents=len(after['orders']),restart_reconciliations=restarts,
        start=str(days[0].date()),end=str(days[-1].date()),new_fits=0,
        real_paper_orders=0,real_paper_fills=0,forward_performance_observations=0,prices_2026_accessed=False,
        unrelated_position_untouched=broker.journal.read()['positions']['UNRELATED_TEST_ASSET']=='17',
        protective_quantities_equal_actual_holdings=True,model_sha256=model['sha256'],
        strategy_manifest_sha256=digest(manifest),no_performance_claim='Synthetic fills do not provide valid strategy returns')
    name='REPEAT_RUN.json' if old_fills else 'completion.json'
    save(REPLAY/name,report)
    client.journal.close();broker.journal.close()
    print(json.dumps(report,indent=2))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-ibkr',action='store_true')
    parser.add_argument('--paper-reconcile',metavar='CONFIG_PATH')
    args=parser.parse_args()
    if args.check_ibkr:
        check_ibkr()
    elif args.paper_reconcile:
        paper_reconcile(args.paper_reconcile)
    else:
        run_virtual()


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
