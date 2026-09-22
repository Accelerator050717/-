"""Fixed historical public evidence; full documents remain ignored/local.

No market API, credentials, 2026 observations, models or orders.
Reruns verify saved bytes and never overwrite a retrieved source version.
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
    'tsla_announcement': 'https://press.spglobal.com/2020-11-16-Tesla-Set-to-Join-S-P-500?asPDF=1',
    'tsla_implementation': 'https://www.spglobal.com/spdji/en/documents/index-news-and-announcements/20201130-spdji-announces-implementation-of-tesla-s-addition-to-sp500.pdf',
    'tsla_implementation_press': 'https://press.spglobal.com/2020-11-30-S-P-Dow-Jones-Indices-Announces-Implementation-of-Teslas-Addition-to-S-P-500?asPDF=1',
    'meta_ticker': 'https://s21.q4cdn.com/399680738/files/doc_news/Meta-Platforms-Inc.-to-Change-Ticker-Symbol-to-META-on-June-9-2022.pdf',
    'aapl_2024_10k': 'https://s2.q4cdn.com/470004039/files/doc_earnings/2024/q4/filing/10-Q4-2024-As-Filed.pdf',
}


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    manifest = OUT / 'identity_http_sources.json'
    rows = json.loads(manifest.read_text(encoding='utf-8')) if manifest.exists() else []
    for key, url in SOURCES.items():
        old = next((r for r in rows if r['source_id'] == key), None)
        if old:
            if old['local_path'] and old['sha256'] != hashlib.sha256((ROOT / old['local_path']).read_bytes()).hexdigest():
                raise ValueError('Saved evidence changed: '+key)
            continue
        obtained = datetime.now(timezone.utc).isoformat()
        try:
            response = requests.get(url, timeout=20, headers={'User-Agent': 'QuantML historical public document research'})
        except requests.RequestException as exc:
            rows.append(dict(source_id=key, url=url, retrieved_at_utc=obtained,
                             http_status=None, body_status=type(exc).__name__,
                             local_path=None, bytes=0, sha256=None,
                             raw_redistribution='not_authorized_no_Git_upload'))
            manifest.write_text(json.dumps(rows, indent=2)+'\n', encoding='utf-8')
            print(key, type(exc).__name__, flush=True)
            continue
        suffix = '.pdf' if response.content.startswith(b'%PDF') else '.html'
        path = RAW / (key + suffix)
        if path.exists():
            raise FileExistsError(path)
        path.write_bytes(response.content)
        rows.append(dict(source_id=key, url=url, resolved_url=response.url,
                         retrieved_at_utc=obtained, http_status=response.status_code,
                         content_type=response.headers.get('Content-Type'),
                         local_path=path.relative_to(ROOT).as_posix(), bytes=len(response.content),
                         sha256=hashlib.sha256(response.content).hexdigest(),
                         body_status='downloaded' if response.ok else 'access_error_not_source_evidence',
                         source_snapshot='retrieved_now_not_contemporaneous_vendor_snapshot',
                         raw_redistribution='not_authorized_no_Git_upload'))
        manifest.write_text(json.dumps(rows, indent=2)+'\n', encoding='utf-8')
        print(key, response.status_code, len(response.content), flush=True)


if __name__ == '__main__':
    main()
