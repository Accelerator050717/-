"""第 3 步：获取真实日线，保存快照并检查；不生成特征或交易信号。"""

import json
import sys
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import pandas as pd
import pandas_market_calendars as mcal
import yfinance as yf


START = "2024-01-01"  # 包含起点
END = "2025-01-01"    # 不包含终点，即查看 2024 全年
SYMBOLS = ("AAPL", "SPY")
DATA_DIR = Path(__file__).resolve().parent / "data" / "raw"
PARAMS = dict(
    start=START, end=END, interval="1d",
    auto_adjust=False, back_adjust=False, actions=True,
    repair=False, keepna=True, prepost=False, rounding=False,
)
PRICE_COLUMNS = ["Open", "High", "Low", "Close", "Adj Close"]


def load_prices(symbol):
    """首次联网下载；已有快照时直接读取，避免历史复权值更新影响练习。"""
    path = DATA_DIR / f"{symbol}_{START}_{END}.csv"
    metadata_path = path.with_suffix(".json")
    if path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata["parameters"] != PARAMS:
            raise ValueError(f"{symbol}: 参数与已有快照不一致，请先检查旁边的 JSON。")
        print(f"读取本地快照: {path.name}")
        return pd.read_csv(path, index_col="Date", parse_dates=["Date"])

    print(f"从 Yahoo Finance 下载 {symbol} ...", flush=True)
    yf.config.debug.hide_exceptions = False  # 下载失败时直接报错
    frame = yf.Ticker(symbol).history(**PARAMS, timeout=30)
    if frame.empty:
        raise RuntimeError(f"{symbol}: 没有取得数据，停止，不生成替代价格。")

    source_timezone = str(frame.index.tz)
    # 日线日期按纽约当地交易日保存，不把午夜误当作实际开盘时间。
    frame.index = frame.index.tz_convert("America/New_York").tz_localize(None)
    frame.index.name = "Date"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, date_format="%Y-%m-%d")  # 保留返回精度，不填充、不删除行
    metadata = {
        "source": "Yahoo Finance via yfinance.Ticker.history",
        "symbol": symbol,
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
        "parameters": PARAMS,
        "source_timezone": source_timezone,
        "date_convention": "America/New_York local trading date",
        "price_currency": "USD",
        "python": sys.version.split()[0],
        "packages": {name: version(name) for name in
                     ("yfinance", "pandas", "pandas_market_calendars")},
        "rows": len(frame),
        "columns": list(frame.columns),
        "note": "Library-returned daily bars; not the unprocessed Yahoo API response.",
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return frame


def inspect_prices(symbol, frame, expected_dates):
    """同时检查单元格缺失和整天缺行；只报告，不补价格。"""
    required = PRICE_COLUMNS + ["Volume", "Dividends", "Stock Splits"]
    absent_columns = sorted(set(required) - set(frame.columns))
    if frame.empty or absent_columns:
        raise ValueError(f"{symbol}: 空表或缺少字段 {absent_columns}")

    missing_dates = expected_dates.difference(frame.index)
    extra_dates = frame.index.difference(expected_dates)
    duplicate_count = int(frame.index.duplicated().sum())
    null_counts = frame.isna().sum()
    prices = frame[PRICE_COLUMNS]
    invalid_prices = (~prices.gt(0) | prices.eq(float("inf"))).any(axis=1)
    invalid_ohlc = (
        frame["High"].lt(frame[["Open", "Low", "Close"]].max(axis=1))
        | frame["Low"].gt(frame[["Open", "High", "Close"]].min(axis=1))
    )
    zero_volume = frame["Volume"].eq(0)
    invalid_volume = ~frame["Volume"].ge(0) | frame["Volume"].eq(float("inf"))
    print(f"\n{symbol}: {len(frame)} 行，{frame.index.min().date()} 至 {frame.index.max().date()}")
    print("字段:", ", ".join(frame.columns))
    print("前 5 行（仅显示时保留 4 位小数）:")
    print(frame.head().to_string(float_format=lambda value: f"{value:.4f}"))
    print("各字段缺失值:", null_counts.to_dict())
    print(f"重复日期: {duplicate_count}; 日期递增: {frame.index.is_monotonic_increasing}")
    print("应有但缺失的交易日:", missing_dates.strftime("%Y-%m-%d").tolist())
    print("不在交易日历中的日期:", extra_dates.strftime("%Y-%m-%d").tolist())
    print(f"非法价格行: {invalid_prices.sum()}; OHLC 关系异常行: {invalid_ohlc.sum()}")
    print(f"非法成交量行: {invalid_volume.sum()}; 零成交量行（需核查）: {zero_volume.sum()}")
    return not (
        null_counts.any() or duplicate_count or len(missing_dates) or len(extra_dates)
        or not frame.index.is_monotonic_increasing or invalid_prices.any()
        or invalid_ohlc.any() or invalid_volume.any() or zero_volume.any()
    )


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    # 2024 年两者的全日休市安排相同；提前收市的日期仍算交易日。
    last_day = pd.Timestamp(END) - pd.Timedelta(days=1)
    expected = mcal.get_calendar("NYSE").valid_days(START, last_day).tz_localize(None)
    weekdays = pd.date_range(START, last_day, freq="B")
    print(f"请求区间: [{START}, {END})；日历预期 {len(expected)} 个交易日")
    print("工作日中的全日休市日:", weekdays.difference(expected).strftime("%Y-%m-%d").tolist())

    frames = {}
    checks = []
    for symbol in SYMBOLS:
        frames[symbol] = load_prices(symbol)
        checks.append(inspect_prices(symbol, frames[symbol], expected))
    dates_match = frames[SYMBOLS[0]].index.equals(frames[SYMBOLS[1]].index)
    print(f"\n{SYMBOLS[0]} 与 {SYMBOLS[1]} 日期及顺序完全一致: {dates_match}")
    if not all(checks) or not dates_match:
        raise SystemExit("发现需核查的数据问题；保留快照，不填充、不进入下一步。")
    print("基础检查通过。这不证明供应商每个价格都正确，也不说明策略能获利。")


if __name__ == "__main__":
    main()
