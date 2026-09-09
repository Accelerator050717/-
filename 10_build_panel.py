"""把同一交易日历上的多股日线变成历史特征、未来标签和时间分组。"""

import json
import sys

import numpy as np
import pandas as pd

from panel_config import (
    BENCHMARK, END, ENTRY_LAG, HORIZON, PANEL_PATH, RAW_DIR, START,
    SYMBOLS, TEST_START, VALID_START,
)


# 训练只允许读取这些列；symbol、未来收益和未来日期都不是特征。
X_COLUMNS = [
    "ret_1d", "ret_5d", "ret_10d", "ret_20d", "ret_60d",
    "relative_5d", "relative_10d", "relative_20d", "relative_60d",
    "volatility_10d", "volatility_20d", "volatility_60d",
    "sma_gap_20d", "sma_gap_60d",
    "volume_ratio_1_20", "volume_ratio_5_20",
    "intraday_range", "overnight_gap",
    "spy_ret_5d", "spy_ret_20d", "spy_ret_60d", "spy_volatility_20d",
]
TARGET = "y_excess_5d"
PRICE_COLUMNS = ["Open", "High", "Low", "Close", "Adj Close"]


def read_raw(symbol):
    table = pd.read_csv(RAW_DIR / f"{symbol}.csv", index_col="Date", parse_dates=["Date"])
    if (table.empty or table.index.hasnans or not table.index.is_unique
            or not table.index.is_monotonic_increasing):
        raise ValueError(f"{symbol}: 日期为空、重复或乱序。")
    required = table[PRICE_COLUMNS + ["Volume"]]
    if np.isinf(required.to_numpy(dtype=float)).any():
        raise ValueError(f"{symbol}: 原始价格或成交量含无穷值。")
    if table[PRICE_COLUMNS].le(0).any().any() or table["Volume"].lt(0).any():
        raise ValueError(f"{symbol}: 价格必须为正、成交量不能为负。")
    return table


def adjusted_open(table):
    # Yahoo 的历史比例调整口径；这是收益研究用价格，不是可成交报价。
    return table["Open"] * table["Adj Close"] / table["Close"]


def build_one(stock, spy, symbol):
    """输入两份原始行情；输出一只股票在每个 SPY 交易日的研究样本。"""
    # 必须先对齐再 shift，否则某只股票缺一天会把“五天后”错移到不同日期。
    stock = stock.reindex(spy.index)
    assert stock.index.equals(spy.index)
    result = pd.DataFrame(index=spy.index)
    result.index.name = "Date"
    result["symbol"] = symbol
    close = stock["Adj Close"]
    spy_close = spy["Adj Close"]
    daily_return = close.pct_change(fill_method=None)
    spy_daily_return = spy_close.pct_change(fill_method=None)

    for days in (1, 5, 10, 20, 60):
        result[f"ret_{days}d"] = close / close.shift(days) - 1
    for days in (5, 10, 20, 60):
        market_return = spy_close / spy_close.shift(days) - 1
        result[f"relative_{days}d"] = result[f"ret_{days}d"] - market_return
    for days in (10, 20, 60):
        # 每日收益的样本标准差，尚未乘 sqrt(252) 年化。
        result[f"volatility_{days}d"] = daily_return.rolling(days).std(ddof=1)
    for days in (20, 60):
        result[f"sma_gap_{days}d"] = close / close.rolling(days).mean() - 1

    volume = stock["Volume"]
    volume_mean_20 = volume.rolling(20).mean()
    result["volume_ratio_1_20"] = volume / volume_mean_20
    result["volume_ratio_5_20"] = volume.rolling(5).mean() / volume_mean_20
    result["intraday_range"] = (stock["High"] - stock["Low"]) / stock["Close"]
    result["overnight_gap"] = adjusted_open(stock) / close.shift(1) - 1
    for days in (5, 20, 60):
        result[f"spy_ret_{days}d"] = spy_close / spy_close.shift(days) - 1
    result["spy_volatility_20d"] = spy_daily_return.rolling(20).std(ddof=1)

    # 收盘后形成样本；下一交易日开盘入场，再经过 HORIZON 个交易日离场。
    dates = pd.Series(spy.index, index=spy.index)
    result["entry_date"] = dates.shift(-ENTRY_LAG)
    result["exit_date"] = dates.shift(-(ENTRY_LAG + HORIZON))
    for name, raw in (("stock", stock), ("spy", spy)):
        opened = adjusted_open(raw)
        result[f"{name}_forward_return"] = (
            opened.shift(-(ENTRY_LAG + HORIZON)) / opened.shift(-ENTRY_LAG) - 1
        )
    result[TARGET] = result["stock_forward_return"] - result["spy_forward_return"]
    return result[["symbol", *X_COLUMNS, "entry_date", "exit_date",
                   "stock_forward_return", "spy_forward_return", TARGET]]


