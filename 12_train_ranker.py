"""比较收益回归与同日股票排序；2024–2025 已见，只作开发比较。"""

import hashlib
import importlib
import json
import sys
import time
from datetime import datetime, timezone
from importlib.metadata import version

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.metrics import ndcg_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from panel_config import LGBM_PARAMS, PANEL_PATH, RIDGE_ALPHA, ROOT, SYMBOLS

features = importlib.import_module("10_build_panel")
previous = importlib.import_module("11_train_panel")
X_COLUMNS, TARGET = features.X_COLUMNS, features.TARGET
OUTPUT = ROOT / "data" / "experiments" / "panel_ranker_v1"
TOP_K = 5  # 评价预测排名前5的位置；本脚本不构建投资组合。
STOPPING_ROUNDS = 50
PARAMS = {**LGBM_PARAMS, "metric": "None"}
RANKER_PARAMS = {**PARAMS, "objective": "lambdarank", "label_gain": [0, 1, 2, 3, 4],
                 "lambdarank_truncation_level": 10}
METHODS = ("constant", "momentum_20d", "ridge", "regressor", "ranker")
PERIODS = (
    ("train", "2015-01-01", "2023-01-01"),
    ("validation_2023", "2023-01-01", "2024-01-01"),
    ("development_2024", "2024-01-01", "2025-01-01"),
    ("development_2025", "2025-01-01", "2026-01-01"),
)


def save_json(name, value):
    (OUTPUT / name).write_text(json.dumps(value, indent=2, ensure_ascii=False,
                                          allow_nan=False), encoding="utf-8")


def record_plan():
    plan = {
        "hypothesis": "Compare same-day ranking with predicting excess-return magnitude.",
        "features": X_COLUMNS, "source_target": TARGET, "symbols": list(SYMBOLS),
        "panel_sha256": hashlib.sha256(PANEL_PATH.read_bytes()).hexdigest(),
        "periods": [list(period) for period in PERIODS], "methods": list(METHODS),
        "regressor_parameters": PARAMS, "ranker_parameters": RANKER_PARAMS,
        "ridge_alpha": RIDGE_ALPHA, "top_k": TOP_K, "early_stopping_rounds": STOPPING_ROUNDS,
        "grades": "floor((average ascending within-date rank - 1) * 5 / stock count)",
        "primary_metric": "Mean daily NDCG@5 with linear 0..4 gains and averaged score ties",
        "stopping_and_selection": "Both trees stop using 2023 NDCG@5; compare fixed methods on same metric.",
        "secondary_metric": "Mean daily Spearman against continuous future excess return",
        "evaluation_status": "2024-2025 already seen in research; NOT new independent tests. No 2026 data used.",
    }
    path = OUTPUT / "plan.json"
    if path.exists():
        old = json.loads(path.read_text(encoding="utf-8"))
        old.pop("created_at_utc")
        if old != plan:
            raise ValueError("配置或输入已改变；请另建实验目录保留原记录。")
    else:
        save_json(path.name, {**plan, "created_at_utc": datetime.now(timezone.utc).isoformat()})


def prepare_samples():
    panel = pd.read_csv(PANEL_PATH, parse_dates=["Date", "entry_date", "exit_date"])
    panel = panel.sort_values(["Date", "symbol"]).reset_index(drop=True)
    ready = np.isfinite(panel[X_COLUMNS + [TARGET]].to_numpy()).all(axis=1)
    # 只改变监督目标：同一天真实收益较高的股票获得较高等级。
    ranks = panel.groupby("Date")[TARGET].rank(method="average", ascending=True)
    counts = panel.groupby("Date")[TARGET].transform("count")
    panel["relevance"] = np.floor((ranks - 1) * 5 / counts).astype("Int64")
    panel["ranking_split"] = "incomplete_features_or_label"
    frames, summaries = {}, []
    for name, start, end in PERIODS:
        in_period = ready & panel["Date"].ge(start) & panel["Date"].lt(end)
        panel.loc[in_period, "ranking_split"] = "purged_before_" + end
        selected = in_period & panel["exit_date"].lt(end)
        panel.loc[selected, "ranking_split"] = name
        rows = panel.loc[selected].copy().reset_index(drop=True)
        rows["relevance"] = rows["relevance"].astype(int)
        group = check_groups(rows)
        frames[name] = rows
        summaries.append({"split": name, "rows": len(rows), "dates": len(group),
                          "first_observation": str(rows["Date"].min().date()),
                          "last_observation": str(rows["Date"].max().date()),
                          "last_exit": str(rows["exit_date"].max().date())})
    panel[["Date", "symbol", "entry_date", "exit_date", "relevance", "ranking_split"]].to_csv(
        OUTPUT / "sample_assignments.csv", index=False, date_format="%Y-%m-%d")
    save_json("sample_summary.json", {"periods": summaries,
              "all_assignments": panel["ranking_split"].value_counts().to_dict()})
    print(pd.DataFrame(summaries).to_string(index=False), flush=True)
    return frames


