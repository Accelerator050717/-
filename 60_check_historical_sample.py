"""Offline acceptance of v14 public cases through the unchanged v9 boundary.

--write creates immutable check outputs; default verifies them after any normal
Git commit. --verify-local additionally hashes private source/price snapshots.
No downloads, fitting, return backtest or broker imports.
"""
import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess

from historical_universe import (TerminalLedger, eligibility_asof, instant,
                                  load_package, membership_asof, sha)
from tools.build_v14_public_sample import IDS, PACKAGE, UNIVERSE, csv_bytes, preserve

ROOT = Path(__file__).resolve().parent
OUT = ROOT/'data/experiments/historical_data_sample_v14'
ATVI = ROOT/'data/reference/universe_events/atvi_2023'
BASE = 'a8cf66223c0d88b3d78dada3ff3f355c6eaf8730'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def ticker_asof(changes, security_id, asof):
    """Only resolve this case's alias once its dated information is available.

    A bare ticker is never used as a join key. This tiny side-table function is
    not a full map-file implementation or proof of an unbroken listing history.
    """
    rows = [r for r in changes if r['security_id'] == security_id]
    if len(rows) > 1:
        raise ValueError('Multiple mapping versions need an explicit revision protocol')
    if not rows or not rows[0].get('available_at'):
        return None
    row = rows[0]
    if instant(asof) < instant(row['available_at']):
        return None
    return row['old_ticker'] if instant(asof) < instant(row['effective_at']) else row['new_ticker']


