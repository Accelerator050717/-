"""从现有训练摘要和可信本地模型汇总训练明细；不拟合、不读取新行情。"""

import ast
import json
from collections import Counter
from pathlib import Path

import joblib
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "data" / "experiments" / "auto_research_45m_v1"
SOURCES = (
    ("original", OUTPUT, 102),
    ("huber_scale_followup", OUTPUT / "huber_scale_followup", 12),
)
COLUMNS = [
    "batch", "candidate", "year", "status", "kind", "feature_group",
    "feature_count", "target", "target_column", "train_rows", "validation_rows",
    "train_first", "train_last_exit", "validation_last_exit", "validation_NDCG",
    "fit_seconds", "best_iteration", "attempted_iterations", "n_iter", "max_iter",
    "huber_alpha", "warning_capture_status", "warnings_count", "warnings",
    "artifact_path", "artifact_exists", "source_summary_path",
]


def nullable(value):
    """缺失字段保持缺失，不能把未记录解释为 0 或没有警告。"""
    return None if value is None or (np.isscalar(value) and pd.isna(value)) else value


def scalar_or_json(value):
    value = nullable(value)
    if value is None:
        return None
    array = np.asarray(value)
    if array.size == 1:
        number = array.reshape(-1)[0].item()
        return int(number) if isinstance(number, (int, float)) and float(number).is_integer() else number
    return json.dumps(array.tolist())


