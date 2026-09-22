"""Acquire fixed, public v14 primary documents. Full bytes stay private/local.

No prices, accounts, credentials or requests outside the listed historical URLs.
This is an evidence snapshot, not a market-data ingestion or return estimator.
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data/experiments/historical_data_sample_v14'
RAW = ROOT / 'data/private/universe/v14_public_sources'
SOURCES = {
    'twtr_merger_8k': 'https://www.sec.gov/Archives/edgar/data/1418091/000119312522272772/d411753d8k.htm',
    'twtr_merger_index': 'https://www.sec.gov/Archives/edgar/data/1418091/000119312522272772/0001193125-22-272772-index.htm',
    'twtr_merger_issuer_pdf': 'https://d18rn0p25nwr6d.cloudfront.net/CIK-0001418091/84881052-8f1d-4857-bda8-2fdb55ebce68.pdf',
    'sivb_halt': 'https://www.nasdaq.com/press-release/nasdaq-halts-svb-financial-group-2023-03-10',
    'sivb_halt_ir_pdf': 'https://ir.nasdaq.com/node/105986/pdf',
    'sivb_sp500_removal': 'https://press.spglobal.com/2023-03-10-Insulet-Set-to-Join-S-P-500',
    'sivb_delisting_notice': 'https://ir.nasdaq.com/news-releases/news-release-details/delisting-securities-pingtan-marine-enterprise-ltd-srax-inc-svb',
    'sivb_otc_symbol': 'https://infomemo.theocc.com/infomemos?number=52179',
    'sivb_bankruptcy_8k': 'https://www.sec.gov/Archives/edgar/data/719739/000119312523073665/d485308d8k.htm',
    'sivb_bankruptcy_index': 'https://www.sec.gov/Archives/edgar/data/719739/000119312523073665/0001193125-23-073665-index.htm',
    'sivb_bankruptcy_issuer_pdf': 'https://d3ka4b6b7wffw2.cloudfront.net/0000719739/100117344648/6b5387e3-4751-4215-92be-35d1c762970c.pdf',
    'sivb_cancellation_8k': 'https://www.sec.gov/Archives/edgar/data/719739/000119312524254186/d904756d8k.htm',
    'sivb_cancellation_index': 'https://www.sec.gov/Archives/edgar/data/719739/000119312524254186/0001193125-24-254186-index.htm',
    'sivb_sp500_addition': 'https://www.spglobal.com/spdji/en/documents/indexnews/announcements/20180309-675150/675150_idesshuf18nktr.pdf',
    'twtr_sp500_removal': 'https://press.spglobal.com/2022-10-27-Arch-Capital-Group-Set-to-Join-S-P-500-RXO-to-Join-S-P-MidCap-400-Bread-Financial-Holdings-to-Join-S-P-SmallCap-600',
    'twtr_nyse_delisting': 'https://www.sec.gov/Archives/edgar/data/876661/000087666122000890/ruleprovisionnotice.htm',
    'twtr_occ_cash': 'https://infomemo.theocc.com/infomemos?number=51250',
    'twtr_sp500_addition': 'https://www.spglobal.com/spdji/en/documents/indexnews/announcements/20180604-719152/719152_nflx1twtr5rgnx6.pdf',
    'sivb_cancellation_issuer_pdf': 'https://d18rn0p25nwr6d.cloudfront.net/CIK-0000719739/d6ba0fc4-dbb4-4689-9d00-efe5318f4743.pdf',
    'sivb_sp500_addition_html': 'https://press.spglobal.com/2018-03-09-Take-Two-Interactive-Software-SVB-Financial-and-Nektar-Pharmaceuticals-Set-to-Join-S-P-500-Others-to-Join-S-P-MidCap-400-and-S-P-SmallCap-600',
    'twtr_sp500_addition_html': 'https://press.spglobal.com/2018-06-04-Netflix-Set-to-Join-S-P-100-Twitter-to-Join-S-P-500-REGENXBIO-to-Join-S-P-SmallCap-600',
    'sivb_form25_index': 'https://www.sec.gov/Archives/edgar/data/719739/000135445723000327/0001354457-23-000327-index.htm',
    'sivb_form25_reason': 'https://www.sec.gov/Archives/edgar/data/719739/000135445723000327/sivbdelistreason.txt',
    'sivb_sec_submissions': 'https://data.sec.gov/submissions/CIK0000719739.json',
    'twtr_sec_submissions': 'https://data.sec.gov/submissions/CIK0001418091.json',
}


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    manifest_path = OUT / 'terminal_http_sources.json'
    rows = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else []
    # The public SEC submissions service was acquired independently after the
    # archival HTML endpoint rejected the request. Preserve original snapshots.
    for source in RAW.glob('*_sec_submissions.metadata.json'):
        meta = json.loads(source.read_text(encoding='utf-8'))
        if not any(r['source_id'] == meta['source_id'] for r in rows):
            rows.append(meta)
    session = requests.Session()
    session.headers['User-Agent'] = 'QuantML public historical data research'
    for source_id, url in SOURCES.items():
        old = next((r for r in rows if r['source_id'] == source_id), None)
        if old:
            if old['local_path'] is None:
                continue
            p = ROOT / old['local_path']
            if hashlib.sha256(p.read_bytes()).hexdigest() != old['sha256']:
                raise ValueError(f'Changed snapshot: {source_id}')
            continue
        retrieved = datetime.now(timezone.utc).isoformat()
        try:
            r = session.get(url, timeout=20)
        except requests.RequestException as exc:
            rows.append({'source_id': source_id, 'url': url,
                         'retrieved_at_utc': retrieved, 'http_status': None,
                         'body_status': type(exc).__name__, 'local_path': None,
                         'bytes': 0, 'sha256': None,
                         'raw_redistribution': 'not_authorized_no_Git_upload'})
            manifest_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
            print(source_id, type(exc).__name__, flush=True)
            continue
        suffix = '.pdf' if r.content.startswith(b'%PDF') else '.json' if 'application/json' in r.headers.get('Content-Type', '') else '.html'
        path = RAW / (source_id + suffix)
        if path.exists():
            raise FileExistsError(path)
        path.write_bytes(r.content)
        row = {'source_id': source_id, 'url': url, 'resolved_url': r.url,
               'retrieved_at_utc': retrieved, 'http_status': r.status_code,
               'content_type': r.headers.get('Content-Type'),
               'source_snapshot': 'retrieved_now_not_contemporaneous_vendor_snapshot',
               'body_status': 'downloaded' if r.ok else 'access_error_not_source_evidence',
               'local_path': path.relative_to(ROOT).as_posix(), 'bytes': len(r.content),
               'sha256': hashlib.sha256(r.content).hexdigest(),
               'raw_redistribution': 'not_authorized_no_Git_upload'}
        rows.append(row)
        manifest_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        print(source_id, r.status_code, len(r.content), flush=True)


if __name__ == '__main__':
    main()
