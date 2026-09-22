"""Read-only Decimal analysis of original QC B10 UI-derived trade records.

Native Trades uses FIFO FillToFill grouping. Its exit-year attribution is NOT
calendar-year mark-to-market P&L. UI tickers may reflect later renames; do not
invent stable SIDs or historical ticker mappings. The v16 observer supplies the
independent daily/interval attribution. No market retrieval or model fitting.
"""
from __future__ import annotations

import csv
from collections import defaultdict
from decimal import Decimal
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/experiments/momentum_loss_attribution_v16"
D = Decimal
ZERO = D("0")


def money(text):
    return D(str(text).replace("Fill:", "").replace(" USD", "").replace("$", "").replace(",", "").strip())


def load(path):
    return json.loads(path.read_text(encoding="utf-8-sig"), parse_float=D)


def serial(value):
    if isinstance(value, D):
        return str(value)
    raise TypeError(type(value).__name__)


def dump(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=serial) + "\n", encoding="utf-8")


def write_csv(path, rows):
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def aggregate(rows):
    by = defaultdict(list)
    for row in rows:
        by[row["ui_ticker"]].append(row)
    result = []
    for ticker, group in by.items():
        gross = sum((r["gross_price_pnl_display"] for r in group), ZERO)
        fees = sum((r["allocated_fees_display"] for r in group), ZERO)
        result.append(dict(ui_ticker=ticker, matched_rows=len(group), gross_price_pnl_display=gross,
                           allocated_fees_display=fees, gross_less_display_allocated_fees=gross-fees,
                           winning_rows=sum(r["gross_price_pnl_display"] > 0 for r in group),
                           losing_rows=sum(r["gross_price_pnl_display"] < 0 for r in group)))
    return sorted(result, key=lambda r: (r["gross_price_pnl_display"], r["ui_ticker"]))


def concentration(grouped, trades, net_account_loss=None):
    losses = sorted((-r["gross_price_pnl_display"] for r in grouped if r["gross_price_pnl_display"] < 0), reverse=True)
    gross_losing_security_sum = sum(losses, ZERO)
    gross_losing_matched_rows = -sum((r["gross_price_pnl_display"] for r in trades if r["gross_price_pnl_display"] < 0), ZERO)
    result = {"sum_negative_ui_ticker_price_pnl_magnitude": gross_losing_security_sum,
              "sum_negative_native_matched_row_price_pnl_magnitude": gross_losing_matched_rows}
    for n in (1, 5, 10):
        amount = sum(losses[:n], ZERO)
        result[f"top_{n}_losing_ui_tickers"] = {
            "gross_price_loss_magnitude": amount,
            "share_of_negative_ticker_price_pnl": amount / gross_losing_security_sum if gross_losing_security_sum else None,
            "share_of_negative_matched_row_price_pnl": amount / gross_losing_matched_rows if gross_losing_matched_rows else None,
            "share_of_net_account_loss": amount / net_account_loss if net_account_loss else None,
        }
    return result


