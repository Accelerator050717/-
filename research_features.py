"""扩展历史信号：长期走势、ETF 环境、历史 beta 和同日横截面名次。

所有特征在观察日收盘后可计算。未来收益只由原来的标签函数生成，
任何特征都不读取未来收益。输入必须已对齐到相同交易日，缺价直接报错。
"""

import hashlib
import importlib
import json

import numpy as np
import pandas as pd

from panel_config import BENCHMARK, HISTORY_PARAMS, RAW_DIR, ROOT, SYMBOLS

_base = importlib.import_module("10_build_panel")
BASE_FEATURES = list(_base.X_COLUMNS)
TARGET = _base.TARGET
CONTEXT_SYMBOLS = (
    "XLK", "XLF", "XLV", "XLE", "XLI", "XLP", "XLY", "XLU",
    "TLT", "HYG", "LQD", "IWM", "QQQ",
)
CONTEXT_DIR = ROOT / "data" / "raw" / "research_context_2015_2025"
RESEARCH_PANEL_PATH = ROOT / "data" / "processed" / "research_panel_v1.csv"

# 固定研究代理映射，不声称是历史 GICS 或历史 ETF 成分股映射。
# GOOGL/META 的 QQQ 是成长科技代理，并非两家公司历史行业分类。
SECTOR_PROXY = {
    **dict.fromkeys(("AAPL", "MSFT", "NVDA"), "XLK"),
    **dict.fromkeys(("AMZN", "HD", "MCD"), "XLY"),
    **dict.fromkeys(("GOOGL", "META"), "QQQ"),
    **dict.fromkeys(("JPM", "BAC", "GS", "V"), "XLF"),
    **dict.fromkeys(("JNJ", "PFE", "MRK", "UNH"), "XLV"),
    **dict.fromkeys(("XOM", "CVX", "COP"), "XLE"),
    **dict.fromkeys(("CAT", "HON", "DE"), "XLI"),
    **dict.fromkeys(("PG", "KO", "PEP", "WMT", "COST"), "XLP"),
    **dict.fromkeys(("NEE", "DUK", "SO"), "XLU"),
}
CONTEXT_FEATURES = [
    f"context_{ticker}_{measure}"
    for ticker in CONTEXT_SYMBOLS
    for measure in ("ret_20d", "ret_60d", "vol_20d")
]
ADDED_FEATURES = [
    "ret_126d", "ret_252d", "mom_252_skip21",
    "drawdown_60d", "drawdown_252d", "beta_spy_60d", "beta_sector_60d",
    *[f"sector_ret_{days}d" for days in (5, 20, 60)],
    *[f"relative_sector_{days}d" for days in (5, 20, 60)],
    *[f"beta_residual_{days}d" for days in (5, 20)],
    *[f"sector_beta_residual_{days}d" for days in (5, 20)],
    *CONTEXT_FEATURES, "credit_proxy_20d",
    "interaction_ret20_spyret20", "interaction_ret5_spyvol20",
]
EXTENDED_FEATURES = BASE_FEATURES + ADDED_FEATURES
COMMON_FEATURES = [name for name in BASE_FEATURES if name.startswith("spy_")]
COMMON_FEATURES += CONTEXT_FEATURES + ["credit_proxy_20d"]
CS_SOURCE_FEATURES = [name for name in EXTENDED_FEATURES if name not in COMMON_FEATURES]
CS_FEATURES = [f"cs_{name}" for name in CS_SOURCE_FEATURES] + COMMON_FEATURES
ALL_FEATURES = list(dict.fromkeys(EXTENDED_FEATURES + CS_FEATURES))


def _read_snapshot(directory, symbol):
    path = directory / f"{symbol}.csv"
    metadata = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    if metadata["parameters"] != HISTORY_PARAMS:
        raise ValueError(f"{symbol}: 缓存的日期或下载参数不符合当前研究。")
    if hashlib.sha256(path.read_bytes()).hexdigest() != metadata["sha256"]:
        raise ValueError(f"{symbol}: 行情文件哈希与下载记录不一致。")
    return pd.read_csv(path, index_col="Date", parse_dates=["Date"])


def load_inputs():
    """只读取已保存的 2015—2025 快照；缺少 ETF 时先运行第 14 步。"""
    raw = {symbol: _read_snapshot(RAW_DIR, symbol) for symbol in (*SYMBOLS, BENCHMARK)}
    context = {symbol: _read_snapshot(CONTEXT_DIR, symbol) for symbol in CONTEXT_SYMBOLS}
    return raw, context


