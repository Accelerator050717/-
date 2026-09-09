"""固定财报变化/申报事件假设后，重用 SEC 快照构造2016—2025样本。"""

import hashlib
import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pandas_market_calendars as mcal

import fundamental_features as fund
import research_event_features as event
from panel_config import RAW_DIR, SYMBOLS


def serial(value):
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, dict):
        return {key: serial(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [serial(item) for item in value]
    if isinstance(value, (np.integer, np.floating)):
        value = value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def save_json(path, value):
    path.write_text(json.dumps(serial(value), indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")


def main():
    payloads, hashes = fund.load_companyfacts()
    plan = {
        "feature_columns": event.EVENT_FEATURES, "formulas": event.FORMULAS, "source_sha256": hashes,
        "scope": "Only existing SEC snapshots; no labels, market returns, model fitting or 2026 prices read.",
        "observation_start": "2016-01-01", "observation_end_exclusive": "2026-01-01",
        "filed_cutoff": fund.MAX_FILED, "availability": "filed < Date; NYSE session strictly after filed is event age 0",
        "annual_match": "Original or amended 10-K annual facts, 330-380 day durations; current/prior start and end gaps each 330-400 days; closest period-end gap to 365",
        "ratio_match": "Each period's facts must share accession and period end; annual flows additionally share start; Assets is instant at annual end in same accession",
        "new_period_event": "Only original 10-K/10-Q that strictly advances latest accepted report period; comparative-only re-reporting and /A never refresh period event clock",
        "amendment_event": "Separate 20-session indicator for 10-K/A or 10-Q/A containing accepted financial concepts; not all possible amendments",
        "missing": "All Date/symbol retained, numerical NaN plus explicit missing indicators; no imputation here",
        "quarterly_scope": "No quarterly income growth or YTD differencing; annual comparisons only, plus quarterly balance-sheet new-period events",
    }
    event.EVENT_AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    plan_path = event.EVENT_AUDIT_DIR / "feature_plan.json"
    if plan_path.exists():
        previous = json.loads(plan_path.read_text(encoding="utf-8"))
        previous.pop("registered_at_utc")
        if previous != plan:
            raise ValueError("预注册特征定义或输入改变，不覆盖旧计划。")
    else:
        with plan_path.open("x", encoding="utf-8") as handle:
            json.dump({**plan, "registered_at_utc": datetime.now(timezone.utc).isoformat()}, handle, indent=2, ensure_ascii=False)
    print("财报变化和事件特征计划已固定；不读取收益结果。", flush=True)

    # 只读既有SPY日期列，并用交易所日历计算申报至观察日之间的交易日数。
    raw_dates = pd.read_csv(RAW_DIR / "SPY.csv", usecols=["Date"], parse_dates=["Date"])["Date"]
    dates = pd.DatetimeIndex(raw_dates.loc[raw_dates.ge("2016-01-01") & raw_dates.lt("2026-01-01")])
    earliest = min(row["filed"] for payload in payloads.values() for row in fund.extract_records(payload)[0])
    calendar = mcal.get_calendar("NYSE").schedule(start_date=earliest-pd.Timedelta(days=7), end_date="2025-12-31").index
    assert dates.isin(calendar).all()
    frames, provenance, period_events, checks, examples = [], [], [], [], []
    cutoff = pd.Timestamp("2024-06-28")
    for symbol in SYMBOLS:
        frame, sources, events, quality = event.build_company_events(symbol, payloads[symbol], dates, calendar)
        prefix, _, _, _ = event.build_company_events(symbol, payloads[symbol], dates[dates <= cutoff], calendar, max_filed=cutoff)
        pd.testing.assert_frame_equal(frame.loc[frame.Date.le(cutoff)].reset_index(drop=True), prefix, check_exact=True)
        quality["prefix_physical_filed_cutoff_passed"] = True
        quality["event_counts"] = {kind: sum(row["kind"] == kind for row in events) for kind in ("balance", "annual", "financial_amendment")}
        frames.append(frame)
        provenance.extend(sources)
        period_events.extend({"symbol": symbol, **row} for row in events)
        checks.append(quality)
        for kind in ("balance", "annual"):
            recent = [row for row in events if row["kind"] == kind and row["filed"].year == 2024]
            if symbol in ("AAPL", "JPM", "XOM") and recent:
                selected = recent[0]
                p = int(calendar.searchsorted(selected["filed"], side="right"))
                windows = calendar[max(0,p-1):p+2]
                example_rows = frame.loc[frame.Date.isin(windows)].copy()
                after = example_rows.loc[example_rows.Date.ge(calendar[p])]
                assert float(after.iloc[0][f"event_sessions_since_new_{kind}"]) == 0
                assert float(after.iloc[0][f"event_new_{kind}_filed_5d"]) == 1
                # 新事件在 filed 当日不可用，第一可用交易日严格晚于 filed。
                assert calendar[p] > selected["filed"]
                values, selected_sources = event.financial_changes_asof(fund.extract_records(payloads[symbol])[0], calendar[p])
                examples.append({"symbol": symbol, "kind": kind, "new_period_event": selected,
                                 "first_usable_session": calendar[p], "before_after_rows": example_rows.to_dict("records"),
                                 "financial_change_sources": selected_sources, "financial_change_values": values})
        print(f"{symbol}: {len(frame)}行；新期/修改事件 {quality['event_counts']}；物理截断前缀通过。", flush=True)
    panel = pd.concat(frames).sort_values(["Date", "symbol"]).reset_index(drop=True)
    assert len(panel) == len(dates)*len(SYMBOLS) and not panel.duplicated(["Date", "symbol"]).any()
    assert panel.groupby("Date").symbol.nunique().eq(len(SYMBOLS)).all()
    panel.to_csv(event.EVENT_PANEL_PATH, index=False, date_format="%Y-%m-%d")
    metadata = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(), "rows": len(panel), "dates": len(dates), "symbols": list(SYMBOLS),
        "first_date": dates.min(), "last_date": dates.max(), "value_features": event.EVENT_VALUE_FEATURES,
        "missing_features": event.EVENT_MISSING_FEATURES, "feature_columns": event.EVENT_FEATURES,
        "source_sha256": hashes, "sha256": hashlib.sha256(event.EVENT_PANEL_PATH.read_bytes()).hexdigest(),
        "formulas": event.FORMULAS,
        "units": {name: "trading sessions" if "sessions_since" in name else "binary 0/1" if "filed_" in name else "decimal ratio or ratio difference" for name in event.EVENT_VALUE_FEATURES},
        "missing_counts": {name: int(panel[name].isna().sum()) for name in event.EVENT_VALUE_FEATURES},
        "missing_counts_by_symbol": panel.groupby("symbol")[event.EVENT_VALUE_FEATURES].agg(lambda values: int(values.isna().sum())).to_dict("index"),
        "checks": checks, "prefix_cutoff": cutoff, "real_event_examples": len(examples),
        "limitations": [
            "Current SEC extract with asof filed filtering is a conservative historical availability approximation, not a complete vintage archive.",
            "Prior-year comparisons may use restated values only once their filing is known; later source deletions/corrections cannot always be reconstructed.",
            "Revenue tags differ in meaning across issuers; fixed fallback and missingness are retained, especially for banks.",
            "Selected accounting facts define effective financial events; earnings press releases may precede SEC filings and are not included.",
            "Events use date-only filed with next-session availability, not exact publication or acceptance timestamps.",
            "No quarterly income flow or synthetic YTD differencing, no training, no labels and no 2026 market data used.",
        ],
    }
    save_json(event.EVENT_PANEL_PATH.with_suffix(".json"), metadata)
    save_json(event.EVENT_AUDIT_DIR / "audit_examples.json", examples)
    save_json(event.EVENT_AUDIT_DIR / "checks.json", checks)
    for name, data in (("provenance.jsonl", provenance), ("period_events.jsonl", period_events)):
        with (event.EVENT_AUDIT_DIR / name).open("w", encoding="utf-8") as handle:
            for row in data:
                handle.write(json.dumps(serial(row), ensure_ascii=False, allow_nan=False)+"\n")
    print(f"完成：{len(panel):,}行；14值+14缺失指标；{len(examples)}个真实事件前后样例。", flush=True)
    print(f"输出：{event.EVENT_PANEL_PATH}", flush=True)
    print(f"缺失：{metadata['missing_counts']}", flush=True)


if __name__ == "__main__":
    __import__("sys").stdout.reconfigure(encoding="utf-8")
    main()
