"""Map the small, actually inspected public facts into the unchanged v9 schema.

This is a fixed case mapping, not a vendor importer or a complete universe.
Raw downloads remain local. Existing normalized outputs must match on rerun.
"""
import csv
import hashlib
import io
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from historical_universe import MEMBERSHIP_COLUMNS, EVENT_COLUMNS, load_package

OUT = ROOT / 'data/experiments/historical_data_sample_v14'
PACKAGE = ROOT / 'data/reference/universe_events/v14_public_sample'
IDS = {
    'AAPL': 'quantml-public:AAPL-common-2024',
    'TSLA': 'quantml-public:TSLA-listed-equity-2020',
    'META_FB': 'quantml-public:META-classA-2012',
    'SIVB_SIVBQ': 'quantml-public:sec-cik-0000719739:common-pre-20241107',
    'TWTR': 'quantml-public:sec-cik-0001418091:common-pre-20221027',
}
UNIVERSE = 'SP500_PARTIAL_PUBLIC_V14'


def read(name):
    return json.loads((OUT/name).read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def preserve(path, content):
    data = content.encode('utf-8')
    if path.exists() and path.read_bytes() != data:
        raise ValueError(f'Existing normalized artifact differs; do not overwrite: {path}')
    if not path.exists():
        path.write_bytes(data)


def csv_bytes(columns, rows):
    buffer = io.StringIO(newline='')
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator='\n')
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def main():
    identity, terminal = read('identity_source_facts.json'), read('terminal_source_facts.json')
    sources = {r['source_id']: r for name in ('identity_http_sources.json', 'terminal_http_sources.json')
               for r in read(name)}
    PACKAGE.mkdir(parents=True, exist_ok=True)
    memberships = []
    for fact in terminal['membership_facts']:
        memberships.append(dict(event_id=fact['event_id'], security_id=IDS[fact['case']],
            universe=UNIVERSE, effective_at=fact['effective_at'], available_at=fact['available_at'],
            member=str(int(fact['member'])), source_id=fact['source_id']))
    confirmed = next(f for f in identity['facts'] if f['fact_id'] == 'tsla_addition_confirmed')
    # A derived nonmember checkpoint at the next regular session after the final
    # announcement. This is NOT a past index deletion or Tesla's listing date.
    memberships += [dict(event_id='tsla_nonmember_checkpoint_20201201', security_id=IDS['TSLA'],
        universe=UNIVERSE, effective_at='2020-12-01T09:30:00-05:00',
        available_at=confirmed['available_at'], member='0', source_id=confirmed['source_id']),
        dict(event_id='tsla_sp500_add_20201221', security_id=IDS['TSLA'], universe=UNIVERSE,
        effective_at=confirmed['effective_at'], available_at=confirmed['available_at'],
        member='1', source_id=confirmed['source_id'])]
    events, side = [], []
    for fact in terminal['lifecycle_facts']:
        mapped = fact['kind'] if fact['kind'] in ('halt', 'cash_entitlement') else None
        side.append(dict(fact, security_id=IDS[fact['case']], v9_mapping=mapped,
                         mapping_status='core' if mapped else 'side_table_only_unsupported'))
        if mapped:
            events.append(dict(event_id=fact['event_id'], security_id=IDS[fact['case']],
                kind=mapped, effective_at=fact['effective_at'], available_at=fact['available_at'],
                cash_per_share=fact.get('cash_per_share', ''), source_id=fact['source_id']))
    meta = next(f for f in identity['facts'] if f['fact_id'] == 'meta_ticker_change')
    side.append(dict(meta, event_id=meta['fact_id'], kind='ticker_change',
                     security_id=IDS['META_FB'], v9_mapping=None, mapping_status='identity_side_table'))
    tickers = [dict(security_id=IDS['META_FB'], old_ticker='FB', new_ticker='META',
        effective_at=meta['effective_at'], available_at=meta['available_at'],
        source_id=meta['source_id'], same_security_basis=meta['same_security_basis']),
        dict(security_id=IDS['SIVB_SIVBQ'], old_ticker='SIVB', new_ticker='SIVBQ',
        **{k: next(f for f in side if f['kind'] == 'ticker_and_venue_change')[k]
           for k in ('effective_at', 'available_at', 'source_id')},
        same_security_basis='OCC memo 52179 retains CUSIP 78486Q101; no price or execution inferred')]
    securities = [dict(case=case, security_id=security,
        id_namespace='quantml-public project-local case identity; not a vendor permanent ID',
        vendor_security_id=None, full_issuance_history_verified=False)
        for case, security in IDS.items()]
    for security in securities:
        case = security['case']
        original = next((f for f in terminal['securities'] if f['case'] == case), None)
        if original:
            security.update({k:v for k,v in original.items() if k not in ('security_id_suggestion','namespace','case')})
        else:
            fid = {'AAPL':'aapl_identity_2024','TSLA':'tsla_addition_confirmed','META_FB':'meta_ticker_change'}[case]
            fact = next(f for f in identity['facts'] if f['fact_id'] == fid)
            security.update({k:fact.get(k) for k in ('issuer','share_class','cusip','source_id')})
            security['identity_limit'] = ('Precise legal share-class ID absent from index notice'
                if case == 'TSLA' else 'Locally named share class; no numeric permanent vendor identifier')
    preserve(PACKAGE/'memberships.csv', csv_bytes(MEMBERSHIP_COLUMNS, memberships))
    preserve(PACKAGE/'events.csv', csv_bytes(EVENT_COLUMNS, events))
    for name, value in [('securities.json', securities), ('ticker_changes.json', tickers), ('lifecycle.json', side)]:
        preserve(PACKAGE/name, json.dumps(value, ensure_ascii=False, indent=2)+'\n')
    used = {r['source_id'] for r in memberships+events}
    manifest = dict(schema_version=1, evidence_kind='public_event_case',
        coverage_scope='Five new project-local security cases; partial S&P500 event stream, not complete membership or trading universe',
        sources={s:sources[s] for s in sorted(used)},
        file_sha256={n:sha(PACKAGE/n) for n in ('memberships.csv','events.csv')},
        side_file_sha256={n:sha(PACKAGE/n) for n in ('securities.json','ticker_changes.json','lifecycle.json')},
        original_fact_sha256={n:sha(OUT/n) for n in ('identity_source_facts.json','terminal_source_facts.json')},
        knowledge_time_policy='Separate dated publication/filing evidence; date-only uses New York day end, not earliest dissemination',
        member_checkpoint='tsla_nonmember_checkpoint_20201201 is a derived next-session state observation, not an index change',
        warnings=['No exhaustive intervening events', 'No vendor permanent IDs',
                  'No proof of historical receipt/vintage; current archive revisions unknown',
                  'Side-table-only events must not be ignored for trading: unresolved scope stays blocked',
                  'AAPL/META membership unknown; TSLA core trade status unknown',
                  'ATVI old v9 package is checked separately and never rewritten'],
        full_universe_validated=False, training_ready=False, prices_2026_accessed=False)
    preserve(PACKAGE/'manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
    _, m, e = load_package(PACKAGE)
    print(json.dumps({'new_local_security_ids':len(securities), 'membership_rows':len(m),
        'actual_membership_changes':len(m)-1, 'v9_security_events':len(e),
        'side_lifecycle_facts':len(side), 'training_ready':False}))


if __name__ == '__main__':
    main()
