"""Pack existing v12 review artifacts only; never fit, replay, fetch prices or trade.

Preserves all previous manifests and ignore rules. The incremental archive uses
the same classifications as the v8-v11 upload; it is independently extractable.
"""
import csv
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = ROOT/'data/experiments/h60_training_cutoff_v12'
OUT = ROOT/'review_upload/sync_v12_20260921'
BUNDLE = ROOT/'review_bundles/20260921/review-v12-incremental-01.zip'
MARKER = b'# Additive v12 review exclusions (20260921); see review_upload/sync_v12_20260921.\n'
MIB = 1024**2
spec = importlib.util.spec_from_file_location('review_rules_v8_v11', ROOT/'tools/prepare_v8_v11_sync.py')
rules = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rules)  # Definition-only upload helpers, no research imports.
sha, save = rules.sha, rules.save


def generator(rel):
    if Path(rel).name in ('REPORT.md','TRAINING_DETAILS.md','NEXT_QUESTION.md'):
        return '.venv\\Scripts\\python.exe 55_summarize_annual_cutoff.py (frozen results only)'
    if 'INDEPENDENT_TRAINING_CHECK' in rel:
        return '.venv\\Scripts\\python.exe -B tools/check_v12_training_artifacts.py (no fitting)'
    if Path(rel).name=='PLAN.md':
        return 'Preregistered design; 53_train_annual_cutoff.py --register-only binds its SHA before fitting'
    if Path(rel).name in ('TESTS.json','ARTIFACTS.csv'):
        return 'Recorded actual checks / final SHA256 inventory; see TESTS.json and review_upload/sync_v12_20260921/README.md'
    if '/drawdown_check/' in rel:
        return '.venv\\Scripts\\python.exe v12_drawdown_check.py (FICTIONAL only)'
    if 'V11_READ_ONLY' in rel:
        return '.venv\\Scripts\\python.exe -B 52_verify_frozen_research.py (read-only)'
    if any(word in rel for word in ('backtests/','EVALUATION','evaluation','all_results','pair_deltas','annual_results',
                                   'equity.csv','selection','signal_','RUN_CHECKS','GATES','trade_reason','stock_contribution')):
        return '.venv\\Scripts\\python.exe 54_evaluate_training_cutoff.py (completed cases verify/reuse)'
    if '/h60_training_cutoff_v12/' in rel:
        return '.venv\\Scripts\\python.exe 53_train_annual_cutoff.py (completed training verifies, no additional fits)'
    return 'Source, test, or review documentation; see REVIEW_INDEX.md'


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    old_inventory_sha = sha(ROOT/'review_upload/inventory.csv')
    prior_sync_sha = sha(ROOT/'review_upload/sync_v8_v11_20260911/inventory.csv')
    names = rules.git_paths('diff','--name-only','HEAD') | rules.git_paths('ls-files','--others','--exclude-standard')
    names |= {p.relative_to(ROOT).as_posix() for p in EXPERIMENT.rglob('*') if p.is_file()}
    names = {p for p in names if not p.startswith(('review_upload/sync_v12_20260921/','review_bundles/'))}
    rows=[]
    for rel in sorted(names):
        path = ROOT/rel
        if path.is_symlink() or not path.is_file():
            raise ValueError(f'Unexpected candidate: {rel}')
        category, reason = rules.disposition(rel,path.stat().st_size)
        if category == 'private':
            raise ValueError(f'Private candidate remains local: {rel}')
        if category == 'cache':
            continue
        if path.name == 'paired_selections.csv':
            category,reason='large','per_decision_selection_detail'
        rows.append(dict(relative_path=rel,absolute_path=path.as_posix(),size_bytes=path.stat().st_size,
                         size_mib=round(path.stat().st_size/MIB,6),sha256=sha(path),disposition=category,reason=reason,
                         experiment=rules.rules.experiment(rel),generator_entrypoint=generator(rel),
                         read_command=f'.\\.venv\\Scripts\\python.exe tools/inspect_review_artifact.py "{rel}"',
                         review_zip=BUNDLE.relative_to(ROOT).as_posix() if category=='large' else ''))
    large=[r for r in rows if r['disposition']=='large']
    if sum(r['size_bytes'] for r in large)>400*MIB:
        raise ValueError('Pack additional independent archives rather than exceeding the per-archive budget.')
    ignore=ROOT/'.gitignore'
    base=ignore.read_bytes().split(MARKER)[0].rstrip(b'\r\n')+b'\n'
    ignore.write_bytes(base+MARKER+''.join('/'+r['relative_path']+'\n' for r in large).encode('utf-8'))
    if not any(r['relative_path']=='.gitignore' for r in rows):
        rows.append(dict(relative_path='.gitignore',absolute_path=ignore.as_posix(),size_bytes=0,size_mib=0,
                         sha256='',disposition='git',reason='source_or_documentation',experiment='project',
                         generator_entrypoint='tools/prepare_v12_sync.py',read_command='Get-Content .gitignore',review_zip=''))
    for row in rows:
        if row['relative_path']=='.gitignore':
            row.update(size_bytes=ignore.stat().st_size,size_mib=round(ignore.stat().st_size/MIB,6),sha256=sha(ignore))
    rules.OUT=OUT  # The shared scanner writes only the new upload folder.
    rules.scan_credentials([r['relative_path'] for r in rows if r['disposition']=='git'])
    manifest=dict(scope='v12 incremental artifacts; restore original v5 snapshot/models and v8 controls from prior bundles as well.',
                  files=[{k:r[k] for k in ('relative_path','size_bytes','sha256','experiment','read_command')} for r in large])
    BUNDLE.parent.mkdir(parents=True,exist_ok=True)
    if BUNDLE.exists():
        with zipfile.ZipFile(BUNDLE) as archive:
            if json.loads(archive.read('REVIEW_BUNDLE_MANIFEST.json'))!=manifest:
                raise ValueError('Archive already exists with different frozen members; preserve it.')
    else:
        with zipfile.ZipFile(BUNDLE,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
            archive.writestr('REVIEW_BUNDLE_MANIFEST.json',json.dumps(manifest,ensure_ascii=False,indent=2))
            for row in large:
                archive.write(ROOT/row['relative_path'],row['relative_path'])
    with zipfile.ZipFile(BUNDLE) as archive:
        assert len(archive.namelist())==len(large)+1
        for row in large:
            with archive.open(row['relative_path']) as stream:
                assert hashlib.file_digest(stream,'sha256').hexdigest()==row['sha256']
    assert BUNDLE.stat().st_size<=450*MIB
    save(OUT/'bundles.json',dict(path=BUNDLE.relative_to(ROOT).as_posix(),absolute_path=BUNDLE.as_posix(),
         size_bytes=BUNDLE.stat().st_size,size_mib=round(BUNDLE.stat().st_size/MIB,6),sha256=sha(BUNDLE),
         files=len(large),uncompressed_bytes=sum(r['size_bytes'] for r in large),independent_zip=True,
         all_member_hashes_verified=True,uploaded_to_git=False,
         dependencies=['review_upload/bundles.json','review_upload/sync_v8_v11_20260911/bundles.json']))
    columns=list(rows[0])
    rules.write_csv(OUT/'inventory.csv',rows,columns)
    rules.write_csv(OUT/'large_artifacts.csv',large,columns)
    assert sha(ROOT/'review_upload/inventory.csv')==old_inventory_sha
    assert sha(ROOT/'review_upload/sync_v8_v11_20260911/inventory.csv')==prior_sync_sha
    save(OUT/'inventory_summary.json',dict(prepared_at_utc=datetime.now(timezone.utc).isoformat(),
         base_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
         git_files=sum(r['disposition']=='git' for r in rows),local_only_files=len(large),
         git_bytes=sum(r['size_bytes'] for r in rows if r['disposition']=='git'),
         local_only_bytes=sum(r['size_bytes'] for r in large),
         original_inventory_sha256=old_inventory_sha,previous_sync_inventory_sha256=prior_sync_sha,
         old_manifests_preserved=True,scope='Current v12 outputs and changed source/docs; own upload metadata excluded from recursive inventory.'))
    print(json.dumps(dict(git_files=sum(r['disposition']=='git' for r in rows),local_only_files=len(large),
                          zip_mib=round(BUNDLE.stat().st_size/MIB,3),old_manifests_preserved=True)))


if __name__=='__main__':
    main()
