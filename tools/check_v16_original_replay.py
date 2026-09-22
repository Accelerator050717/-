"""Independent original UI vs recovered diagnostic fields; no new replay.

This verifies economic content that was actually recovered. A local file SHA
does not verify the truncated cloud payload or its omitted tail.
"""
import csv
from collections import Counter, defaultdict
from decimal import Decimal as D
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/experiments/momentum_loss_attribution_v16"
ZERO = D(0)
ALIASES = {"GOLD": "B", "FB": "META", "SQ": "XYZ"}


def load(path):
    return json.loads(path.read_text(encoding="utf-8-sig"), parse_float=D)


def compare_native_order_ui():
    original_path = OUT / "ORIGINAL_B10_ORDERS_UI.json"
    diagnostic_path = OUT / "DIAGNOSTIC_ORDERS_UI.json"
    original, diagnostic = load(original_path), load(diagnostic_path)
    assert original["columns"] == diagnostic["columns"]
    assert original["backtest_id"] == "549882ad625e8d4d5a4c149d8f943cd0"
    assert diagnostic["backtest_id"] == "3f5d23c2dd0ee166d0bbaa1699553c03"
    normalize = lambda rows: [tuple(" ".join(str(cell).split()) for cell in row) for row in rows]
    old, new = normalize(original["rows"]), normalize(diagnostic["rows"])
    assert all(len(row) == 7 for row in old+new)
    differences = []
    for index in range(max(len(old), len(new))):
        a = old[index] if index < len(old) else None
        b = new[index] if index < len(new) else None
        if a != b:
            differences.append({"one_based_row": index+1, "original": a, "diagnostic": b})
    datasets = {}
    for name, rows, path in (("original", old, original_path), ("diagnostic", new, diagnostic_path)):
        counts = Counter(rows)
        statuses = Counter(r[5] for r in rows)
        tags = Counter(r[6] for r in rows)
        types = Counter(r[2] for r in rows)
        datasets[name] = dict(
            source=str(path.relative_to(ROOT)), source_local_file_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            normalized_rows_sha256=hashlib.sha256(json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest(),
            row_count=len(rows), displayed_cell_count=len(rows)*7,
            duplicate_visible_rows=[{"row": row, "occurrences": count} for row, count in counts.items() if count > 1],
            statuses=dict(statuses), tags=dict(tags), order_types=dict(types),
            positive_quantity_count=sum(D(r[4]) > 0 for r in rows),
            negative_quantity_count=sum(D(r[4]) < 0 for r in rows),
            zero_quantity_count=sum(D(r[4]) == 0 for r in rows))
    result = dict(
        status="PASS" if not differences and len(old) == len(new) == 458 else "FAIL",
        comparison="all seven UI columns, same row order, whitespace normalized only",
        columns=original["columns"], differences=differences, datasets=datasets,
        all_statuses_filled=all(set(info["statuses"]) == {"Filled"} for info in datasets.values()),
        no_duplicate_visible_rows=all(not info["duplicate_visible_rows"] for info in datasets.values()),
        expected_tags_only=all(set(info["tags"]) <= {"v15:monthly:buy", "v15:monthly:reduce", "v15:terminal:reduce", "Liquidate from delisting"} for info in datasets.values()),
        limitations=["These are UI-rendered submitted timestamps, quantities, status, tags and rounded fill prices.",
                     "Matching 458 displayed rows does not assert equality of every unrounded fill field or prove an omitted unique order identifier.",
                     "No duplicate visible rows is a property of these captured tables; it does not replace the native order-state and quantity checks.",
                     "This independent full Orders UI comparison does not restore or validate the truncated diagnostic log tail."])
    (OUT / "INDEPENDENT_NATIVE_ORDER_CHECK.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str)+"\n", encoding="utf-8")
    assert result["status"] == "PASS" and result["all_statuses_filled"] and result["no_duplicate_visible_rows"] and result["expected_tags_only"], result
    return result


def main():
    native_order_check = compare_native_order_ui()
    path = OUT / "DIAGNOSTIC_RECOVERED_FIELDS.json"
    recovered = load(path)
    original = list(csv.DictReader((OUT / "original_native_ticker_pnl.csv").open(encoding="utf-8")))
    by_ui = {r["ui_ticker"]: r for r in original}
    total = defaultdict(lambda: {"price_pnl": ZERO, "fees": ZERO, "dividends": ZERO, "split_cash": ZERO})
    assert len(recovered["ids"]) == len(by_ui) == 133
    for values in recovered["securities"]:
        row = dict(zip(recovered["security_fields"], values))
        for field in ("price_pnl", "fees"):
            total[row["sid_index"]][field] += row[field]
    for values in recovered["corporate_by_security"]:
        row = dict(zip(recovered["corporate_fields"], values))
        for field in ("dividends", "split_cash"):
            total[row["sid_index"]][field] += row[field]
    checks, seen = [], set()
    for index, (sid, label) in enumerate(recovered["ids"]):
        ticker = ALIASES.get(label, label)
        assert ticker in by_ui and ticker not in seen, (sid, label, ticker)
        seen.add(ticker)
        old = by_ui[ticker]
        actual = total[index]
        actual["net_pnl"] = actual["price_pnl"]+actual["dividends"]+actual["split_cash"]-actual["fees"]
        delta = actual["price_pnl"]-D(old["gross_price_pnl_display"])
        # UI native matched P&L is displayed to cents. This is a conservative
        # sum-of-rounding bound, plus tiny floating point tolerance only.
        bound = D(old["matched_rows"])*D("0.005")
        checks.append(dict(sid=sid, observer_label=label, original_ui_ticker=ticker,
                           matched_rows=int(old["matched_rows"]),
                           original_gross_pnl_display=D(old["gross_price_pnl_display"]),
                           recovered_gross_price_pnl=actual["price_pnl"],
                           delta=delta, display_rounding_bound=bound,
                           within_bound=abs(delta) <= bound+D("0.00000001"),
                           dividends=actual["dividends"], split_cash=actual["split_cash"], fees=actual["fees"], net_pnl=actual["net_pnl"]))
    assert seen == set(by_ui)
    assert all(r["within_bound"] for r in checks)
    precise = {field: sum((r[field] for r in checks), ZERO) for field in ("recovered_gross_price_pnl", "dividends", "split_cash", "fees", "net_pnl")}
    baseline = load(ROOT / "data/experiments/dynamic_universe_pilot_v15/runs/B10.json")["summary"][0]
    account_pnl = baseline["final_equity"]-D(100000)
    assert abs(precise["net_pnl"]-account_pnl) < D("0.00000001")
    assert abs(precise["fees"]-baseline["fees_paid"]) < D("0.00000001")
    assert recovered["summary"]["final_equity"] == baseline["final_equity"]
    assert recovered["comparison"]["annual"] == baseline["annual_returns"]
    priority = []
    intervals = load(OUT / "ORIGINAL_ORDER_ANALYSIS.json")["intervals"]
    identity_by_ui = {r["original_ui_ticker"]: r for r in checks}
    linked_intervals = []
    for interval in intervals:
        identity = identity_by_ui[interval["ui_ticker"]]
        linked_intervals.append(dict(sid=identity["sid"], observer_label=identity["observer_label"],
                                     **{k: v for k, v in interval.items() if k not in ("order_rows", "native_matched_rows", "events")}))
    with (OUT / "original_intervals_with_sid.csv").open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(linked_intervals[0]))
        writer.writeheader()
        writer.writerows(linked_intervals)
    for values in recovered["priority_entries"]:
        row = dict(zip(recovered["priority_entry_fields"], values))
        sid, label = recovered["ids"][row["sid_index"]]
        ui = ALIASES.get(label, label)
        match = [r for r in intervals if r["ui_ticker"] == ui and
                 r["first_entry_receipt_local"][:10] == row["entry"] and r["last_exit_receipt_local"][:10] == row["exit"]]
        assert len(match) == 1, (row, match)
        old = match[0]
        # These recovered 12 focus intervals each have one unchanged-quantity
        # buy and one sell. This claim is checked, not generalized to splits.
        assert len(old["order_rows"]) == 2 and not old["events"]
        assert row["first_buy_quantity"] == row["total_sold_quantity"]
        exact_price = row["total_sold_quantity"]*row["weighted_exit_price"]-row["first_buy_quantity"]*row["first_buy_price"]
        delta = exact_price-D(old["native_gross_price_pnl_display"])
        bound = D(len(old["native_matched_rows"]))*D("0.005")
        assert abs(delta) <= bound+D("0.00000001")
        priority.append(dict(sid=sid, observer_label=label, original_ui_ticker=ui,
                             entry=row["entry"], exit=row["exit"],
                             original_interval_id=old["interval_id"], observer_episode_id=row["episode_id"],
                             original_price_pnl_display=D(old["native_gross_price_pnl_display"]),
                             recovered_price_pnl=exact_price, delta=delta, rounding_bound=bound,
                             recovered_net_pnl=row["net_pnl"], recovered_fees=row["fees"]))
    result = dict(
        status="RECOVERED_FIELDS_ECONOMIC_RECONCILIATION_PASS_NOT_FULL_PAYLOAD_VERIFICATION",
        original_backtest_id="549882ad625e8d4d5a4c149d8f943cd0",
        diagnostic_backtest_id="3f5d23c2dd0ee166d0bbaa1699553c03",
        source_local_file_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        source_local_hash_scope="local recovered JSON only; NOT a verification of complete compressed cloud payload",
        limitations=["Cloud compressed log was truncated. No omitted tail, checksum, focus fills or metadata are invented.",
                     "Only complete recovered objects used: 133 IDs, 167 security-year rows, 41 corporate rows and 12 priority intervals.",
                     "Full-period UI gross matched P&L compares to full-period diagnostic price P&L. Exit-year UI is NOT compared to calendar-year MTM.",
                     "GOLD/B, FB/META and SQ/XYZ are paired source labels, not an assertion that either source label is always the historical ticker.",
                     "Dividend and fee allocation is diagnostic evidence; original aggregate amounts match independently.",
                     "Per-security equality corroborates recovered economics, not completeness of omitted payload or detailed daily path."],
        alias_pairs=[dict(sid=r["sid"], observer_label=r["observer_label"], original_ui_ticker=r["original_ui_ticker"], delta=r["delta"])
                     for r in checks if r["observer_label"] != r["original_ui_ticker"]],
        totals=dict(**precise, original_account_net_pnl=account_pnl,
                    original_UI_display_price_sum=sum((D(r["gross_price_pnl_display"]) for r in original), ZERO),
                    net_sum_minus_original_account=precise["net_pnl"]-account_pnl,
                    max_abs_per_security_display_delta=max(abs(r["delta"]) for r in checks)),
        compared_security_count=len(checks), all_security_display_bounds_pass=True,
        original_intervals_linked_to_recovered_sid=len(linked_intervals),
        security_checks=checks,
        top_10_net_losses=sorted(checks, key=lambda r: r["net_pnl"])[:10],
        top_10_net_winners=sorted(checks, key=lambda r: r["net_pnl"], reverse=True)[:10],
        priority_interval_checks=priority)
    result["native_order_ui_comparison"] = {key: native_order_check[key] for key in
                                            ("status", "comparison", "all_statuses_filled", "no_duplicate_visible_rows", "expected_tags_only")}
    dump = lambda value: json.dumps(value, ensure_ascii=False, indent=2, default=str)+"\n"
    (OUT / "INDEPENDENT_ORIGINAL_REPLAY_CHECK.json").write_text(dump(result), encoding="utf-8")
    lines = ["# 原运行与诊断恢复字段：独立金额对账", "",
             "133个证券全部能一一对齐；逐证券全期价格损益差均在原生UI每配对交易最多0.005美元的舍入界限内。没有拿原UI退出年度结果和日历年盯市损益直接比较。", "",
             "另独立逐行比较原运行和诊断的458条原生Orders UI记录，全部7列共3,206个显示单元格在仅规范空白后完全相同。两边均无重复显示行，状态全部Filled，数量为219买/239卖；状态、订单类型和标签分布相同。详见[独立订单检查](INDEPENDENT_NATIVE_ORDER_CHECK.json)。这仍是显示价精度与提交时点核对，不冒充完整精度成交或缺失订单ID验证。", "",
             "**这不等于完整日志传输验证。** 诊断压缩日志尾部被截断；仅使用实际恢复的完整对象，不补造尾部、不宣称压缩内容SHA验收通过。文件哈希仅识别本地恢复结果。", "",
             "| 项目 | 美元 |", "|---|---:|"]
    for key, value in result["totals"].items():
        lines.append(f"| {key} | {value} |")
    lines += ["", "GOLD→原UI B、FB→原UI META、SQ→原UI XYZ三组标签均保留稳定SID和金额核验。它们不是三笔额外交易，也不能把任一来源标签自动称为当时ticker。", "",
              "12个重点区间的首买和最终卖出日期、单笔数量、价格损益也独立对应原订单/交易。EQT实际卖价33.675，与原UI33.67的显示舍入差解释了0.655美元现金差；最终价格损益−2007.575，原UI显示−2007.58。", "",
              "| 证券SID | 来源标签 / 原UI | 全期净损益 | 价格损益 | 分红 | 费用 |", "|---|---|---:|---:|---:|---:|"]
    for r in result["top_10_net_losses"]:
        lines.append(f"| {r['sid']} | {r['observer_label']} / {r['original_ui_ticker']} | {r['net_pnl']} | {r['recovered_gross_price_pnl']} | {r['dividends']} | {r['fees']} |")
    lines += ["", "盈利来源:", "", "| 证券SID | 标签 | 净损益 |", "|---|---|---:|"]
    for r in result["top_10_net_winners"]:
        lines.append(f"| {r['sid']} | {r['observer_label']} / {r['original_ui_ticker']} | {r['net_pnl']} |")
    (OUT / "INDEPENDENT_ORIGINAL_REPLAY_CHECK.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    print(dump({k: result[k] for k in ("status", "compared_security_count", "totals", "alias_pairs")}))


if __name__ == "__main__":
    main()
