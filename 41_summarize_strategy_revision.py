"""汇总v6/v7实际结果、失败原因和数据/执行边界；不再调参或训练。"""
import importlib
import json
import re
from datetime import datetime, timezone

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from panel_config import ROOT, SYMBOLS

t = importlib.import_module("38_train_robust_strategy")
V6 = t.OUT
V7 = ROOT/"data/experiments/profit_priority_v7"
OUT = ROOT/"data/experiments/strategy_reflection_20260909"


def load(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def md_table(frame, columns):
    lines = ["| "+" | ".join(columns)+" |", "| "+" | ".join(["---"]*len(columns))+" |"]
    for _,row in frame.iterrows():
        values = []
        for key in columns:
            value = row[key]
            values.append(f"{value:.2%}" if key in {"cagr","max_drawdown","average_gross","worst_day","low_stress_drawdown"} else str(value))
        lines.append("| "+" | ".join(values)+" |")
    return "\n".join(lines)


def score_analysis():
    scores = pd.read_csv(V6/"all_scores.csv",parse_dates=["Date"],float_precision="round_trip")
    actual = scores.pivot(index="Date",columns="symbol",values="y_5").reindex(columns=SYMBOLS).rank(axis=1)
    centered_y = actual.sub(actual.mean(axis=1),axis=0)
    rows = {}
    for key in ("ridge_h20_price","ridge_h60_price","ensemble","momentum"):
        x = scores.pivot(index="Date",columns="symbol",values=key).reindex(columns=SYMBOLS).rank(axis=1)
        centered_x = x.sub(x.mean(axis=1),axis=0)
        rows[key] = (centered_x*centered_y).sum(axis=1)/np.sqrt(centered_x.pow(2).sum(axis=1)*centered_y.pow(2).sum(axis=1))
    daily = pd.DataFrame(rows)
    daily.to_csv(OUT/"daily_rank_ic.csv",date_format="%Y-%m-%d")
    daily.groupby(daily.index.year).mean().to_csv(OUT/"annual_rank_ic.csv")
    return {k:float(v) for k,v in daily.mean().items()}


def stop_analysis():
    closes = {s:pd.read_csv(ROOT/f"data/raw/extended_2012_2025/{s}.csv",index_col="Date",parse_dates=["Date"],float_precision="round_trip")["Adj Close"] for s in SYMBOLS}
    summaries,events = [],[]
    for label,folder,name in (("v6",V6,"ensemble_full_cost10"),("v7",V7,"h60_full_cost10")):
        trades = pd.read_csv(folder/f"backtests/{name}_trades.csv",parse_dates=["Date"],float_precision="round_trip")
        stops = trades.loc[trades.reason.str.startswith("stop_")].copy()
        local = []
        for row in stops.itertuples():
            series = closes[row.symbol]
            at = series.index.get_loc(row.Date)
            if at+5 < len(series):
                future = float(series.iloc[at+5]/row.proxy_fill-1)
            else:
                future = np.nan
            event = dict(strategy=label,Date=row.Date,symbol=row.symbol,reason=row.reason,
                         threshold=row.stop_threshold,fill=row.proxy_fill,
                         slippage_from_threshold=float(row.proxy_fill/row.stop_threshold-1),
                         stock_5_session_later_close_vs_exit=future)
            events.append(event); local.append(event)
        frame = pd.DataFrame(local)
        daily = pd.read_csv(folder/f"backtests/{name}_daily.csv",index_col="Date",parse_dates=["Date"],float_precision="round_trip")
        summaries.append(dict(strategy=label,stops=len(frame),gap_stops=int(frame.reason.eq("stop_gap").sum()),
                   worst_gap_below_stop=float(frame.loc[frame.reason.eq("stop_gap"),"slippage_from_threshold"].min()),
                   mean_5_session_stock_change=float(frame.stock_5_session_later_close_vs_exit.mean()),
                   fraction_5_session_stock_higher=float(frame.stock_5_session_later_close_vs_exit.dropna().gt(0).mean()),
                   soft_days=int(daily.soft.sum()),paused_days=int(daily.paused.sum()),days=len(daily)))
    pd.DataFrame(events).to_csv(OUT/"stop_events_diagnostic.csv",index=False,date_format="%Y-%m-%d")
    t.save(OUT/"stop_diagnostics.json",summaries)
    return summaries


def profit_analysis():
    rows = []
    for label,folder,name in (("old",V6,"incumbent_cost10"),("v6",V6,"ensemble_full_cost10"),("v7",V7,"h60_full_cost10")):
        trades = pd.read_csv(folder/f"backtests/{name}_trades.csv",float_precision="round_trip")
        pnl = trades.groupby("symbol").cash_change.sum().sort_values(ascending=False)
        final_nav = load(folder/f"backtests/{name}_metrics.json")["final_equity"]
        np.testing.assert_allclose(pnl.sum(),final_nav-1,rtol=1e-10,atol=1e-10)
        rows.append(dict(strategy=label,top_symbol=pnl.index[0],
                         top_pnl_per_initial_nav=float(pnl.iloc[0]),
                         top_share_total_profit=float(pnl.iloc[0]/pnl.sum()),
                         nvda_share_total_profit=float(pnl.get("NVDA",0)/pnl.sum())))
    pd.DataFrame(rows).to_csv(OUT/"profit_concentration.csv",index=False)
    return rows


def main():
    assert load(V6/"completion.json") and load(V7/"completion.json")
    OUT.mkdir(exist_ok=True)
    a = pd.read_csv(V6/"comparison.csv",index_col="candidate")
    b = pd.read_csv(V7/"comparison.csv",index_col="candidate")
    names = [("旧H60+SPY波动率仓位",a,"incumbent_cost10"),
             ("v6 集成+分散仓位",a,"ensemble_allocation_cost10"),
             ("v6 再加ATR跟踪止损",a,"ensemble_stops_cost10"),
             ("v6 完整规则",a,"ensemble_full_cost10"),
             ("v7 H60+精简仓位",b,"h60_allocation_cost10"),
             ("v7 再加15%保护止损",b,"h60_stops_cost10"),
             ("v7 完整规则",b,"h60_full_cost10"),
             ("同池满仓等权",a,"equal_full_cost10"),
             ("SPY满仓",a,"spy_full_cost10")]
    overview = pd.DataFrame([dict(strategy=label,**table.loc[key].to_dict()) for label,table,key in names])
    overview.to_csv(OUT/"OVERVIEW.csv",index=False)
    ic = score_analysis()
    stops = stop_analysis()
    concentration = profit_analysis()
    checks6,checks7 = load(V6/"RUN_CHECKS.json"),load(V7/"RUN_CHECKS.json")
    assert len(checks6)==23 and len(checks7)==18
    assert all(r["all_checks_passed"] for r in checks6)
    assert all(r["all_checks_passed"] for r in checks7.values())
    summary = dict(new_fits=10,reused_h60_year_models=10,new_historical_backtests=41,
                   v6_diagnostic=load(V6/"diagnostic_gates.json"),v7_diagnostic=load(V7/"diagnostic_gates.json"),
                   rank_ic=ic,stop_diagnostics=stops,profit_concentration=concentration,all_41_ledger_checks_passed=True,
                   largest_old_control_open_NAV_difference=max(r.get("old_open_NAV_max_absolute_difference",0) for r in checks6),
                   training_warning_count=load(V6/"training_complete.json")["warning_count"],
                   final_decision="Both principal strategies rejected for profitability; retain old research baseline, no deployment",
                   research_only=True,live_trading_enabled=False,paper_trading_enabled=False,orders_sent=0,
                   prices_2026_accessed=False,old_0_of_98_unchanged=True,
                   generated_at_utc=datetime.now(timezone.utc).isoformat())
    t.save(OUT/"SUMMARY.json",summary)
    # 明确机器可读状态，不能把报告中最高收益一行当成已获准部署模型。
    t.save(OUT/"strategy_status.json",dict(candidate="v7_h60_full",research_status="rejected_for_profitability",
         deploy_eligible=False,reason=summary["v7_diagnostic"],validation_period="2016-2025 reused development history",
         required_future_evidence=["historical universe/delist coverage","independent prospective validation",
                                   "raw execution-price and corporate-action reconciliation","broker paper execution validation",
                                   "explicit account, capital and risk limits"],
         note="此文件记录研究结论，不是已集成到券商的运行时开关。"))
    # 研究图使用固定三方案，不按结果选择曲线。
    fig,axs = plt.subplots(2,2,figsize=(12.8,8),layout="constrained")
    configs = [(V6,"incumbent_cost10","Previous H60", "#1f77b4"),
               (V6,"ensemble_full_cost10","v6 full", "#e07b39"),
               (V7,"h60_full_cost10","v7 full", "#1a8a6c")]
    for folder,key,label,color in configs:
        d = pd.read_csv(folder/f"backtests/{key}_daily.csv",index_col="Date",parse_dates=["Date"])
        axs[0,0].plot(d.index,d.equity,label=label,color=color,lw=1.3)
        axs[1,0].plot(d.index,100*d.drawdown,color=color,lw=1.)
        axs[1,1].plot(d.index,100*d.gross.rolling(21).mean(),label=label,color=color,lw=.9)
    points = [("Previous",a.loc["incumbent_cost10"]),("v6 allocation",a.loc["ensemble_allocation_cost10"]),
              ("v6 full",a.loc["ensemble_full_cost10"]),("v7 allocation",b.loc["h60_allocation_cost10"]),
              ("v7 stop",b.loc["h60_stops_cost10"]),("v7 full",b.loc["h60_full_cost10"]),
              ("SPY",a.loc["spy_full_cost10"])]
    for label,row in points:
        color = "#1f77b4" if label=="Previous" else "#e07b39" if label.startswith("v6") else "#1a8a6c" if label.startswith("v7") else "#777777"
        offset = (4,-14) if label=="v7 stop" else (-28,6) if label=="SPY" else (4,4)
        axs[0,1].scatter(abs(row.max_drawdown)*100,row.cagr*100,s=32,color=color)
        axs[0,1].annotate(label,(abs(row.max_drawdown)*100,row.cagr*100),xytext=offset,textcoords="offset points",fontsize=8)
    axs[0,0].set(title="Historical NAV (initial cash = 1)",yscale="log",ylabel="NAV, log scale")
    axs[0,0].legend(fontsize=8)
    axs[0,1].set(title="Profit / risk trade-off",xlabel="Worst close drawdown magnitude (%)",ylabel="CAGR (%)")
    axs[1,0].set(title="Drawdown from close-equity peak",ylabel="Drawdown (%)")
    axs[1,1].set(title="Realized stock exposure (21-session mean)",ylabel="Stock value / NAV (%)")
    for ax in axs.flat:
        ax.grid(alpha=.2)
    for ax in (axs[0,0],axs[1,0],axs[1,1]):
        ax.set_xlim(pd.Timestamp("2016-01-01"),pd.Timestamp("2025-12-31"))
    fig.suptitle("2016-2025 reused development sample | adjusted OHLC proxy | 10bp per side + 10bp stop slippage",fontsize=11)
    fig.savefig(OUT/"strategy_comparison.png",dpi=170)
    plt.close(fig)
    stress6 = pd.read_csv(V6/"stress_comparison.csv")
    stress7 = pd.read_csv(V7/"stress_comparison.csv")
    ablation = load(V7/"score_ablation.json")
    v7row = b.loc["h60_full_cost10"]
    v7cost = b.loc["h60_full_cost20"]
    v6row = a.loc["ensemble_full_cost10"]
    tests = load(OUT/"TESTS.json") if (OUT/"TESTS.json").exists() else {"tests_run":"尚未保存","passed":False}
    report = f"""# 反思、两版新策略与执行结果

结论：已制定并实际执行两版策略，完成10次新增年度拟合和41次历史回测。两版都降低了历史回撤，但均未通过先登记的盈利要求，因此拒绝替换旧研究基线。当前没有可被证明“完全放心”、稳定盈利的全自动交易模型，没有开启券商模拟或真实下单。

## 我需要改正的地方

1. 训练次数不是有效性的证据。之前固定股票池上的多轮比较已经反复使用开发期；更大的模型和更多组合不自动带来新信息。旧模型有可继续研究的表现，但尚未满足全部统计筛选，且当前30股名单存在存续样本偏差。
2. 旧SPY波动率缩仓不是止损。此前按每日开盘估值的回撤还漏掉了收盘及盘中变化。本轮在相同价格快照、相同调仓网格、相同末次清仓日重现旧开盘NAV，再为所有对照增加一致的收盘估值。
3. 把多种风险规则相乘会牺牲持仓机会；不能把低仓位导致的浅回撤包装成更强预测。v6完整规则平均股票仓位只有{v6row.average_gross:.2%}；软降仓又缺乏正常恢复条件。这是本轮需要承认的设计缺陷，原结果没有被悄悄修改。
4. 模型预测相对收益，股票池一起下跌时仍会排出第一名。选股、是否持仓、损失退出和订单可靠性需要分别验证。止损可降低某些损失，也可能在暂时下跌后卖出并错过反弹；止损触发价不保证实际成交价。[FINRA官方说明](https://www.finra.org/investors/insights/stop-orders-factors-consider-during-volatile-markets)

## 同口径实际结果

区间2016-01-05至2025-12-29；普通买卖单边10bp，止损额外10bp。价格均为原Yahoo快照的调整OHLC研究代理，碎股、零息现金，无杠杆。`max_drawdown`为**收盘权益**峰值回撤，负号表示下跌。所有方案包括首次建仓和最终清仓成本。

{md_table(overview,["strategy","cagr","max_drawdown","average_gross","stop_exits"])}

![风险收益、净值与仓位](strategy_comparison.png)

旧控制开盘NAV和原v5文件的最大绝对差仅{summary['largest_old_control_open_NAV_difference']:.3g}，属于浮点运算差异。旧控制本次收盘最大回撤{a.loc['incumbent_cost10','max_drawdown']:.2%}，原开盘口径为{a.loc['incumbent_cost10','open_max_drawdown']:.2%}；不能把估值时点变化当成策略进步。

## v6做了什么，为什么拒绝

固定H20/H60 Ridge横截面名次各占一半；81个历史价格/ETF特征。新增H20模型按2016—2025逐年拟合10次，H60复用同快照10份模型并逐一恢复评分。Y年评分时只训练至Y-2，Y-1验证标签出场严格早于Y年；验证没有挑参数。没有2026行情输入。

每5日最多10股、保留名次15、个股10%/行业25%/大型科技群35%目标上限、60日逆波动分配、组合波动率缩仓及SPY趋势限制。个股止损为3倍14日平均真实波幅、距离限制5%—12%，逐日收盘提高次日保护线；单股/合计计划损失预算0.75%/5%。组合回撤8%降仓、12%清仓冷却。

不含止损版本年化{a.loc['ensemble_allocation_cost10','cagr']:.2%}，加入个股止损后{a.loc['ensemble_stops_cost10','cagr']:.2%}，完整规则{v6row.cagr:.2%}。新规则不能满足用户的盈利优先要求，且v6软降仓没有正常恢复，故整体拒绝。

单独控制预测这一项：相同v6仓位规则、关闭止损和组合暂停，H60单模型年化{ablation['h60_v6_allocation']['cagr']:.2%}，集成年化{ablation['ensemble_v6_allocation']['cagr']:.2%}。这才是比较模型混合影响的成对证据；不能直接用旧top5与新top10差异归因于模型。

统一5日Rank IC：H20={ic['ridge_h20_price']:.4f}，H60={ic['ridge_h60_price']:.4f}，集成={ic['ensemble']:.4f}，简单动量={ic['momentum']:.4f}。预测名次、具体持仓和最终账户收益仍是不同层次。

## v7的修订与最终判断

保留H60预测，最多8股，保留名次12；等权基础，个股12.5%、行业30%、大型科技群40%上限。使用原SPY波动率缩仓，不再同时叠加逆波动选股、组合波动率上限和趋势降仓。调仓时计划个股/合计止损损失预算2%/12%，目标总仓位最多80%。

止损改为入场/每5交易日计划调仓价格下方15%的保护线，只提高、不放宽，不逐日追踪峰值。组合回撤10%减半，恢复到5%以内允许在下一调仓恢复；20%清仓，经过20日冷却及市场趋势恢复后才在固定网格重启，先半仓10日。保留整个历史的真实回撤，风险周期峰值重置不抹去亏损。参数是本轮研究选择，未经用户确认为实盘风险额度。

完整v7年化{v7row.cagr:.2%}、收盘最大回撤{v7row.max_drawdown:.2%}；成本加倍年化{v7cost.cagr:.2%}、回撤{v7cost.max_drawdown:.2%}。它优于v6，但未达到旧方案年化80%的门槛（{.8*a.loc['incumbent_cost10','cagr']:.2%}），且未跑赢满仓SPY。因此仍拒绝作为盈利优先的替代方案。未把无止损的高收益行偷偷换成最终策略。

完整诊断通过状态：[v6门槛](../robust_strategy_v6/diagnostic_gates.json)、[v7门槛](../profit_priority_v7/diagnostic_gates.json)。这些是风险设计诊断；此前0/98统计筛选保留，本轮后验修订不能当成新的独立终测，也没有自动进入2026验证。重复挑选历史好成绩会产生回测过拟合风险。[原研究论文](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf)

## 跳空、止损和压力结果

模型看到t日收盘，调仓在t+1开盘代理执行。生效止损若被开盘跳空穿过，按更差开盘再扣止损滑点；普通日内触价假设能在阈值附近执行，并额外计费。这个日线假设仍不能证明真实撮合、停牌后成交或市场冲击。另列触发后延迟到下一开盘的压力情形。

v6止损{stops[0]['stops']}次，其中跳空{stops[0]['gap_stops']}次，最差跳空模拟成交比保护阈值低{abs(stops[0]['worst_gap_below_stop']):.2%}。v7止损{stops[1]['stops']}次，其中跳空{stops[1]['gap_stops']}次，最差低{abs(stops[1]['worst_gap_below_stop']):.2%}。可见15%止损距离不是实际最大损失承诺。

事后诊断中，卖出后第5交易日收盘高于退出代理价的比例：v6 {stops[0]['fraction_5_session_stock_higher']:.2%}，v7 {stops[1]['fraction_5_session_stock_higher']:.2%}。这仅描述触发后的股票路径，不能直接等同于该次止损“做错了”或取消止损后的组合收益。

v7固定压力表：

{md_table(stress7,["candidate","cagr","max_drawdown","worst_day"])}

[v6完整压力表](../robust_strategy_v6/stress_comparison.csv)也全部保留。相位0—4改变交易起点；结束日固定，最后持有期可能缩短，不能当成完全相同成交样本。禁NVDA只是禁止交易、没有重训，不能替代历史股票池检验。

最终全部清仓后，按每股净现金流计算NVDA占总利润的比例：旧控制{concentration[0]['nvda_share_total_profit']:.2%}，v6 {concentration[1]['nvda_share_total_profit']:.2%}，v7 {concentration[2]['nvda_share_total_profit']:.2%}。这不是独立因果贡献，但说明降低仓位集中后，收益仍依赖个别强势股。[利润来源明细](profit_concentration.csv)

费用或延迟会改变账户回撤触发日期和后续持仓，所以压力场景的回撤不一定单调变差；更低的回撤不能解释为更高成本有利。

`low_stress_drawdown`是假设持仓同时到达各自日Low、且不享受止损保护时的悲观估值诊断。它不是实际观测到的盘中组合极值，也不是概率承诺。普通收盘回撤同样不能作为盘中最大亏损的保证。

## 验证与可靠性的实际边界

31个输入股票/基准快照哈希、完整共同日历和OHLC关系通过；物理截断后风险特征前缀完全不变；新增10份模型仅用训练集标准化，已保存H60评分精确重现。训练警告0。全部41次历史回测逐笔费用、现金变化、股份数量、最终清仓和每日权益核对通过，目标约束也逐次检查。

本轮及原项目共{tests['tests_run']}项虚构行情/执行故障测试，保存结果通过={tests['passed']}。包括跳空穿价、触发后延迟、禁止同日重新买入、阈值不读取同日未来High、软降仓恢复、数据缺失拒绝继续、未来截断、重复成交与恢复核对。它们不是券商集成证据。

本轮没有接券商订单，没有用调整价格生成可提交券商的订单，也没有启动后台交易服务。策略状态文件记录`deploy_eligible=false`，它是研究状态记录，尚不是接到券商上的风险开关。既有IBKR只读探测和订单状态原型仍需要真实模拟账户联调。IBKR模拟撮合与真实撮合也有差异，模拟通过不能直接证明实盘执行可靠。[IBKR官方模拟限制](https://www.interactivebrokers.com/docs/tws-api/doc/notes-limitations/limitations/paper-trading)

## 接下来的策略方向

保留H60作为研究基线，保留已经检验的时间边界、成本和跳空处理；不采用本轮损害收益的整体规则。下一项研究应优先检验新增信息和信号的可交易性：历史股票池/退市、公告真实可用时间，以及模型对绝对收益和下行风险的判断。预先固定下一次比较，不为通过门槛继续放宽止损。

在可部署之前，还需要独立前瞻样本、真实报价和公司行动账本、券商模拟下的止损/部分成交/断线恢复、账户与资金损失限额。这些缺口是当前“不能完全放心”的具体原因。任何账户硬止损也是触发规则，极端跳空或停牌可能使损失超出阈值。

## 记录与重现

- [v6运行前策略](../robust_strategy_v6/DESIGN.md)、[v7运行前修订](../profit_priority_v7/DESIGN.md)
- [10次新训练明细](../robust_strategy_v6/training_summary.csv)、[v6全部16条成本对照](../robust_strategy_v6/comparison.csv)、[v7全部10条成本对照](../profit_priority_v7/comparison.csv)
- [逐日/逐笔v6输出](../robust_strategy_v6/backtests)、[逐日/逐笔v7输出](../profit_priority_v7/backtests)、[研究状态](strategy_status.json)
- 运行38新增训练，39执行v6，40执行v7，41重建本报告；已完成时保留既有模型与结果，不重新训练、不下载2026。
"""
    (OUT/"REFLECTION_AND_RESULTS.md").write_text(report,encoding="utf-8")
    # 保留完整训练参数和验证边界，短报告直接链接原始逐年记录。
    fits = pd.read_csv(V6/"training_summary.csv")
    lines = ["# 本轮10次H20年度拟合", "", "固定Ridge alpha=100, solver=svd，81个价格/ETF特征，训练集StandardScaler。H60十份既有模型逐一恢复，评分精确一致。没有搜索超参数，训练警告0。", "",
             md_table(fits,["year","horizon","train_rows","validation_rows","development_rows","train_last_exit","validation_last_exit","seconds","old_h60_exact_reproduced"]), "",
             "完整模型哈希见[原始拟合记录](../robust_strategy_v6/training_summary.csv)，特征顺序和混合公式见[登记计划](../robust_strategy_v6/plan.json)。每年joblib、开发评分、验证评分及JSON在同一目录。",
             "验证标签和训练标签都在下一段开始前完整，测试年预测不要求未来标签已发生。2016—2025已被多轮研究，本轮不是新的独立留出验证。"]
    (OUT/"TRAINING_DETAILS.md").write_text("\n".join(lines),encoding="utf-8")
    broken=[]
    for target in re.findall(r"\]\(([^)]+)\)",report):
        if not target.startswith("http") and not (OUT/target).exists():
            broken.append(target)
    assert not broken,broken
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
