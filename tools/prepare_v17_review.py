"""Inventory only v17 reviewable materials; preserve original experiments."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / 'data/experiments/adaptive_strategy_research_v17'
DEST = ROOT / 'review_upload/sync_v17_20261002'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def collect():
    with (EXP/'local_prototype/LARGE_ARTIFACTS.csv').open(encoding='utf-8', newline='') as stream:
        bulky = list(csv.DictReader(stream))
    excluded = {row['relative_path'] for row in bulky}
    for row in bulky:
        path = ROOT/row['relative_path']
        assert path.stat().st_size == int(row['size_bytes']) and digest(path) == row['sha256'], path
    candidates = set(EXP.rglob('*'))
    candidates.update((ROOT/'tools').glob('*v17*.py'))
    candidates.update((ROOT/'tests').glob('*v17*.py'))
    candidates.update([ROOT/'README.md', ROOT/'REVIEW_INDEX.md', ROOT/'.gitignore', DEST/'README.md'])
    files = []
    for path in sorted(candidates):
        rel = path.relative_to(ROOT).as_posix()
        if not path.is_file() or '__pycache__' in path.parts or rel in excluded:
            continue
        assert path.stat().st_size < 10*1024*1024, f'Unreviewed large file: {rel}'
        files.append(dict(path=rel, bytes=path.stat().st_size, sha256=digest(path)))
    return dict(baseline_commit='de51b46adf082a7708701cd2a209d44ade83fa8d',
                tracked_material=files, total_bytes=sum(r['bytes'] for r in files),
                excluded_local_material=bulky,
                local_bundle=json.loads((EXP/'local_prototype/ZIP_MANIFEST.json').read_text(encoding='utf-8')),
                supplier_raw_data='No new raw data exported; existing Yahoo inputs remain at original paths; QC data cloud only')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify', action='store_true')
    parser.add_argument('--add-exclusions', action='store_true')
    args = parser.parse_args()
    if args.add_exclusions:
        if args.verify:
            raise ValueError('Verification cannot mutate ignore rules')
        with (EXP/'local_prototype/LARGE_ARTIFACTS.csv').open(encoding='utf-8', newline='') as stream:
            lines = ['/'+r['relative_path'] for r in csv.DictReader(stream)]
        ignore = ROOT/'.gitignore'
        existing = ignore.read_bytes()
        present = set(existing.decode('utf-8').splitlines())
        additions = [line for line in lines if line not in present]
        if additions:
            with ignore.open('ab') as stream:
                stream.write(('\n# v17 local model/prediction/trade bundle; see local_prototype/LARGE_ARTIFACTS.csv\n'
                              +'\n'.join(additions)+'\n').encode())
    payload = collect()
    path = DEST/'files.json'
    if args.verify:
        previous = json.loads(path.read_text(encoding='utf-8'))
        assert all(previous.get(k) == v for k,v in payload.items()), 'Review files changed after inventory'
    else:
        DEST.mkdir(parents=True, exist_ok=True)
        payload.update(generated_at_utc=datetime.now(timezone.utc).isoformat(),
                       generation_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip())
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(verified=args.verify, upload_files=len(payload['tracked_material'])+1,
                          upload_bytes=payload['total_bytes'], local_only_files=len(payload['excluded_local_material']))))


if __name__ == '__main__':
    main()