def check_groups(rows):
    # LightGBM 的 group 表示连续行的组长度，不是每行的日期编号。
    assert rows["Date"].is_monotonic_increasing
    assert not rows.duplicated(["Date", "symbol"]).any()
    group = rows.groupby("Date", sort=False).size().to_numpy()
    assert group.sum() == len(rows) and (group == len(SYMBOLS)).all()
    grouped = rows.groupby("Date", sort=False)
    assert grouped["symbol"].agg(set).apply(lambda names: names == set(SYMBOLS)).all()
    assert grouped[["entry_date", "exit_date"]].nunique().eq(1).all().all()
    assert rows["relevance"].between(0, 4).all()
    assert rows.groupby(["Date", TARGET])["relevance"].nunique().eq(1).all()
    by_truth = rows.sort_values(["Date", TARGET])
    assert by_truth.groupby("Date")["relevance"].diff().dropna().ge(0).all()
    return group


def make_ranking_metric(validation):
    truth = validation["relevance"].to_numpy().reshape(-1, len(SYMBOLS))

    def metric(y_true, y_pred):
        # 闭包只持有验证期等级；两种模型使用同一个并列评分口径。
        assert len(y_true) == truth.size
        scores = np.asarray(y_pred).reshape(truth.shape)
        value = ndcg_score(truth, scores, k=TOP_K, ignore_ties=False)
        return "daily_ndcg5", float(value), True

    return metric


def fit_models(train, validation):
    metric = make_ranking_metric(validation)
    ridge = make_pipeline(StandardScaler(), Ridge(alpha=RIDGE_ALPHA, solver="svd"))
    ridge.fit(train[X_COLUMNS], train[TARGET])
    models, training = {"ridge": ridge}, {}
    for name, params, target in (("regressor", PARAMS, TARGET),
                                 ("ranker", RANKER_PARAMS, "relevance")):
        model_type = lgb.LGBMRegressor if name == "regressor" else lgb.LGBMRanker
        model = model_type(**params)
        group_arguments = {} if name == "regressor" else {
            "group": check_groups(train), "eval_group": [check_groups(validation)],
            "eval_at": [TOP_K],
        }
        started = time.perf_counter()
        print(f"开始训练 {name}，共同按2023排序指标停止", flush=True)
        model.fit(
            train[X_COLUMNS], train[target],
            eval_X=validation[X_COLUMNS], eval_y=validation[target],
            eval_names=["validation_2023"], eval_metric=metric,
            callbacks=[lgb.early_stopping(STOPPING_ROUNDS, first_metric_only=True),
                       lgb.log_evaluation(period=100)], **group_arguments,
        )
        curve = model.evals_result_["validation_2023"]["daily_ndcg5"]
        assert list(model.evals_result_["validation_2023"]) == ["daily_ndcg5"]
        assert model.best_iteration_ == int(np.argmax(curve)) + 1
        training[name] = {"best_iteration": int(model.best_iteration_),
                          "attempted_iterations": len(curve),
                          "best_validation_ndcg5": float(max(curve)),
                          "fit_seconds": time.perf_counter() - started}
        save_json(f"{name}_learning_curve.json", model.evals_result_)
        text = model.booster_.model_to_string(num_iteration=model.best_iteration_)
        (OUTPUT / f"{name}_model.txt").write_text(text, encoding="utf-8")
        restored = lgb.Booster(model_str=text)
        np.testing.assert_allclose(restored.predict(validation[X_COLUMNS], num_threads=4),
                                   model.predict(validation[X_COLUMNS]), atol=1e-14, rtol=1e-12)
        models[name] = model
    scaler, linear = ridge.named_steps["standardscaler"], ridge.named_steps["ridge"]
    save_json("ridge_model.json", {"features": X_COLUMNS, "mean": scaler.mean_.tolist(),
              "scale": scaler.scale_.tolist(), "coef": linear.coef_.tolist(),
              "intercept": float(linear.intercept_), "alpha": RIDGE_ALPHA})
    save_json("training_details.json", training)
    return models, training