def _validate_inputs(raw_frames, context_frames):
    if set(raw_frames) != set(SYMBOLS) | {BENCHMARK}:
        raise ValueError("原始行情必须包含固定的 30 股与 SPY。")
    if set(context_frames) != set(CONTEXT_SYMBOLS):
        raise ValueError("ETF 环境行情缺少所需代码。")
    calendar = raw_frames[BENCHMARK].index
    if calendar.empty or calendar.hasnans or not calendar.is_unique or not calendar.is_monotonic_increasing:
        raise ValueError("SPY 日期为空、缺失、重复或乱序。")
    for symbol, frame in {**raw_frames, **context_frames}.items():
        if not frame.index.equals(calendar):
            raise ValueError(f"{symbol}: 交易日与 SPY 不一致，不自动填价格。")
        values = frame[_base.PRICE_COLUMNS + ["Volume"]]
        if not np.isfinite(values.to_numpy(dtype=float)).all():
            raise ValueError(f"{symbol}: 行情存在缺值或非有限值。")
        if frame[_base.PRICE_COLUMNS].le(0).any().any() or frame["Volume"].lt(0).any():
            raise ValueError(f"{symbol}: 价格或成交量非法。")


def _beta(stock_returns, benchmark_returns):
    # 用同一 60 日窗口的协方差/方差估计暴露；零方差保持缺失。
    variance = benchmark_returns.rolling(60).var(ddof=1)
    return stock_returns.rolling(60).cov(benchmark_returns) / variance.where(variance > 0)


def compute_features(raw_frames, context_frames):
    """输入同日期的原始行情字典，返回全量样本，包括未成熟的尾部标签。

    后续新时期使用时，输入需带至少 252 个交易日历史预热。
    函数不限制年份、不下载、不填缺值、不按结果删掉股票或日期。
    """
    _validate_inputs(raw_frames, context_frames)
    spy = raw_frames[BENCHMARK]
    spy_close = spy["Adj Close"]
    spy_daily = spy_close.pct_change(fill_method=None)
    common = {}
    for ticker, frame in context_frames.items():
        close = frame["Adj Close"]
        for days in (20, 60):
            common[f"context_{ticker}_ret_{days}d"] = close / close.shift(days) - 1
        common[f"context_{ticker}_vol_20d"] = close.pct_change(fill_method=None).rolling(20).std(ddof=1)
    common["credit_proxy_20d"] = common["context_HYG_ret_20d"] - common["context_LQD_ret_20d"]

    frames = []
    for symbol in SYMBOLS:
        stock = raw_frames[symbol]
        result = _base.build_one(stock, spy, symbol)
        close = stock["Adj Close"]
        daily = close.pct_change(fill_method=None)
        sector_close = context_frames[SECTOR_PROXY[symbol]]["Adj Close"]
        sector_daily = sector_close.pct_change(fill_method=None)
        added = {}
        for days in (126, 252):
            added[f"ret_{days}d"] = close / close.shift(days) - 1
        added["mom_252_skip21"] = close.shift(21) / close.shift(252) - 1
        for days in (60, 252):
            added[f"drawdown_{days}d"] = close / close.rolling(days).max() - 1
        added["beta_spy_60d"] = _beta(daily, spy_daily)
        added["beta_sector_60d"] = _beta(daily, sector_daily)
        for days in (5, 20, 60):
            sector_return = sector_close / sector_close.shift(days) - 1
            added[f"sector_ret_{days}d"] = sector_return
            added[f"relative_sector_{days}d"] = result[f"ret_{days}d"] - sector_return
            if days in (5, 20):
                spy_return = spy_close / spy_close.shift(days) - 1
                added[f"beta_residual_{days}d"] = result[f"ret_{days}d"] - added["beta_spy_60d"] * spy_return
                added[f"sector_beta_residual_{days}d"] = result[f"ret_{days}d"] - added["beta_sector_60d"] * sector_return
        added.update(common)
        added["interaction_ret20_spyret20"] = result["ret_20d"] * result["spy_ret_20d"]
        added["interaction_ret5_spyvol20"] = result["ret_5d"] * result["spy_volatility_20d"]
        frames.append(pd.concat([result, pd.DataFrame(added, index=spy.index)], axis=1))

    panel = pd.concat(frames).reset_index().sort_values(["Date", "symbol"]).reset_index(drop=True)
    if panel.duplicated(["Date", "symbol"]).any():
        raise ValueError("同日同股样本重复。")
    # 仅在同一天横向比较历史 X。某列缺任一股票时，该日该列的名次保持缺失。
    groups = panel.groupby("Date", sort=False)
    ranks = groups[CS_SOURCE_FEATURES].rank(method="average", pct=True) - 0.5
    counts = groups[CS_SOURCE_FEATURES].transform("count")
    ranks = ranks.where(counts.eq(len(SYMBOLS))).add_prefix("cs_")
    panel = pd.concat([panel, ranks], axis=1)
    panel["features_ready"] = np.isfinite(panel[ALL_FEATURES].to_numpy(dtype=float)).all(axis=1)
    panel["label_ready"] = np.isfinite(panel[TARGET].to_numpy(dtype=float))
    ready = panel["features_ready"] & panel["label_ready"]
    daily_count = panel.loc[ready].groupby("Date")["symbol"].nunique()
    if not daily_count.eq(len(SYMBOLS)).all():
        raise ValueError("完整样本的某交易日不足 30 股，不能悄悄改变横截面。")
    if np.isinf(panel[ALL_FEATURES].to_numpy(dtype=float)).any():
        raise ValueError("特征含无穷值。")
    return panel
