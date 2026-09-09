"""下载并保存 30 股 + SPY 的真实 Yahoo 日线；复用快照，不填补价格。"""

import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from importlib.metadata import version

import numpy as np
import pandas as pd
import pandas_market_calendars as mcal
import yfinance as yf

from panel_config import (
    BENCHMARK, END, HISTORY_PARAMS, RAW_DIR, START, SYMBOLS,
)

PRICE_COLUMNS = ["Open", "High", "Low", "Close", "Adj Close"]
REQUIRED = PRICE_COLUMNS + ["Volume", "Dividends", "Stock Splits"]


def load_prices(symbol):
    path = RAW_DIR / f"{symbol}.csv"
    meta_path = path.with_suffix(".json")
    if path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        assert meta["parameters"] == HISTORY_PARAMS, "快照参数不一致"
        assert meta["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        return pd.read_csv(path, index_col="Date", parse_dates=["Date"])

    yf.config.debug.hide_exceptions = False
    for attempt in range(3):
        try:
            frame = yf.Ticker(symbol).history(**HISTORY_PARAMS, timeout=30)
            if frame.empty:
                raise ValueError("数据源返回空表")
            break
        except Exception as exc:
            if attempt == 2:
                raise RuntimeError(f"{symbol} 下载失败；保留已成功的快照") from exc
            print(f"{symbol} 请求失败，第 {attempt + 1} 次重试: {type(exc).__name__}", flush=True)
            time.sleep(2 * (attempt + 1))

    source_timezone = str(frame.index.tz)
    frame.index = frame.index.tz_convert("America/New_York").tz_localize(None)
    frame.index.name = "Date"
    frame.to_csv(path, date_format="%Y-%m-%d")
    meta = {
        "source": "Yahoo Finance via yfinance.Ticker.history",
        "symbol": symbol, "parameters": HISTORY_PARAMS,
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_timezone": source_timezone,
        "date_convention": "America/New_York local session date",
        "python": sys.version.split()[0],
        "packages": {name: version(name) for name in
                     ("yfinance", "pandas", "pandas_market_calendars")},
        "rows": len(frame), "columns": list(frame.columns),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "note": "Library-returned snapshot; adjusted history can be revised by vendor.",
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return frame


def inspect_prices(symbol, frame, expected):
    if not set(REQUIRED).issubset(frame.columns) or frame.empty:
        raise ValueError(f"{symbol}: 空数据或必需字段缺失")
    prices = frame[PRICE_COLUMNS]
    bad_prices = (~np.isfinite(prices) | prices.le(0)).any(axis=1)
    bad_volume = ~np.isfinite(frame["Volume"]) | frame["Volume"].lt(0)
    # 只容许浮点舍入误差，不修补异常行情。
    tolerance = 1e-6
    bad_ohlc = (
        frame["High"] + tolerance < frame[["Open", "Low", "Close"]].max(axis=1)
    ) | (frame["Low"] - tolerance > frame[["Open", "High", "Close"]].min(axis=1))
    missing = expected.difference(frame.index)
    extra = frame.index.difference(expected)
    report = {
        "symbol": symbol, "rows": len(frame),
        "first_date": str(frame.index.min().date()),
        "last_date": str(frame.index.max().date()),
        "null_counts": frame[REQUIRED].isna().sum().astype(int).to_dict(),
        "duplicate_dates": int(frame.index.duplicated().sum()),
        "sorted_dates": frame.index.is_monotonic_increasing,
        "missing_sessions": missing.strftime("%Y-%m-%d").tolist(),
        "extra_dates": extra.strftime("%Y-%m-%d").tolist(),
        "bad_price_dates": frame.index[bad_prices].strftime("%Y-%m-%d").tolist(),
        "bad_ohlc_dates": frame.index[bad_ohlc].strftime("%Y-%m-%d").tolist(),
        "bad_volume_dates": frame.index[bad_volume].strftime("%Y-%m-%d").tolist(),
        "zero_volume_dates": frame.index[frame["Volume"].eq(0)].strftime("%Y-%m-%d").tolist(),
        "dividend_rows": int(frame["Dividends"].ne(0).sum()),
        "split_rows": int(frame["Stock Splits"].ne(0).sum()),
    }
    report["passed"] = not (
        any(report["null_counts"].values()) or report["duplicate_dates"]
        or not report["sorted_dates"] or len(missing) or len(extra)
        or bad_prices.any() or bad_ohlc.any() or bad_volume.any()
        or len(report["zero_volume_dates"])
    )
    return report


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    universe = {"symbols": list(SYMBOLS), "benchmark": BENCHMARK,
                "parameters": HISTORY_PARAMS,
                "selection": "Manually chosen current survivors across sectors; NOT historical constituents."}
    manifest = RAW_DIR / "universe.json"
    if manifest.exists():
        assert json.loads(manifest.read_text(encoding="utf-8")) == universe
    else:
        manifest.write_text(json.dumps(universe, indent=2), encoding="utf-8")
    last_day = pd.Timestamp(END) - pd.Timedelta(days=1)
    expected = mcal.get_calendar("NYSE").valid_days(START, last_day).tz_localize(None)
    nasdaq = mcal.get_calendar("NASDAQ").valid_days(START, last_day).tz_localize(None)
    assert expected.equals(nasdaq), "需分别核对两市场休市安排"
    print(f"固定区间 [{START}, {END}), {len(SYMBOLS)} 股 + SPY, {len(expected)} 个交易日", flush=True)
    reports = []
    for number, symbol in enumerate((BENCHMARK,) + SYMBOLS, start=1):
        frame = load_prices(symbol)
        report = inspect_prices(symbol, frame, expected)
        reports.append(report)
        print(f"[{number}/31] {symbol}: {len(frame)} 行, {report['first_date']}~{report['last_date']}, 检查={report['passed']}", flush=True)
        (RAW_DIR / "data_checks.json").write_text(json.dumps(reports, indent=2), encoding="utf-8")
    if not all(item["passed"] for item in reports):
        raise SystemExit("发现数据异常；查看 data_checks.json，不能带着异常直接训练。")
    print(f"完成：{sum(item['rows'] for item in reports):,} 行。数据检查通过；不证明每个供应商数值正确。")


if __name__ == "__main__":
    main()
