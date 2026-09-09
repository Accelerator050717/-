"""第 5 步：给历史特征配上未来超额收益标签；不训练、不回测。"""

import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent
LOOKBACK = 10   # 沿用第 4 步现有的过去观察窗口
HORIZON = 5     # 本轮试用：入场之后经过多少个交易日再离场
ENTRY_LAG = 1   # 收盘数据到齐后观察，下一交易日开盘入场
X_COLUMNS = ["aapl_ret_1d", f"aapl_ret_{LOOKBACK}d", f"aapl_relative_{LOOKBACK}d"]
TARGET = f"y_excess_{HORIZON}d"


def read_table(path):
    table = pd.read_csv(path, index_col="Date", parse_dates=["Date"])
    if (table.empty or table.index.hasnans or not table.index.is_unique
            or not table.index.is_monotonic_increasing):
        raise ValueError(f"{path.name}: 日期为空、重复或顺序错误，请核查。")
    return table


def build_labels(aapl, spy, horizon=HORIZON, entry_lag=ENTRY_LAG):
    if any(not isinstance(value, int) or value < 1 for value in (horizon, entry_lag)):
        raise ValueError("horizon 和 entry_lag 必须是正整数。")
    if not aapl.index.equals(spy.index):
        raise ValueError("AAPL 与 SPY 日期不一致，不能计算不同区间的超额收益。")

    # t 行存放未来的入场和离场日期，用于核查；它们不是输入特征。
    dates = pd.Series(aapl.index, index=aapl.index)
    labels = pd.DataFrame(index=aapl.index)
    labels["entry_date"] = dates.shift(-entry_lag)
    labels["exit_date"] = dates.shift(-(entry_lag + horizon))

    for symbol, prices in (("aapl", aapl), ("spy", spy)):
        required = prices[["Open", "Close", "Adj Close"]]
        if not required.gt(0).all().all() or required.eq(float("inf")).any().any():
            raise ValueError(f"{symbol}: 开盘价或调整所需价格无效，不补价格。")
        # 沿用 yfinance 比例调整口径；这不是实际成交报价或现金分红账本。
        adjusted_open = prices["Open"] * (prices["Adj Close"] / prices["Close"])
        entry_price = adjusted_open.shift(-entry_lag)
        exit_price = adjusted_open.shift(-(entry_lag + horizon))
        labels[f"{symbol}_entry_adj_open"] = entry_price
        labels[f"{symbol}_exit_adj_open"] = exit_price
        labels[f"{symbol}_forward_{horizon}d"] = exit_price / entry_price - 1

    labels[f"y_excess_{horizon}d"] = (
        labels[f"aapl_forward_{horizon}d"] - labels[f"spy_forward_{horizon}d"]
    )
    return labels


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    processed = ROOT / "data" / "processed"
    features = read_table(processed / f"returns_features_{LOOKBACK}d.csv")
    aapl = read_table(ROOT / "data" / "raw" / "AAPL_2024-01-01_2025-01-01.csv")
    spy = read_table(ROOT / "data" / "raw" / "SPY_2024-01-01_2025-01-01.csv")
    if not features.index.equals(aapl.index):
        raise ValueError("特征表与原始行情日期不一致，请先重新检查第 4 步。")
    if len(features) <= LOOKBACK + ENTRY_LAG + HORIZON:
        raise ValueError("记录不足，无法同时形成完整的特征和标签。")

    labels = build_labels(aapl, spy)
    # 显式选 X：不能把 labels 中的未来价格或收益作为模型输入。
    X = features[X_COLUMNS]
    y = labels[TARGET]
    x_ready = X.notna().all(axis=1)
    y_ready = y.notna()
    ready = x_ready & y_ready
    expected_ready = len(features) - LOOKBACK - ENTRY_LAG - HORIZON
    if (not X.iloc[:LOOKBACK].isna().any(axis=1).all()
            or not x_ready.iloc[LOOKBACK:].all()
            or X.isin([float("inf"), -float("inf")]).any().any()):
        raise ValueError("X 的缺失位置或数值异常，请核查第 4 步。")
    tail = ENTRY_LAG + HORIZON
    if not y_ready.iloc[:-tail].all() or y_ready.iloc[-tail:].any():
        raise ValueError("标签缺失位置异常，应当仅在文件尾部缺失。")
    if int(ready.sum()) != expected_ready:
        raise ValueError("完整样本数与时间窗口不符。")
    if not ((labels.loc[y_ready, "entry_date"] > labels.index[y_ready])
            & (labels.loc[y_ready, "exit_date"] > labels.loc[y_ready, "entry_date"])).all():
        raise ValueError("观察、入场、离场的时间顺序错误。")

    # 模拟数据只到某日：只有离场日已出现的标签才完整，不能填补尾端。
    cutoff = "2024-06-28"
    prefix = build_labels(aapl.loc[:cutoff], spy.loc[:cutoff])
    matured_dates = prefix.index[prefix[TARGET].notna()]
    pd.testing.assert_frame_equal(prefix.loc[matured_dates], labels.loc[matured_dates])
    if prefix[TARGET].tail(tail).notna().any():
        raise ValueError("截断数据后尾端仍出现完整标签，需检查未来数据依赖。")

    samples = pd.concat([X, labels], axis=1)
    output = processed / f"samples_lb{LOOKBACK}_h{HORIZON}_lag{ENTRY_LAG}.csv"
    samples.to_csv(output, date_format="%Y-%m-%d")  # 保留头尾缺失，便于理解
    print(f"过去观察 {LOOKBACK} 日；下一交易日开盘入场；再过 {HORIZON} 日开盘离场")
    print("X 列:", X_COLUMNS)
    print("y 列:", TARGET)
    print(f"总记录 {len(samples)}；X 完整 {x_ready.sum()}；y 完整 {y_ready.sum()}；同时完整 {ready.sum()}")
    print(f"完整样本观察日期: {samples.index[ready][0].date()} 至 {samples.index[ready][-1].date()}")
    print(f"前 {LOOKBACK} 行历史不足；后 {tail} 行在文件内没有完整未来区间。")
    print("\n真实标签样例（收益为百分比，y 为百分点；CSV 均存小数）:")
    preview = labels.loc[["2024-01-17", "2024-02-08"],
                         ["entry_date", "exit_date", f"aapl_forward_{HORIZON}d",
                          f"spy_forward_{HORIZON}d", TARGET]].copy()
    preview.iloc[:, 2:] *= 100
    print(preview.to_string(float_format=lambda value: f"{value:.6f}"))
    print("\n时间顺序、缺失边界和截断后已完整标签的一致性检查通过。")
    print(f"已保存: {output}")
    print("该文件包含未来核查列；以后训练只取 X_COLUMNS，不能自动选取所有数值列。")
    print("相邻样本的未来区间会重叠，不能把这些标签当成独立交易收益相加。")


if __name__ == "__main__":
    main()
