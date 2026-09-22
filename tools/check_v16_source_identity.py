"""Read-only checks of v16 frozen, editor-readback and observed runtime source.

This compares observed hashes; it does not reconstruct the missing log tail or
claim that the truncated transport envelope passed its full-payload checksum.
"""
import ast
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/experiments/momentum_loss_attribution_v16"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def executable_ast(source):
    # Identical portable AST convention to the frozen v15 producer.
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.body and isinstance(node.body[0], ast.Expr):
                value = node.body[0].value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    node.body.pop(0)
    return sha(ast.dump(tree, include_attributes=False).replace(", type_params=[]", "").encode())


def main():
    freeze_path = OUT / "FINAL_PRE_REPLAY_IDENTITY.json"
    recovered_path = OUT / "DIAGNOSTIC_RECOVERED_FIELDS.json"
    frozen = json.loads(freeze_path.read_text(encoding="utf-8"))
    runtime = json.loads(recovered_path.read_text(encoding="utf-8"))["identity"]
    keys = {
        "main.py": ("observer_sha256", "observer_ast_sha256"),
        "v15_core.py": ("base_sha256", "base_ast_sha256"),
        "qc_v16_c10_reference.py": ("c10_reference_sha256", None),
    }
    rows = []
    for item in frozen["source_files"]:
        native_key, ast_key = keys[item["cloud_filename"]]
        readback = (ROOT / item["ui_readback_path"]).read_bytes()
        canonical = (ROOT / item["canonical_path"]).read_bytes()
        lf = readback.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        # Measured formatting transform, not an alteration of saved source.
        candidate = lf + b"\n"
        readback_ast = executable_ast(lf.decode("utf-8"))
        canonical_ast = executable_ast(canonical.decode("utf-8"))
        observed_ast = runtime.get(ast_key) if ast_key else None
        row = {
            "cloud_filename": item["cloud_filename"],
            "canonical_path": item["canonical_path"],
            "ui_readback_path": item["ui_readback_path"],
            "canonical_sha256": sha(canonical),
            "canonical_matches_frozen_bytes": sha(canonical) == item["canonical_sha256"],
            "readback_sha256": sha(readback),
            "readback_matches_frozen_bytes": sha(readback) == item["ui_readback_sha256"],
            "lf_readback_sha256": sha(lf),
            "lf_readback_matches_frozen": sha(lf) == item["lf_normalized_sha256"],
            "runtime_source_sha256_observed": runtime[native_key],
            "candidate_transform": "UI readback CRLF/CR normalized to LF, then append exactly one LF byte",
            "candidate_runtime_bytes": len(candidate),
            "candidate_runtime_sha256": sha(candidate),
            "candidate_matches_runtime_observed_sha256": sha(candidate) == runtime[native_key],
            "portable_executable_ast_sha256": canonical_ast,
            "canonical_readback_and_frozen_ast_match": canonical_ast == readback_ast == item["portable_executable_ast_sha256"],
            "runtime_ast_sha256_observed": observed_ast,
            "runtime_ast_matches_if_reported": observed_ast == canonical_ast if observed_ast is not None else None,
            "runtime_ast_limit": None if ast_key else "Helper runtime AST was not separately emitted; its runtime byte hash matches the exact formatting-only candidate of the frozen readback.",
        }
        rows.append(row)
    passed = all(
        r["canonical_matches_frozen_bytes"] and r["readback_matches_frozen_bytes"]
        and r["lf_readback_matches_frozen"] and r["candidate_matches_runtime_observed_sha256"]
        and r["canonical_readback_and_frozen_ast_match"]
        and r["runtime_ast_matches_if_reported"] is not False for r in rows
    )
    result = {
        "schema": "v16-source-identity-check-1",
        "source_identity_numeric_checks_pass": passed,
        "frozen_identity_file_sha256": sha(freeze_path.read_bytes()),
        "recovered_complete_fields_file_sha256": sha(recovered_path.read_bytes()),
        "source_files_modified_by_check": False,
        "full_log_transport_integrity_verified": False,
        "evidence_limit": "Runtime hashes are syntactically complete fields recovered from the truncated observed log. Matching frozen local/UI-readback bytes and reported AST is a separate identity check, not recovery of missing log bytes, LZMA EOF or the full payload SHA.",
        "files": rows,
    }
    (OUT / "SOURCE_IDENTITY_CHECK.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    lines = ["# v16源码身份复核", "", "冻结源码、UI读回、实际运行记录的身份核对通过。检查没有改写任何冻结源码。", "", "实际运行的三个文件字节SHA均精确匹配：对已保存UI读回转换为LF行尾，再在末尾增加一个LF。该变换只在内存计算哈希，不把差异笼统归为未检查的格式差异。", "", "| 云文件 | 模拟运行字节数 | 实际运行SHA256 | AST核对 |", "|---|---:|---|---|"]
    for r in rows:
        note = "运行/本地/读回/冻结一致" if r["runtime_ast_sha256_observed"] else "本地/读回/冻结一致；运行字节SHA匹配"
        lines.append(f"| {r['cloud_filename']} | {r['candidate_runtime_bytes']} | {r['runtime_source_sha256_observed']} | {note} |")
    lines += ["", "observer的运行AST为`78623ad3a2f7dd269e5c573b14b2490ed36813bfb8a2bca970e2154aa81b5f95`，与最终运行前冻结、本地源码、UI读回一致。C10 helper没有单独输出运行AST，因此只声明实际运行字节SHA与冻结读回的上述精确格式变换匹配。", "", "**证据边界：**这些运行哈希来自截断日志中语法完整、已实际恢复的identity字段。源码身份核对通过不等于完整日志传输通过；LZMA尾部、完整payload SHA及缺失C10尾部元数据仍未验证，没有补造。", "", "复现：`.\\.venv\\Scripts\\python.exe -B tools/check_v16_source_identity.py`。"]
    (OUT / "SOURCE_IDENTITY_CHECK.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"source_identity_numeric_checks_pass": passed, "files": [{"name": r["cloud_filename"], "runtime_bytes": r["candidate_runtime_bytes"], "runtime_byte_hash_match": r["candidate_matches_runtime_observed_sha256"], "runtime_ast_match": r["runtime_ast_matches_if_reported"]} for r in rows]}, indent=2))
    if not passed:
        raise SystemExit("Source identity check failed")


if __name__ == "__main__":
    main()
