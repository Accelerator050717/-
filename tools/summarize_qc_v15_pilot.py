"""Summarize saved cloud aggregates only; never import the algorithm or fetch data."""
import argparse
import ast
import base64
import csv
from datetime import datetime, timedelta
import hashlib
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "data/experiments/dynamic_universe_pilot_v15"
ORDER = [f"{mode}{bps}" for bps in (10, 20) for mode in "ABC"]
LABELS = {"A": "股票池等权", "B": "20日动量前10", "C": "SPY"}


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def only(payload, name):
    rows = payload.get(name, [])
    if len(rows) != 1:
        raise ValueError(f"Expected exactly one {name}")
    return rows[0]


def digest(rows):
    return hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode()).hexdigest()


def write_csv(name, rows):
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with (EXP / name).open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def pct(value):
    return f"{value * 100:.2f}%"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-partial", action="store_true", help="Explicitly label fewer than six results")
    args = parser.parse_args()
    paths = {p.stem: p for p in (EXP / "runs").glob("*.json")}
    if not paths or set(paths) - set(ORDER):
        raise ValueError("No main results, or unregistered run files")
    missing = [key for key in ORDER if key not in paths]
    if missing and not args.allow_partial:
        raise ValueError("Six fixed results required; missing " + ", ".join(missing))
    audit = read(EXP / "AUDIT_RESULTS.json")
    audit_summary = only(audit, "summary")
    tree = ast.parse((ROOT / "tools/qc_v15_dynamic_pilot.py").read_text(encoding="utf-8"))
    fields = next(ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == "MONTH_FIELDS" for t in node.targets))
    if fields.index("target_count") != 23 or len(audit["month"]) != 24:
        raise ValueError("Unexpected monthly schema")
    month_rows = []
    for packed in audit["month"]:
        if len(packed) != len(fields):
            raise ValueError("Monthly row is truncated")
        row = {"source": "accepted_cloud_audit", **dict(zip(fields, packed))}
        for key in ("observation_time", "engine_available_time", "selection_callback", "decision_time"):
            row[key + "_new_york_local"] = (datetime(2022, 1, 1) + timedelta(seconds=row[key])).isoformat()
        row["member_sid_sha256_hex"] = base64.b64decode(row["member_sid_sha256"], validate=True).hex()
        row["target_count_scope"] = "audit reference; actual baseline target counts are separate columns"
        month_rows.append(row)
    results, annual, issues, summaries = [], [], [], {}
    payloads = {"audit": audit}
    for key in ORDER:
        if key not in paths:
            continue
        payload = read(paths[key])
        identity, summary, check = (only(payload, name) for name in ("identity", "summary", "month_check"))
        if (identity["mode"], identity["cost_bps"]) != (key[0], int(key[1:])):
            raise ValueError("Run filename and identity disagree: " + key)
        if (summary["mode"], summary["cost_bps"]) != (identity["mode"], identity["cost_bps"]):
            raise ValueError("Identity and summary disagree: " + key)
        if check["rows"] != 24 or len(check["target_counts"]) != 24 or check["pool_excludes_only"] != "target_count":
            raise ValueError("Invalid monthly check: " + key)
        reconstructed = [list(row) for row in audit["month"]]
        for index, target_count in enumerate(check["target_counts"]):
            reconstructed[index][23] = target_count
            month_rows[index][key + "_target_count"] = target_count
        if digest(reconstructed) != check["packed_sha256"] or digest(
                [row[:23] + row[24:] for row in reconstructed]) != check["pool_sha256"]:
            raise ValueError("Baseline monthly data differs from the audit: " + key)
        row = {"run": key, "baseline": LABELS[identity["mode"]],
               "source_file": paths[key].relative_to(EXP).as_posix(),
               "payload_sha256": hashlib.sha256(paths[key].read_bytes()).hexdigest(),
               "source_executable_ast_sha256": identity["executable_ast_sha256"]}
        row.update({k: v for k, v in summary.items() if not isinstance(v, (dict, list))})
        row.update({"stats." + k: v for k, v in summary["stats"].items()})
        ordinary_notional = summary["traded_notional"] - summary["stats"].get("native_liquidation_notional", 0)
        expected_fees = ordinary_notional * identity["cost_bps"] / 10000 + summary["stats"].get("native_liquidation_fees", 0)
        if not math.isclose(expected_fees, summary["fees_paid"], rel_tol=1e-10, abs_tol=1e-6):
            raise ValueError("Recorded fees do not reconcile with ordinary notional: " + key)
        row["fees_reconciled_from_normal_and_native_notional"] = expected_fees
        # Static accounting diagnostic only, not a self-financing return path.
        unverified = summary["unverified_terminal_gross_cash"]
        row["static_terminal_cash_nonrecognition_equity"] = summary["final_equity"] - unverified
        row["static_terminal_cash_nonrecognition_cumulative"] = (summary["final_equity"] - unverified) / identity["initial_cash"] - 1
        results.append(row)
        annual.extend({"run": key, "mode": identity["mode"], "cost_bps": identity["cost_bps"],
                       "year": year, "net_return": value, "source_file": row["source_file"]}
                      for year, value in sorted(summary["annual_returns"].items()))
        summaries[key], payloads[key] = summary, payload
    for key, payload in payloads.items():
        if len(payload.get("issue", [])) != only(payload, "summary")["issue_detail_emitted"]:
            raise ValueError("Issue records incomplete: " + key)
        for packed in payload.get("issue", []):
            if len(packed) != 7 or not isinstance(packed[6], dict):
                raise ValueError("Issue schema invalid: " + key)
            row = dict(zip(("kind", "ticker", "first_date", "last_date", "observations", "max_held_value"), packed[:6]))
            row.update(run=key, extra_json=json.dumps(packed[6], separators=(",", ":")),
                       amount_scope="cash_in_lieu_proxy_not_full_position" if packed[0] == "split_fraction_cash_proxy" else "as_logged_max_held_value")
            issues.append(row)
    write_csv("results.csv", results)
    write_csv("annual.csv", annual)
    write_csv("monthly_universe.csv", month_rows)
    write_csv("issues.csv", issues)
    costs = []
    for mode in "ABC":
        if mode + "10" in summaries and mode + "20" in summaries:
            lo, hi = summaries[mode + "10"], summaries[mode + "20"]
            extra = (lo["traded_notional"] - lo["stats"].get("native_liquidation_notional", 0)) * .001
            costs.append({"mode": mode, "net_cumulative_delta_20_minus_10": hi["net_cumulative"] - lo["net_cumulative"],
                          "net_cagr_delta_20_minus_10": hi["net_cagr"] - lo["net_cagr"],
                          "max_drawdown_delta_20_minus_10": hi["max_drawdown"] - lo["max_drawdown"],
                          "fees_paid_delta_usd": hi["fees_paid"] - lo["fees_paid"],
                          "static_extra_10bp_on_10bp_order_path_usd": extra,
                          "static_cumulative_delta_extra_10bp_on_10bp_path": -extra / 100000,
                          "interpretation": "static fixed-orders cost diagnostic; not a separately executable backtest"})
    if costs:
        write_csv("cost_comparison.csv", costs)
    status = f"不完整：已保存{len(results)}/6组；尚缺{', '.join(missing)}" if missing else "已汇总全部6组保存结果；是否最终验收通过另看只读验证器和主报告"
    lines = ["# v15已保存聚合结果", "", status + "。", "",
             "来源是实际保存的AUDIT_RESULTS.json及runs/*.json；本程序不读行情、不运行引擎、不训练。CSV收益率为小数，美元金额不作百分比换算。", "",
             "| 运行 | 累计净收益 | 净年化 | 全历史最大回撤 | 平均仓位 | 总换手倍数 | 费用USD | 引擎门槛 |",
             "|---|---:|---:|---:|---:|---:|---:|---|"]
    for key in ORDER:
        if key in summaries:
            s = summaries[key]
            lines.append(f"| {key} {LABELS[s['mode']]} | {pct(s['net_cumulative'])} | {pct(s['net_cagr'])} | {pct(s['max_drawdown'])} | {pct(s['average_exposure'])} | {s['turnover_gross_notional_over_average_equity']:.3f} | {s['fees_paid']:.2f} | {s['gate_pass']} |")
    if costs:
        lines += ["", "| 成本20bp相对10bp | 实际累计差(百分点) | 实际年化差(百分点) | 费用增加USD | 固定10bp订单路径再收10bp的静态费用USD |",
                  "|---|---:|---:|---:|---:|"]
        for cost in costs:
            lines.append(f"| {cost['mode']} | {cost['net_cumulative_delta_20_minus_10'] * 100:.3f} | {cost['net_cagr_delta_20_minus_10'] * 100:.3f} | {cost['fees_paid_delta_usd']:.2f} | {cost['static_extra_10bp_on_10bp_order_path_usd']:.2f} |")
        lines += ["", "两档成本会改变可用现金、整股取整和后续订单，所以实际收益差不必等于静态额外费用。每组实际费用已按普通成交额×该档费率加原生强清费用独立对齐，差值见[cost_comparison.csv](cost_comparison.csv)；静态列不是新增回测。"]
    stats = audit_summary["stats"]
    if stats["observed_security_days"] + stats["known_terminated_missing"] + stats["unknown_missing"] != stats["expected_security_days"]:
        raise ValueError("Audit security-day counts do not reconcile")
    if sum(r["added"] for r in month_rows) - sum(r["removed"] for r in month_rows) != month_rows[-1]["selected"]:
        raise ValueError("Monthly membership transitions do not reconcile")
    lines += ["", f"连续审计：{len(month_rows)}月、{audit_summary['daily_close_rows']}个收盘观察、累计{audit_summary['cumulative_security_ids']}个SID；预期证券日{stats['expected_security_days']}、取得{stats['observed_security_days']}，引擎终止后缺价{stats.get('known_terminated_missing', 0)}、原日志未知缺价{stats.get('unknown_missing', 0)}。事后公开停牌解释见[事件证据](TERMINAL_EVENT_EVIDENCE.md)，不覆盖原始日志分类或改变历史交易。",
              "", f"24月输入累计{sum(r['input'] for r in month_rows)}条、筛选后合格累计{sum(r['eligible'] for r in month_rows)}条、最终股票月条目{sum(r['selected'] for r in month_rows)}；新增累计{sum(r['added'] for r in month_rows)}（含初始100）、移出累计{sum(r['removed'] for r in month_rows)}。这些是重复出现次数，不是唯一证券数。股票短历史请求{sum(r['history_calls'] for r in month_rows)}次、返回{sum(r['history_rows'] for r in month_rows)}条；动量21点不足{sum(r['momentum_history_insufficient'] for r in month_rows)}个股票月观察。全池月首无当天RAW标记{sum(r['unknown_price_excluded_from_order_only'] for r in month_rows)}个股票月（unknown_price_excluded_from_order_only）；通过21点历史检查后的缺当前价{sum(r['decision_missing_current_price'] for r in month_rows)}个（decision_missing_current_price）。前者不自动表示原因未知；历史不足的证券提前退出动量分支，所以两字段不可混称。A的成员仍保留，缺价新买数量不生成、已有缺价持仓另行保留。",
              "", "月度筛选、新增/移出、信息与决定时间见[monthly_universe.csv](monthly_universe.csv)；实际各年收益见[annual.csv](annual.csv)；完整指标、现金核对及事件统计见[results.csv](results.csv)；实际异常范围及金额见[issues.csv](issues.csv)。总换手为全区间买卖绝对成交金额/平均收盘权益，不是单边年化换手。最大回撤、最小现金、最大/平均仓位来自正常收盘观察，不是盘中极值或逐笔风险上限保证。",
              "", "原生强制清算金额、零费与现金未核实状态：", ""]
    for key, s in summaries.items():
        lines.append(f"- {key}：{s['stats'].get('native_nonstrategy_fills', 0)}笔；未核实现金代理{s['unverified_terminal_gross_cash']:.2f} USD；原生强清费用{s['stats'].get('native_liquidation_fees', 0):.2f} USD；缺价持仓{s['stats'].get('missing_held_days', 0)}个观察，最大持仓代理{s['stats'].get('max_missing_held_value', 0):.2f} USD。")
    lines += ["", "results.csv的static_terminal_cash_nonrecognition列仅从期末权益扣除未核实强清现金。它不模拟资金不足、再投资及后续订单，是静态诊断，不是自融资回测、收益下界或置信区间。",
              "", "引擎SplitOccurred不等于法律上的普通拆股：T/WarnerMedia分拆、选择性换股等需依[事件证据](TERMINAL_EVENT_EVIDENCE.md)另行对齐。碎股现金残差很小不能证明完整权利影响很小；股数/现金与引擎对上不证明承接证券已正确回放。",
              "", "以上是2022—2023开发历史及固定两阶段MOO的研究代理结果，不是独立验证、真实paper或长期收益保证。2025全年和2016—2025覆盖仍未验收，2026封存；最终净年化30%/争取50%及30%回撤预算不因本页而降低。没有自动升级策略。"]
    (EXP / "GENERATED_RESULTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"status": "partial" if missing else "six_saved_results_summarized",
                      "runs": list(summaries), "missing": missing, "monthly_rows": len(month_rows),
                      "annual_rows": len(annual), "issue_rows": len(issues),
                      "market_data_reads": 0, "model_fits": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
