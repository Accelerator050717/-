"""Read-only verification of real terminal-case snapshots and manual mapping.

Full source snapshots are intentionally local. No network calls or synthetic data.
PDF extracted text is a derivative of the retained PDF, never a replacement for it.
"""
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data/experiments/historical_data_sample_v14'
RAW = ROOT / 'data/private/universe/v14_public_sources'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    sources = json.loads((OUT / 'terminal_http_sources.json').read_text(encoding='utf-8'))
    facts = json.loads((OUT / 'terminal_source_facts.json').read_text(encoding='utf-8'))
    checks = []
    private_files = []
    for row in sources:
        if row['local_path'] is not None:
            path = ROOT / row['local_path']
            assert path.stat().st_size == row['bytes']
            assert sha(path) == row['sha256'], row['source_id']
            private_files.append({**row, 'verified_sha256': True})
    for name in ['sivb_web_extraction.json', 'twtr_sivb_web_extraction.json']:
        path = RAW / name
        row = json.loads(path.read_text(encoding='utf-8'))
        assert row['capture_kind'] == 'web_tool_extraction_not_original_HTTP_bytes'
        private_files.append({'source_id': path.stem, 'local_path': path.relative_to(ROOT).as_posix(),
                              'bytes': path.stat().st_size, 'sha256': sha(path),
                              'retrieved_at_utc': row['retrieved_at_utc'],
                              'body_status': 'web_tool_extraction_not_original_HTTP_bytes',
                              'raw_redistribution': 'not_authorized_no_Git_upload'})
    for case, cik, accession in [('sivb', '0000719739', '0001193125-24-254186'),
                                  ('twtr', '0001418091', '0001193125-22-272772')]:
        data = json.loads((RAW / f'{case}_sec_submissions.json').read_text(encoding='utf-8'))
        assert str(data['cik']).zfill(10) == cik
        table = data['filings']['recent']
        i = table['accessionNumber'].index(accession)
        checks.append({'check': 'actual_sec_identity_and_filing', 'case': case,
                       'cik': cik, 'accession': accession, 'filing_date': table['filingDate'][i],
                       'raw_acceptance_string': table['acceptanceDateTime'][i],
                       'acceptance_note': 'Retained verbatim, not used as verified first public dissemination time',
                       'status': 'PASS'})
    tokens = {
        'sivb_halt.html': ['08:35:18', '106.04', '4:45pm EST'],
        'sivb_sp500_removal.html': ['March 15', 'March 10, 2023', 'SVB Financial Group'],
        'sivb_sp500_addition_html.html': ['March 19', 'March 9, 2018', 'SVB Financial'],
        'twtr_sp500_addition_html.html': ['June 7', 'June 4, 2018', 'Twitter'],
        'twtr_sp500_removal.html': ['November 1', 'Oct. 27, 2022', 'Twitter'],
        'sivb_web_extraction.json': ['78486Q101', 'May 12, 2023', 'March 28, 2023'],
        'twtr_sivb_web_extraction.json': ['November 08, 2022', '0.001', '54.20'],
    }
    for filename, expected in tokens.items():
        text = (RAW / filename).read_text(encoding='utf-8', errors='replace')
        # HTML formatting can split date tokens across spans; normalize tags.
        normalized = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', text))
        for token in expected:
            assert token in normalized, (filename, token)
        checks.append({'check': 'actual_source_field_tokens', 'file': filename, 'status': 'PASS'})
    # These text derivatives were extracted from the downloaded PDF by pypdf.
    for filename, expected in {
        'twtr_merger_issuer_pdf.pdf.extracted.txt': ['October 27, 2022', '$54.20'],
        'sivb_cancellation_issuer_pdf.pdf.extracted.txt': [
            'November 7, 2024', 'No holders of Common Equity Interests', 'received any distributions'],
    }.items():
        path = RAW / filename
        text = path.read_text(encoding='utf-8')
        for token in expected:
            assert token in text, (filename, token)
        private_files.append({'source_id': filename, 'local_path': path.relative_to(ROOT).as_posix(),
                              'bytes': path.stat().st_size, 'sha256': sha(path),
                              'body_status': 'pypdf_extraction_derivative_original_pdf_retained',
                              'raw_redistribution': 'not_authorized_no_Git_upload'})
        checks.append({'check': 'actual_pdf_fields', 'file': filename, 'status': 'PASS'})
    for row in facts['membership_facts'] + facts['lifecycle_facts']:
        for field in ('effective_at', 'available_at'):
            assert datetime.fromisoformat(row[field]) < datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert row['effective_at'] != row['available_at'], row['event_id']
    changes = {r['kind']: r for r in facts['lifecycle_facts'] if r['case'] == 'SIVB_SIVBQ'}
    assert len({changes[k]['effective_date'] for k in ('halt', 'exchange_delisting', 'common_equity_cancelled_no_distribution')}) == 3
    assert changes['common_equity_cancelled_no_distribution']['amount_status'].startswith('explicit_no_distribution')
    assert changes['common_equity_cancelled_no_distribution']['terminal_total_return'] is None
    checks.append({'check': 'event_type_date_and_information_boundaries', 'status': 'PASS'})
    report_path = OUT / 'terminal_source_checks.json'
    previous = json.loads(report_path.read_text(encoding='utf-8')) if report_path.exists() else None
    # Preserve generation time. A later read-only verification (or normal Git
    # commit) must not rewrite an input hash consumed by the acceptance checker.
    report = {'checked_at_utc': previous['checked_at_utc'] if previous else datetime.now(timezone.utc).isoformat(),
              'facts_sha256': sha(OUT / 'terminal_source_facts.json'),
              'checks': checks, 'private_files': private_files,
              'http_downloaded_source_count': sum(r['http_status'] == 200 for r in sources),
              'http_access_error_or_timeout_count': sum(r['http_status'] != 200 for r in sources),
              'format_field_status': 'PASS_WITH_DOCUMENTED_SOURCE_CONFLICTS',
              'strict_point_in_time_snapshot_status': 'NOT_PROVEN',
              'return_research_sufficiency': 'INSUFFICIENT', 'complete_universe_coverage': False,
              'trains': 0, 'backtests': 0, 'broker_connections': 0, 'orders': 0}
    if previous is not None:
        if previous != report:
            raise ValueError('Frozen terminal evidence changed; preserve it and use a new snapshot version')
    else:
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ['checks','private_files']},indent=2))


if __name__ == '__main__':
    main()
