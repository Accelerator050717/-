"""固定初始保护线的 H60 单笔标签；它不是每五日调仓组合的真实收益。

输入沿用研究回放的调整 OHLC 宽表。t 收盘观察，t+1 开盘入场，
t+H+1 开盘结束。提前止损后的现金零息持有至同一个结束日，基准也
使用完整 H 区间。所有标签都等到完整结束日成熟；不提前纳入早停样本。
"""
from numbers import Integral

import numpy as np
import pandas as pd


OHLC = ("Open", "High", "Low", "Close")


def _validate_bars(bars, *, name, calendar=None, one_symbol=False):
    if not isinstance(bars, dict) or not set(OHLC).issubset(bars):
        raise ValueError(f"{name}: 缺少 OHLC 宽表。")
    opened = bars["Open"]
    if not isinstance(opened, pd.DataFrame):
        raise ValueError(f"{name}: 每个字段必须是 DataFrame。")
    dates, symbols = opened.index, opened.columns
    if (not isinstance(dates, pd.DatetimeIndex) or dates.empty or dates.hasnans
            or not dates.is_unique or not dates.is_monotonic_increasing):
        raise ValueError(f"{name}: 日期为空、缺失、重复或乱序。")
    if calendar is not None and not dates.equals(calendar):
        raise ValueError(f"{name}: 与股票交易日历不一致，不补价格。")
    if (symbols.empty or not symbols.is_unique
            or not all(isinstance(s, str) and s for s in symbols)
            or (one_symbol and len(symbols) != 1)):
        raise ValueError(f"{name}: 股票列必须唯一且非空，基准必须只有一列。")
    arrays = {}
    for field in OHLC:
        frame = bars[field]
        if (not isinstance(frame, pd.DataFrame) or not frame.index.equals(dates)
                or not frame.columns.equals(symbols)):
            raise ValueError(f"{name}: OHLC 索引或列顺序不一致。")
        try:
            values = frame.to_numpy(dtype=float)
        except (ValueError, TypeError) as error:
            raise ValueError(f"{name}: 行情必须是数值。") from error
        if not np.isfinite(values).all() or (values <= 0).any():
            raise ValueError(f"{name}: 行情缺失、非有限或非正，不补价格。")
        arrays[field] = values
    if ((arrays["Low"] > np.minimum(arrays["Open"], arrays["Close"]) + 1e-10).any()
            or (arrays["High"] < np.maximum(arrays["Open"], arrays["Close"]) - 1e-10).any()
            or (arrays["Low"] > arrays["High"]).any()):
        raise ValueError(f"{name}: OHLC 高低关系非法。")
    return dates, symbols, arrays