def collect():
    records, missing_artifacts, artifact_errors = [], [], []
    mlp_iterations, warning_events = [], []
    for batch_name, directory, expected_count in SOURCES:
        source = directory / "training_summary.csv"
        summary = pd.read_csv(source)
        if len(summary) != expected_count or summary.duplicated(["candidate", "year"]).any():
            raise ValueError(f"{source}: 行数或候选/年份唯一性与已完成实验不符。")
        for row in summary.to_dict("records"):
            candidate, year = row["candidate"], int(row["year"])
            artifact = directory / str(year) / f"{candidate}.joblib"
            captured = "warnings" in row and nullable(row["warnings"]) is not None
            warning_list = ast.literal_eval(row["warnings"]) if captured else None
            if captured and not isinstance(warning_list, list):
                raise ValueError(f"{candidate}/{year}: 警告记录不是列表。")
            record = {
                "batch": batch_name, "candidate": candidate, "year": year,
                **{key: nullable(row.get(key)) for key in (
                    "status", "kind", "feature_group", "train_rows", "validation_rows",
                    "train_first", "train_last_exit", "validation_last_exit", "best_iteration",
                    "attempted_iterations", "huber_alpha",
                )},
                "validation_NDCG": nullable(row.get("validation_ndcg5")),
                "fit_seconds": nullable(row.get("seconds")),
                "warning_capture_status": "captured" if captured else "unavailable",
                "warnings_count": len(warning_list) if captured else None,
                "warnings": json.dumps(warning_list, ensure_ascii=False) if captured else None,
                "artifact_path": artifact.as_posix(), "artifact_exists": artifact.exists(),
                "source_summary_path": source.as_posix(),
            }
            if warning_list:
                warning_events.append({"candidate": candidate, "year": year, "warnings": warning_list})
            if not artifact.exists():
                missing_artifacts.append(artifact.as_posix())
                records.append(record)
                continue
            try:
                # 仅加载本项目刚保存的可信训练产物；不接收外部 pickle 文件。
                bundle = joblib.load(artifact)
                model, features, config = bundle["model"], bundle["features"], bundle["candidate"]
                if config["id"] != candidate:
                    raise ValueError("模型文件候选标识不匹配。")
                if getattr(model, "n_features_in_", len(features)) != len(features):
                    raise ValueError("保存特征清单与模型输入维数不匹配。")
                record["feature_count"] = len(features)
                record["target"] = config.get("target")
                record["target_column"] = {
                    "return": "y_excess_5d", "rank": "rank_target", "grade": "relevance",
                }.get(config.get("target"))
                estimator = model.steps[-1][1] if hasattr(model, "steps") else model
                record["n_iter"] = scalar_or_json(getattr(estimator, "n_iter_", None))
                record["max_iter"] = scalar_or_json(getattr(estimator, "max_iter", None))
                if record["kind"] == "mlp":
                    mlp_iterations.append({
                        "candidate": candidate, "year": year, "n_iter": record["n_iter"],
                        "max_iter": record["max_iter"],
                        "reached_max_iter": bool(estimator.n_iter_ >= estimator.max_iter),
                        "early_stopping": bool(estimator.early_stopping),
                    })
            except Exception as exc:
                artifact_errors.append({"artifact_path": artifact.as_posix(), "error": repr(exc)})
            records.append(record)

    table = pd.DataFrame(records).reindex(columns=COLUMNS).sort_values(["year", "batch", "candidate"])
    if len(table) != 114 or table.duplicated(["candidate", "year"]).any():
        raise AssertionError("应有 114 个唯一的实际训练记录。")
    for column in ("year", "feature_count", "train_rows", "validation_rows", "best_iteration",
                   "attempted_iterations", "n_iter", "max_iter", "warnings_count"):
        table[column] = pd.to_numeric(table[column], errors="raise").astype("Int64")

    # 只读取既有 2020—2025 预测文件，核对原 Huber/L2 的退化重复。
    duplicate_checks = []
    for year in range(2020, 2026):
        for split in ("validation", "development"):
            path = OUTPUT / str(year) / f"{split}_scores.csv"
            scores = pd.read_csv(path, usecols=["m18_lgb_return", "m19_lgb_huber"])
            left, right = scores.iloc[:, 0].to_numpy(), scores.iloc[:, 1].to_numpy()
            duplicate_checks.append({
                "year": year, "split": split, "rows": len(scores),
                "exactly_equal": bool(np.array_equal(left, right)),
                "max_absolute_difference": float(np.max(np.abs(left - right))),
            })

    warning_counts = Counter(message for event in warning_events for message in event["warnings"])
    diagnostics = {
        "scope": "Read existing 2015-2025 research summaries/models/predictions only; no fit, no new market data, no 2026 access.",
        "total_training_runs": len(table),
        "successful_summary_records": int(table.status.eq("trained").sum()),
        "runs_by_batch": table.groupby("batch").size().to_dict(),
        "successful_runs_by_year": {str(year): int(count) for year, count in table.loc[table.status.eq("trained")].groupby("year").size().items()},
        "runs_by_year_and_batch": [
            {"year": int(year), "batch": batch_name, "runs": int(count)}
            for (year, batch_name), count in table.groupby(["year", "batch"]).size().items()
        ],
        "artifact_files_present": int(table.artifact_exists.sum()),
        "artifact_models_loaded": len(table) - len(missing_artifacts) - len(artifact_errors),
        "missing_artifacts": missing_artifacts, "artifact_load_errors": artifact_errors,
        "warning_capture": {
            "captured_runs": int(table.warning_capture_status.eq("captured").sum()),
            "unavailable_runs": int(table.warning_capture_status.eq("unavailable").sum()),
            "captured_runs_with_warnings": len(warning_events),
            "captured_runs_without_warnings": int((table.warning_capture_status.eq("captured") & table.warnings_count.eq(0)).sum()),
            "unavailable_reason": "The 12 Huber followup training summaries do not capture warnings; absence of records does not establish absence of warnings.",
            "warning_message_counts": dict(warning_counts), "warning_events": warning_events,
        },
        "mlp_actual_iterations": mlp_iterations,
        "mlp_reached_max_iter_runs": sum(item["reached_max_iter"] for item in mlp_iterations),
        "original_m18_m19_duplicate": {
            "all_six_years_validation_and_development_exactly_equal": all(item["exactly_equal"] for item in duplicate_checks),
            "checks": duplicate_checks,
            "interpretation": "Original regression and default-alpha Huber are separate fit runs but not distinct prediction results; the two scaled Huber followups remain separate candidates.",
        },
        "missing_field_policy": "Unrecorded fields remain blank in CSV. In particular, followup train_first and warnings are not inferred from other runs.",
        "iteration_semantics": "n_iter is read from the saved final estimator: MLP epochs, ElasticNet solver iterations, or LightGBM retained boosting iterations. attempted_iterations is the recorded validation-curve length and may exceed the retained best_iteration.",
        "fit_seconds_semantics": "Copied verbatim from each source summary's seconds field. Timing scopes in the original and followup scripts are not identical; these numbers are not a controlled model-speed comparison.",
        "does_not_count_as_fitting": "The original 60 rule calculations and 18 fixed ensembles are excluded from the 114 fitted-model rows.",
    }
    table.to_csv(OUTPUT / "ALL_TRAINING_RUNS.csv", index=False, encoding="utf-8-sig")
    (OUTPUT / "training_diagnostics.json").write_text(
        json.dumps(diagnostics, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({
        "rows": len(table), "loaded_artifacts": diagnostics["artifact_models_loaded"],
        "warnings": diagnostics["warning_capture"],
        "mlp_reached_max_iter_runs": diagnostics["mlp_reached_max_iter_runs"],
        "original_m18_m19_exactly_equal": diagnostics["original_m18_m19_duplicate"]["all_six_years_validation_and_development_exactly_equal"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    collect()
