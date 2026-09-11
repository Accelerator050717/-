"""Check local historical-universe CSVs; default runs a public ATVI event case.

No downloads, fitting, market-price reads or broker calls. An optional vendor
package is read locally and only aggregate counts/hashes are written to stdout.
"""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys

import pandas as pd

from historical_universe import (load_package, membership_asof, eligibility_asof,
    combined_return, TerminalLedger, sha)

ROOT = Path(__file__).resolve().parent
OUT = ROOT/'data/experiments/universe_delisting_v9'
FIXTURE = ROOT/'data/fixtures/universe_delisting_v9'
PUBLIC = ROOT/'data/reference/universe_events/atvi_2023'


def save(name, value):
    (OUT/name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def inspect_package(path, universe, asof):
    meta, memberships, events = load_package(path)
    state = eligibility_asof(memberships, events, universe, asof)
    return dict(evidence_kind=meta['evidence_kind'],coverage_scope=meta['coverage_scope'],
        asof=asof,membership_rows=len(memberships),security_event_rows=len(events),
        known_member_count=sum(r['member'] for r in state.values()),
        eligible_count=sum(r['can_open'] for r in state.values()),
        full_universe_validated=False,training_ready=False,prices_2026_accessed=False,
        input_sha256=meta['file_sha256'])


def run_examples():
    OUT.mkdir(parents=True, exist_ok=True)
    fixture_meta, members, events = load_package(FIXTURE)
    public_meta, public_members, public_events = load_package(PUBLIC)
    identity = dict(schema_version=1,
        source_sha256={name:sha(ROOT/name) for name in ('historical_universe.py', '46_check_historical_universe.py')},
        input_sha256={str(p.relative_to(ROOT)):sha(p) for folder in (FIXTURE, PUBLIC)
                      for p in sorted(folder.iterdir()) if p.is_file()})
    identity_path = OUT/'INPUT_IDENTITY.json'
    if identity_path.exists():
        if json.loads(identity_path.read_text(encoding='utf-8')) != identity:
            raise ValueError('Completed example identity changed; preserve this directory and use a new experiment')
        if (OUT/'completion.json').exists():
            print('Saved examples and source hashes match; no example results rewritten.')
            return
    save('INPUT_IDENTITY.json', identity)

    synthetic = []
    for day in range(2, 7):
        asof = f'2023-10-{day:02}T23:59:59-04:00'
        state = eligibility_asof(members, events, 'SIM_INDEX', asof)
        synthetic.append(dict(asof=asof,eligible_count=sum(r['can_open'] for r in state.values()),
                              eligible_ids=';'.join(s for s,r in state.items() if r['can_open'])))
    assert [r['eligible_count'] for r in synthetic] == [2,2,3,2,1]
    pd.DataFrame(synthetic).to_csv(OUT/'synthetic_membership_timeline.csv', index=False)
    ledger = TerminalLedger('2023-10-02T16:00:00-04:00', {'SIM_A':10,'SIM_B':5}, '1000')
    before_payment = ledger.apply(events, '2023-10-06T16:00:00-04:00')
    assert before_payment['receivable_cash'] == '500' and before_payment['available_cash'] == '1000'
    ledger.settle('sim_a_cash',500,'SIM_PAYMENT','2023-10-06T10:00:00-04:00','2023-10-06T16:00:00-04:00')
    ledger.settle('sim_a_cash',500,'SIM_PAYMENT','2023-10-06T10:00:00-04:00','2023-10-06T16:00:00-04:00')
    assert ledger.snapshot()['available_cash'] == '1500' and ledger.snapshot()['unresolved'] == ['SIM_B']
    save('SYNTHETIC_LEDGER.json', dict(evidence='All events, positions and payment are invented',
        before_payment=before_payment,after_payment=ledger.snapshot(),state=ledger.to_state()))

    public_ledger = TerminalLedger('2023-10-12T16:00:00-04:00', {'PUBLIC_ATVI_COMMON_2023':10})
    timeline = []
    for asof in ('2023-10-13T16:00:00-04:00','2023-10-13T23:59:59-04:00',
                 '2023-10-16T09:30:00-04:00','2023-10-18T09:30:00-04:00'):
        membership = membership_asof(public_members, 'SP500_PARTIAL_CASE', asof)
        state = eligibility_asof(public_members, public_events, 'SP500_PARTIAL_CASE', asof)
        snapshot = public_ledger.apply(public_events, asof)
        item = state.get('PUBLIC_ATVI_COMMON_2023', {})
        timeline.append(dict(asof=asof,member=membership.get('PUBLIC_ATVI_COMMON_2023'),
            can_open=item.get('can_open',False),trading_status=item.get('trading_status','unknown'),
            shares=snapshot['holdings']['PUBLIC_ATVI_COMMON_2023'],
            receivable_cash=snapshot['receivable_cash'],available_cash=snapshot['available_cash']))
    assert timeline[2]['member'] and not timeline[2]['can_open']
    assert not timeline[3]['member'] and timeline[3]['receivable_cash'] == '950'
    assert all(row['available_cash'] == '0' for row in timeline)
    saved = public_ledger.to_state()
    restored = TerminalLedger(**json.loads(json.dumps(saved)))
    restored.apply(public_events, timeline[-1]['asof'])
    assert restored.to_state() == saved
    pd.DataFrame(timeline).to_csv(OUT/'atvi_event_timeline.csv', index=False)
    save('ATVI_LEDGER.json', dict(evidence='Official event facts; 10 qualifying common shares are hypothetical',
        share_count_is_fictitious=True,real_account=False,payment_proven=False,
        snapshot=public_ledger.snapshot(),state=public_ledger.to_state(),sources=public_meta['sources']))
    save('RETURN_CONVENTIONS.json',dict(evidence='Invented return arithmetic only, no strategy performance',
        regular='-0.10',separate_terminal='-0.50',combined=str(combined_return('-.1','-.5','separate')),
        inclusive=str(combined_return('-.55',None,'already_included')),
        missing_terminal=combined_return('-.1',None,'separate')))
    probe = dict(checked_at_utc=datetime.now(timezone.utc).isoformat(),python=sys.version,executable=sys.executable,
        installed={name:importlib.util.find_spec(name) is not None for name in ('wrds','norgatedata')},
        updater_standard_paths={p:Path(p).exists() for p in ('C:/Program Files/Norgate Data','C:/Program Files (x86)/Norgate Data')},
        user_confirmation='No current subscription; complete local input boundary first',
        vendor_session_verified=False)
    save('ENVIRONMENT.json', probe)
    completion = dict(completed_at_utc=datetime.now(timezone.utc).isoformat(),
        public_event_case_passed=True,hypothetical_atvi_shares=10,receivable_usd='950',available_cash_usd='0',
        actual_broker_payment_verified=False,synthetic_group_sizes=[r['eligible_count'] for r in synthetic],
        restore_did_not_duplicate_cash_right=True,new_fits=0,new_strategy_backtests=0,new_trades=0,
        prices_2026_accessed=False,full_historical_universe_acquired=False,survivorship_bias_resolved=False,
        current_strategy_decision='REJECT_NO_2026',
        blocker='No licensed historical universe/delisting dataset; public case cannot establish full coverage',
        source_sha256=identity['source_sha256'])
    save('completion.json', completion)
    print(json.dumps(completion, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package',type=Path,help='Local canonical CSV package; no vendor API calls')
    parser.add_argument('--universe',help='Universe identifier present in memberships.csv')
    parser.add_argument('--asof',help='ISO timestamp with timezone, before 2026')
    args = parser.parse_args()
    if args.package:
        if not args.universe or not args.asof:
            parser.error('--package requires --universe and --asof')
        print(json.dumps(inspect_package(args.package,args.universe,args.asof),ensure_ascii=False,indent=2))
    else:
        if args.universe or args.asof:
            parser.error('Use --package with --universe/--asof')
        run_examples()


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
