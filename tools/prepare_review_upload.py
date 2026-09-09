"""Inventory/pack existing artifacts for a Git review. Uses the standard library only.

No project module is imported, and no training, strategy, download or broker code
is executed. Existing artifacts are read only. Generated manifests live under
review_upload; independent ZIP files live under the Git-ignored review_bundles.
"""
import argparse
import csv
import hashlib
import json
import os
import re
import sys
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "review_upload"
BUNDLES = ROOT / "review_bundles" / "20260909"
MIB = 1024**2
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache",
             ".ruff_cache", "node_modules", "review_upload", "review_bundles"}
MODEL_SUFFIXES = {".joblib", ".pkl", ".pickle", ".npy", ".npz", ".onnx", ".pt", ".pth"}
ARCHIVE_SUFFIXES = {".zip", ".7z", ".rar", ".tar", ".gz", ".bz2", ".xz"}
CODE_SUFFIXES = {".py", ".md", ".ps1", ".sh", ".toml", ".yaml", ".yml"}


def sha(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def classify(rel, size):
    path = Path(rel)
    name, suffix = path.name.lower(), path.suffix.lower()
    if (name == ".env" or (name.startswith(".env.") and name != ".env.example")
            or suffix in {".pem", ".key", ".p12", ".pfx"}
            or name in {"credentials.json", "token.json", "tokens.json", "id_rsa", "id_ed25519"}):
        return "private", "credential_or_local_environment"
    if suffix in ARCHIVE_SUFFIXES or suffix in {".pyc", ".pyo"} or name in {".coverage", "thumbs.db", ".ds_store"}:
        return "cache", "rebuildable_or_old_archive"
    if suffix in CODE_SUFFIXES or name in {"requirements.txt", ".env.example", ".gitignore", ".gitattributes"}:
        return "git", "source_or_documentation"
    if suffix in MODEL_SUFFIXES:
        return "large", "serialized_model_or_array"
    if rel.startswith("data/raw/") and suffix == ".csv":
        return "large", "original_market_snapshot"
    if rel.startswith("data/raw/sec_") and size > 512*1024:
        return "large", "original_sec_payload"
    if rel.startswith("data/processed/") and size > MIB:
        return "large", "feature_label_or_provenance_table"
    if size > 4*MIB:
        return "large", "artifact_over_4_MiB"
    # Per-row predictions and detailed trades remain reconstructible from ZIP.
    # Keep named summary/diagnostic tables even when their name contains scores.
    if suffix == ".csv" and not any(word in name for word in ("summary", "comparison", "metrics", "diagnostic")):
        if any(word in name for word in ("predict", "scores", "_development", "_validation")):
            return "large", "full_predictions"
        if any(word in name for word in ("_trades", "_positions", "_targets", "stock_contributions")):
            return "large", "full_execution_or_position_detail"
    return "git", "review_result_or_metadata"


def experiment(rel):
    parts = rel.split("/")
    if rel.startswith("data/experiments/"):
        return parts[2]
    if rel.startswith("data/raw/extended_"):
        return "extended_history_v5;robust_strategy_v6;profit_priority_v7"
    if rel.startswith("data/raw/sec_") or "fundamental" in rel or "event_panel" in rel:
        return "automation_research_v2;continuous_research_2h_v3"
    if rel.startswith("data/raw/") or rel.startswith("data/processed/"):
        return "original_2015_2025_research_and_offline_replay"
    return rel.rsplit("/",1)[0] if "/" in rel else "project"


def generator(rel):
    mapping = [
        ("extended_history_v5", "35_extend_historical_diagnostic.py"),
        ("extended_2012_2025", "35_extend_historical_diagnostic.py"),
        ("profit_priority_v7", "40_evaluate_profit_priority.py"),
        ("robust_strategy_v6", "38_train_robust_strategy.py / 39_evaluate_robust_strategy.py"),
        ("risk_controls_v4", "34_research_risk_controls.py"),
        ("continuous_research_2h_v3", "28_train_multihorizon.py / 31_research_robustness_v3.py / 32_write_multihorizon_report.py"),
        ("automation_research_v2", "22_train_fundamental_comparison.py / 25_write_automation_report.py"),
        ("auto_research_45m_v1", "15_run_research_batch.py / 16_huber_scale_followup.py / 18_finalize_research.py"),
        ("walkforward_ranker_v1", "13_walkforward_training.py"),
        ("panel_ranker_v1", "12_train_ranker.py"),
        ("panel_lgbm_v1", "11_train_panel.py"),
        ("sec_companyfacts", "21_prepare_fundamentals.py"),
        ("fundamental", "fundamental_features.py"),
        ("event_panel", "26_prepare_event_features.py"),
        ("horizon_targets", "27_prepare_horizon_panel.py"),
        ("research_panel", "14_prepare_research_data.py"),
        ("data/raw/", "03_download_and_check.py / 09_download_panel.py / 14_prepare_research_data.py"),
        ("panel_2015_2025.csv", "10_build_panel.py"),
    ]
    return next((entry for marker,entry in mapping if marker in rel), "see experiment plan and README")


def inventory():
    rows = []
    for parent,dirs,files in os.walk(ROOT):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(files):
            path = Path(parent)/name
            if path.is_symlink():
                raise ValueError(f"Review symlink before publishing: {path.relative_to(ROOT)}")
            rel = path.relative_to(ROOT).as_posix()
            size = path.stat().st_size
            disposition,reason = classify(rel,size)
            rows.append(dict(relative_path=rel,absolute_path=path.as_posix(),size_bytes=size,
                        size_mib=round(size/MIB,6),sha256=sha(path),disposition=disposition,reason=reason,
                        experiment=experiment(rel),generator_entrypoint=generator(rel),
                        read_command=f'.\\.venv\\Scripts\\python.exe tools/inspect_review_artifact.py "{rel}"'))
    return rows


def write_csv(path, rows, columns):
    with path.open("w",encoding="utf-8",newline="") as handle:
        writer = csv.DictWriter(handle,fieldnames=columns,extrasaction="ignore")
        writer.writeheader();writer.writerows(rows)


def group_packages(rows):
    current, historical_inputs, historical_runs = [],[],[]
    for row in rows:
        rel = row["relative_path"]
        if any(marker in rel for marker in ("extended_2012_2025", "extended_history_v5", "robust_strategy_v6", "profit_priority_v7")):
            current.append(row)
        elif rel.startswith("data/raw/") or rel.startswith("data/processed/"):
            historical_inputs.append(row)
        else:
            historical_runs.append(row)
    result = []
    # Split by uncompressed size, so each independently readable ZIP is safely
    # below 450 MiB even for incompressible content. No multi-volume ZIP format.
    for group, items in (("current-v5-v7",current),("historical-inputs",historical_inputs),("historical-models-results",historical_runs)):
        items.sort(key=lambda row: row["relative_path"])
        batches, batch, total = [],[],0
        for row in items:
            if row["size_bytes"] > 400*MIB:
                raise ValueError("A single artifact exceeds the packing ceiling; preserve and handle explicitly.")
            if batch and total+row["size_bytes"] > 400*MIB:
                batches.append(batch);batch=[];total=0
            batch.append(row);total+=row["size_bytes"]
        if batch:
            batches.append(batch)
        for number,batch in enumerate(batches,1):
            result.append((f"review-{group}-{number:02}.zip",batch))
    return result


def pack(rows):
    BUNDLES.mkdir(parents=True,exist_ok=True)
    records=[]
    for name,batch in group_packages(rows):
        path = BUNDLES/name
        manifest = dict(bundle=name,repository="https://github.com/Accelerator050717/-",branch="main",
                        extraction="Independent ZIP; extract into project root, preserving data/... paths. Other ZIPs are additive.",
                        files=[{k:r[k] for k in ("relative_path","size_bytes","sha256","experiment","read_command")} for r in batch])
        if path.exists():
            with zipfile.ZipFile(path) as archive:
                old = json.loads(archive.read("REVIEW_BUNDLE_MANIFEST.json"))
            if old != manifest:
                raise ValueError(f"Existing ZIP differs; will not overwrite: {path}")
        else:
            with zipfile.ZipFile(path,"x",compression=zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True) as archive:
                archive.writestr("REVIEW_BUNDLE_MANIFEST.json",json.dumps(manifest,ensure_ascii=False,indent=2))
                archive.writestr("REVIEW_BUNDLE_README.txt","Existing research artifacts only. No training/download was performed.\nExtract into a clone of Accelerator050717/- using the original data paths.\nVerify against the SHA256 list before loading any model.\n")
                for row in batch:
                    archive.write(ROOT/row["relative_path"],row["relative_path"])
        if path.stat().st_size > 450*MIB:
            raise AssertionError(f"ZIP exceeds 450MiB: {path}")
        # Verify each archived byte stream against the pre-upload inventory.
        with zipfile.ZipFile(path) as archive:
            if len(archive.namelist()) != len(batch)+2:
                raise AssertionError("ZIP file count differs.")
            for row in batch:
                with archive.open(row["relative_path"]) as handle:
                    actual = hashlib.file_digest(handle,"sha256").hexdigest()
                if actual != row["sha256"]:
                    raise AssertionError(f"ZIP content differs: {row['relative_path']}")
                row["review_zip"] = path.relative_to(ROOT).as_posix()
        record=dict(name=name,relative_path=path.relative_to(ROOT).as_posix(),absolute_path=path.as_posix(),
                    files=len(batch),uncompressed_bytes=sum(r["size_bytes"] for r in batch),
                    size_bytes=path.stat().st_size,size_mib=round(path.stat().st_size/MIB,3),sha256=sha(path),
                    independent_zip=True,all_entry_sha256_verified=True)
        records.append(record)
        print(json.dumps(record,ensure_ascii=True),flush=True)
    return records


def secret_name_scan(rows):
    # Known credential forms; findings print file/line/rule only, never values.
    patterns = {
        "github_token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b"),
        "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        "openai_key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}\b"),
        "credential_url": re.compile(r"https?://[^\s/:]+:[^\s/@]+@"),
        "literal_bearer": re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._-]{30,}"),
    }
    findings=[];count=0
    for row in rows:
        if row["disposition"]!="git":
            continue
        path=ROOT/row["relative_path"]
        if path.suffix.lower() in {".png",".jpg",".jpeg",".gif",".pdf"}:
            continue
        try:
            text=path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            continue
        count+=1
        for name,pattern in patterns.items():
            for match in pattern.finditer(text):
                findings.append(dict(path=row["relative_path"],line=text.count("\n",0,match.start())+1,rule=name))
    save(OUT/"credential_scan.json",dict(scanned_text_files=count,findings=findings,
          scope="Targeted known credential forms and file names; not a proof of absence of every possible secret."))
    if findings:
        raise ValueError(f"Credential-like content requires review; values not printed: {findings}")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack",action="store_true")
    args=parser.parse_args()
    OUT.mkdir(exist_ok=True)
    rows=inventory()
    secret_name_scan(rows)
    large=[r for r in rows if r["disposition"]=="large"]
    columns=["relative_path","absolute_path","size_bytes","size_mib","sha256","experiment","reason","generator_entrypoint","read_command","review_zip"]
    base_ignore="""# Rebuildable local environment and caches
.venv/
venv/
__pycache__/
*.py[cod]
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage
htmlcov/
node_modules/
# Credentials stay local; retain the blank configuration template.
.env
.env.*
!.env.example
*.pem
*.key
*.p12
*.pfx
credentials.json
token.json
tokens.json
id_rsa
id_ed25519
# Archives remain local. See review_upload/large_artifacts.csv and bundles.json.
/review_bundles/
*.zip
*.7z
*.rar
*.tar
*.gz
*.bz2
*.xz
# Precise existing bulky-artifact exclusions, generated by upload preparation.
# Do not ignore the entire data directory: designs/reports/results are tracked.
"""
    (ROOT/".gitignore").write_text(base_ignore+"".join("/"+r["relative_path"]+"\n" for r in large),encoding="utf-8")
    if args.pack:
        bundles=pack(large)
        save(OUT/"bundles.json",bundles)
    elif (OUT/"bundles.json").exists():
        # Refresh documentation/source inventory without rebuilding existing ZIPs.
        mapping = {}
        for bundle in json.loads((OUT/"bundles.json").read_text(encoding="utf-8")):
            path = ROOT/bundle["relative_path"]
            if path.stat().st_size != bundle["size_bytes"] or sha(path) != bundle["sha256"]:
                raise ValueError(f"Archived ZIP changed: {bundle['relative_path']}")
            with zipfile.ZipFile(path) as archive:
                manifest = json.loads(archive.read("REVIEW_BUNDLE_MANIFEST.json"))
            for item in manifest["files"]:
                mapping[item["relative_path"]] = (item,bundle["relative_path"])
        if set(mapping) != {r["relative_path"] for r in large}:
            raise ValueError("Large-artifact inventory changed; do not reuse mismatched ZIPs.")
        for row in large:
            item,bundle_path = mapping[row["relative_path"]]
            if item["size_bytes"] != row["size_bytes"] or item["sha256"] != row["sha256"]:
                raise ValueError(f"Artifact changed after packing: {row['relative_path']}")
            row["review_zip"] = bundle_path
    write_csv(OUT/"large_artifacts.csv",large,columns)
    write_csv(OUT/"inventory.csv",rows,["relative_path","size_bytes","sha256","disposition","reason"])
    totals=defaultdict(lambda:dict(files=0,size_bytes=0))
    for row in rows:
        totals[row["disposition"]]["files"]+=1
        totals[row["disposition"]]["size_bytes"]+=row["size_bytes"]
    save(OUT/"inventory_summary.json",dict(captured_at_utc=datetime.now(timezone.utc).isoformat(),
         root=ROOT.as_posix(),totals=totals,large_artifacts_manifest="large_artifacts.csv",
         business_artifacts_modified=False,training_run=False,market_data_downloaded=False,broker_accessed=False))
    print(json.dumps(totals,indent=2),flush=True)


if __name__=="__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
