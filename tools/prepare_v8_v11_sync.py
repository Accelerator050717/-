"""Prepare an additive Git review snapshot; no research modules or broker APIs.

Preserves the old review_upload/inventory.csv input identity and all experiments.
Writes only this dated upload folder, an additive .gitignore block, and a ZIP.
"""
import csv
import hashlib
import importlib.util
import importlib.metadata
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import zipfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'review_upload/sync_v8_v11_20260911'
BUNDLE = ROOT / 'review_bundles/20260911/review-v8-v11-incremental-01.zip'
EXPERIMENTS = ('h60_risk_execution_v8','universe_delisting_v9','lean_migration_v10','h60_signal_objectives_v11')
MARKER = b'# Additive v8-v11 review exclusions (20260911); see review_upload/sync_v8_v11_20260911.\n'
MIB = 1024**2
spec = importlib.util.spec_from_file_location('old_upload_rules', ROOT/'tools/prepare_review_upload.py')
rules = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rules)  # Definition-only stdlib upload helper; main is not called.


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f,'sha256').hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8',newline='\n')


def git_paths(*args):
    output=subprocess.check_output(['git',*args,'-z'],cwd=ROOT).decode('utf-8')
    return {p for p in output.split('\0') if p}


def disposition(rel, size):
    path=Path(rel);name=path.name.lower()
    if (rel.startswith('data/private/') or '/paper_private/' in rel or name.endswith('.paper.local.json')):
        return 'private','local_account_or_licensed_private_material'
    category,reason=rules.classify(rel,size)
    if category in ('private','cache','large'):
        return category,reason
    if any(part in ('__pycache__','.pytest_cache') for part in path.parts):
        return 'cache','rebuildable_cache'
    if '/lean_migration_v10/' in rel and any(f'/{part}/bars/' in rel for part in ('input','smoke_input')):
        return 'large','exported_historical_price_phases'
    if name in ('trades.csv','positions.csv','targets.csv','order_events.csv'):
        return 'large','full_execution_or_position_detail'
    if name in ('top8_target_paths.csv','signal_daily_ic.csv'):
        return 'large','per_observation_prediction_diagnostic'
    if path.suffix in ('.sqlite','.sqlite3','.db') or name.endswith(('.sqlite.initialized','.sqlite3.initialized','.db.initialized')):
        return 'large','recoverable_offline_sqlite_and_marker'
    if path.suffix=='.log' and size>MIB:
        return 'large','verbose_native_build_log'
    return category,reason


def generator(rel):
    if 'h60_risk_execution_v8' in rel:
        if 'execution_fault' in rel:return '44_test_h60_recovery.py (synthetic recovery; NOT run for upload)'
        if '/execution' in rel:return '43_run_h60_simulation.py (synthetic broker; NOT run for upload)'
        return '42_evaluate_h60_risk_fixes.py / 45_summarize_h60_v8.py (NOT run for upload)'
    if 'universe_delisting_v9' in rel:return '46_check_historical_universe.py (NOT run for upload)'
    if 'lean_migration_v10' in rel:
        if '/input/' in rel:return '47_prepare_lean_migration.py --case full (NOT run for upload)'
        if '/smoke_input/' in rel:return '47_prepare_lean_migration.py --case smoke (NOT run for upload)'
        return 'tools/lean_runtime/make_config.py; tools/lean_runtime/run_lean.py; 48_compare_lean_migration.py; 49_summarize_lean_migration.py (NOT run for upload)'
    if 'h60_signal_objectives_v11' in rel:
        return '50_train_signal_objectives.py / 51_evaluate_signal_objectives.py (NOT run for upload)'
    return 'source/config/test or retained documentation; see REVIEW_INDEX.md'


def write_csv(path, rows, columns):
    with path.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=columns,extrasaction='ignore');w.writeheader();w.writerows(rows)


