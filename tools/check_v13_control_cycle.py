"""Write a separate FICTIONAL proof for automatic close/open fund-risk control."""
import argparse
from dataclasses import asdict
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from h60_execution import ExecutionConfig, H60Executor, VirtualBroker, digest
from h60_fund_risk_bridge import FundRiskBridge
from h60_fund_control_cycle import FundControlCycle
from profit_priority_strategy import DrawdownState
from strategy_fund_journal import FundJournal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path,
        default=ROOT / 'data/experiments/continuous_fund_risk_v13/engineering/automatic_control')
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit('Preserve existing proof; select a new output directory')
    args.output.mkdir(parents=True)
    days, day = [], datetime(2025, 1, 6)
    while len(days) < 60:
        if day.weekday() < 5:
            days.append(day.date().isoformat())
        day += timedelta(days=1)
    def time(index, close=False):
        return datetime.fromisoformat(days[index] + ('T21:00:00+00:00' if close else 'T14:30:00+00:00'))
    def quote(index, price):
        return {'AAPL': dict(bid=price, ask=price, asof=time(index).isoformat(),
            basis='synthetic_unadjusted_quote', regular_session=True,
            quantity_step_confirmed=True, corporate_action_pending=False)}
    scope = dict(scope_id='fictional-automatic-control', owner='v13-fixture', currency='USD',
                 universe=['AAPL'], execution_strategy_id='h60-v8-engineering')
    manifest = dict(calendar=days, observations=days[:-1], symbols=['AAPL'],
                    strategy_id='h60-v8-engineering', budget='10000')
    client = H60Executor(args.output / 'execution.sqlite', ExecutionConfig(), digest(manifest), ['AAPL'])
    broker = VirtualBroker(args.output / 'broker.sqlite')
    fund = FundJournal.create(args.output / 'fund.sqlite', scope, '10000', time(0).isoformat())
    try:
        bridge = FundRiskBridge(client, fund, broker, run_id='fictional-first-process')
        cycle = FundControlCycle(bridge, runtime_manifest=manifest)
        cycle.initialize(time(0), {'AAPL': '100'})
        key = bridge.plan_targets('entry', {'AAPL': .9}, quote(0, '100'), time(0))[0]
        bridge.submit_virtual(key, quote(0, '100'), time(0))
        quantity = client.journal.read()['orders'][key]['state']['quantity']
        broker.fill(key, quantity, 100, time(0), execution_id='FICTIONAL-ENTRY')
        episode = asdict(DrawdownState())
        client.save_runtime(dict(drawdown=episode))
        transitions = [cycle.close(days[0], time(0, True), {'AAPL': '88'}),
                       cycle.close(days[1], time(1, True), {'AAPL': '77'})]
        before_count = len(broker.journal.read()['orders'])
        client.journal.close()
        fund.close()
        client = H60Executor(args.output / 'execution.sqlite', ExecutionConfig(), digest(manifest), ['AAPL'])
        fund = FundJournal(args.output / 'fund.sqlite', scope)
        bridge = FundRiskBridge(client, fund, broker, run_id='fictional-restarted-process')
        cycle = FundControlCycle(bridge, runtime_manifest=manifest)
        repeated = cycle.close(days[1], time(1, True), {'AAPL': '77'})
        assert repeated == transitions[-1]
        bridge.require_ready(increasing_risk=False)
        transitions.append(cycle.resume_open(days[23], time(23), {'AAPL': '77'},
            trend_observation=days[22], trend=True, episode_input=episode))
        assert not transitions[-1]['resumed'] and len(broker.journal.read()['orders']) == before_count
        # Only this fixture explicitly creates/fills a virtual liquidation order.
        # The control cycle never sends it or pretends it has already filled.
        bridge.sync(time(24), {'AAPL': '77'})
        sell = bridge.plan_targets('exit', {'AAPL': 0.}, quote(24, '77'), time(24), reduction=True)[0]
        bridge.submit_virtual(sell, quote(24, '77'), time(24))
        broker.fill(sell, quantity, 77, time(24), execution_id='FICTIONAL-EXIT')
        after_count = len(broker.journal.read()['orders'])
        transitions.append(cycle.resume_open(days[25], time(25), {'AAPL': '77'},
            trend_observation=days[24], trend=True, episode_input=episode))
        transitions.append(cycle.close(days[25], time(25, True), {'AAPL': '77'}))
        assert transitions[-1]['mode'] == 'RECOVERY'
        assert len(broker.journal.read()['orders']) == after_count
        assert all(row['high_water_nav'] == 1. for row in transitions)
        sources = ['h60_fund_control_cycle.py', 'tools/check_v13_control_cycle.py', 'tests/test_v13_control_cycle.py']
        report = dict(evidence='FICTIONAL VirtualBroker engineering only; no paper/live orders',
            closes_observe_only=True, opens_resume_only=True, old_foundation_evidence_unchanged=True,
            restart_repeated_close_identical=True, controller_generated_orders=0,
            calendar_bound_to_execution_manifest=True,
            valuation_boundary='Engineering journal retains all trusted valuation highs; historical experiment uses close highs. '
                               'Normal held-position opens are rejected; no full trading-path equivalence is claimed.',
            fixture_virtual_orders=after_count, high_water_preserved=True,
            outcomes=[dict(day=row['day'], phase=row['phase'], mode=row['mode'],
                unit_nav=row['unit_nav'], high_water_nav=row['high_water_nav'],
                positions=row['positions'], resumed=row['resumed']) for row in transitions],
            source_sha256={name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sources},
            limitations='This closes the previously documented automatic-transition gap only for the offline adapter. '
                        'No real paper entry, company-action adapter, or production model handoff is established.')
        (args.output / 'AUTOMATIC_CONTROL_REPORT.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        (args.output / 'TRANSITIONS.json').write_text(json.dumps(transitions, indent=2), encoding='utf-8')
        (args.output / 'FUND_STATE.json').write_text(json.dumps(fund.read(), indent=2), encoding='utf-8')
        client.export(args.output / 'EXECUTION_STATE.json')
        print(json.dumps(report, indent=2))
    finally:
        client.journal.close()
        broker.journal.close()
        fund.close()


if __name__ == '__main__':
    main()
