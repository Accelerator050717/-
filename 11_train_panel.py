"""扩大实验：固定线性基线 + LightGBM；验证选模型，最后评估 2025。"""

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
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from panel_config import (
    EARLY_STOPPING_ROUNDS, END, ENTRY_LAG, EXPERIMENT_DIR, HORIZON,
    LGBM_PARAMS, PANEL_PATH, RAW_DIR, RIDGE_ALPHA, START, SYMBOLS,
    TEST_START, VALID_START,
)

features = importlib.import_module("10_build_panel")
X_COLUMNS, TARGET = features.X_COLUMNS, features.TARGET
MODEL_NAMES = ("zero", "train_mean", "ridge", "lightgbm")


def save_json(name, value):
    (EXPERIMENT_DIR / name).write_text(
        json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8"
    )


def fixed_plan():
    """先记录数据、特征、划分和候选模型，禁止用测试成绩回头修改同一实验。"""
    plan = {
        "symbols": list(SYMBOLS), "start": START, "end_exclusive": END,
        "features": X_COLUMNS, "target": TARGET,
        "entry_lag": ENTRY_LAG, "horizon": HORIZON,
        "validation_start": VALID_START, "test_start": TEST_START,
        "panel_sha256": hashlib.sha256(PANEL_PATH.read_bytes()).hexdigest(),
        "raw_sha256": {path.stem: hashlib.sha256(path.read_bytes()).hexdigest()
                       for path in sorted(RAW_DIR.glob("*.csv"))},
        "models": list(MODEL_NAMES), "ridge_alpha": RIDGE_ALPHA,
        "lightgbm": LGBM_PARAMS, "early_stopping_rounds": EARLY_STOPPING_ROUNDS,
        "selection_rule": "Lowest validation RMSE, including constants; no refit on validation.",
        "secondary_metric": "Mean daily cross-sectional Spearman; undefined for constants.",
        "test_policy": "One frozen comparison on 2025; no parameter selection using its scores.",
    }
    path = EXPERIMENT_DIR / "predeclared_plan.json"
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        existing.pop("created_at_utc")
        if existing != plan:
            raise ValueError("本实验的数据或配置已变化。请使用新的实验目录并明确测试期已被查看。")
    else:
        save_json(path.name, {**plan, "created_at_utc": datetime.now(timezone.utc).isoformat()})


def fit_models(train, validation):
    """只有训练和验证输入；最终测试数据不传入此函数。"""
    ridge = make_pipeline(StandardScaler(), Ridge(alpha=RIDGE_ALPHA, solver="svd"))
    ridge.fit(train[X_COLUMNS], train[TARGET])
    booster = lgb.LGBMRegressor(**LGBM_PARAMS, metric="rmse")
    booster.fit(
        train[X_COLUMNS], train[TARGET],
        eval_X=validation[X_COLUMNS], eval_y=validation[TARGET],
        eval_names=["validation"], eval_metric="rmse",
        callbacks=[lgb.early_stopping(EARLY_STOPPING_ROUNDS, first_metric_only=True),
                   lgb.log_evaluation(period=100)],
    )
    assert int(ridge.named_steps["standardscaler"].n_samples_seen_) == len(train)
    return ridge, booster, float(train[TARGET].mean())


def predict(X, ridge, booster, train_mean):
    """预测只读取 X，不读取未来真实标签。收益和预测始终存小数。"""
    return pd.DataFrame({
        "pred_zero": np.zeros(len(X)), "pred_train_mean": np.full(len(X), train_mean),
        "pred_ridge": ridge.predict(X),
        "pred_lightgbm": booster.predict(X, num_iteration=booster.best_iteration_),
    }, index=X.index)


def daily_rank_ic(rows, prediction):
    """先分别给每天的股票排序，再算相关；不能把不同日期混成一个排名。"""
    paired = rows[["Date", "y_true"]].copy()
    paired["prediction"] = prediction
    ranks = paired.groupby("Date")[["y_true", "prediction"]].rank(method="average")
    centered = ranks - ranks.groupby(paired["Date"]).transform("mean")
    terms = pd.DataFrame({
        "Date": paired["Date"],
        "cross": centered["y_true"] * centered["prediction"],
        "y_square": centered["y_true"] ** 2,
        "p_square": centered["prediction"] ** 2,
    }).groupby("Date").sum()
    denominator = np.sqrt(terms["y_square"] * terms["p_square"])
    ic = terms["cross"] / denominator.replace(0, np.nan)
    return pd.DataFrame({"rank_ic": ic, "stock_count": paired.groupby("Date").size()})