def scan_credentials(paths):
    patterns={
        'github_token':re.compile(r'\bgh[pousr]_[A-Za-z0-9]{30,}\b|\bgithub_pat_[A-Za-z0-9_]{30,}\b'),
        'private_key':re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
        'openai_token':re.compile(r'\bsk-(?:proj-)?[A-Za-z0-9_-]{40,}\b'),
        'aws_access_key':re.compile(r'\bAKIA[A-Z0-9]{16}\b')}
    matches=[];checked=0;config_values=0
    for rel in sorted(paths):
        p=ROOT/rel
        try:text=p.read_text(encoding='utf-8')
        except UnicodeDecodeError:continue
        checked+=1
        for name,pattern in patterns.items():
            if pattern.search(text):matches.append({'path':rel,'kind':name})
        if p.suffix=='.json' and any(word in p.name.lower() for word in ('config','paper')):
            try:value=json.loads(text)
            except json.JSONDecodeError:continue
            def walk(obj):
                nonlocal config_values
                if isinstance(obj,dict):
                    for k,v in obj.items():
                        key=k.lower().replace('_','-')
                        if key in ('password','api-key','api-token','api-access-token','access-token','secret','client-secret') and isinstance(v,str):
                            config_values+=1
                            if v.strip() and v.lower() not in ('null','none','redacted','0') and not v.upper().startswith(('YOUR_','EXAMPLE','PLACEHOLDER','<')):
                                matches.append({'path':rel,'kind':'nonempty_credential_field','key':k})
                        walk(v)
                elif isinstance(obj,list):
                    for x in obj:walk(x)
            walk(value)
    save(OUT/'credential_scan.json',dict(text_files_checked=checked,config_credential_fields_checked=config_values,
          findings=matches,scope='Common token/private-key forms and selected config fields; not a guarantee against every secret format. Values are never printed.'))
    if matches:raise ValueError('Potential credentials detected; inspect path-only credential_scan.json before staging')


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    original_inventory=sha(ROOT/'review_upload/inventory.csv')
    names=git_paths('diff','--name-only','HEAD')|git_paths('ls-files','--others','--exclude-standard')
    for exp in EXPERIMENTS:
        for parent,dirs,files in os.walk(ROOT/'data/experiments'/exp):
            dirs[:]=[d for d in dirs if d not in ('__pycache__','.pytest_cache')]
            names.update((Path(parent)/f).relative_to(ROOT).as_posix() for f in files)
    names={p for p in names if not p.startswith(('review_upload/sync_v8_v11_20260911/','review_bundles/'))}
    rows=[]
    for rel in sorted(names):
        p=ROOT/rel
        if not p.is_file():raise ValueError(f'Missing candidate path: {rel}')
        if p.is_symlink():raise ValueError(f'Symlink needs separate review: {rel}')
        size=p.stat().st_size;category,reason=disposition(rel,size)
        if category=='private':raise ValueError(f'Private candidate stays local; inspect before proceeding: {rel}')
        if category=='cache':continue
        rows.append(dict(relative_path=rel,absolute_path=p.as_posix(),size_bytes=size,size_mib=round(size/MIB,6),
             sha256=sha(p),disposition=category,reason=reason,experiment=rules.experiment(rel),
             generator_entrypoint=generator(rel),read_command=f'.\\.venv\\Scripts\\python.exe tools/inspect_review_artifact.py "{rel}"',
             review_zip=BUNDLE.relative_to(ROOT).as_posix() if category=='large' else ''))
    large=[r for r in rows if r['disposition']=='large']
    assert sum(r['size_bytes'] for r in large)<400*MIB,'Use additional independent ZIPs if upload scope grows'
    # Preserve every existing ignore rule. Replace only this helper's own suffix on repeat.
    ignore=ROOT/'.gitignore';base=ignore.read_bytes().split(MARKER)[0].rstrip(b'\r\n')+b'\n'
    ignore.write_bytes(base+MARKER+''.join('/'+r['relative_path']+'\n' for r in large).encode('utf-8'))
    for row in rows:
        if row['relative_path']=='.gitignore':
            row.update(size_bytes=ignore.stat().st_size,size_mib=round(ignore.stat().st_size/MIB,6),sha256=sha(ignore))
    scan_credentials([r['relative_path'] for r in rows if r['disposition']=='git'])
    BUNDLE.parent.mkdir(parents=True,exist_ok=True)
    manifest=dict(scope='Only additive v8-v11 local materials. Also restore original 20260909 bundles for v5 raw inputs/models.',
                  files=[{k:r[k] for k in ('relative_path','size_bytes','sha256','experiment','read_command')} for r in large])
    if BUNDLE.exists():
        with zipfile.ZipFile(BUNDLE) as z:
            assert json.loads(z.read('REVIEW_BUNDLE_MANIFEST.json'))==manifest,'Existing ZIP differs; do not overwrite'
    else:
        with zipfile.ZipFile(BUNDLE,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
            z.writestr('REVIEW_BUNDLE_MANIFEST.json',json.dumps(manifest,ensure_ascii=False,indent=2))
            for row in large:z.write(ROOT/row['relative_path'],row['relative_path'])
    with zipfile.ZipFile(BUNDLE) as z:
        assert len(z.namelist())==len(large)+1
        for row in large:
            with z.open(row['relative_path']) as f:
                assert hashlib.file_digest(f,'sha256').hexdigest()==row['sha256'],row['relative_path']
    assert BUNDLE.stat().st_size<=450*MIB
    save(OUT/'bundles.json',dict(path=BUNDLE.relative_to(ROOT).as_posix(),absolute_path=BUNDLE.as_posix(),
         size_bytes=BUNDLE.stat().st_size,size_mib=round(BUNDLE.stat().st_size/MIB,6),sha256=sha(BUNDLE),
         files=len(large),uncompressed_bytes=sum(r['size_bytes'] for r in large),independent_zip=True,all_member_hashes_verified=True,
         dependency_manifest='review_upload/bundles.json',uploaded_to_git=False))
    columns=list(rows[0]);write_csv(OUT/'inventory.csv',rows,columns);write_csv(OUT/'large_artifacts.csv',large,columns)
    save(OUT/'inventory_summary.json',dict(prepared_at_utc=datetime.now(timezone.utc).isoformat(),
         base_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
         branch=subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip(),
         git_files=sum(r['disposition']=='git' for r in rows),local_only_files=len(large),
         git_bytes=sum(r['size_bytes'] for r in rows if r['disposition']=='git'),local_only_bytes=sum(r['size_bytes'] for r in large),
         old_inventory_sha256=original_inventory,old_inventory_preserved=sha(ROOT/'review_upload/inventory.csv')==original_inventory,
         note='Snapshot lists changed/new review source and v8-v11 artifacts. Its own upload metadata are excluded to avoid recursive hashes. No training, simulation, market acquisition, or broker code was run.'))
    save(OUT/'DEPENDENCIES.json',dict(python=sys.version,interpreter=sys.executable,
         requirements_sha256=sha(ROOT/'requirements.txt'),packages={d.metadata['Name']:d.version for d in importlib.metadata.distributions()},
         lean_runtime='External pinned LEAN + recorded patch; tools/lean_runtime/README.md and v10 runtime/RUNTIME_IDENTITY.json. Not copied into Git.'))
    print(json.dumps(dict(git_files=sum(r['disposition']=='git' for r in rows),local_only_files=len(large),
         zip_mib=round(BUNDLE.stat().st_size/MIB,2),old_inventory_preserved=True),ensure_ascii=False))


if __name__=='__main__':
    main()
