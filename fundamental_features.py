"""SEC 财务特征：先按 filed 筛可用事实，再选报告期间与已知申报版本。

缺失保留 NaN；这里不拟合、不填补、不读取未来收益。当前快照不是完整
历史版本数据库，filed 过滤只提供保守的历史可用性研究近似。
"""

import hashlib
import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from panel_config import ROOT, RAW_DIR, SYMBOLS

SEC_DIR = ROOT / "data" / "raw" / "sec_companyfacts_20260909"
FUNDAMENTAL_PANEL_PATH = ROOT / "data" / "processed" / "fundamental_panel_v1.csv"
FUND_VALUE_FEATURES = [
    "fund_liabilities_to_assets", "fund_equity_to_assets", "fund_asset_growth_yoy",
    "fund_annual_profit_margin", "fund_annual_profit_to_latest_assets",
    "fund_annual_cfo_to_latest_assets", "fund_balance_age_days", "fund_annual_age_days",
]
FUND_MISSING_FEATURES = [f"{name}_missing" for name in FUND_VALUE_FEATURES]
FUND_FEATURES = FUND_VALUE_FEATURES + FUND_MISSING_FEATURES
MAX_FILED = "2025-12-31"
ALLOWED_FORMS = {"10-K", "10-Q", "10-K/A", "10-Q/A"}
ANNUAL_FORMS = {"10-K", "10-K/A"}
CONCEPTS = {
    "assets": ["Assets"], "liabilities": ["Liabilities"], "equity": ["StockholdersEquity"],
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"],
    "profit": ["NetIncomeLoss"], "cfo": ["NetCashProvidedByUsedInOperatingActivities"],
}
FORMULAS = {
    "fund_liabilities_to_assets": "Liabilities / Assets; same period end and accession",
    "fund_equity_to_assets": "StockholdersEquity / Assets; same period end and accession",
    "fund_asset_growth_yoy": "latest Assets / latest-known Assets from closest period end to 365 days before - 1; permitted gap 330-400 days",
    "fund_annual_profit_margin": "annual NetIncomeLoss / annual revenue; exact same start, end and accession; duration 330-380 days",
    "fund_annual_profit_to_latest_assets": "latest annual NetIncomeLoss / latest balance-sheet Assets; different periods allowed explicitly as a proxy",
    "fund_annual_cfo_to_latest_assets": "annual operating cash flow matching annual-profit start/end/accession / latest Assets; proxy",
    "fund_balance_age_days": "observation Date minus selected Assets period end, calendar days (not days since filing)",
    "fund_annual_age_days": "observation Date minus selected annual-profit period end, calendar days (not days since filing)",
}


def extract_records(payload, max_filed=MAX_FILED):
    """按白名单解析，保留每个 accession 的原事实；不跨时间提前去重。"""
    gaap = payload.get("facts", {}).get("us-gaap", {})
    records, rejected = [], {}
    max_filed = pd.Timestamp(max_filed)
    for role, tags in CONCEPTS.items():
        for priority, tag in enumerate(tags):
            for item in gaap.get(tag, {}).get("units", {}).get("USD", []):
                reason = None
                try:
                    filed, end = pd.Timestamp(item["filed"]), pd.Timestamp(item["end"])
                    start = pd.Timestamp(item["start"]) if item.get("start") else None
                    if filed > max_filed:
                        reason = "filed_after_cutoff"
                    elif item.get("form") not in ALLOWED_FORMS or end > filed:
                        reason = "form_or_period_unavailable"
                    elif role in {"revenue", "profit", "cfo"} and (
                        item.get("form") not in ANNUAL_FORMS or start is None or not 330 <= (end-start).days+1 <= 380
                    ):
                        reason = "not_annual_10k_330_to_380_days"
                    elif role in {"assets", "liabilities", "equity"} and start is not None:
                        reason = "balance_sheet_not_instant"
                    elif not np.isfinite(float(item["val"])) or not item.get("accn"):
                        reason = "invalid_value_or_accession"
                    if reason is None:
                        records.append({"role": role, "tag": tag, "tag_priority": priority,
                            "unit": "USD", "val": float(item["val"]), "start": start, "end": end,
                            "filed": filed, "accn": item["accn"], "form": item["form"]})
                except (KeyError, TypeError, ValueError):
                    reason = "unparseable_fact"
                if reason:
                    rejected[reason] = rejected.get(reason, 0) + 1
    # 同一个概念、期间、申报出现冲突值时整组排除；不任意取最后一个值。
    groups = {}
    for record in records:
        key = tuple(record[name] for name in ("role", "tag", "start", "end", "filed", "accn"))
        groups.setdefault(key, []).append(record)
    clean = []
    conflicts = 0
    for group in groups.values():
        if len({row["val"] for row in group}) == 1:
            clean.append(group[0])
        else:
            conflicts += len(group)
    rejected["conflicting_duplicate_facts"] = conflicts
    return sorted(clean, key=lambda row: (row["filed"], row["end"], row["accn"], row["tag_priority"])), rejected


