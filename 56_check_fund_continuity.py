"""FICTITIOUS process-crash verification; VirtualBroker only, no network adapter.

Run without --worker to compare uninterrupted execution with two real subprocess
exits around fund checkpoint commit. No training, history download or paper order.
"""
import argparse
from dataclasses import asdict, replace
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd

from h60_execution import ExecutionConfig, H60Executor, VirtualBroker, number
from h60_fund_risk_bridge import FundRiskBridge
from h60_global_control import GlobalRisk
from h60_strategy_runtime import H60Runtime
import profit_priority_strategy as strategy
from strategy_fund_journal import FundJournal


ROOT = Path(__file__).resolve().parent
DEFAULT = ROOT / 'data/experiments/continuous_fund_risk_v13/engineering'
SCOPE = dict(scope_id='fictional-strategy-fund-v13', currency='USD',
             owner='isolated fictitious H60 budget', universe=['AAPL', 'MSFT'],
             execution_strategy_id='fictional-v13-continuity')
MODEL = 'FICTIONAL-frozen-runtime-manifest'
RECORD_ONLY = dict(mode='record_only', allow_new_risk=True,
                   reason='verify unchanged frozen execution decisions')


def context():
    dates = pd.bdate_range('2020-01-01', periods=290)
    base = 100 + np.arange(290) * .01 + np.sin(np.arange(290) * .3)
    closes = pd.DataFrame({'AAPL': base, 'MSFT': base * 1.5}, index=dates)
    bars = dict(Open=closes * .999, High=closes * 1.015, Low=closes * .985, Close=closes)
    spy = pd.Series(100 + np.arange(290) * .1 + np.sin(np.arange(290)) * .1, index=dates)
    day, observation = str(dates[251].date()), str(dates[250].date())
    manifest = dict(calendar=[str(d.date()) for d in dates], observations=[observation],
        symbols=['AAPL', 'MSFT'], groups={'AAPL': 'tech', 'MSFT': 'tech'},
        risk_policy=asdict(replace(strategy.Policy(), soft_enabled=False)),
        budget='10000', strategy_id='fictional-v13-continuity')
    now = datetime.fromisoformat(day + 'T15:00:00+00:00')
    quotes = {s: dict(bid='100', ask='100', asof=now.isoformat(),
        basis='synthetic_unadjusted_quote', regular_session=True,
        quantity_step_confirmed=True, corporate_action_pending=False) for s in manifest['symbols']}
    risk = strategy.risk_inputs({key: value.loc[:observation] for key, value in bars.items()},
                                spy.loc[:observation])
    scores = pd.Series({'AAPL': 1., 'MSFT': 0.})
    return manifest, day, now, quotes, risk, scores


