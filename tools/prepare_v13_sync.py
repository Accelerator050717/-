"""Additive v13 review packaging only: no research, training, prices, or broker calls.

Run only after research outputs and SQLite writers have finished. Existing local
artifacts, incomplete pre-freeze evidence, old manifests and prior ignore rules
are preserved. ZIPs are independent archives, not multi-volume ZIP segments.
"""
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import zipfile


ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = ROOT / 'data/experiments/continuous_fund_risk_v13'
OUT = ROOT / 'review_upload/sync_v13_20260922'
BUNDLES = ROOT / 'review_bundles/20260922'
MIB = 1024 ** 2
MAX_MEMBERS_BYTES = 400 * MIB
MAX_ARCHIVE_BYTES = 450 * MIB
BEGIN = b'# Additive v13 review exclusions (20260922); see review_upload/sync_v13_20260922.\n'
END = b'# End additive v13 review exclusions (20260922).\n'
PRIOR_MANIFESTS = (
    'review_upload/inventory.csv',
    'review_upload/sync_v8_v11_20260911/inventory.csv',
    'review_upload/sync_v12_20260921/inventory.csv',
)
DEPENDENCIES = ['review_upload/bundles.json',
                'review_upload/sync_v8_v11_20260911/bundles.json']
spec = importlib.util.spec_from_file_location('v13_existing_upload_rules', ROOT / 'tools/prepare_v8_v11_sync.py')
rules = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rules)  # Definition-only stdlib helpers. Never calls main.
sha, save = rules.sha, rules.save


def generator(rel):
    name = Path(rel).name
    if '/engineering/' in rel:
        if '/automatic_control/' in rel:
            return '.venv\\Scripts\\python.exe tools/check_v13_control_cycle.py (FICTIONAL automatic control proof; existing output preserved)'
        if '/final_verification/' in rel:
            return '.venv\\Scripts\\python.exe 56_check_fund_continuity.py --output data/experiments/continuous_fund_risk_v13/engineering/final_verification (FICTIONAL; existing output preserved)'
        return '.venv\\Scripts\\python.exe 56_check_fund_continuity.py (FICTIONAL; existing initial engineering output preserved)'
    if '/record_only/' in rel:
        return '57_check_fund_recording.py pre-freeze implementation attempt; retained original incomplete journal, see PRE_FREEZE_IMPLEMENTATION_NOTES.json; do not overwrite'
    if '/record_only_final/' in rel or name == 'RECORD_ONLY_CHECK.json':
        return '.venv\\Scripts\\python.exe 57_check_fund_recording.py (completed record-only proof; no fitting)'
    if name in ('PLAN.md', 'PLAN.json', 'plan.json', 'PLAN_IDENTITY.json'):
        return 'Preregistered single-controller design; PLAN.md/PLAN.json frozen before 58_evaluate_continuous_risk.py; --check-only verifies identities'
    if name in ('REPORT.md', 'NEXT_QUESTION.md'):
        return 'Report assembled from frozen v13 results; source result paths and checks are recorded in REPORT.md'
    if name in ('FUND_EVENT_EXAMPLE.json', 'ENGINEERING_CONTRACT.md'):
        return 'strategy_fund_journal.py and tests/test_v13_fund_journal.py; FICTIONAL event contract/examples'
    if '/continuous_fund_risk_v13/' in rel:
        return '.venv\\Scripts\\python.exe 58_evaluate_continuous_risk.py (fixed comparisons; completed cases verify/reuse; no fitting)'
    return 'Source/test/review document; see REVIEW_INDEX.md and continuous_fund_risk_v13/PLAN.md'


def sqlite_family(rel):
    """Keep a SQLite file, scope marker, rollback journal and sidecars together."""
    for suffix in ('.sqlite3', '.sqlite', '.db'):
        position = rel.lower().find(suffix)
        if position >= 0 and (position + len(suffix) == len(rel) or rel[position + len(suffix)] in '.-'):
            return rel[:position + len(suffix)]
    return None


def disposition(rel, size):
    category, reason = rules.disposition(rel, size)
    if category in ('private', 'cache'):
        return category, reason
    if sqlite_family(rel):
        return 'large', 'recoverable_sqlite_scope_marker_or_sidecar'
    return category, reason