def case_checks():
    meta, members, events = load_package(PACKAGE)
    for name, expected in meta['side_file_sha256'].items():
        if sha(PACKAGE/name) != expected:
            raise ValueError('Side table changed: '+name)
    for name, expected in meta['original_fact_sha256'].items():
        if sha(OUT/name) != expected:
            raise ValueError('Original source facts changed: '+name)
    securities, changes, lifecycle = [read(PACKAGE/n) for n in
                                      ('securities.json','ticker_changes.json','lifecycle.json')]
    assert len({r['security_id'] for r in securities}) == len(securities) == 5
    assert {r['security_id'] for r in securities} == set(IDS.values())
    assert all(r['security_id'] in IDS.values() for r in members+events+changes+lifecycle)
    timeline = []
    cases = [
        ('TSLA','before_announcement','2020-11-13T16:00:00-05:00',None),
        ('TSLA','announced_not_effective','2020-12-01T09:30:00-05:00',False),
        ('TSLA','effective','2020-12-21T09:30:00-05:00',True),
        ('SIVB_SIVBQ','before_removal_announcement','2023-03-09T16:00:00-05:00',True),
        ('SIVB_SIVBQ','announced_not_effective','2023-03-13T09:30:00-04:00',True),
        ('SIVB_SIVBQ','removed','2023-03-15T09:30:00-04:00',False),
        ('TWTR','before_removal_announcement','2022-10-26T16:00:00-04:00',True),
        ('TWTR','announced_not_effective','2022-10-31T09:30:00-04:00',True),
        ('TWTR','removed','2022-11-01T09:30:00-04:00',False),
        ('AAPL','missing_membership','2025-12-31T16:00:00-05:00',None),
        ('META_FB','missing_membership','2025-12-31T16:00:00-05:00',None),
    ]
    for case, phase, asof, expected in cases:
        result = membership_asof(members, UNIVERSE, asof).get(IDS[case])
        eligibility = eligibility_asof(members, events, UNIVERSE, asof).get(IDS[case], {})
        assert result is expected, (case, phase, result, expected)
        assert not eligibility.get('can_open', False)
        timeline.append(dict(case=case, phase=phase, asof=asof,
            member='unknown' if result is None else str(result).lower(),
            trading_status=eligibility.get('trading_status','unknown'), can_open=False))
    # A true historical survivor of the event stream must not vanish merely
    # because a later row says removed. This is partial-stream, not full-index proof.
    assert membership_asof(members, UNIVERSE, '2020-01-02T16:00:00-05:00')[IDS['SIVB_SIVBQ']]
    assert not eligibility_asof(members, events, UNIVERSE,
                               '2023-03-13T16:00:00-04:00')[IDS['SIVB_SIVBQ']]['can_open']
    mapping_cases = [
        ('META_FB','2022-05-30T16:00:00-04:00',None),
        ('META_FB','2022-06-08T16:00:00-04:00','FB'),
        ('META_FB','2022-06-09T09:30:00-04:00','META'),
        ('SIVB_SIVBQ','2023-03-27T16:00:00-04:00',None),
        ('SIVB_SIVBQ','2023-03-28T08:00:00-04:00','SIVB'),
        ('SIVB_SIVBQ','2023-03-28T09:30:00-04:00','SIVBQ'),
    ]
    mappings = []
    for case, asof, expected in mapping_cases:
        actual = ticker_asof(changes, IDS[case], asof)
        assert actual == expected
        mappings.append(dict(case=case, security_id=IDS[case], asof=asof, ticker=actual))
    assert ticker_asof(changes,'new-reorganization-equity-not-old-common',
                       '2025-01-02T16:00:00-05:00') is None
    try:
        ticker_asof(changes+[deepcopy(changes[0])], IDS['META_FB'], '2022-06-10T16:00:00-04:00')
    except ValueError:
        conflict_rejected = True
    else:
        raise AssertionError('Conflicting source versions were silently accepted')
    missing = deepcopy(changes)
    missing[0]['available_at'] = None
    assert ticker_asof(missing, IDS['META_FB'], '2022-06-10T16:00:00-04:00') is None
    sivb = [f for f in lifecycle if f['security_id'] == IDS['SIVB_SIVBQ']]
    assert {f['kind'] for f in sivb} == {'halt','exchange_suspension','ticker_and_venue_change',
                                       'exchange_delisting','common_equity_cancelled_no_distribution'}
    assert not any(f['kind'] == 'unknown_terminal' for f in events)
    cancellation = next(f for f in sivb if f['kind'] == 'common_equity_cancelled_no_distribution')
    assert cancellation['entitlement_amount_per_old_common_share'] == '0'
    assert cancellation['v9_mapping'] is None  # explicit unsupported, not a fake cash receipt
    # Real event, hypothetical qualifying ordinary shares; no account payment or
    # purchase price exists. Do not call settle, infer a sale, or compute returns.
    twtr_events = [e for e in events if e['security_id'] == IDS['TWTR']]
    ledger = TerminalLedger('2022-10-26T16:00:00-04:00', {IDS['TWTR']:10})
    before = ledger.apply(twtr_events,'2022-10-28T16:00:00-04:00')
    assert before['holdings'][IDS['TWTR']] == '10' and before['receivable_cash'] == '0'
    after = ledger.apply(twtr_events,'2022-11-01T09:30:00-04:00')
    assert after['holdings'][IDS['TWTR']] == '0' and after['receivable_cash'] == '542.00'
    assert after['available_cash'] == '0' and not ledger.receipts
    state = ledger.to_state()
    restored = TerminalLedger(**json.loads(json.dumps(state)))
    restored.apply(twtr_events, '2022-11-01T09:30:00-04:00')
    assert restored.to_state() == state
    sivb_ledger = TerminalLedger('2023-03-09T16:00:00-05:00', {IDS['SIVB_SIVBQ']:10})
    sivb_ledger.apply([e for e in events if e['security_id']==IDS['SIVB_SIVBQ']],
                      '2024-11-11T16:00:00-05:00')
    assert sivb_ledger.holdings[IDS['SIVB_SIVBQ']] == '10'
    # This retained book quantity is unresolved, NOT evidence shares still exist.
    _, am, ae = load_package(ATVI)
    atvi = TerminalLedger('2023-10-12T16:00:00-04:00', {'PUBLIC_ATVI_COMMON_2023':10})
    aa = atvi.apply(ae, '2023-10-18T09:30:00-04:00')
    assert aa['receivable_cash'] == '950' and aa['available_cash'] == '0'
    assert membership_asof(am,'SP500_PARTIAL_CASE','2023-10-16T09:30:00-04:00')['PUBLIC_ATVI_COMMON_2023']
    identity, terminal = read(OUT/'identity_source_facts.json'), read(OUT/'terminal_source_facts.json')
    facts = identity['facts']+terminal['membership_facts']+terminal['lifecycle_facts']
    missing_date = sum(not (f.get('publication_date') or f.get('published_date')) for f in facts)
    missing_intraday = sum(f.get('published_at') is None for f in facts)
    prices = read(OUT/'PRICE_COVERAGE.json')
    assert prices['format_checks_pass'] and prices['price_snapshots_checked'] == 2
    summary = dict(
        sample_security_count=6, new_security_cases=5, inherited_reference_cases=1,
        observation_start='2020-01-01', observation_end='2025-12-31',
        earlier_baseline_membership_dates=['2018-03-19','2018-06-07'],
        new_membership_change_events=len(members)-1, derived_nonmember_checkpoints=1,
        inherited_atvi_membership_removals=1, new_v9_security_event_rows=len(events),
        lifecycle_side_rows=len(lifecycle), lifecycle_kind_counts=dict(Counter(f['kind'] for f in lifecycle)),
        real_terminal_cases=3, new_terminal_cases=2,
        verified_cash_entitlement_cases=2, unverified_cash_receipt_cases=2,
        unsupported_explicit_zero_distribution_cases=1, unresolved_terminal_return_series_cases=3,
        price_covered_cases=2, price_missing_cases=4, actual_source_conflicts_preserved=2,
        information_evidence=dict(denominator='all 16 new identity/announcement/membership/lifecycle fact records, including unsupported; ATVI reference excluded',
            fact_count=len(facts), missing_publication_date_count=missing_date,
            missing_publication_date_fraction=missing_date/len(facts),
            missing_verified_intraday_timestamp_count=missing_intraday,
            missing_verified_intraday_timestamp_fraction=missing_intraday/len(facts),
            original_vendor_receipt_or_revision_vintage_missing=len(facts)),
        checks=dict(member_timelines=len(timeline), ticker_timelines=len(mappings),
            conflict_rejected=conflict_rejected, missing_mapping_time_blocks=True,
            unknown_membership_or_trade_status_blocks=True, terminal_cash_not_released=True,
            ledger_restore_idempotent=True, old_atvi_reference_unchanged=True),
        verdicts=dict(format_and_local_identity='PASS_WITH_LIMITS: schema/unique local IDs/two alias links; no universal vendor ID or complete issuance history',
            information_time='LIMITED: cited dated event queries only; not complete point-in-time tradability or original vintages',
            return_research='FAIL: four missing price histories, incomplete terminal return linkage, two missing cash receipts, one unsupported cancellation',
            complete_historical_universe='FAIL: partial deliberately selected index events only'),
        new_fits=0, strategy_backtests=0, broker_connections=0, orders=0,
        prices_2026_accessed=False, survivorship_bias_resolved=False, training_ready=False)
    outputs = {
        'CHECKS.json':summary,
        'TICKER_CHECKS.json':mappings,
        'TERMINAL_LEDGER_CHECKS.json':dict(holdings_are_hypothetical=True, actual_account=False,
            twtr=dict(qualifying_shares=10,before_information=before,after_information=after,recovery_state=state,
                      selected_source_boundary='issuer 8-K filing date end; earlier OCC corroboration retained separately'),
            sivb=dict(qualifying_shares=10,legacy_ledger=sivb_ledger.snapshot(),
                source_fact='old common cancelled; no distribution explicitly documented',
                status='UNSUPPORTED_RECONCILIATION_REQUIRED', allow_new_risk=False,
                warning='Ledger quantity is pending reconciliation, not a valid tradable asset or a marked valuation; no return computed'),
            atvi_reference=aa, actual_payment_receipts=0),
    }
    return outputs, timeline