def analyze_orders(trades, base):
    """Group displayed original fills using only two confirmed held splits.

    Full-period price P&L is the negative signed-notional sum because the
    original run starts and ends flat. Displayed fill-price rounding remains a
    measured residual. Native matched rows supply receipt times and a second
    independently rounded price-P&L sum; neither is silently made exact.
    """
    source = OUT / "ORIGINAL_B10_ORDERS_UI.json"
    if not source.exists():
        return None
    doc = load(source)
    assert doc["backtest_id"] == "549882ad625e8d4d5a4c149d8f943cd0"
    splits = [("2022-08-25", "TSLA", D(3)), ("2022-09-14", "PANW", D(3))]
    split_index = 0
    positions = defaultdict(lambda: ZERO)
    active = {}
    completed = []
    orders = []
    for index, raw in enumerate(doc["rows"], 1):
        submitted, ticker = raw[0].lstrip("+"), raw[1]
        assert raw[5] == "Filled", (index, raw)
        while split_index < len(splits) and splits[split_index][0] <= submitted[:10]:
            date, split_ticker, multiplier = splits[split_index]
            if positions[split_ticker]:
                active[split_ticker]["events"].append({"date": date, "type": "confirmed_held_split", "quantity_multiplier": multiplier,
                                                       "before": positions[split_ticker], "after": positions[split_ticker]*multiplier})
                positions[split_ticker] *= multiplier
            split_index += 1
        quantity, price = D(raw[4]), money(raw[3])
        assert quantity != 0 and price > 0
        if positions[ticker] == 0:
            assert quantity > 0, (ticker, quantity)
            active[ticker] = dict(ui_ticker=ticker, first_submission_local=submitted,
                                  order_rows=[], events=[], displayed_buy_notional=ZERO,
                                  displayed_sell_notional=ZERO, displayed_notional_fee_estimate=ZERO)
        interval = active[ticker]
        fee = ZERO if raw[6] == "Liquidate from delisting" else abs(quantity*price)*D("0.001")
        row = dict(original_order_row=index, submitted_local=submitted, ui_ticker=ticker,
                   order_type=raw[2], signed_quantity=quantity, fill_price_display=price,
                   signed_notional_display=quantity*price, fee_estimate_from_display_notional=fee,
                   native_terminal=raw[6] == "Liquidate from delisting", status=raw[5], tag=raw[6])
        orders.append(row)
        interval["order_rows"].append(index)
        interval["displayed_notional_fee_estimate"] += fee
        if quantity > 0:
            interval["displayed_buy_notional"] += quantity*price
        else:
            interval["displayed_sell_notional"] -= quantity*price
        positions[ticker] += quantity
        assert positions[ticker] >= 0, (index, ticker, positions[ticker])
        if positions[ticker] == 0:
            interval["last_submission_local"] = submitted
            interval["gross_price_pnl_from_display_orders"] = interval["displayed_sell_notional"]-interval["displayed_buy_notional"]
            completed.append(interval)
            del active[ticker]
    assert not active and all(q == 0 for q in positions.values()), (active, dict(positions))
    completed.sort(key=lambda r: (r["first_submission_local"], r["ui_ticker"]))
    assigned = []
    for i, interval in enumerate(completed, 1):
        interval["interval_id"] = f"original-{i:03d}"
        later = [r["first_submission_local"] for r in completed
                 if r["ui_ticker"] == interval["ui_ticker"] and r["first_submission_local"] > interval["first_submission_local"]]
        next_start = min(later) if later else "9999"
        matched = [r for r in trades if r["ui_ticker"] == interval["ui_ticker"] and
                   interval["first_submission_local"] < r["entry_receipt_local"] < next_start]
        assert matched, interval
        assigned.extend(r["native_trade_row"] for r in matched)
        interval["native_matched_rows"] = [r["native_trade_row"] for r in matched]
        interval["first_entry_receipt_local"] = min(r["entry_receipt_local"] for r in matched)
        interval["last_exit_receipt_local"] = max(r["exit_receipt_local"] for r in matched)
        interval["native_gross_price_pnl_display"] = sum((r["gross_price_pnl_display"] for r in matched), ZERO)
        interval["native_allocated_fee_display"] = sum((r["allocated_fees_display"] for r in matched), ZERO)
        interval["native_minus_display_order_pnl"] = interval["native_gross_price_pnl_display"]-interval["gross_price_pnl_from_display_orders"]
    assert sorted(assigned) == sorted(r["native_trade_row"] for r in trades)
    write_csv(OUT / "original_orders.csv", orders)
    scalar = [{k: v for k, v in r.items() if k not in ("order_rows", "events", "native_matched_rows")} for r in completed]
    write_csv(OUT / "original_flat_intervals.csv", scalar)
    gross = sum((r["gross_price_pnl_from_display_orders"] for r in completed), ZERO)
    net = gross+base["dividend_cash_engine_proxy"]+base["split_fraction_cash_engine_proxy"]-base["fees_paid"]
    by_exit_year = {}
    for year in ("2022", "2023", "full"):
        group = [r for r in completed if year == "full" or r["last_exit_receipt_local"][:4] == year]
        pnls = [r["native_gross_price_pnl_display"] for r in group]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        by_exit_year[year] = dict(
            scope="flat-to-flat, grouped by final exit year; NOT calendar-year MTM",
            intervals=len(group), winning_intervals=len(wins), losing_intervals=len(losses),
            zero_intervals=sum(p == 0 for p in pnls),
            gross_winning_interval_pnl=sum(wins, ZERO), gross_losing_interval_pnl=sum(losses, ZERO),
            mean_winner=sum(wins, ZERO)/len(wins) if wins else None,
            mean_loser=sum(losses, ZERO)/len(losses) if losses else None,
            worst_10=sorted(group, key=lambda r: r["native_gross_price_pnl_display"])[:10],
            best_10=sorted(group, key=lambda r: r["native_gross_price_pnl_display"], reverse=True)[:10])
    result = dict(
        source={"path": str(source.relative_to(ROOT)), "sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "backtest_id": doc["backtest_id"]},
        limitations=["Grouping uses displayed original order quantities and confirmed TSLA/PANW 3-for-1 splits; all positions finish flat.",
                     "Order timestamps are submissions, not fills. First/last receipt times come from associated original native matched rows.",
                     "UI tickers are not asserted as historical ticker or stable SID.",
                     "Order price and native trade P&L display rounding differ. Observer is required for precise daily MTM and fees.",
                     "Flat-interval gross P&L excludes dividends and split cash; do not label it total economic P&L."],
        order_count=len(orders), flat_interval_count=len(completed), native_matched_row_count=len(assigned),
        gross_price_pnl_from_display_orders=gross,
        displayed_notional_fee_estimate=sum((r["fee_estimate_from_display_notional"] for r in orders), ZERO),
        original_actual_fees=base["fees_paid"],
        unexplained_residual_with_display_order_prices=base["final_equity"]-D(100000)-net,
        intervals=completed,
        interval_exit_year_statistics=by_exit_year,
        worst_10_flat_intervals_by_native_display_price_pnl=sorted(completed, key=lambda r: r["native_gross_price_pnl_display"])[:10],
        best_10_flat_intervals_by_native_display_price_pnl=sorted(completed, key=lambda r: r["native_gross_price_pnl_display"], reverse=True)[:10],
        TOP={"orders": [r for r in orders if r["ui_ticker"] == "TOP"], "intervals": [r for r in completed if r["ui_ticker"] == "TOP"]},
        TWTR={"orders": [r for r in orders if r["ui_ticker"] == "TWTR"], "intervals": [r for r in completed if r["ui_ticker"] == "TWTR"]},
    )
    dump(OUT / "ORIGINAL_ORDER_ANALYSIS.json", result)
    write_event_checks(result, base)
    return {k: result[k] for k in ("order_count", "flat_interval_count", "native_matched_row_count", "gross_price_pnl_from_display_orders", "unexplained_residual_with_display_order_prices")}


def write_event_checks(orders, base):
    """Amounts derive from original fills; corporate facts reuse v15 evidence."""
    evidence = load(ROOT / "data/experiments/dynamic_universe_pilot_v15/runs/B10.json")
    checks = []
    def add(kind, ticker, start, end, quantity, buy, sell, gross, fees, held, action, limitation, source):
        checks.append(dict(kind=kind, ui_ticker=ticker, start_local=start, end_local=end,
                           quantity=quantity, entry_cash_cost=buy, exit_cash_credit=sell,
                           gross_price_pnl=gross, fee_amount=fees,
                           price_pnl_less_fees=gross-fees if gross is not None and fees is not None else None,
                           cash_right_nominal=None, cash_right_minus_already_credited=None,
                           max_B10_held_value_at_missing_observation=held,
                           handling=action, limitation=limitation, source=source))
    for ticker in ("TOP", "TWTR"):
        for interval in orders[ticker]["intervals"]:
            actual_orders = [r for r in orders[ticker]["orders"] if r["original_order_row"] in interval["order_rows"]]
            assert len(actual_orders) == 2
            assert interval["native_gross_price_pnl_display"] == interval["gross_price_pnl_from_display_orders"]
            assert not interval["events"]
            is_terminal = any(r["native_terminal"] for r in actual_orders)
            add("native_held_interval", ticker, interval["first_entry_receipt_local"], interval["last_exit_receipt_local"],
                actual_orders[0]["signed_quantity"], interval["displayed_buy_notional"], interval["displayed_sell_notional"],
                interval["native_gross_price_pnl_display"], interval["displayed_notional_fee_estimate"], None,
                "native forced cash already credited once; zero terminal fee" if is_terminal else "native monthly MOO; buy and sell quantity unchanged",
                "TOP holding-period split not observed in v15 engine; precise external quotes not independently certified" if ticker == "TOP" else
                "terminal credit is an engine cached-price proxy, not evidence of actual payment" if is_terminal else "ordinary trading interval before acquisition",
                "ORIGINAL_B10_ORDERS_UI.json + ORIGINAL_B10_TRADES_UI.json + ../dynamic_universe_pilot_v15/runs/B10.json")
    # The prior v15 issuer-evidence table states $54.20 per eligible TWTR share.
    # This is a claim comparison only: never add the whole receivable again.
    terminal = [r for r in orders["TWTR"]["orders"] if r["native_terminal"]]
    assert len(terminal) == 1
    q = -terminal[0]["signed_quantity"]
    already_credited = -terminal[0]["signed_notional_display"]
    right = q*D("54.20")
    add("cash_right_comparison_only", "TWTR", "2022-10-27", "payment_time_unverified", q,
        None, None, None, None, None,
        "eligible per-share cash right minus already credited cached-price liquidation; NOT added to original NAV",
        "111-share eligibility and payment timing not account-confirmed; static difference excludes reuse timing effects",
        "../dynamic_universe_pilot_v15/TERMINAL_EVENT_EVIDENCE.md + ORIGINAL_B10_ORDERS_UI.json")
    checks[-1]["cash_right_nominal"] = right
    checks[-1]["cash_right_minus_already_credited"] = right-already_credited
    targets = [("WDAY", "2022-06-15"), ("MDT", "2022-09-23"), ("QCOM", "2022-09-28"),
               ("QCOM", "2022-10-03"), ("CSCO", "2022-10-21"), ("MSFT", "2022-12-02"),
               ("GOOG", "2023-04-13"), ("AMZN", "2023-06-28")]
    for ticker, date in targets:
        matches = [r for r in evidence["issue"] if r[0] == "unknown_missing" and r[1] == ticker and r[2] <= date <= r[3]]
        assert len(matches) == 1 and matches[0][5] == 0, (ticker, date, matches)
        add("ordinary_raw_gap", ticker, date, date, ZERO, None, None, None, None, ZERO,
            "B10 had no holding at this observation; no missing-held-price valuation amount belongs to B10",
            "may invalidate a later 21-point momentum history or current-price eligibility; no counterfactual selection P&L established",
            "../dynamic_universe_pilot_v15/runs/B10.json + ../dynamic_universe_pilot_v15/MISSING_PRICE_RESULTS.json")
    write_csv(OUT / "event_missing_checks.csv", checks)
    text = """# TOP、TWTR及普通缺价：原运行证据核查

这份核查只读取已有原生订单、原生配对交易和v15事件记录，没有重放、下载行情或新增假设交易。完整数值见[event_missing_checks.csv](event_missing_checks.csv)。日期是原生回报日；日线MOO模型的开盘成交和16:00收到回报必须分开理解。

|实际区间|买入|卖出/引擎记账|价格损益|费用|价格损益减费用|
|---|---:|---:|---:|---:|---:|
|TOP 2023-05-03—06-02|94股×53.41 = 5,020.54|94股×8.30 = 780.20|−4,240.34|5.80074|−4,246.14074|
|TWTR 2022-05-04—06-02|136股×48.78 = 6,634.08|136股×39.00 = 5,304.00|−1,330.08|11.93808|−1,342.01808|
|TWTR 2022-10-05—10-29|111股×50.25 = 5,577.75|111股×53.78 = 5,969.58|+391.83|5.57775|+386.25225|

以上三段的显示成交金额与原生配对损益完全一致；费用用原10bp公式核算，TWTR引擎终止卖出明确为零费。其他证券的UI价格存在舍入，不能将所有显示订单当作完整精度。TOP持仓从94股至卖出94股，原引擎没有记录该持仓期拆股；v15有限公开文书也未找到对应5月拆股。这个结论不是对任何遗漏公司行动或每个精确报价的独立认证。

TOP大跌异常记录中的7,796.36美元是引擎当时记录的持仓估值，不是亏损额。该异常在v15 `on_data`更新`latest`之前读取`portfolio.holdings_value`，可能含缓存价格，不能用它除以买入成本，宣称买后先盈利约55%。原TOP、KALA、NTRB配对交易显示MFE均为0，MAE分别为−4,418.94、−4,999.92、−4,350.24美元；MFE/MAE也不是完整逐日价格路径，不证明每天单调下跌。应以实际成交及独立日末记账核对路径。

停牌期间10次观察使用旧价市值601.60美元，持仓未消失；恢复时974.78美元同样不是新的现金。实际94股于6月2日模型开盘卖出，不能把5月12—30停牌和恢复标记当成额外损益再相加。

TWTR两段合计价格损益−938.25美元，计费用后−955.76583美元。5,969.58美元已经在原权益中，不能再加一次，也不能全当损失。v15已核实条款每股54.20美元对应111股名义现金权利6,016.20美元，与引擎已记账金额差46.62美元；本轮没有重写原净值。实际到账时点和适用权利仍未得到该模拟持仓的账户证据，46.62只是金额对照，不是含后续现金再投入的反事实总影响。原引擎终止零费还使原结果比普通10bp费用口径高5.96958美元；不能用其解释五万多美元亏损。

八个普通缺价日期分别是WDAY 2022-06-15、MDT 2022-09-23、QCOM 2022-09-28及10-03、CSCO 2022-10-21、MSFT 2022-12-02、GOOG 2023-04-13、AMZN 2023-06-28。v15 B10相应持仓金额均为0；A在QCOM缺价日阻止卖出的金额不属于B。B10的11个持仓缺价观察来自TOP十天和TWTR 2022-10-28一天。无持仓并不证明选股不受影响：这些空缺可能进入后续21点历史检查或当日价格门槛。尚未取得明确的逐月排除原因/替代价格反事实之前，不给它们分摊虚构的交易损失。

来源为原B10 `549882ad625e8d4d5a4c149d8f943cd0` 的Orders/Trades UI、v15 `runs/B10.json`、`MISSING_PRICE_RESULTS.json`和[已有事件证据](../dynamic_universe_pilot_v15/TERMINAL_EVENT_EVIDENCE.md)。供应商原始行情未移出云端。这些结论不同于诊断重放取得的当时信号、稳定SID或完整精度逐日归因。
"""
    (OUT / "EVENT_AND_MISSING_CHECKS.md").write_text(text, encoding="utf-8")


def main():
    source = OUT / "ORIGINAL_B10_TRADES_UI.json"
    data = load(source)
    assert data["backtest_id"] == "549882ad625e8d4d5a4c149d8f943cd0"
    rows = []
    for i, raw in enumerate(data["rows"], 1):
        assert len(raw) == 13 and raw[3] == "Buy", (i, raw)
        rows.append(dict(native_trade_row=i, ui_ticker=raw[1],
                         entry_receipt_local=raw[0].lstrip("+"), exit_receipt_local=raw[2],
                         exit_year=raw[2][:4], quantity=D(raw[6]),
                         entry_price_display=money(raw[4]), exit_price_display=money(raw[5]),
                         gross_price_pnl_display=money(raw[7]), allocated_fees_display=money(raw[8]),
                         gross_less_display_allocated_fees=money(raw[7])-money(raw[8]),
                         display_price_quantity_pnl=(money(raw[5])-money(raw[4]))*D(raw[6])))
    # Displayed prices can be rounded even when the displayed P&L has more
    # precision, and split-normalized entry quantities differ from raw buys.
    write_csv(OUT / "original_native_matched_trades.csv", rows)
    grouped = aggregate(rows)
    write_csv(OUT / "original_native_ticker_pnl.csv", grouped)
    annual = []
    periods = {}
    base = load(ROOT / "data/experiments/dynamic_universe_pilot_v15/runs/B10.json")["summary"][0]
    order_summary = analyze_orders(rows, base)
    account_pnl = base["final_equity"] - D(100000)
    for year in ("2022", "2023", "full"):
        trades = rows if year == "full" else [r for r in rows if r["exit_year"] == year]
        groups = aggregate(trades)
        for r in groups:
            annual.append({"native_exit_year_scope": year, **r})
        periods[year] = dict(
            grouping="Native FIFO FillToFill, exit year; NOT calendar-year MTM",
            matched_rows=len(trades), unique_ui_tickers=len(groups),
            gross_price_pnl_display=sum((r["gross_price_pnl_display"] for r in trades), ZERO),
            allocated_fees_display=sum((r["allocated_fees_display"] for r in trades), ZERO),
            losing_rows=sum(r["gross_price_pnl_display"] < 0 for r in trades),
            winning_rows=sum(r["gross_price_pnl_display"] > 0 for r in trades),
            top_10_losing_ui_tickers=groups[:10],
            top_10_winning_ui_tickers=list(reversed(groups[-10:])),
            worst_10_native_matched_rows=sorted(trades, key=lambda r: r["gross_price_pnl_display"])[:10],
            concentration=concentration(groups, trades, -account_pnl if year == "full" else None),
        )
    write_csv(OUT / "original_native_exit_year_ticker_pnl.csv", annual)
    gross = periods["full"]["gross_price_pnl_display"]
    bridge = gross + base["dividend_cash_engine_proxy"] + base["split_fraction_cash_engine_proxy"] - base["fees_paid"]
    evidence = dict(
        source={"path": str(source.relative_to(ROOT)), "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "backtest_id": data["backtest_id"], "retrieved_at": data["retrieved_at"]},
        limitations=[
            "UI-rendered original records: all displayed decimals preserved, not claimed as full native precision.",
            "Matched rows are FIFO FillToFill, not flat-to-flat episodes; quantities/prices may be split adjusted.",
            "UI ticker can show later ticker mapping (e.g. XYZ); SID is not supplied by this UI table.",
            "Exit-year tables include cross-year unrealized P&L at exit and cannot replace calendar-year MTM.",
            "Native displayed allocated fees differ from actual aggregate order fees; bridge uses v15 actual fees.",
        ],
        money_bridge=dict(initial_equity=D(100000), final_equity=base["final_equity"], net_account_pnl=account_pnl,
                          native_matched_price_pnl_display=gross,
                          dividend_cash_engine_proxy=base["dividend_cash_engine_proxy"],
                          split_fraction_cash_engine_proxy=base["split_fraction_cash_engine_proxy"],
                          actual_fees=base["fees_paid"],
                          explained_with_display_price_pnl=bridge,
                          unexplained_residual_account_minus_bridge=account_pnl-bridge,
                          displayed_allocated_fees=periods["full"]["allocated_fees_display"],
                          display_allocated_fee_difference=periods["full"]["allocated_fees_display"]-base["fees_paid"]),
        periods=periods,
        TOP=[r for r in rows if r["ui_ticker"] == "TOP"],
        TWTR=[r for r in rows if r["ui_ticker"] == "TWTR"],
        original_order_summary=order_summary,
    )
    dump(OUT / "ORIGINAL_TRADE_ANALYSIS.json", evidence)
    lines = ["# Original B10 native matched-trade evidence", "",
             "Original run, UI display precision. These are FIFO FillToFill rows; annual grouping uses exit year, not calendar-year mark-to-market.", "",
             "## Money bridge (USD)", "", "| Component | USD |", "|---|---:|"]
    for key, value in evidence["money_bridge"].items():
        lines.append(f"| {key} | {value} |")
    for year, period in periods.items():
        lines += ["", f"## {year}: native exit-year scope", "", "| UI ticker | Gross price P&L | Allocated displayed fee | Matched rows |", "|---|---:|---:|---:|"]
        for r in period["top_10_losing_ui_tickers"]:
            lines.append(f"| {r['ui_ticker']} | {r['gross_price_pnl_display']} | {r['allocated_fees_display']} | {r['matched_rows']} |")
        lines += ["", "Winners:", "", "| UI ticker | Gross price P&L | Matched rows |", "|---|---:|---:|"]
        for r in period["top_10_winning_ui_tickers"]:
            lines.append(f"| {r['ui_ticker']} | {r['gross_price_pnl_display']} | {r['matched_rows']} |")
    (OUT / "ORIGINAL_TRADE_ANALYSIS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"rows": len(rows), "ui_tickers": len(grouped), "money_bridge": evidence["money_bridge"]}, default=serial))


if __name__ == "__main__":
    main()