def partition(rows, limit=MAX_MEMBERS_BYTES - MIB):
    """Stable packing; never split an individual artifact or its SQLite family."""
    groups = {}
    for row in rows:
        key = sqlite_family(row['relative_path']) or row['relative_path']
        groups.setdefault(key, []).append(row)
    batches, current, current_bytes = [], [], 0
    for key in sorted(groups):
        group = groups[key]
        count = sum(row['size_bytes'] for row in group)
        if count > limit:
            raise ValueError('One artifact/family exceeds 400 MiB; preserve locally and review packaging: ' + key)
        if current and current_bytes + count > limit:
            batches.append(current)
            current, current_bytes = [], 0
        current.extend(group)
        current_bytes += count
    if current:
        batches.append(current)
    return batches


def add_ignore_rules(large):
    path = ROOT / '.gitignore'
    original = path.read_bytes()
    block = BEGIN + ''.join('/' + row['relative_path'] + '\n' for row in large).encode('utf-8') + END
    if BEGIN in original:
        before, remaining = original.split(BEGIN, 1)
        if END not in remaining:
            raise ValueError('Own previous ignore block incomplete; do not truncate other rules')
        _, after = remaining.split(END, 1)
        updated = before + block + after
    else:
        updated = original + (b'' if original.endswith(b'\n') else b'\n') + block
    path.write_bytes(updated)