def _latest(records):
    if not records:
        return None
    end = max(row["end"] for row in records)
    same_period = [row for row in records if row["end"] == end]
    filed = max(row["filed"] for row in same_period)
    latest = [row for row in same_period if row["filed"] == filed]
    # 同日多个申报值不一致而无 intraday timestamp 时，不猜哪份最后公布。
    if len({row["val"] for row in latest}) > 1:
        return None
    return sorted(latest, key=lambda row: (row["accn"], row["tag_priority"]))[-1]


def _matching(records, anchor, role):
    if anchor is None:
        return None
    matches = [row for row in records if row["role"] == role and row["accn"] == anchor["accn"]
               and row["end"] == anchor["end"] and row["start"] == anchor["start"]]
    if not matches:
        return None
    priority = min(row["tag_priority"] for row in matches)
    chosen = [row for row in matches if row["tag_priority"] == priority]
    if len({row["val"] for row in chosen}) != 1:
        return None
    return chosen[0]


def _ratio(numerator, denominator):
    if numerator is None or denominator is None or denominator["val"] <= 0:
        return np.nan
    return numerator["val"] / denominator["val"]


def snapshot_asof(records, date):
    """date 之前已经 filed 的事实才可用；Date 当日申报不能进入特征。"""
    date = pd.Timestamp(date)
    known = [row for row in records if row["filed"] < date and row["end"] <= row["filed"]]
    assets = _latest([row for row in known if row["role"] == "assets"])
    profit = _latest([row for row in known if row["role"] == "profit"])
    liabilities, equity = _matching(known, assets, "liabilities"), _matching(known, assets, "equity")
    revenue, cfo = _matching(known, profit, "revenue"), _matching(known, profit, "cfo")
    prior_assets = None
    if assets is not None:
        prior = [row for row in known if row["role"] == "assets" and 330 <= (assets["end"] - row["end"]).days <= 400]
        if prior:
            gap = min(abs((assets["end"] - row["end"]).days - 365) for row in prior)
            prior_assets = _latest([row for row in prior if abs((assets["end"]-row["end"]).days-365) == gap])
    growth = _ratio(assets, prior_assets)
    values = {
        "fund_liabilities_to_assets": _ratio(liabilities, assets),
        "fund_equity_to_assets": _ratio(equity, assets),
        "fund_asset_growth_yoy": growth - 1 if np.isfinite(growth) else np.nan,
        "fund_annual_profit_margin": _ratio(profit, revenue),
        "fund_annual_profit_to_latest_assets": _ratio(profit, assets),
        "fund_annual_cfo_to_latest_assets": _ratio(cfo, assets),
        "fund_balance_age_days": (date-assets["end"]).days if assets else np.nan,
        "fund_annual_age_days": (date-profit["end"]).days if profit else np.nan,
    }
    provenance = {"assets": assets, "liabilities": liabilities, "equity": equity, "prior_assets": prior_assets,
                  "annual_profit": profit, "annual_revenue": revenue, "annual_cfo": cfo}
    return values, provenance


def _json_record(record):
    if record is None:
        return None
    return {name: value.strftime("%Y-%m-%d") if isinstance(value, pd.Timestamp) else value for name, value in record.items()}


