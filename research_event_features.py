"""从已保存 SEC 事实构造财务同比变化与真正新报告期公开事件。

不读取标签/价格收益，不把 comparative 重列或修改申报当成新报告期。
财务数值严格 filed < 观察日；缺失原样保留，填补应只在训练集拟合。
"""

import numpy as np
import pandas as pd

import fundamental_features as fund
from panel_config import ROOT

EVENT_PANEL_PATH = ROOT / "data" / "processed" / "event_panel_v1.csv"
EVENT_AUDIT_DIR = ROOT / "data" / "processed" / "event_panel_v1_audit"
EVENT_VALUE_FEATURES = [
    "event_annual_revenue_growth_yoy",
    "event_annual_profit_margin_change_yoy",
    "event_annual_cfo_margin_change_yoy",
    "event_annual_profit_change_to_assets",
    "event_annual_cfo_to_assets_change_yoy",
    "event_balance_liabilities_ratio_change_yoy",
    "event_balance_equity_ratio_change_yoy",
    "event_sessions_since_new_balance",
    "event_sessions_since_new_annual",
    "event_new_balance_filed_5d", "event_new_balance_filed_20d",
    "event_new_annual_filed_5d", "event_new_annual_filed_20d",
    "event_financial_amendment_filed_20d",
]
EVENT_MISSING_FEATURES = [f"{name}_missing" for name in EVENT_VALUE_FEATURES]
EVENT_FEATURES = EVENT_VALUE_FEATURES + EVENT_MISSING_FEATURES
CHANGE_FEATURES = EVENT_VALUE_FEATURES[:7]
FORMULAS = {
    EVENT_VALUE_FEATURES[0]: "current annual revenue / prior annual revenue - 1; denominator positive",
    EVENT_VALUE_FEATURES[1]: "current annual profit/revenue minus prior annual profit/revenue",
    EVENT_VALUE_FEATURES[2]: "current annual operating cash flow/revenue minus prior annual operating cash flow/revenue",
    EVENT_VALUE_FEATURES[3]: "(current annual net income - prior annual net income) / current same-year-end Assets",
    EVENT_VALUE_FEATURES[4]: "current annual CFO/same-year-end Assets minus prior annual CFO/same-year-end Assets",
    EVENT_VALUE_FEATURES[5]: "latest liabilities/assets minus prior-year liabilities/assets; ratios matched within each accession/end",
    EVENT_VALUE_FEATURES[6]: "latest stockholders equity/assets minus prior-year stockholders equity/assets; ratios matched within each accession/end",
    EVENT_VALUE_FEATURES[7]: "NYSE sessions since first usable session strictly after the filing that advanced the latest original balance-sheet period",
    EVENT_VALUE_FEATURES[8]: "NYSE sessions since first usable session strictly after the original 10-K filing that advanced the latest annual period",
    EVENT_VALUE_FEATURES[9]: "1 when new balance-period event age is 0-4 sessions, otherwise 0 after coverage begins",
    EVENT_VALUE_FEATURES[10]: "1 when new balance-period event age is 0-19 sessions, otherwise 0 after coverage begins",
    EVENT_VALUE_FEATURES[11]: "1 when new annual-period event age is 0-4 sessions, otherwise 0 after coverage begins",
    EVENT_VALUE_FEATURES[12]: "1 when new annual-period event age is 0-19 sessions, otherwise 0 after coverage begins",
    EVENT_VALUE_FEATURES[13]: "1 if an eligible 10-K/A or 10-Q/A containing selected financial facts became usable in last 20 sessions; distinct from new-period events",
}


def _prior_period(known, current, role, match_start=False):
    if current is None:
        return None
    candidates = [row for row in known if row["role"] == role
                  and 330 <= (current["end"]-row["end"]).days <= 400]
    if match_start:
        candidates = [row for row in candidates if row["start"] is not None
                      and 330 <= (current["start"]-row["start"]).days <= 400]
    if not candidates:
        return None
    closest = min(abs((current["end"]-row["end"]).days-365) for row in candidates)
    return fund._latest([row for row in candidates if abs((current["end"]-row["end"]).days-365) == closest])


