"""第 6 步：按时间划分研究样本，排除训练时尚未完整的标签。"""

import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "data" / "processed" / "samples_lb10_h5_lag1.csv"
SPLIT_DATE = "2024-07-01"  # 模型在此日期前冻结；从此日的观察样本开始测试
X_COLUMNS = ["aapl_ret_1d", "aapl_ret_10d", "aapl_relative_10d"]
TARGET = "y_excess_5d"


def split_samples(samples, split_date=SPLIT_DATE):
    cutoff = pd.Timestamp(split_date)
    if (samples.empty or samples.index.hasnans or not samples.index.is_unique
            or not samples.index.is_monotonic_increasing):
        raise ValueError("观察日期为空、重复或顺序错误，请先核查样本表。")
    values = samples[X_COLUMNS + [TARGET]]
    if values.isin([float("inf"), -float("inf")]).any().any():
        raise ValueError("X 或 y 含无穷值，请先核查。")
    x_ready = samples[X_COLUMNS].notna().all(axis=1)
    y_ready = samples[TARGET].notna()
    ready = x_ready & y_ready

    if not ((samples.loc[ready, "entry_date"] > samples.index[ready])
            & (samples.loc[ready, "exit_date"] > samples.loc[ready, "entry_date"])).all():
        raise ValueError("完整样本的入场、离场日期缺失或时间顺序错误。")

    # 核心：观察日早于分界还不够，训练标签也必须在分界前完整。
    before_cutoff = samples.index < cutoff
    label_known = samples["exit_date"] < cutoff
    train_mask = ready & before_cutoff & label_known
    test_mask = ready & ~before_cutoff
    purged_mask = ready & before_cutoff & ~label_known

    # 保留日期供核查；模型的输入仍然只允许使用 X_COLUMNS。
    columns = ["entry_date", "exit_date"] + X_COLUMNS + [TARGET]
    train = samples.loc[train_mask, columns].copy()
    test = samples.loc[test_mask, columns].copy()
    if train.empty or test.empty:
        raise ValueError("该分界下训练集或测试集为空，请调整分界或增加数据。")

    assignments = samples[["entry_date", "exit_date"]].copy()
    assignments["x_ready"] = x_ready
    assignments["y_ready"] = y_ready
    assignments["split"] = "incomplete"
    assignments.loc[train_mask, "split"] = "train"
    assignments.loc[test_mask, "split"] = "test"
    assignments.loc[purged_mask, "split"] = "purged_label_not_known"

    # 检查时间边界、集合不相交，以及每条完整样本都有去向。
    if len(train.index.intersection(test.index)):
        raise ValueError("训练集和测试集出现重复样本。")
    if train.index.max() >= test.index.min() or train["exit_date"].max() >= cutoff:
        raise ValueError("训练样本或其标签跨越了指定训练截止时间。")
    if len(train) + len(test) + int(purged_mask.sum()) != int(ready.sum()):
        raise ValueError("完整样本的分配数量不一致。")
    return train, test, assignments


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    samples = pd.read_csv(
        SOURCE, index_col="Date", parse_dates=["Date", "entry_date", "exit_date"]
    )
    train, test, assignments = split_samples(samples)
    purged = assignments[assignments["split"] == "purged_label_not_known"]
    incomplete = assignments[assignments["split"] == "incomplete"]
    output_dir = ROOT / "data" / "splits" / f"{SPLIT_DATE}_lb10_h5_lag1"
    output_dir.mkdir(parents=True, exist_ok=True)
    train.to_csv(output_dir / "train.csv", date_format="%Y-%m-%d")
    test.to_csv(output_dir / "test.csv", date_format="%Y-%m-%d")
    assignments.to_csv(output_dir / "split_assignments.csv", date_format="%Y-%m-%d")

    print(f"测试观察日期起点: {SPLIT_DATE}；模型在该日期前冻结")
    print(f"总记录 {len(samples)}；不完整 {len(incomplete)}；完整 {len(samples) - len(incomplete)}")
    print(f"仅按观察日会得到 {len(train) + len(purged)} 行候选训练样本")
    print(f"排除标签尚未完整的 {len(purged)} 行后：训练 {len(train)}；测试 {len(test)}")
    print(f"训练观察日期: {train.index.min().date()} 至 {train.index.max().date()}")
    print(f"最晚训练标签离场日期: {train['exit_date'].max().date()}")
    print(f"测试观察日期: {test.index.min().date()} 至 {test.index.max().date()}")
    print(f"首个测试样本: {test.index[0].date()} 观察 -> "
          f"{test.iloc[0]['entry_date'].date()} 入场 -> {test.iloc[0]['exit_date'].date()} 离场")
    print("\n被排除的边界样本（原始文件仍保留）:")
    print(purged[["entry_date", "exit_date"]].to_string())
    print(f"\nX_train: {train[X_COLUMNS].shape}; y_train: {train[TARGET].shape}")
    print(f"X_test: {test[X_COLUMNS].shape}; y_test: {test[TARGET].shape}")
    print("时间边界、样本互斥和数量核对通过；尚未拟合模型或标准化器。")
    print(f"已保存: {output_dir}")


if __name__ == "__main__":
    main()