def worker(directory, phase, fault=None):
    directory.mkdir(parents=True, exist_ok=True)
    manifest, day, now, quotes, risk, scores = context()
    config = ExecutionConfig(strategy_id=manifest['strategy_id'])
    client = H60Executor(directory / 'execution.sqlite', config, MODEL, manifest['symbols'])
    broker = VirtualBroker(directory / 'broker.sqlite', outside_positions={'FOREIGN': '17'})
    if phase == 'seed':
        fund = FundJournal.create(directory / 'fund.sqlite', scope=SCOPE, initial_cash='10000', at=now.isoformat())
    else:
        fund = FundJournal(directory / 'fund.sqlite', expected_scope=SCOPE)
    bridge = FundRiskBridge(client, fund, broker, run_id='fictional-process-' + phase)
    try:
        if phase == 'seed':
            bridge.sync(now, {'AAPL': '100', 'MSFT': '100'}, risk_state=RECORD_ONLY)
            cycle = bridge.record_only_open_cycle(manifest, day, scores, risk, quotes, now)
            key = next(key for key in cycle['intents'] if client.journal.read()['orders'][key]['state']['symbol'] == 'AAPL')
            bridge.submit_virtual(key, quotes, now)
            broker.fill(key, 3, 100, now, execution_id='FICTITIOUS-BUY-001')
            assert client.reconcile(broker, now)
            runtime = H60Runtime(manifest, client.journal.read()['runtime'])
            runtime.apply_fills(client.journal.read(), day)
            cash, positions = client.balances()
            runtime.close(day, positions, cash, {'AAPL': 100., 'MSFT': 100.})
            client.save_runtime(runtime.state)
            if fault == 'before':
                os._exit(73)  # Intentionally skip finally/SQLite closes: real process crash.
            bridge.sync(now, {'AAPL': '100', 'MSFT': '100'})
            if fault == 'after':
                os._exit(74)
        else:
            # This MUST merge the old broker/client facts before another decision.
            bridge.sync(now, {'AAPL': '100', 'MSFT': '100'})
        resumed = bridge.record_only_open_cycle(manifest, day, scores, risk, quotes, now)
        assert resumed['status'] == 'resume_persisted_batch'
        document = client.journal.read()
        key = next(key for key, row in document['orders'].items() if row['state']['symbol'] == 'AAPL')
        assert not bridge.submit_virtual(key, quotes, now)  # Attempt is never repeated.
        # A gap stop fills only one of three shares. The remainder is real risk.
        bridge.sync(now, {'AAPL': '100', 'MSFT': '100'})
        if not any(row['reason'] == 'stock_protection' for row in client.journal.read()['orders'].values()):
            stop = client.plan_protection({'AAPL': 85}, quotes, now)[0]
            bridge.sync(now, {'AAPL': '100', 'MSFT': '100'})
            bridge.submit_virtual(stop, quotes, now)
            broker.fill(stop, 1, 70, now, execution_id='FICTITIOUS-GAP-EXIT-001')
        final = bridge.sync(now, {'AAPL': '70', 'MSFT': '100'},
            risk_state=GlobalRisk(mode='HALTED', pending_flat=True,
                            reason='FICTIONAL exit only partly filled').as_dict())
        cash, positions = client.balances()
        source = client.journal.read()
        result = dict(evidence='FICTIONAL; no real/paper broker',
            cash=str(cash), positions={s: str(q) for s, q in positions.items()},
            targets={key: value['signature'] for key, value in source['batches'].items()},
            orders={key: dict(side=row['state']['side'], symbol=row['state']['symbol'],
                quantity=row['state']['quantity'], executions=row['state']['executions'])
                for key, row in source['orders'].items()},
            runtime=source['runtime'], unit_nav=final['unit_nav'], high_water_nav=final['high_water_nav'],
            max_drawdown=final['max_drawdown'], equity=final['equity'],
            risk_state=final['risk_state'], foreign_position=broker.journal.read()['positions']['FOREIGN'],
            broker_submit_count=sum(event['kind'] == 'submit' for event in broker.journal.read()['events']))
        (directory / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        client.export(directory / 'execution_snapshot.json')
        (directory / 'fund_snapshot.json').write_text(json.dumps(final, indent=2), encoding='utf-8')
        return result
    finally:
        client.journal.close()
        broker.journal.close()
        fund.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=DEFAULT)
    parser.add_argument('--worker', choices=['seed', 'recover'])
    parser.add_argument('--fault', choices=['before', 'after'])
    args = parser.parse_args()
    if args.worker:
        worker(args.output, args.worker, args.fault)
        return
    args.output.mkdir(parents=True, exist_ok=True)
    cases = [('uninterrupted', None), ('crash_before_checkpoint', 'before'), ('crash_after_checkpoint', 'after')]
    outcomes = {}
    for name, fault in cases:
        folder = args.output / name
        if folder.exists():
            raise SystemExit('Preserve prior evidence: supply a new --output directory')
        command = [sys.executable, str(Path(__file__).resolve()), '--output', str(folder), '--worker', 'seed']
        if fault:
            command += ['--fault', fault]
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        expected = {'before': 73, 'after': 74, None: 0}[fault]
        if completed.returncode != expected:
            raise RuntimeError(completed.stdout + completed.stderr)
        if fault:
            recovered = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--output', str(folder),
                '--worker', 'recover'], cwd=ROOT, capture_output=True, text=True)
            if recovered.returncode:
                raise RuntimeError(recovered.stdout + recovered.stderr)
        outcomes[name] = json.loads((folder / 'result.json').read_text(encoding='utf-8'))
    baseline = outcomes['uninterrupted']
    assert all(value == baseline for value in outcomes.values()), 'Restart changed economic state/decisions'
    report = dict(evidence='FICTIONAL VirtualBroker process test; not paper integration',
        scenarios=3, intentional_process_exits=2, equality=True,
        compared=['targets', 'orders/fills', 'cash', 'positions', 'runtime', 'NAV/high water', 'risk mode'],
        remaining_position_after_partial_gap_exit=baseline['positions'],
        actual_unit_nav=baseline['unit_nav'], foreign_position_untouched=baseline['foreign_position'],
        limitation='Source and fund DBs are recoverably bridged, not a distributed transaction. '
                   'Existing executor manifest cannot be swapped in place. No paper entry is added.')
    (args.output / 'CONTINUITY_REPORT.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