def evaluate(rows, models, split):
    scores = pd.DataFrame({
        "score_constant": np.zeros(len(rows)),
        "score_momentum_20d": rows["ret_20d"].to_numpy(),
        **{f"score_{name}": model.predict(rows[X_COLUMNS]) for name, model in models.items()},
    })
    report = rows[["Date", "symbol", "entry_date", "exit_date", TARGET, "relevance"]].copy()
    report = report.rename(columns={TARGET: "y_true"}).join(scores)
    report["split"] = split
    grade_matrix = rows["relevance"].to_numpy().reshape(-1, len(SYMBOLS))
    dates = rows["Date"].drop_duplicates().to_numpy()
    summaries, all_daily = [], []
    for name in METHODS:
        score = report[f"score_{name}"]
        matrix = score.to_numpy().reshape(grade_matrix.shape)
        # 逐日保留指标，便于之后分析稳定性；并列分数按可能名次的平均处理。
        ndcg = [ndcg_score(grade[None, :], prediction[None, :], k=TOP_K, ignore_ties=False)
                for grade, prediction in zip(grade_matrix, matrix)]
        daily = previous.daily_rank_ic(report, score)
        np.testing.assert_array_equal(daily.index.to_numpy(), dates)
        daily["ndcg5"] = ndcg
        daily["split"], daily["method"] = split, name
        summaries.append({"split": split, "method": name, "rows": len(rows),
                          "dates": len(dates), "ndcg5": float(np.mean(ndcg)),
                          "rank_ic": daily["rank_ic"].mean(),
                          "valid_ic_dates": int(daily["rank_ic"].notna().sum())})
        all_daily.append(daily.reset_index())
    return report, pd.DataFrame(summaries), pd.concat(all_daily, ignore_index=True)


def check_metric_examples():
    # 虚构等级，仅测试新指标的方向和并列行为，不是行情或训练成绩。
    grades = np.repeat(np.arange(5), 6)[None, :]
    for scores, expected in ((grades, 1.0), (-grades, 0.0), (np.zeros_like(grades), 0.5)):
        np.testing.assert_allclose(ndcg_score(grades, scores, k=TOP_K, ignore_ties=False), expected)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    record_plan()
    if (OUTPUT / "metrics.csv").exists():
        print("显示已完成的固定排序实验；未重新训练。")
        print(pd.read_csv(OUTPUT / "metrics.csv").to_string(index=False))
        return
    check_metric_examples()
    frames = prepare_samples()
    models, training = fit_models(frames["train"], frames["validation_2023"])
    results = [evaluate(frames[name], models, name) for name in ("train", "validation_2023")]
    validation_metrics = results[1][1]
    selected = validation_metrics.sort_values("ndcg5", ascending=False, kind="stable").iloc[0]["method"]
    save_json("frozen_selection.json", {
        "saved_before_development_comparison_at_utc": datetime.now(timezone.utc).isoformat(),
        "selected_method": selected, "selection_metric": "2023 NDCG@5",
        "training": training,
        "versions": {name: version(name) for name in ("lightgbm", "scikit-learn", "pandas", "numpy")},
        "interpretation": "2024-2025 are already-seen development comparisons; no new final holdout score.",
    })
    for name in ("development_2024", "development_2025"):
        results.append(evaluate(frames[name], models, name))
    pd.concat([item[0] for item in results], ignore_index=True).to_csv(
        OUTPUT / "predictions.csv", index=False, date_format="%Y-%m-%d")
    pd.concat([item[2] for item in results], ignore_index=True).to_csv(
        OUTPUT / "daily_metrics.csv", index=False, date_format="%Y-%m-%d")
    metrics = pd.concat([item[1] for item in results], ignore_index=True)
    metrics.to_csv(OUTPUT / "metrics.csv", index=False)
    print(metrics.to_string(index=False, float_format=lambda value: f"{value:.6f}"))
    print(f"按2023排序指标选择：{selected}；保存到 {OUTPUT}")
    print("排序分数不是收益预测；NDCG/IC不是交易收益，本次无回测或交易信号。")


if __name__ == "__main__":
    main()
