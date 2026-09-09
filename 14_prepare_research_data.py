"""下载 13 个真实 ETF 环境快照，并生成三组可比较的历史特征。"""

import hashlib
import importlib
import json
import sys
from datetime import datetime, timezone

import pandas as pd
import pandas_market_calendars as mcal

from panel_config import END, START, SYMBOLS
from research_features import (
    ALL_FEATURES, BASE_FEATURES, CONTEXT_DIR, CONTEXT_SYMBOLS, CS_FEATURES,
    EXTENDED_FEATURES, RESEARCH_PANEL_PATH, SECTOR_PROXY, compute_features, load_inputs,
)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    download = importlib.import_module("09_download_panel")
    # 只在当前进程替换此模块的输出路径；不修改任何旧脚本或旧快照。
    download.RAW_DIR = CONTEXT_DIR
    CONTEXT_DIR.mkdir(parents=True, exist_ok=True)
    expected = mcal.get_calendar("NYSE").schedule(start_date=START, end_date="2025-12-31").index
    reports = []
    for symbol in CONTEXT_SYMBOLS:
        frame = download.load_prices(symbol)
        report = download.inspect_prices(symbol, frame, expected)
        reports.append(report)
        print(f"{symbol}: {len(frame):,} 行，{frame.index.min().date()} 至 {frame.index.max().date()}，检查={report['passed']}", flush=True)
        if not report["passed"]:
            raise ValueError(f"{symbol} 行情检查未通过: {report}")
    (CONTEXT_DIR / "checks.json").write_text(json.dumps(reports, indent=2), encoding="utf-8")

    raw, context = load_inputs()
    panel = compute_features(raw, context)
    cutoff = pd.Timestamp("2024-06-28")
    prefix = compute_features(
        {symbol: frame.loc[:cutoff] for symbol, frame in raw.items()},
        {symbol: frame.loc[:cutoff] for symbol, frame in context.items()},
    )
    full_before = panel.loc[panel["Date"].le(cutoff)].reset_index(drop=True)
    pd.testing.assert_frame_equal(prefix[["Date", "symbol", *ALL_FEATURES]], full_before[["Date", "symbol", *ALL_FEATURES]], rtol=1e-11, atol=1e-13)
    matured = prefix["label_ready"]
    audit = ["entry_date", "exit_date", "stock_forward_return", "spy_forward_return", "y_excess_5d"]
    pd.testing.assert_frame_equal(prefix.loc[matured, audit], full_before.loc[matured, audit], rtol=1e-11, atol=1e-13)

    RESEARCH_PANEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(RESEARCH_PANEL_PATH, index=False, date_format="%Y-%m-%d")
    ready = panel.loc[panel["features_ready"] & panel["label_ready"]]
    metadata = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "start_inclusive": START, "end_exclusive": END,
        "rows": len(panel), "dates": panel["Date"].nunique(),
        "ready_rows": len(ready), "ready_dates": ready["Date"].nunique(),
        "ready_first": str(ready["Date"].min().date()), "ready_last": str(ready["Date"].max().date()),
        "symbols": list(SYMBOLS), "context_symbols": list(CONTEXT_SYMBOLS),
        "feature_sets": {"base": BASE_FEATURES, "extended": EXTENDED_FEATURES, "cross_sectional": CS_FEATURES},
        "all_feature_columns": ALL_FEATURES, "fixed_research_proxy_mapping": SECTOR_PROXY,
        "feature_counts": {"base": len(BASE_FEATURES), "extended": len(EXTENDED_FEATURES), "cross_sectional": len(CS_FEATURES)},
        "prefix_check_cutoff": str(cutoff.date()), "prefix_features_and_matured_labels_match": True,
        "complete_daily_ready_universe": True,
        "sha256": hashlib.sha256(RESEARCH_PANEL_PATH.read_bytes()).hexdigest(),
        "formulas": {
            "beta_residual": "stock trailing return - trailing 60-day beta * SPY trailing return",
            "sector_beta_residual": "stock trailing return - trailing 60-day sector beta * proxy trailing return",
            "momentum_skip": "adjusted_close.shift(21) / adjusted_close.shift(252) - 1",
            "drawdown": "adjusted_close / trailing rolling maximum adjusted_close - 1",
            "cs_rank": "same Date average percentile rank of historical feature - 0.5; requires all 30 stocks",
            "credit_proxy": "HYG 20-day adjusted return minus LQD 20-day adjusted return; not a pure credit spread",
        },
        "limitations": [
            "Current survivors and fixed research mappings are not historical constituents or historical GICS.",
            "GOOGL/META use QQQ as a growth/technology proxy, not a historical sector label.",
            "Yahoo adjusted snapshots can be revised; prefix checks do not certify vendor point-in-time history.",
            "ETF states remain market-price information, not new fundamental or news data.",
            "No missing prices filled; no abnormal return removed; first 252 sessions are historical warmup.",
            "All feature groups share ready dates for fair comparisons; no 2026 prices downloaded.",
        ],
    }
    RESEARCH_PANEL_PATH.with_suffix(".json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"特征数：{metadata['feature_counts']}", flush=True)
    print(f"全量 {len(panel):,} 行；共同完整 {len(ready):,} 行 / {ready['Date'].nunique()} 日，{metadata['ready_first']} 至 {metadata['ready_last']}。", flush=True)
    print("全 30 股截至 2024-06-28 的特征截断一致，成熟标签一致。", flush=True)
    print(f"已保存：{RESEARCH_PANEL_PATH}", flush=True)


if __name__ == "__main__":
    main()