def build_company(symbol, payload, dates, max_filed=MAX_FILED):
    """按申报事件计算一次，向后关联到交易日；仅 report age 随日增长。"""
    dates = pd.DatetimeIndex(dates)
    records, rejected = extract_records(payload, max_filed=max_filed)
    events = sorted({row["filed"] for row in records if row["filed"] < dates.max()})
    snapshots, provenance = [], []
    for filed in events:
        asof = filed + pd.Timedelta(days=1)
        values, sources = snapshot_asof(records, asof)
        values.update(filed=filed,
                      balance_period_end=sources["assets"]["end"] if sources["assets"] else pd.NaT,
                      annual_period_end=sources["annual_profit"]["end"] if sources["annual_profit"] else pd.NaT)
        snapshots.append(values)
        provenance.append({"symbol": symbol, "event_filed": str(filed.date()),
                           "earliest_calendar_availability": str(asof.date()),
                           "facts": {name: _json_record(record) for name, record in sources.items()}})
    output = pd.DataFrame({"Date": dates})
    if snapshots:
        right = pd.DataFrame(snapshots).sort_values("filed")
        output = pd.merge_asof(output, right, left_on="Date", right_on="filed", direction="backward", allow_exact_matches=False)
        output["fund_balance_age_days"] = (output.Date-output.balance_period_end).dt.days
        output["fund_annual_age_days"] = (output.Date-output.annual_period_end).dt.days
    else:
        for name in FUND_VALUE_FEATURES:
            output[name] = np.nan
    output["symbol"] = symbol
    for name in FUND_VALUE_FEATURES:
        output[f"{name}_missing"] = output[name].isna().astype(int)
    output = output[["Date", "symbol", *FUND_FEATURES]]
    assert not np.isinf(output[FUND_FEATURES].to_numpy(dtype=float)).any()
    return output, provenance, {"symbol": symbol, "accepted_records": len(records), "filing_events": len(events), "rejected": rejected}


def load_companyfacts():
    payloads, hashes = {}, {}
    for symbol in SYMBOLS:
        path, meta_path = SEC_DIR / f"{symbol}.json", SEC_DIR / f"{symbol}.metadata.json"
        if not path.exists() or not meta_path.exists():
            payloads[symbol] = {}
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if meta["status"] != "ok" or digest != meta["sha256"]:
            raise ValueError(f"{symbol}: SEC 快照元数据或哈希错误。")
        payloads[symbol] = json.loads(path.read_text(encoding="utf-8"))
        hashes[symbol] = digest
    return payloads, hashes


