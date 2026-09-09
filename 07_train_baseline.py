"""第 7 步：训练一个岭回归，与两个常数预测比较；不调参、不回测。"""

import json
import sys
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, root_mean_squared_error
from sklearn.preprocessing import StandardScaler


ROOT = Path(__file__).resolve().parent
SPLIT_DATE = "2024-07-01"
SPLIT_NAME = f"{SPLIT_DATE}_lb10_h5_lag1"
SPLIT_DIR = ROOT / "data" / "splits" / SPLIT_NAME
X_COLUMNS = ["aapl_ret_1d", "aapl_ret_10d", "aapl_relative_10d"]
TARGET = "y_excess_5d"
ALPHA = 1.0  # 在看测试成绩前固定的起点，不代表最优值


def read_split(name):
    frame = pd.read_csv(
        SPLIT_DIR / f"{name}.csv", index_col="Date",
        parse_dates=["Date", "entry_date", "exit_date"],
    )
    if (frame.empty or frame.index.hasnans or not frame.index.is_unique
            or not frame.index.is_monotonic_increasing):
        raise ValueError(f"{name}: 日期或记录无效，请先核查第 6 步。")
    if not np.isfinite(frame[X_COLUMNS + [TARGET]].to_numpy()).all():
        raise ValueError(f"{name}: X/y 含缺失或无穷值，不自动填充。")
    if not ((frame["entry_date"] > frame.index)
            & (frame["exit_date"] > frame["entry_date"])).all():
        raise ValueError(f"{name}: 观察、入场、离场顺序错误。")
    return frame


def fit_ridge(X_train, y_train):
    """拟合只接收训练数据，测试数据不参与参数选择或标准化。"""
    scaler = StandardScaler()
    Z_train = scaler.fit_transform(X_train)
    model = Ridge(alpha=ALPHA, fit_intercept=True, solver="svd")
    model.fit(Z_train, y_train)
    return scaler, model


def make_predictions(X, scaler, model, training_mean):
    """这里不接收真实标签，只用已经学好的参数和当前 X 产生预测。"""
    Z = scaler.transform(X)  # 测试时只能 transform，不能重新 fit
    return pd.DataFrame({
        "pred_zero": np.zeros(len(X)),
        "pred_train_mean": np.full(len(X), training_mean),
        "pred_ridge": model.predict(Z),
    }, index=X.index)


def evaluate(y_true, predictions, split_name):
    rows = []
    for name in predictions.columns:
        rows.append({
            "split": split_name,
            "model": name.removeprefix("pred_"),
            "rows": len(y_true),
            # y 是收益率小数，乘 100 后，误差单位为百分点（pp）。
            "rmse_pp": root_mean_squared_error(y_true, predictions[name]) * 100,
            "mae_pp": mean_absolute_error(y_true, predictions[name]) * 100,
        })
    return pd.DataFrame(rows)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    train = read_split("train")
    test = read_split("test")
    cutoff = pd.Timestamp(SPLIT_DATE)
    if (train.index.max() >= cutoff or train["exit_date"].max() >= cutoff
            or test.index.min() < cutoff or len(train.index.intersection(test.index))):
        raise ValueError("训练/测试时间边界错误，请先核查第 6 步。")

    X_train, y_train = train[X_COLUMNS], train[TARGET]
    X_test, y_test = test[X_COLUMNS], test[TARGET]
    scaler, model = fit_ridge(X_train, y_train)
    training_mean = float(y_train.mean())  # 均值基线也只能使用训练 y
    pred_train = make_predictions(X_train, scaler, model, training_mean)
    pred_test = make_predictions(X_test, scaler, model, training_mean)
    metrics = pd.concat([
        evaluate(y_train, pred_train, "train"),
        evaluate(y_test, pred_test, "test"),
    ], ignore_index=True)

    # 用保存参数将预测还原为 z @ w + b，核对公式和模型输出一致。
    manual_prediction = (
        (X_test.to_numpy() - scaler.mean_) / scaler.scale_
    ) @ model.coef_ + model.intercept_
    np.testing.assert_allclose(manual_prediction, pred_test["pred_ridge"], atol=1e-12)
    if int(scaler.n_samples_seen_) != len(train):
        raise ValueError("标准化器使用的样本数量不是训练集行数。")

    output_dir = ROOT / "data" / "experiments" / f"ridge_{SPLIT_NAME}_alpha{ALPHA:g}"
    output_dir.mkdir(parents=True, exist_ok=True)
    metrics.to_csv(output_dir / "metrics.csv", index=False)
    predictions = pd.concat([
        pred_train.assign(split="train", y_true=y_train),
        pred_test.assign(split="test", y_true=y_test),
    ])
    predictions["error_ridge"] = predictions["pred_ridge"] - predictions["y_true"]
    predictions.to_csv(output_dir / "predictions.csv", date_format="%Y-%m-%d")
    details = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_split": str(SPLIT_DIR),
        "split_date": SPLIT_DATE,
        "x_columns": X_COLUMNS,
        "target": TARGET,
        "alpha": ALPHA,
        "solver": "svd",
        "train_rows": len(train),
        "test_rows": len(test),
        "training_target_mean": training_mean,
        "scaler_mean": scaler.mean_.tolist(),
        "scaler_scale": scaler.scale_.tolist(),
        "ridge_coef_on_standardized_x": model.coef_.tolist(),
        "ridge_intercept": float(model.intercept_),
        "prediction_formula": "((X - scaler_mean) / scaler_scale) @ coef + intercept",
        "prediction_units": "decimal excess return; 0.01 means 1 percentage point",
        "metric_units": "percentage points (pp)",
        "alpha_selection": "Fixed before test evaluation; no tuning in this lesson",
        "packages": {name: version(name) for name in
                     ("scikit-learn", "numpy", "pandas", "scipy")},
    }
    (output_dir / "model_details.json").write_text(
        json.dumps(details, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"训练 {len(train)} 行，测试 {len(test)} 行；特征: {X_COLUMNS}")
    print(f"岭回归 alpha={ALPHA:g}；训练标签均值 {training_mean * 100:.6f} 个百分点")
    print("\n误差（单位：百分点；越小越好）：")
    print(metrics.to_string(index=False, float_format=lambda value: f"{value:.6f}"))
    print("\n标准化后特征的系数（单位：百分点 / 1个训练标准差；不是因果效应）：")
    print(pd.Series(model.coef_ * 100, index=X_COLUMNS).to_string(float_format=lambda v: f"{v:.6f}"))
    print(f"截距: {model.intercept_ * 100:.6f} 个百分点")
    print("\n测试集前 3 行（单位：百分点；预测文件保存小数）：")
    preview = pred_test.assign(y_true=y_test).head(3) * 100
    print(preview.to_string(float_format=lambda value: f"{value:.6f}"))
    print("\n时间边界、标准化样本数量、预测公式核对通过。")
    print(f"已保存: {output_dir}")
    print("这是一次固定时间划分的教学实验。误差不代表策略收益，不据此调参或下单。")


if __name__ == "__main__":
    main()