def assign_splits(panel):
    """给所有行标明用途；历史/未来不足的行也保留在输出文件中。"""
    result = panel.copy()
    x_ready = np.isfinite(result[X_COLUMNS].to_numpy(dtype=float)).all(axis=1)
    y_ready = np.isfinite(result[TARGET].to_numpy(dtype=float))
    ready = x_ready & y_ready
    dates = result["Date"]
    exits = result["exit_date"]
    if not ((result.loc[ready, "entry_date"] > dates[ready])
            & (exits[ready] > result.loc[ready, "entry_date"])).all():
        raise ValueError("观察、入场和离场日期的顺序错误。")

    # 同时缺历史和未来时优先标 missing_history；两个 ready 列保留完整原因。
    result["features_ready"] = x_ready
    result["label_ready"] = y_ready
    result["split"] = "missing_history"
    result.loc[x_ready & ~y_ready, "split"] = "missing_future"
    train_period = ready & dates.lt(VALID_START)
    valid_period = ready & dates.ge(VALID_START) & dates.lt(TEST_START)
    result.loc[train_period, "split"] = "purged_train"
    result.loc[train_period & exits.lt(VALID_START), "split"] = "train"
    result.loc[valid_period, "split"] = "purged_validation"
    result.loc[valid_period & exits.lt(TEST_START), "split"] = "validation"
    result.loc[ready & dates.ge(TEST_START), "split"] = "test"
    assert result.loc[result["split"].eq("train"), "exit_date"].lt(VALID_START).all()
    assert result.loc[result["split"].eq("validation"), "exit_date"].lt(TEST_START).all()
    return result