def prepare_and_save():
    # 仅读取旧 SPY 文件日期列，不取得 2026 行情，也不读取或计算 y。
    calendar = pd.read_csv(RAW_DIR / "SPY.csv", usecols=["Date"], parse_dates=["Date"])["Date"]
    dates = pd.DatetimeIndex(calendar.loc[calendar.ge("2016-01-01") & calendar.lt("2026-01-01")])
    payloads, hashes = load_companyfacts()
    plan = {
        "registered_at_utc": datetime.now(timezone.utc).isoformat(), "features": FUND_FEATURES,
        "concept_fallback_order": CONCEPTS, "formulas": FORMULAS,
        "source_sha256": hashes, "max_filed_in_features": MAX_FILED,
        "asof_rule": "filed < observation Date AND period end <= filed; never use period-end as publication date",
        "version_rule": "Filter by asof first; latest period end then latest filed; conflicting same-day versions stay missing",
        "matching": "Balance sheet ratios require same end/accession; annual margin requires same start/end/accession and 330-380 day 10-K duration",
        "missing": "NaN retained; explicit 0/1 indicators; never drop a Date/symbol or impute using whole sample",
        "raw_snapshot_scope": "Current full companyfacts snapshots may include 2026 facts and later restatements; feature extraction strictly filters filed before historical observation dates through 2025",
    }
    plan_path = SEC_DIR / "feature_plan.json"
    if plan_path.exists():
        old = json.loads(plan_path.read_text(encoding="utf-8"))
        old.pop("registered_at_utc")
        current = dict(plan)
        current.pop("registered_at_utc")
        if current != old:
            raise ValueError("已有财务特征计划不同，不能覆盖。")
    else:
        plan_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    frames, provenance, checks, samples = [], [], [], []
    cutoff = pd.Timestamp("2024-06-28")
    for symbol in SYMBOLS:
        frame, source, quality = build_company(symbol, payloads[symbol], dates)
        # 物理排除 cutoff 之后的 filed 记录，再重算此前日期，验证未来申报不影响过去。
        prefix, _, _ = build_company(symbol, payloads[symbol], dates[dates <= cutoff], max_filed=cutoff)
        pd.testing.assert_frame_equal(frame.loc[frame.Date.le(cutoff)].reset_index(drop=True), prefix, check_exact=True)
        quality["prefix_asof_check_passed"] = True
        frames.append(frame)
        provenance.extend(source)
        checks.append(quality)
        for date in ("2016-01-04", "2020-03-16", "2024-06-28", "2025-12-31"):
            if symbol in ("AAPL", "JPM", "XOM", "GOOGL"):
                values, selected = snapshot_asof(extract_records(payloads[symbol])[0], date)
                samples.append({"Date": date, "symbol": symbol,
                                "values": {key: float(value) if np.isfinite(value) else None for key, value in values.items()},
                                "facts": {key: _json_record(value) for key, value in selected.items()}})
        print(f"{symbol}: {len(frame)} 个观察日；有效事实{quality['accepted_records']}；PIT前缀检查通过。", flush=True)
    panel = pd.concat(frames).sort_values(["Date", "symbol"]).reset_index(drop=True)
    assert len(panel) == len(dates)*len(SYMBOLS) and not panel.duplicated(["Date", "symbol"]).any()
    assert panel.groupby("Date").symbol.nunique().eq(len(SYMBOLS)).all()
    FUNDAMENTAL_PANEL_PATH.parent.mkdir(exist_ok=True)
    panel.to_csv(FUNDAMENTAL_PANEL_PATH, index=False, date_format="%Y-%m-%d")
    metadata = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(), "rows": len(panel), "dates": len(dates),
        "first_date": str(dates.min().date()), "last_date": str(dates.max().date()), "symbols": list(SYMBOLS),
        "value_features": FUND_VALUE_FEATURES, "missing_indicator_features": FUND_MISSING_FEATURES, "feature_columns": FUND_FEATURES,
        "units": {name: "calendar days since financial period end" if name.endswith("age_days") else "decimal ratio" for name in FUND_VALUE_FEATURES},
        "formulas": FORMULAS, "source_sha256": hashes,
        "missing_counts": {name: int(panel[name].isna().sum()) for name in FUND_VALUE_FEATURES},
        "missing_counts_by_symbol": panel.groupby("symbol")[FUND_VALUE_FEATURES].agg(lambda col: int(col.isna().sum())).to_dict("index"),
        "checks": checks, "prefix_cutoff": str(cutoff.date()),
        "sha256": hashlib.sha256(FUNDAMENTAL_PANEL_PATH.read_bytes()).hexdigest(),
        "limitations": [
            "Historical asof reconstruction from today's SEC extract is not a complete vintage database; later deletion/correction of source filings can remain unobservable.",
            "Raw snapshots include post-2025 records, but no post-observation filed fact enters features; no 2026 price/holdout data used.",
            "Revenue concept fallback follows a fixed priority among matching facts, not assumed economic equivalence across all industries.",
            "Annual profit/CFO divided by latest assets are timing-mismatched proxies, not precise same-period return on assets.",
            "Current 30 surviving stocks, coverage differences, bank accounting and historical company reorganizations remain limitations.",
            "Annual and balance ages measure period-end age; later re-reporting of an old period does not make performance recent.",
        ],
    }
    FUNDAMENTAL_PANEL_PATH.with_suffix(".json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    (FUNDAMENTAL_PANEL_PATH.parent / "fundamental_audit_examples_v1.json").write_text(json.dumps(samples, indent=2, ensure_ascii=False), encoding="utf-8")
    with (FUNDAMENTAL_PANEL_PATH.parent / "fundamental_provenance_v1.jsonl").open("w", encoding="utf-8") as handle:
        for item in provenance:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    print(f"已保存 {len(panel):,} 行、8财务值+8缺失标记，30股全部保留：{FUNDAMENTAL_PANEL_PATH}", flush=True)
    print(f"缺失行数：{metadata['missing_counts']}", flush=True)


if __name__ == "__main__":
    prepare_and_save()
