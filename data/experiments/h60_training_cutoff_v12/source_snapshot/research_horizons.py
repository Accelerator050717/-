"""同一价格快照的多周期标签；未来标签缺失不妨碍对当前 X 评分。"""

import hashlib
import importlib
import json

import numpy as np
import pandas as pd

import fundamental_features as ff
import research_event_features as ef
import research_features as rf
from panel_config import ROOT, SYMBOLS

HORIZONS = (5, 20, 60)
TARGET_PATH = ROOT / "data/processed/horizon_targets_v1.csv"
old_batch = importlib.import_module("15_run_research_batch")


def adjusted_opens():
    raw, _ = rf.load_inputs()
    opens = pd.DataFrame({s: raw[s].Open * raw[s]["Adj Close"] / raw[s].Close for s in SYMBOLS})
    spy = raw["SPY"].Open * raw["SPY"]["Adj Close"] / raw["SPY"].Close
    return opens, spy


def build_targets(opens, spy):
    if not opens.index.equals(spy.index) or not np.isfinite(opens).all().all():
        raise ValueError("股票和基准必须使用同一完整交易日历。")
    dates = pd.Series(opens.index, index=opens.index)
    blocks = []
    for symbol in SYMBOLS:
        row = pd.DataFrame({"Date": opens.index, "symbol": symbol})
        for h in HORIZONS:
            # t 收盘后观察，t+1 开盘进入，t+h+1 开盘退出；不使用 t 收盘成交。
            stock_return = opens[symbol].shift(-(h + 1)) / opens[symbol].shift(-1) - 1
            market_return = spy.shift(-(h + 1)) / spy.shift(-1) - 1
            row[f"y_{h}"] = (stock_return - market_return).to_numpy()
            row[f"exit_{h}"] = dates.shift(-(h + 1)).to_numpy()
        blocks.append(row)
    return pd.concat(blocks, ignore_index=True).sort_values(["Date", "symbol"]).reset_index(drop=True)


def prepare_targets():
    opens, spy = adjusted_opens()
    targets = build_targets(opens, spy)
    TARGET_PATH.parent.mkdir(parents=True, exist_ok=True)
    targets.to_csv(TARGET_PATH, index=False, date_format="%Y-%m-%d")
    checks = []
    for h in HORIZONS:
        mature = targets.loc[targets[f"y_{h}"].notna()]
        checks.append({"horizon": h, "mature_rows": len(mature),
                       "last_observation": str(mature.Date.max().date()),
                       "last_exit": str(mature[f"exit_{h}"].max().date())})
    metadata = {"rows": len(targets), "horizons": checks,
                "sha256": hashlib.sha256(TARGET_PATH.read_bytes()).hexdigest(),
                "source": "Existing 2015-2025 cached adjusted-open proxies; no 2026 prices.",
                "definition": "stock A[t+h+1]/A[t+1]-1 minus SPY same interval return"}
    TARGET_PATH.with_suffix(".json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata


def load_panel():
    panel = old_batch.load_panel()  # 保持已研究过的共同 X/y5 样本及解析口径。
    targets = pd.read_csv(TARGET_PATH, float_precision="round_trip",
                          parse_dates=["Date", *[f"exit_{h}" for h in HORIZONS]])
    sources = [(targets, [f"{kind}_{h}" for h in HORIZONS for kind in ("y", "exit")]),
               (pd.read_csv(ff.FUNDAMENTAL_PANEL_PATH, parse_dates=["Date"], float_precision="round_trip"), ff.FUND_FEATURES),
               (pd.read_csv(ef.EVENT_PANEL_PATH, parse_dates=["Date"], float_precision="round_trip"), ef.EVENT_FEATURES)]
    for source, columns in sources:
        panel = panel.merge(source[["Date", "symbol", *columns]], on=["Date", "symbol"],
                            how="left", validate="one_to_one", indicator=True)
        if not panel._merge.eq("both").all():
            raise ValueError("来源缺少 Date/symbol 键；不能静默删除股票或填价格。")
        panel = panel.drop(columns="_merge")
    panel = panel.sort_values(["Date", "symbol"]).reset_index(drop=True)
    np.testing.assert_allclose(panel.y_5, panel[rf.TARGET], rtol=0, atol=2e-15)
    pd.testing.assert_series_equal(panel.exit_5, panel.exit_date, check_names=False)
    # y5 控制使用原始数值，避免浮点极小差异改变并列名次。
    panel["y_5"] = panel[rf.TARGET]
    for h in HORIZONS:
        ranks = panel.groupby("Date")[f"y_{h}"].rank(method="average")
        counts = panel.groupby("Date")[f"y_{h}"].transform("count")
        if not counts.isin([0, len(SYMBOLS)]).all():
            raise ValueError(f"H{h} 同一天的标签不完整。")
        panel[f"rank_{h}"] = (ranks - 1) / (counts - 1) - 0.5
        panel[f"grade_{h}"] = np.floor((ranks - 1) * 5 / counts.replace(0, np.nan))
    np.testing.assert_array_equal(panel.rank_5, panel.rank_target)
    np.testing.assert_array_equal(panel.grade_5, panel.relevance)
    if len(panel) != 75240 or np.isinf(panel[ff.FUND_FEATURES + ef.EVENT_FEATURES].to_numpy()).any():
        raise ValueError("共同面板长度或财报数值非法。")
    old_batch.ranking.check_groups(panel)
    return panel


def split_fold(panel, year, horizon):
    exit_col = f"exit_{horizon}"
    mature = panel[f"y_{horizon}"].notna()
    train = panel.loc[mature & panel.Date.lt(f"{year-1}-01-01") & panel[exit_col].lt(f"{year-1}-01-01")].copy()
    valid = panel.loc[mature & panel.Date.ge(f"{year-1}-01-01") & panel.Date.lt(f"{year}-01-01") & panel[exit_col].lt(f"{year}-01-01")].copy()
    # 预测只看 X：此处不按 y20/y60 是否成熟删掉年末样本。
    develop = panel.loc[panel.Date.ge(f"{year}-01-01") & panel.Date.lt(f"{year+1}-01-01")].copy()
    assert train[exit_col].max() < valid.Date.min() and valid[exit_col].max() < develop.Date.min()
    result = []
    for rows in (train, valid, develop):
        rows = rows.reset_index(drop=True)
        old_batch.ranking.check_groups(rows)
        result.append(rows)
    return tuple(result)