def _annual_assets(known, annual):
    if annual is None:
        return None
    # 年度利润为duration，Assets为instant；先换成同一end的instant匹配锚。
    return fund._matching(known, {**annual, "start": None}, "assets")


def _difference(left, right):
    return left-right if np.isfinite(left) and np.isfinite(right) else np.nan


def financial_changes_asof(records, date):
    """每个日期先筛当时已知版本；同比两期各自保留完整原始事实来源。"""
    date = pd.Timestamp(date)
    known = [row for row in records if row["filed"] < date]
    balance = fund._latest([row for row in known if row["role"] == "assets"])
    prior_balance = _prior_period(known, balance, "assets")
    annual = fund._latest([row for row in known if row["role"] == "profit"])
    prior_annual = _prior_period(known, annual, "profit", match_start=True)
    sources = {"balance_assets": balance, "prior_balance_assets": prior_balance,
               "annual_profit": annual, "prior_annual_profit": prior_annual}
    for prefix, anchor in (("balance", balance), ("prior_balance", prior_balance)):
        sources[f"{prefix}_liabilities"] = fund._matching(known, anchor, "liabilities")
        sources[f"{prefix}_equity"] = fund._matching(known, anchor, "equity")
    for prefix, anchor in (("annual", annual), ("prior_annual", prior_annual)):
        sources[f"{prefix}_revenue"] = fund._matching(known, anchor, "revenue")
        sources[f"{prefix}_cfo"] = fund._matching(known, anchor, "cfo")
        sources[f"{prefix}_assets"] = _annual_assets(known, anchor)
    revenue, prior_revenue = sources["annual_revenue"], sources["prior_annual_revenue"]
    cfo, prior_cfo = sources["annual_cfo"], sources["prior_annual_cfo"]
    assets, prior_assets = sources["annual_assets"], sources["prior_annual_assets"]
    revenue_growth = fund._ratio(revenue, prior_revenue)
    delta_profit = ({"val": annual["val"]-prior_annual["val"]} if annual and prior_annual else None)
    values = {
        "event_annual_revenue_growth_yoy": revenue_growth-1 if np.isfinite(revenue_growth) else np.nan,
        "event_annual_profit_margin_change_yoy": _difference(fund._ratio(annual, revenue), fund._ratio(prior_annual, prior_revenue)),
        "event_annual_cfo_margin_change_yoy": _difference(fund._ratio(cfo, revenue), fund._ratio(prior_cfo, prior_revenue)),
        "event_annual_profit_change_to_assets": fund._ratio(delta_profit, assets),
        "event_annual_cfo_to_assets_change_yoy": _difference(fund._ratio(cfo, assets), fund._ratio(prior_cfo, prior_assets)),
        "event_balance_liabilities_ratio_change_yoy": _difference(fund._ratio(sources["balance_liabilities"], balance), fund._ratio(sources["prior_balance_liabilities"], prior_balance)),
        "event_balance_equity_ratio_change_yoy": _difference(fund._ratio(sources["balance_equity"], balance), fund._ratio(sources["prior_balance_equity"], prior_balance)),
    }
    return values, sources