def build_path_labels(bars, spy_bars, horizon=60, stop_fraction=.15,
                      cost_bps=10, stop_extra_bps=10):
    """返回全部 Date/symbol，包括未来标签尚未成熟的尾部。

    bars/spy_bars: dict[OHLC字段, DataFrame]，各字段行是共同交易日，
    列是股票/单一 SPY。exit_60 保留项目既有列名，实际间隔由 horizon 定义。

    普通净收益 = 出场/入场 × (1-单边费用)/(1+单边费用) - 1。
    gross 不扣普通费用，但止损成交仍含明确的额外滑点。基准统一减去
    SPY 的完整区间毛收益；提前止损不改变基准区间，也不重新投资。
    """
    if isinstance(horizon, bool) or not isinstance(horizon, Integral) or horizon < 1:
        raise ValueError("horizon 必须是正整数交易日数。")
    if not np.isfinite(stop_fraction) or not 0 < stop_fraction < 1:
        raise ValueError("stop_fraction 必须在 (0,1)。")
    for name, value in (("cost_bps", cost_bps), ("stop_extra_bps", stop_extra_bps)):
        if not np.isfinite(value) or not 0 <= value < 10000:
            raise ValueError(f"{name} 必须在 [0,10000)。")
    dates, symbols, stock = _validate_bars(bars, name="股票")
    _, _, market = _validate_bars(spy_bars, name="SPY", calendar=dates, one_symbol=True)
    dates_series = pd.Series(dates)
    entry_dates = dates_series.shift(-1)
    terminal_dates = dates_series.shift(-(horizon + 1))
    mature_count = max(0, len(dates) - horizon - 1)
    fee_factor = (1 - cost_bps / 10000) / (1 + cost_bps / 10000)
    stop_multiplier = 1 - stop_extra_bps / 10000
    stock_count = len(symbols)
    blocks = []

    for column, symbol in enumerate(symbols):
        row = pd.DataFrame({"Date": dates, "symbol": symbol,
                            "entry_date": entry_dates, "exit_60": terminal_dates})
        row["stopped_exit_date"] = terminal_dates.copy()
        row["stop_reason"] = pd.Series(pd.NA, index=row.index, dtype="string")
        for label in ("plain_net_excess", "stopped_net_excess",
                      "plain_gross_excess", "stopped_gross_excess"):
            row[label] = np.nan
        if mature_count:
            entry = stock["Open"][1:mature_count + 1, column]
            terminal = stock["Open"][horizon + 1:horizon + 1 + mature_count, column]
            threshold = entry * (1 - stop_fraction)
            plain_ratio = terminal / entry
            stopped_ratio = plain_ratio.copy()
            stopped_day = np.arange(mature_count) + horizon + 1
            reasons = np.full(mature_count, "horizon", dtype=object)
            alive = np.ones(mature_count, dtype=bool)

            # 同时扫描所有观察日：先开盘穿价，再盘中穿价；第一次退出后不再交易。
            for offset in range(1, horizon + 2):
                opened = stock["Open"][offset:offset + mature_count, column]
                gap = alive & (opened <= threshold)
                stopped_ratio[gap] = opened[gap] / entry[gap] * stop_multiplier
                reasons[gap] = "stop_gap"
                stopped_day[gap] = np.flatnonzero(gap) + offset
                alive[gap] = False
                if offset == horizon + 1:
                    # 和现有回放相同：末次开盘的已有止损先处理；末日 Low 不可用。
                    break
                low = stock["Low"][offset:offset + mature_count, column]
                intraday = alive & (low <= threshold)
                # 直接使用比例，避免不同股价的等价保护收益被浮点乘除拆成不同名次。
                stopped_ratio[intraday] = (1 - stop_fraction) * stop_multiplier
                reasons[intraday] = "stop_intraday"
                stopped_day[intraday] = np.flatnonzero(intraday) + offset
                alive[intraday] = False

            spy_ratio = (market["Open"][horizon + 1:horizon + 1 + mature_count, 0]
                         / market["Open"][1:mature_count + 1, 0])
            labels = {
                "plain_gross_excess": plain_ratio - spy_ratio,
                "stopped_gross_excess": stopped_ratio - spy_ratio,
                "plain_net_excess": plain_ratio * fee_factor - spy_ratio,
                "stopped_net_excess": stopped_ratio * fee_factor - spy_ratio,
            }
            for name, values in labels.items():
                row.loc[:mature_count - 1, name] = values
            row.loc[:mature_count - 1, "stop_reason"] = reasons
            row.loc[:mature_count - 1, "stopped_exit_date"] = pd.Series(dates[stopped_day]).array
        blocks.append(row)

    result = pd.concat(blocks, ignore_index=True).sort_values(["Date", "symbol"]).reset_index(drop=True)
    for label in ("plain_net", "stopped_net"):
        groups = result.groupby("Date", sort=False)[f"{label}_excess"]
        counts = groups.transform("count")
        if not counts.isin((0, stock_count)).all():
            raise AssertionError("某观察日只有部分股票标签成熟。")
        ranks = groups.rank(method="average")
        result[f"{label}_rank"] = ((ranks - 1) / (stock_count - 1) - .5
                                     if stock_count > 1 else ranks * 0.)
    return result
