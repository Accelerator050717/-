"""第 4 步：把已保存的日线转换成历史收益特征，不计算未来标签。"""

import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent
RAW_DIR = ROOT / "data" / "raw"
LOOKBACK = 10  # 过去多少个交易日；不是预测周期，也不是持仓期


def read_prices(symbol):
    path = RAW_DIR / f"{symbol}_2024-01-01_2025-01-01.csv"
    frame = pd.read_csv(path, index_col="Date", parse_dates=["Date"])
    if frame.empty or frame.index.hasnans or not frame.index.is_unique:
        raise ValueError(f"{symbol}: 空表、缺失日期或重复日期，请先检查原始数据。")
    if not frame.index.is_monotonic_increasing:
        raise ValueError(f"{symbol}: 日期必须从早到晚排列。")
    price = frame["Adj Close"]
    if not price.gt(0).all() or price.eq(float("inf")).any():
        raise ValueError(f"{symbol}: 调整价缺失或无效，不自动补价格。")
    return frame


def build_features(aapl, spy, lookback=LOOKBACK):
    if not isinstance(lookback, int) or lookback < 1:
        raise ValueError("lookback 必须是正整数。")
    if not aapl.index.equals(spy.index):
        raise ValueError("AAPL 与 SPY 日期不一致，请先核查，不能按行号硬凑。")

    result = pd.DataFrame(index=aapl.index)
    # 两个价格列留作追溯；本步研究的是收益特征，不使用绝对价格当特征。
    result["aapl_adj_close"] = aapl["Adj Close"]
    result["spy_adj_close"] = spy["Adj Close"]
    aapl_price = result["aapl_adj_close"]
    spy_price = result["spy_adj_close"]

    # shift(k) 把 k 行前的数值移到当前行：只看过去，不填补开头的空值。
    result["aapl_ret_1d"] = aapl_price / aapl_price.shift(1) - 1
    result[f"aapl_ret_{lookback}d"] = aapl_price / aapl_price.shift(lookback) - 1
    result[f"spy_ret_{lookback}d"] = spy_price / spy_price.shift(lookback) - 1
    result[f"aapl_relative_{lookback}d"] = (
        result[f"aapl_ret_{lookback}d"] - result[f"spy_ret_{lookback}d"]
    )
    return result


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    aapl = read_prices("AAPL")
    spy = read_prices("SPY")
    if len(aapl) <= LOOKBACK:
        raise ValueError("历史记录不足，至少需要 lookback + 1 行价格。")
    result = build_features(aapl, spy)
    return_columns = list(result.columns[2:])
    complete = result[return_columns].notna().all(axis=1)

    # 自检：删掉后半年的输入再算，上半年的收益特征应完全不变。
    cutoff = "2024-06-28"
    prefix = build_features(aapl.loc[:cutoff], spy.loc[:cutoff])
    pd.testing.assert_frame_equal(result.loc[:cutoff], prefix)
    expected_complete = len(result) - LOOKBACK
    if int(complete.sum()) != expected_complete or result.iloc[LOOKBACK:].isna().any().any():
        raise ValueError("出现了开头观察窗口以外的缺失值，请核查。")

    output = ROOT / "data" / "processed" / f"returns_features_{LOOKBACK}d.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output, date_format="%Y-%m-%d")  # 小数形式；保留开头的 NaN
    print(f"输入 {len(result)} 行；观察窗口 {LOOKBACK} 个交易日")
    print(f"特征完整 {complete.sum()} 行；首个完整日期 {result.index[complete][0].date()}")
    print("各列缺失数:", result.isna().sum().to_dict())
    print("\n前 8 行收益（CSV 存小数；此处乘 100 显示，relative 的单位为百分点）:")
    print((result[return_columns].head(8) * 100).to_string(float_format=lambda v: f"{v:.4f}"))
    print(f"\n首个 {LOOKBACK} 日区间: {result.index[0].date()} 收盘 -> "
          f"{result.index[LOOKBACK].date()} 收盘")
    print("截断未来行检查通过：2024-06-28 之后的输入行不影响此前的收益特征。")
    print("该检查只验证计算方向；当前调整价快照不等于当时可得的数据版本。")

    # 用现有快照中的真实除息日，收束 Close / Adj Close 的差别。
    ex_date = "2024-02-09"
    close_return = aapl["Close"] / aapl["Close"].shift(1) - 1
    print(f"\nAAPL {ex_date} 分红: ${aapl.loc[ex_date, 'Dividends']:.2f}/股")
    print(f"Close 计算的当日价格收益: {close_return.loc[ex_date]:.4%}")
    print(f"Adj Close 计算的当日调整收益: {result.loc[ex_date, 'aapl_ret_1d']:.4%}")
    print(f"\n已保存: {output}")
    print("这些是收盘数据到齐后可计算的历史描述，不是预测，也不是策略收益。")


if __name__ == "__main__":
    main()