def identify_period_events(records):
    """原始申报的报告期须严格推进；旧期间的重列值不会刷新事件时钟。"""
    grouped = {}
    for row in records:
        grouped.setdefault(row["filed"], []).append(row)
    high_watermark = {"balance": None, "annual": None}
    events = []
    for filed, same_day in sorted(grouped.items()):
        for kind in ("balance", "annual"):
            if kind == "balance":
                possible = [row for row in same_day if row["role"] == "assets" and row["form"] in {"10-K", "10-Q"}]
            else:
                possible = [row for row in same_day if row["role"] in {"profit", "revenue", "cfo"} and row["form"] == "10-K"]
            if not possible:
                continue
            period_end = max(row["end"] for row in possible)
            prior_end = high_watermark[kind]
            if prior_end is None or period_end > prior_end:
                selected = sorted([row for row in possible if row["end"] == period_end],
                                  key=lambda row: ({"profit": 0, "assets": 0, "revenue": 1, "cfo": 2}[row["role"]], row["accn"], row["tag_priority"]))[0]
                events.append({"kind": kind, "filed": filed, "period_end": period_end,
                               "previous_period_end": prior_end, "accn": selected["accn"],
                               "form": selected["form"], "source_fact": selected})
                high_watermark[kind] = period_end
        amendments = [row for row in same_day if row["form"] in {"10-K/A", "10-Q/A"}]
        if amendments:
            selected = sorted(amendments, key=lambda row: (row["end"], row["accn"]))[-1]
            events.append({"kind": "financial_amendment", "filed": filed, "period_end": selected["end"],
                           "previous_period_end": None, "accn": selected["accn"], "form": selected["form"], "source_fact": selected})
    return events


def _event_age(dates, calendar, events, kind):
    positions = sorted({int(calendar.searchsorted(row["filed"], side="right")) for row in events if row["kind"] == kind})
    result = np.full(len(dates), np.nan)
    if not positions:
        return result
    positions = np.asarray(positions)
    observation_positions = calendar.get_indexer(dates)
    if (observation_positions < 0).any():
        raise ValueError("观察日期不是指定 NYSE 交易日。")
    selected = np.searchsorted(positions, observation_positions, side="right")-1
    valid = selected >= 0
    result[valid] = observation_positions[valid]-positions[selected[valid]]
    return result


def build_company_events(symbol, payload, dates, calendar, max_filed=fund.MAX_FILED):
    dates, calendar = pd.DatetimeIndex(dates), pd.DatetimeIndex(calendar)
    records, rejected = fund.extract_records(payload, max_filed=max_filed)
    filing_dates = sorted({row["filed"] for row in records if row["filed"] < dates.max()})
    snapshots, provenance = [], []
    for filed in filing_dates:
        values, sources = financial_changes_asof(records, filed+pd.Timedelta(days=1))
        snapshots.append({"filed": filed, **values})
        provenance.append({"symbol": symbol, "event_filed": str(filed.date()),
                           "facts": {name: fund._json_record(record) for name, record in sources.items()}})
    output = pd.DataFrame({"Date": dates})
    if snapshots:
        output = pd.merge_asof(output, pd.DataFrame(snapshots), left_on="Date", right_on="filed", direction="backward", allow_exact_matches=False)
    else:
        for name in CHANGE_FEATURES:
            output[name] = np.nan
    events = identify_period_events(records)
    for kind in ("balance", "annual"):
        age = _event_age(dates, calendar, events, kind)
        output[f"event_sessions_since_new_{kind}"] = age
        for days in (5, 20):
            output[f"event_new_{kind}_filed_{days}d"] = np.where(np.isfinite(age), (age < days).astype(float), np.nan)
    amendment_age = _event_age(dates, calendar, events, "financial_amendment")
    coverage = dates > min(row["filed"] for row in records) if records else np.zeros(len(dates), dtype=bool)
    output["event_financial_amendment_filed_20d"] = np.where(coverage, (amendment_age < 20).astype(float), np.nan)
    output["symbol"] = symbol
    for name in EVENT_VALUE_FEATURES:
        output[f"{name}_missing"] = output[name].isna().astype(int)
    result = output[["Date", "symbol", *EVENT_FEATURES]]
    assert not np.isinf(result[EVENT_FEATURES].to_numpy(dtype=float)).any()
    return result, provenance, events, {"symbol": symbol, "accepted_records": len(records), "rejected": rejected}
