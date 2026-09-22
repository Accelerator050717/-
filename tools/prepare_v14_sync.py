"""Inventory only v14 local documents and two reused price snapshots.

No archive of restricted full text, no mutation of older manifests/ignore rules.
"""
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT/'data/experiments/historical_data_sample_v14'
RAW = ROOT/'data/private/universe/v14_public_sources'
OUT = ROOT/'review_upload/sync_v14_20260922'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    sources = [r for name in ('identity_http_sources.json','terminal_http_sources.json')
               for r in json.loads((EXP/name).read_text(encoding='utf-8'))]
    by_path = {r['local_path']:r for r in sources if r.get('local_path')}
    rows = []
    for path in sorted(RAW.iterdir()):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT).as_posix()
        origin = by_path.get(rel,{})
        rows.append(dict(path=rel, absolute_path=str(path), bytes=path.stat().st_size,
            sha256=sha(path), experiment='historical_data_sample_v14',
            status=origin.get('body_status','local_extraction_or_capture_metadata_not_original_download'),
            source_url=origin.get('url','See terminal_source_checks.json and local capture metadata'),
            retrieval_time=origin.get('retrieved_at_utc','See capture metadata; not historical observation time'),
            git_upload=False, reason='Full source/derivative or HTTP error kept local; redistribution not authorized',
            generation_entry='tools/collect_v14_identity_sources.py or tools/collect_v14_terminal_sources.py; PDF derivatives via tools/extract_v14_terminal_pdfs.py',
            verification_entry='.venv/Scripts/python.exe -B 60_check_historical_sample.py --verify-local; this inventory covers extra metadata too',
            recovery='Restore exact hash from local backup; fresh retrieval requires a new version, never overwrite frozen sources'))
    for symbol in ('AAPL','META'):
        for suffix in ('.csv','.json'):
            path = ROOT/'data/raw/extended_2012_2025'/f'{symbol}{suffix}'
            rows.append(dict(path=path.relative_to(ROOT).as_posix(), absolute_path=str(path),
                bytes=path.stat().st_size, sha256=sha(path), experiment='reused_pre_v14_price_input',
                status='existing_2025_and_earlier_observations', source_url='Original adjacent download metadata',
                retrieval_time='2026-09-09 original download; no new market request',
                git_upload=suffix=='.json',reason='Original price snapshot kept local; metadata already tracked',
                generation_entry='Original snapshot retained; no download or retraining in v14',
                verification_entry='.venv/Scripts/python.exe -B tools/check_v14_price_coverage.py',
                recovery='Use existing frozen local snapshot/older review bundle; do not replace with today adjusted history'))
    OUT.mkdir(parents=True,exist_ok=True)
    with (OUT/'local_materials.csv').open('w',encoding='utf-8',newline='') as stream:
        writer = csv.DictWriter(stream,fieldnames=list(rows[0]),lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)
    private_rows = [r for r in rows if r['experiment']=='historical_data_sample_v14']
    report = dict(new_local_document_files=len(private_rows), new_local_document_bytes=sum(r['bytes'] for r in private_rows),
        reused_price_files=4, reused_price_bytes=sum(r['bytes'] for r in rows if r['experiment']!='historical_data_sample_v14'),
        original_http_success=sum(r.get('http_status')==200 for r in sources),
        recorded_http_errors_or_timeouts=sum(r.get('http_status')!=200 for r in sources),
        large_models_or_predictions_generated=0, redistribution_archives_created=0,
        archive_reason='Full-source redistribution not licensed; no raw/normalized vendor data acquired',
        local_material_manifest_sha256=sha(OUT/'local_materials.csv'))
    (OUT/'summary.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