def check_one(stock, spy, symbol, full):
    """用截断数据和直接取价格的方式，检查时点与标签公式。"""
    cutoff = "2024-06-28"
    prefix = build_one(stock.loc[:cutoff], spy.loc[:cutoff], symbol)
    pd.testing.assert_frame_equal(prefix[X_COLUMNS], full.loc[:cutoff, X_COLUMNS])
    matured = prefix[TARGET].notna()
    audit_columns = ["entry_date", "exit_date", "stock_forward_return",
                     "spy_forward_return", TARGET]
    pd.testing.assert_frame_equal(prefix.loc[matured, audit_columns],
                                  full.loc[prefix.index[matured], audit_columns])
    assert prefix[TARGET].tail(ENTRY_LAG + HORIZON).isna().all()

    stock_open = adjusted_open(stock.reindex(spy.index))
    spy_open = adjusted_open(spy)
    available = np.flatnonzero(np.isfinite(full[TARGET].to_numpy(dtype=float)))
    # 首个标签以及一次公司行动附近的标签，避免只检查普通交易日。
    positions = [int(available[0])]
    for action in ("Dividends", "Stock Splits"):
        if action in stock:
            action_dates = stock.index[stock[action].fillna(0).ne(0)]
            for action_date in action_dates:
                position = spy.index.get_indexer([action_date])[0] - ENTRY_LAG
                if position >= 0 and position in available:
                    positions.append(int(position))
                    break
    for position in positions:
        entry = position + ENTRY_LAG
        exit_ = entry + HORIZON
        expected = (stock_open.iloc[exit_] / stock_open.iloc[entry] - 1
                    - (spy_open.iloc[exit_] / spy_open.iloc[entry] - 1))
        np.testing.assert_allclose(full[TARGET].iloc[position], expected, rtol=1e-12, atol=1e-14)
        assert full["entry_date"].iloc[position] == spy.index[entry]
        assert full["exit_date"].iloc[position] == spy.index[exit_]
    return {"symbol": symbol, "prefix_cutoff": cutoff, "manual_label_checks": len(positions)}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    if HORIZON != 5 or ENTRY_LAG != 1:
        raise ValueError("本实验约定 t+1 至 t+6；修改周期时必须同步标签定义和实验配置。")
    spy = read_raw(BENCHMARK)
    frames, checks, date_gaps = [], [], {}
    for number, symbol in enumerate(SYMBOLS):
        stock = read_raw(symbol)
        missing = spy.index.difference(stock.index)
        extra = stock.index.difference(spy.index)
        date_gaps[symbol] = {"missing": missing.strftime("%Y-%m-%d").tolist(),
                             "extra": extra.strftime("%Y-%m-%d").tolist()}
        if len(extra):
            raise ValueError(f"{symbol}: 存在 SPY 日历以外日期，应先检查下载数据。")
        frame = build_one(stock, spy, symbol)
        if number < 2:
            checks.append(check_one(stock, spy, symbol, frame))
        frames.append(frame)

    panel = pd.concat(frames).reset_index().sort_values(["Date", "symbol"]).reset_index(drop=True)
    if panel.duplicated(["Date", "symbol"]).any():
        raise ValueError("同一股票、同一日期重复。")
    assert len(panel) == len(spy) * len(SYMBOLS)
    panel = assign_splits(panel)
    for column in ("entry_date", "exit_date"):
        if not panel.groupby("Date")[column].nunique(dropna=False).eq(1).all():
            raise ValueError(f"同一观察日的 {column} 在股票之间不一致。")
    for split in ("train", "validation", "test"):
        daily_counts = panel.loc[panel["split"].eq(split)].groupby("Date")["symbol"].nunique()
        if daily_counts.empty or not daily_counts.eq(len(SYMBOLS)).all():
            raise ValueError(f"{split}: 某交易日没有完整的 {len(SYMBOLS)} 只股票，请核查原始缺失。")
    summary_rows = []
    for split, rows in panel.groupby("split", sort=True):
        summary_rows.append({"split": split, "rows": len(rows),
                             "dates": rows["Date"].nunique(),
                             "first_date": rows["Date"].min().strftime("%Y-%m-%d"),
                             "last_date": rows["Date"].max().strftime("%Y-%m-%d"),
                             "symbols": rows["symbol"].nunique()})
    summary = {
        "source_directory": str(RAW_DIR), "start_inclusive": START, "end_exclusive": END,
        "benchmark": BENCHMARK, "symbols": list(SYMBOLS), "feature_columns": X_COLUMNS,
        "target": TARGET, "entry_lag": ENTRY_LAG, "horizon": HORIZON,
        "validation_start": VALID_START, "test_start": TEST_START,
        "total_rows": len(panel), "dates": len(spy), "splits": summary_rows,
        "counts_per_symbol": panel.groupby(["symbol", "split"]).size().unstack(fill_value=0).to_dict("index"),
        "raw_date_gaps": date_gaps, "checks": checks,
        "common_label_dates_across_symbols": True,
        "complete_daily_universe_in_model_splits": True,
        "return_units": "decimal; volatility is daily standard deviation, not annualized",
        "limitations": ["Current surviving stock list is not a historical constituent universe.",
                        "Yahoo adjusted-open ratios are research proxies, not executable prices.",
                        "Prefix checks cannot establish point-in-time availability of the data vendor snapshot."],
    }
    PANEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(PANEL_PATH, index=False, date_format="%Y-%m-%d")
    PANEL_PATH.with_suffix(".json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"已保存 {len(SYMBOLS)} 只股票 × {len(spy)} 个交易日 = {len(panel):,} 行，{len(X_COLUMNS)} 个特征。")
    print(pd.DataFrame(summary_rows).to_string(index=False))
    print(f"日期缺口数：{sum(len(value['missing']) for value in date_gaps.values())}；缺口没有填价格。")
    print("两只股票的截断特征检查、已成熟标签检查和直接取价核查通过。")
    print("同日入场/离场日期一致；训练、验证、测试的每个观察日均有完整股票池。")
    print(f"输出：{PANEL_PATH}")


if __name__ == "__main__":
    main()