def evaluate(rows, predictions, split):
    output = rows[["Date", "symbol", "entry_date", "exit_date", TARGET]].copy()
    output = output.rename(columns={TARGET: "y_true"})
    output["split"] = split
    output = output.join(predictions)
    metrics, daily = [], []
    for name in MODEL_NAMES:
        predicted = output[f"pred_{name}"]
        error_pp = 100 * (predicted - output["y_true"])
        ic = daily_rank_ic(output, predicted)
        metrics.append({
            "split": split, "model": name, "rows": len(output),
            "rmse_pp": float(np.sqrt(np.mean(error_pp ** 2))),
            "mae_pp": float(np.mean(np.abs(error_pp))),
            "mean_daily_rank_ic": ic["rank_ic"].mean(),
            "valid_ic_dates": int(ic["rank_ic"].notna().sum()),
        })
        daily.append(ic.assign(split=split, model=name).reset_index())
    return output, pd.DataFrame(metrics), pd.concat(daily, ignore_index=True)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    EXPERIMENT_DIR.mkdir(parents=True, exist_ok=True)
    fixed_plan()
    metrics_path = EXPERIMENT_DIR / "metrics.csv"
    if metrics_path.exists():
        print("复用已完成的固定实验。2025 已经评估过，本次不重新拟合或挑参数。")
        print(pd.read_csv(metrics_path).to_string(index=False))
        return

    panel = pd.read_csv(PANEL_PATH, parse_dates=["Date", "entry_date", "exit_date"])
    train = panel.loc[panel["split"].eq("train")].copy()
    validation = panel.loc[panel["split"].eq("validation")].copy()
    assert train["exit_date"].max() < pd.Timestamp(VALID_START)
    assert validation["exit_date"].max() < pd.Timestamp(TEST_START)
    for rows in (train, validation):
        assert np.isfinite(rows[X_COLUMNS + [TARGET]].to_numpy()).all()
        assert rows.groupby("Date")["symbol"].nunique().eq(len(SYMBOLS)).all()
    print(f"训练 {len(train):,} 行 × {len(X_COLUMNS)} 特征；验证 {len(validation):,} 行", flush=True)

    started = time.perf_counter()
    ridge, booster, train_mean = fit_models(train, validation)
    fit_seconds = time.perf_counter() - started
    results = [evaluate(rows, predict(rows[X_COLUMNS], ridge, booster, train_mean), split)
               for split, rows in (("train", train), ("validation", validation))]
    validation_metrics = results[1][1]
    selected = validation_metrics.sort_values("rmse_pp", kind="stable").iloc[0]["model"]
    validation_metrics.to_csv(EXPERIMENT_DIR / "validation_metrics.csv", index=False)
    best_iteration = int(booster.best_iteration_)
    print(f"验证期选择: {selected}；LightGBM 保留 {best_iteration} 棵树；拟合 {fit_seconds:.2f} 秒", flush=True)

    # 保存并校验模型，再冻结选择；下一段才进行 2025 的预测和评分。
    model_text = booster.booster_.model_to_string(num_iteration=best_iteration)
    (EXPERIMENT_DIR / "lightgbm_model.txt").write_text(model_text, encoding="utf-8")
    restored = lgb.Booster(model_str=model_text)
    np.testing.assert_allclose(restored.predict(validation[X_COLUMNS], num_threads=4),
                               results[1][0]["pred_lightgbm"], rtol=1e-12, atol=1e-14)
    scaler, linear = ridge.named_steps["standardscaler"], ridge.named_steps["ridge"]
    save_json("ridge_model.json", {"features": X_COLUMNS, "mean": scaler.mean_.tolist(),
              "scale": scaler.scale_.tolist(), "coef": linear.coef_.tolist(),
              "intercept": float(linear.intercept_), "alpha": RIDGE_ALPHA})
    save_json("frozen_selection.json", {
        "frozen_before_test_at_utc": datetime.now(timezone.utc).isoformat(),
        "selected_model": selected, "criterion": "validation RMSE",
        "lightgbm_best_iteration": best_iteration, "train_mean": train_mean,
        "fit_seconds": fit_seconds, "no_validation_refit": True,
        "feature_order": X_COLUMNS,
        "packages": {name: version(name) for name in
                     ("lightgbm", "scikit-learn", "pandas", "numpy")},
    })
    save_json("learning_curve.json", booster.evals_result_)
    pd.DataFrame({"feature": X_COLUMNS, "training_split_gain": booster.feature_importances_})\
        .sort_values("training_split_gain", ascending=False)\
        .to_csv(EXPERIMENT_DIR / "feature_importance.csv", index=False)

    test = panel.loc[panel["split"].eq("test")].copy()
    assert test["Date"].min() >= pd.Timestamp(TEST_START)
    assert test["exit_date"].max() < pd.Timestamp(END)
    assert np.isfinite(test[X_COLUMNS + [TARGET]].to_numpy()).all()
    assert test.groupby("Date")["symbol"].nunique().eq(len(SYMBOLS)).all()
    results.append(evaluate(test, predict(test[X_COLUMNS], ridge, booster, train_mean), "test"))
    all_metrics = pd.concat([result[1] for result in results], ignore_index=True)
    pd.concat([result[0] for result in results], ignore_index=True).to_csv(
        EXPERIMENT_DIR / "predictions.csv", index=False, date_format="%Y-%m-%d")
    pd.concat([result[2] for result in results], ignore_index=True).to_csv(
        EXPERIMENT_DIR / "daily_rank_ic.csv", index=False, date_format="%Y-%m-%d")
    all_metrics.to_csv(metrics_path, index=False)
    print(all_metrics.to_string(index=False, float_format=lambda v: f"{v:.6f}"))
    print(f"保存至 {EXPERIMENT_DIR}")
    print("误差单位为百分点；Rank IC 不是收益率。没有组合回测、成本计算或订单。")


if __name__ == "__main__":
    main()