def make_bundle(index, rows):
    path = BUNDLES / f'review-v13-incremental-{index:02}.zip'
    manifest = dict(
        scope='v13 incremental outputs, including initial/incomplete evidence. Restore original v5 A data/models/predictions and v8 controls from prior bundles.',
        independent_zip=True, dependencies=DEPENDENCIES,
        files=[{key: row[key] for key in ('relative_path', 'absolute_path', 'size_bytes', 'sha256',
               'experiment', 'generator_entrypoint', 'read_command')} for row in rows])
    payload = json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8')
    if sum(row['size_bytes'] for row in rows) + len(payload) > MAX_MEMBERS_BYTES:
        raise ValueError('Archive manifest would exceed 400 MiB uncompressed cap; use a smaller packing limit')
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        with zipfile.ZipFile(path) as archive:
            if json.loads(archive.read('REVIEW_BUNDLE_MANIFEST.json')) != manifest:
                raise ValueError('Existing archive members differ; preserve the old archive: ' + str(path))
    else:
        with zipfile.ZipFile(path, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            archive.writestr('REVIEW_BUNDLE_MANIFEST.json', payload)
            for row in rows:
                archive.write(ROOT / row['relative_path'], row['relative_path'])
    with zipfile.ZipFile(path) as archive:
        if len(archive.namelist()) != len(rows) + 1:
            raise ValueError('Unexpected archive member count')
        for row in rows:
            with archive.open(row['relative_path']) as stream:
                actual = hashlib.file_digest(stream, 'sha256').hexdigest()
            if actual != row['sha256'] or sha(ROOT / row['relative_path']) != row['sha256']:
                raise ValueError('Input changed while packaging or archive hash differs: ' + row['relative_path'])
        if sum(info.file_size for info in archive.infolist()) > MAX_MEMBERS_BYTES:
            raise ValueError('Archive uncompressed bytes exceed 400 MiB')
    if path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError('Archive exceeds 450 MiB compressed')
    return dict(path=path.relative_to(ROOT).as_posix(), absolute_path=path.as_posix(),
        size_bytes=path.stat().st_size, size_mib=round(path.stat().st_size / MIB, 6), sha256=sha(path),
        files=len(rows), uncompressed_artifact_bytes=sum(row['size_bytes'] for row in rows),
        uncompressed_bytes=sum(row['size_bytes'] for row in rows) + len(payload),
        independent_zip=True, all_member_hashes_verified=True, uploaded_to_git=False)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    prior = {rel: sha(ROOT / rel) for rel in PRIOR_MANIFESTS}
    names = rules.git_paths('diff', '--name-only', 'HEAD') | rules.git_paths('ls-files', '--others', '--exclude-standard')
    names |= {path.relative_to(ROOT).as_posix() for path in EXPERIMENT.rglob('*') if path.is_file()}
    names = {rel for rel in names if not rel.startswith(('review_upload/sync_v13_20260922/', 'review_bundles/'))}
    rows = []
    for rel in sorted(names):
        path = ROOT / rel
        if path.is_symlink() or not path.is_file():
            raise ValueError('Missing or symlink candidate requires review: ' + rel)
        size = path.stat().st_size
        category, reason = disposition(rel, size)
        if category == 'private':
            raise ValueError('Private candidate must remain local; review path only: ' + rel)
        if category == 'cache':
            continue
        rows.append(dict(relative_path=rel, absolute_path=path.as_posix(), size_bytes=size,
            size_mib=round(size / MIB, 6), sha256=sha(path), disposition=category, reason=reason,
            experiment=rules.rules.experiment(rel), generator_entrypoint=generator(rel),
            read_command=f'.\\.venv\\Scripts\\python.exe tools/inspect_review_artifact.py "{rel}"', review_zip=''))
    large = [row for row in rows if row['disposition'] == 'large']
    # Reserve manifest space so both full archive and artifact bytes fit the cap.
    batches = partition(large)
    for index, batch in enumerate(batches, 1):
        for row in batch:
            row['review_zip'] = f'review_bundles/20260922/review-v13-incremental-{index:02}.zip'
    add_ignore_rules(large)
    ignore = ROOT / '.gitignore'
    if not any(row['relative_path'] == '.gitignore' for row in rows):
        rows.append(dict(relative_path='.gitignore', absolute_path=ignore.as_posix(), disposition='git',
            reason='additive_v13_exact_path_exclusions', experiment='project',
            generator_entrypoint='tools/prepare_v13_sync.py', read_command='Get-Content .gitignore', review_zip=''))
    for row in rows:
        if row['relative_path'] == '.gitignore':
            row.update(size_bytes=ignore.stat().st_size, size_mib=round(ignore.stat().st_size / MIB, 6), sha256=sha(ignore))
    rules.OUT = OUT
    rules.scan_credentials([row['relative_path'] for row in rows
                            if row['disposition'] == 'git' and row['relative_path'] != '.gitignore'])
    packed = [make_bundle(index, batch) for index, batch in enumerate(batches, 1)]
    columns = ['relative_path', 'absolute_path', 'size_bytes', 'size_mib', 'sha256', 'disposition',
               'reason', 'experiment', 'generator_entrypoint', 'read_command', 'review_zip']
    rows.sort(key=lambda row: row['relative_path'])
    rules.write_csv(OUT / 'inventory.csv', rows, columns)
    rules.write_csv(OUT / 'large_artifacts.csv', large, columns)
    if any(sha(ROOT / rel) != value for rel, value in prior.items()):
        raise ValueError('A previous input manifest changed during packaging')
    save(OUT / 'bundles.json', dict(bundles=packed, dependencies=DEPENDENCIES,
        original_A_inputs_required=True, v12_B_models_required=False,
        all_members_hash_verified=True, no_model_fit_or_replay_or_download_or_broker_call=True))
    summary = dict(prepared_at_utc=datetime.now(timezone.utc).isoformat(),
        base_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        branch=subprocess.check_output(['git', 'branch', '--show-current'], cwd=ROOT, text=True).strip(),
        git_files=sum(row['disposition'] == 'git' for row in rows), local_only_files=len(large),
        git_bytes=sum(row['size_bytes'] for row in rows if row['disposition'] == 'git'),
        local_only_bytes=sum(row['size_bytes'] for row in large), zip_count=len(packed),
        previous_manifest_sha256=prior, old_manifests_preserved=True,
        scope='Only changed/new source/docs and all v13 outputs, including incomplete pre-freeze journals. '
              'Own upload metadata excluded to prevent recursive hashes. No old output tree is scanned.')
    save(OUT / 'inventory_summary.json', summary)
    print(json.dumps({key: summary[key] for key in ('git_files', 'local_only_files', 'zip_count', 'old_manifests_preserved')}))


if __name__ == '__main__':
    main()