def identity_files():
    names = ['60_check_historical_sample.py','tools/build_v14_public_sample.py',
             'tools/check_v14_price_coverage.py','historical_universe.py','46_check_historical_universe.py']
    paths = [ROOT/n for n in names]+list(PACKAGE.iterdir())+list(ATVI.iterdir())
    paths += [OUT/n for n in ('PLAN.md','plan.json','identity_source_facts.json',
        'terminal_source_facts.json','identity_http_sources.json','terminal_http_sources.json',
        'terminal_source_checks.json','PRICE_COVERAGE.json')]
    return {p.relative_to(ROOT).as_posix():sha(p) for p in sorted(paths) if p.is_file()}


def verify_local():
    rows = read(OUT/'identity_http_sources.json')+read(OUT/'terminal_source_checks.json')['private_files']
    verified = {}
    for row in rows:
        path = row.get('local_path')
        if path:
            p = ROOT/path
            assert sha(p) == row['sha256'], path
            assert p.stat().st_size == row['bytes'], path
            verified[path] = row['sha256']
    for row in read(OUT/'PRICE_COVERAGE.json')['securities']:
        for prefix in ('csv','metadata'):
            path = row[prefix+'_path']
            assert sha(ROOT/path) == row[prefix+'_sha256'], path
            verified[path] = row[prefix+'_sha256']
    return len(verified)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write',action='store_true')
    parser.add_argument('--verify-local',action='store_true')
    args = parser.parse_args()
    plan = read(OUT/'plan.json')
    assert sha(OUT/'PLAN.md') == plan['plan_sha256']
    inputs = identity_files()
    ipath = OUT/'ACCEPTANCE_IDENTITY.json'
    current = subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    if ipath.exists():
        saved = read(ipath)
        if saved['input_sha256'] != inputs:
            raise ValueError('Frozen facts/source/price-summary identity changed, not just Git HEAD')
    elif not args.write:
        raise FileNotFoundError('Run --write once to save the actual acceptance')
    results, timeline = case_checks()
    serialized = {n:json.dumps(v,ensure_ascii=False,indent=2)+'\n' for n,v in results.items()}
    serialized['MEMBERSHIP_CHECKS.csv'] = csv_bytes(list(timeline[0]),timeline)
    for name, text in serialized.items():
        if args.write:
            preserve(OUT/name,text)
        elif (OUT/name).read_bytes() != text.encode('utf-8'):
            raise ValueError('Saved check output differs: '+name)
    if not ipath.exists():
        record = dict(generated_at_utc=datetime.now(timezone.utc).isoformat(),
            base_commit=BASE, generation_git_head=current, input_sha256=inputs,
            output_sha256={n:sha(OUT/n) for n in serialized},
            normal_later_commits_allowed=True, unchanged_source_and_input_hashes_required=True)
        preserve(ipath,json.dumps(record,ensure_ascii=False,indent=2)+'\n')
    else:
        assert all(sha(OUT/n)==h for n,h in saved['output_sha256'].items())
    private_count = verify_local() if args.verify_local else None
    print(json.dumps(dict(status='acceptance_checks_verified', current_review_commit=current,
        generation_commit=read(ipath)['generation_git_head'],
        local_private_and_price_files_verified=private_count, **results['CHECKS.json']),ensure_ascii=False))


if __name__ == '__main__':
    main()
