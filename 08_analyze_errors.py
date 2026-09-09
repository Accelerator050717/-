"""第 8 步：分析已保存预测的误差；不重新训练、不筛除困难样本。"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
EXPERIMENT = ROOT / "data" / "experiments" / "ridge_2024-07-01_lb10_h5_lag1_alpha1"
SAMPLES = ROOT / "data" / "processed" / "samples_lb10_h5_lag1.csv"
TOP_N = 5  # 仅控制展示数量，不改变数据或模型


def build_errors(predictions, samples):
    test = predictions.loc[predictions["split"].eq("test")].copy()
    if (test.empty or test.index.hasnans or not test.index.is_unique
            or not test.index.is_monotonic_increasing or not samples.index.is_unique):
        raise ValueError("预测表或样本表的日期无效，请先检查。")
    if not np.isfinite(test[["y_true", "pred_ridge", "pred_zero"]].to_numpy()).all():
        raise ValueError("预测或标签含缺失/无穷值，不删除异常行来改善成绩。")
    # 用日期对齐标签区间，不能按行号把入场/离场日期拼错。
    context = samples.loc[test.index]
    np.testing.assert_allclose(test["y_true"], context["y_excess_5d"], atol=1e-12)
    if not ((context["entry_date"] > context.index)
            & (context["exit_date"] > context["entry_date"])).all():
        raise ValueError("观察、入场、离场日期缺失或顺序错误。")

    errors = context[["entry_date", "exit_date"]].copy()
    # 本报告把收益小数全部转成百分点；平方误差的单位为百分点平方。
    errors["actual_pp"] = test["y_true"] * 100
    errors["prediction_pp"] = test["pred_ridge"] * 100
    errors["error_pp"] = errors["prediction_pp"] - errors["actual_pp"]
    errors["abs_error_pp"] = errors["error_pp"].abs()
    errors["zero_abs_error_pp"] = ((test["pred_zero"] - test["y_true"]) * 100).abs()
    errors["squared_error_pp2"] = errors["error_pp"] ** 2
    errors["zero_squared_error_pp2"] = errors["zero_abs_error_pp"] ** 2
    errors["extra_squared_error_pp2"] = (
        errors["squared_error_pp2"] - errors["zero_squared_error_pp2"]
    )  # 正值：该样本上，岭回归比零预测错得更多
    return errors


def summarize(errors):
    return {
        "n": len(errors),
        "zero_rmse_pp": np.sqrt(errors["zero_squared_error_pp2"].mean()),
        "ridge_rmse_pp": np.sqrt(errors["squared_error_pp2"].mean()),
        "ridge_mae_pp": errors["abs_error_pp"].mean(),
        "mean_error_pp": errors["error_pp"].mean(),
        "extra_mse_pp2": errors["extra_squared_error_pp2"].mean(),
    }


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    predictions = pd.read_csv(EXPERIMENT / "predictions.csv", index_col="Date", parse_dates=["Date"])
    samples = pd.read_csv(SAMPLES, index_col="Date", parse_dates=["Date", "entry_date", "exit_date"])
    errors = build_errors(predictions, samples)
    overall = summarize(errors)
    rows = []
    # 按观察日归属月份。标签的入场/离场区间可能跨月，不是月度投资收益。
    for month, group in errors.groupby(errors.index.to_period("M")):
        rows.append({"month": str(month), **summarize(group)})
    monthly = pd.DataFrame(rows)

    # 总体 MSE 是按行数加权的月度 MSE；不能直接平均月度 RMSE。
    weighted_mse = np.average(monthly["ridge_rmse_pp"] ** 2, weights=monthly["n"])
    np.testing.assert_allclose(np.sqrt(weighted_mse), overall["ridge_rmse_pp"], atol=1e-12)
    original = pd.read_csv(EXPERIMENT / "metrics.csv")
    prior = original.loc[original["split"].eq("test") & original["model"].eq("ridge")].iloc[0]
    np.testing.assert_allclose(
        [overall["ridge_rmse_pp"], overall["ridge_mae_pp"]],
        [prior["rmse_pp"], prior["mae_pp"]], atol=1e-12,
    )
    if int(monthly["n"].sum()) != len(errors):
        raise ValueError("按月分组漏掉或重复了样本。")

    output = EXPERIMENT / "error_analysis"
    output.mkdir(parents=True, exist_ok=True)
    errors.to_csv(output / "per_sample_errors.csv", date_format="%Y-%m-%d")
    monthly.to_csv(output / "monthly_errors.csv", index=False)
    display_columns = ["entry_date", "exit_date", "actual_pp", "prediction_pp", "error_pp"]
    print("按观察月份分组（收益/误差为百分点，extra_mse 为百分点平方）：")
    print(monthly.to_string(index=False, float_format=lambda value: f"{value:.4f}"))
    print(f"\n绝对误差最大的 {TOP_N} 条观察样本：")
    print(errors.nlargest(TOP_N, "abs_error_pp")[display_columns].to_string(
        float_format=lambda value: f"{value:.4f}"
    ))
    print("\n相对零预测，额外平方误差最大的 3 条观察样本：")
    print(errors.nlargest(3, "extra_squared_error_pp2")[
        display_columns + ["extra_squared_error_pp2"]
    ].to_string(float_format=lambda value: f"{value:.4f}"))
    # 1e-10 个百分点等于 1e-12 收益小数，仅用于区分浮点意义的平局。
    delta = errors["abs_error_pp"] - errors["zero_abs_error_pp"]
    better = int((delta < -1e-10).sum())
    worse = int((delta > 1e-10).sum())
    ties = len(errors) - better - worse
    print(f"\n比零预测误差更小/更大/持平的样本数: {better}/{worse}/{ties}")
    print(f"整体平均误差: {overall['mean_error_pp']:.4f} 个百分点；"
          f"整体 MAE: {overall['ridge_mae_pp']:.4f} 个百分点")
    print("注意平均正负误差会抵消；相邻标签区间重叠，不是独立交易。")
    print("日期对齐、原始成绩复算、分组数量及加权误差核对通过。")
    print(f"已保存: {output}")
    print("本分析用于形成待验证假设，不自动归因为新闻，不删除错误大的样本。")
    print("该观察段今后用于开发/验证；改进模型的最终测试需另留数据。")


if __name__ == "__main__":
    main()
