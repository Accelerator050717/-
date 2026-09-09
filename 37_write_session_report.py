"""本次持续研究的汇总：144主拟合、6仓位变体、20更早历史拟合。"""
import importlib
import json
from datetime import datetime, timezone

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from panel_config import ROOT

v3 = importlib.import_module("28_train_multihorizon")
formatting = importlib.import_module("32_write_multihorizon_report")
OUT = v3.OUTPUT
RISK = ROOT/"data/experiments/risk_controls_v4"
EXT = ROOT/"data/experiments/extended_history_v5"


def main():
    risk = pd.read_csv(RISK/"comparison_new6.csv",float_precision="round_trip")
    risk_all = pd.read_csv(RISK/"comparison_all98.csv",float_precision="round_trip")
    costs = json.loads((RISK/"cost_metrics_all98.json").read_text(encoding="utf-8"))
    extended = pd.read_csv(EXT/"comparison.csv",float_precision="round_trip")
    extended_fits = pd.read_csv(EXT/"training_summary.csv",float_precision="round_trip")
    extended_validation = pd.read_csv(EXT/"validation_metrics.csv",float_precision="round_trip")
    expanded_data = json.loads((EXT/"data_ready.json").read_text(encoding="utf-8"))
    extended_complete = json.loads((EXT/"completion.json").read_text(encoding="utf-8"))
    fits = pd.read_csv(OUT/"training_summary.csv",float_precision="round_trip")
    input_checks = json.loads((OUT/"INPUT_CHECKS.json").read_text(encoding="utf-8"))
    fit_checks = json.loads((OUT/"FIT_CHECKS.json").read_text(encoding="utf-8"))
    ext_checks = json.loads((EXT/"CHECKS.json").read_text(encoding="utf-8"))
    execution = json.loads((OUT/"EXECUTION_TESTS.json").read_text(encoding="utf-8"))
    best_name = "v4_ridge_h60_price_top5_vol15"
    best = risk.set_index("candidate").loc[best_name]
    old = risk_all.set_index("candidate").loc["v3_elastic_h5_price_top5"]
    raw_new = risk_all.set_index("candidate").loc["v3_ridge_h60_price_top5"]
    rows = []
    for label,name in (("原5日ElasticNet满仓","v3_elastic_h5_price_top5"),
                       ("60日Ridge满仓","v3_ridge_h60_price_top5"),
                       ("60日Ridge＋波动率仓位",best_name),
                       ("同池等权满仓","benchmark_equal"),("SPY","benchmark_spy")):
        if name.startswith("benchmark"):
            row = {"方案":label,"年化":costs[name]["cagr"],"最大回撤":costs[name]["max_drawdown"],"5日Rank IC":None,"20bp年化":None}
        else:
            item = risk_all.set_index("candidate").loc[name]
            row = {"方案":label,"年化":item.cagr,"最大回撤":item.max_drawdown,"5日Rank IC":item.mean_rank_ic,"20bp年化":item.stress_cagr}
        rows.append(row)
    overview = formatting.table(formatting.fmt(pd.DataFrame(rows),percentages=["年化","最大回撤","20bp年化"],decimals=["5日Rank IC"]))
    risk_table = risk[["candidate","cagr","max_drawdown","stress_cagr","matched_risk_equal_cagr","IR_vs_matched_risk_equal","gate_all"]]
    ext_view = extended[["candidate","cagr","max_drawdown","mean_rank_ic","IR_vs_matched_equal","positive_active_years_out_of_10"]]
    training = extended_fits.rename(columns={"id":"model"}).merge(
        extended_validation.rename(columns={"candidate":"model","mean_rank_ic":"validation_native_IC","ndcg5":"validation_native_NDCG"})[
            ["model","year","validation_native_IC","validation_native_NDCG","n_iter"]],on=["model","year"],validate="one_to_one")
    training.to_csv(EXT/"training_details20.csv",index=False)
    cols = ["model","year","train_rows","validation_rows","train_first","train_last_exit","validation_last_exit",
            "validation_native_IC","validation_native_NDCG","n_iter","fit_seconds","warnings"]
    (EXT/"TRAINING_DETAILS.md").write_text("# 扩展历史的20次实际拟合\n\n参数固定，验证评分在拟合后统一补存并检查，没有据此选择参数或改模型。\n\n"+
        formatting.table(formatting.fmt(training[cols],decimals=["validation_native_IC","validation_native_NDCG","fit_seconds"],integers=["n_iter"]))+"\n",encoding="utf-8")

    equity = pd.read_csv(RISK/"equity_all98.csv",index_col="Date",parse_dates=["Date"],float_precision="round_trip")
    targets = pd.read_csv(RISK/f"backtests/{best_name}_periods.csv",parse_dates=["observation_date"],float_precision="round_trip")
    fig,axes = plt.subplots(3,1,figsize=(11,9),sharex=True,gridspec_kw={"height_ratios":[2,1,0.65]})
    for name,label,color in (("v3_ridge_h60_price_top5","Ridge H60, fully invested","#3475a5"),
                              (best_name,"Ridge H60, volatility-based exposure","#128061"),
                              ("v3_elastic_h5_price_top5","Original ElasticNet H5","#d68b35"),
                              ("benchmark_equal","Equal-weight 30 stocks","#808080"),
                              ("benchmark_spy","SPY","#9d5364")):
        axes[0].plot(equity.index,equity[name],label=label,color=color,lw=1.4)
        axes[1].plot(equity.index,100*(equity[name]/equity[name].cummax().clip(lower=1)-1),color=color,lw=1.0)
    axes[0].set_yscale("log")
    axes[0].set_ylabel("NAV, starting cash=1 (log)")
    axes[0].legend(fontsize=8,loc="upper left")
    axes[1].set_ylabel("Drawdown (%)")
    axes[2].step(targets.observation_date,targets.target_gross_exposure*100,where="post",color="#128061",lw=1)
    axes[2].set_ylabel("Rebalance target (%)")
    axes[2].set_ylim(0,105)
    axes[2].set_xlabel("Observation-date exposure; orders would execute at next open, every 5 sessions")
    axes[0].set_title("2020-2025 DEVELOPMENT ONLY | 10bp each side | 2026 market data kept sealed",fontsize=12)
    for ax in axes:
        ax.grid(alpha=.18)
        ax.set_xlim(pd.Timestamp("2020-01-01"),pd.Timestamp("2025-12-31"))
    fig.tight_layout()
    fig.savefig(OUT/"risk_return_progress.png",dpi=170)
    plt.close(fig)

    diagnostics = pd.read_csv(OUT/"robustness/schedule_cost_exclusion.csv",float_precision="round_trip")
    phase = diagnostics.loc[diagnostics.candidate.eq("v3_ridge_h60_price_top5") & diagnostics.diagnostic.eq("phase")]
    without = diagnostics.loc[diagnostics.candidate.eq("v3_ridge_h60_price_top5") & diagnostics.diagnostic.eq("exclude_tradable_NVDA")].iloc[0]
    report = f"""# 本轮持续研究完整汇报

本轮发现了更好的历史风险收益折中：60日相对收益名次的岭回归，配合固定波动率仓位规则，值得继续验证。它仍未达到预设的全部研究准入标准，不能称为已经获得可实盘、稳定盈利或市场最强的模型。

## 先看主要结果

以下是完全相同2020—2025开发区间、5交易日调仓、次日开盘、单边10bp费用的结果。回撤显示负数；例如-20.75%表示从历史峰值最大下跌20.75%。数据为供应商调整开盘价研究代理，不是实际账户成交。

{overview}

与原5日ElasticNet相比，新组合历史CAGR相差{(best.cagr-old.cagr)*100:+.2f}个百分点，最大回撤浅{(best.max_drawdown-old.max_drawdown)*100:.2f}个百分点；费用翻倍后CAGR为{best.stress_cagr:.2%}。这说明值得研究的进步同时来自预测周期和仓位规则，不能归功于单纯把模型做大。

![同区间风险收益与仓位](risk_return_progress.png)

仓位规则为 `min(1, 0.15 / (SPY过去20日收益标准差 × sqrt(252)))`。它只用观察日已知价格，原调仓网格的下一开盘实施；未投入部分按零息现金处理，不借款。15%是基于SPY的缩放参数，不保证股票组合实际波动率等于15%，也不是止损价格。实际目标之间会发生价格漂移。

## 为什么还没有启用交易

最终联合98条目中，**{int(risk_all.gate_all.sum())}/98通过全部门槛**。该岭回归＋仓位规则通过收益、IR、年度一致性、回撤、Rank IC和20bp压力检查，但未通过共同多重尝试校正后的主动收益置信下界：日主动收益同时下界为{best.simultaneous_lower_daily:.6f}，未大于0。这个置信判断无法证明它没有价值，也不足以证明优势稳定存在。

主筛选对比满仓同池等权与SPY；同样仓位规则的等权基准另列，用于区分选股和风险控制的作用，主门槛沿用预登记设置。2015—2025被多轮研究过，98列也包括重复控制；区块bootstrap不能消除全部历史反复尝试或存续股票池偏差。2026行情仍未读取。

本机IBKR检查仍为not_connected：默认本机候选端口没有可用连接，未完成API握手或paper身份确认。没有真实或券商模拟订单发送，没有启用常驻自动下单服务。未来券商模拟成交与实际成交也存在差异，见[IBKR官方paper说明](https://www.interactivebrokers.com/docs/tws-api/doc/notes-limitations/limitations/paper-trading)。

## 这轮实际做过的训练和策略

| 环节 | 已完成工作 | 记录 |
| --- | --- | --- |
| 多周期模型 | Ridge、ElasticNet、LambdaRank；H=5/20/60；基础22、价格81、加财务97、加事件125列的24配置；每配置6年度，共144次拟合 | [24组完整对照](MODEL_COMPARISON.md)、[144次训练明细](TRAINING_DETAILS.md) |
| 组合比较 | 每个模型top5/top10，48条新主策略，分别10/20bp；联合旧44条目，共92条 | [48条新策略](comparison_new48.csv)、[92条表](comparison_all92.csv) |
| 持有周期诊断 | 固定ElasticNet full H20/H60、top5/top10，各匹配H调仓及自身基准 | [持有期结果](holding_diagnostics/comparison.csv) |
| 风险控制 | 原ElasticNet H5与新Ridge H60，分别波动率规则、200日趋势规则、两者组合，共6变体，联合评价扩为98条 | [风险6条](../risk_controls_v4/comparison_new6.csv)、[最终98条](../risk_controls_v4/comparison_all98.csv) |
| 更早历史 | 重新取得2012—2025连续快照，固定上述两模型在2016—2025逐年拟合，共20次；满仓/波动率仓位诊断 | [20次训练明细](../extended_history_v5/TRAINING_DETAILS.md)、[完整结果](../extended_history_v5/comparison.csv) |

本轮合计{len(fits)+len(extended_fits)}次实际模型拟合；144次中的{int(fits.control.notna().sum())}次是旧控制重现。更早历史20次使用新的训练样本，未计作控制重现。此前两批自动研究150次，加本轮共314次，包含重复控制，不包括更早教学脚本。当前两批新拟合均无训练警告；模型数量不能代替有效信息量或验证质量。

输入中的财报事件来自SEC已保存事实：财务同比变化、真正推进报告期间的新申报、距申报的交易日数和修改申报。只用filed早于观察日的事实；没有把财季截止日当作可知日期。数据来源与限制参见[SEC API说明](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)。本轮主矩阵9组price/full成对对照的统一5日IC均未因加全套财报事件而改善；ElasticNet内部单独加事件在H5有小幅回升，在H20/H60下降。完整失败项保留，不能因此推断所有基本面或新闻都无用。

## 全部6组仓位实验

vol15是上述波动率规则；trend25在SPY调整收盘低于过去200日均值时降到25%股票目标仓位，否则100%；combined取两者乘积。参数先固定，没有搜索最好的阈值。与模型无关的同风险等权也使用同一规则。

{formatting.table(formatting.fmt(risk_table,percentages=['cagr','max_drawdown','stress_cagr','matched_risk_equal_cagr'],decimals=['IR_vs_matched_risk_equal']))}

## 更多历史给出的约束

已获取44份连续价格文件。共同原始日历从{expanded_data['raw_common_start']}开始，共{expanded_data['raw_common_dates']}日；META此前没有返回记录，不补历史价格。252日预热后，可用面板{expanded_data['ready_rows']:,}行、{expanded_data['ready_dates']}日，从{expanded_data['ready_first']}至{expanded_data['ready_last']}。

2016—2025的逐年连续评分为{extended_complete['score_rows']:,}行/{extended_complete['score_dates']}日。下表的年数是在10个日历年中战胜“同一仓位规则的等权基准”的数量。没有将这张较长历史表加入98条冠军选择，也没有用它替换失败的门槛。

{formatting.table(formatting.fmt(ext_view,percentages=['cagr','max_drawdown'],decimals=['mean_rank_ic','IR_vs_matched_equal'],integers=['positive_active_years_out_of_10']))}

该实验使用更早训练样本、新连续供应商快照和更早锚定的调仓日程，不能把收益差异单独归因于数据量；原快照未覆盖或拼接改写。重叠历史价格差异记录在snapshot_overlap.csv。2016—2019此前曾用于旧模型训练，这次逐年重训诊断也不能称全新、从未接触的测试。

## 稳定性诊断和局限

Ridge H60满仓的5个调仓起点CAGR范围为{phase.cagr.min():.2%}—{phase.cagr.max():.2%}，没有选最高相位去替换原计划。禁止交易NVDA但不重训后，CAGR为{without.cagr:.2%}、最大回撤{without.max_drawdown:.2%}；同一29股等权为{without.matched_equal_cagr:.2%}。说明原成绩受个别强势股票影响，需要继续检查，不等于已做完删除该股后的模型重训。

目前仍是今天选出的30只存续股票、静态行业ETF代理、供应商可修订的调整价格；缺少完整历史股票池和退市覆盖。回撤是每日开盘代理估值，不是盘中极值。没有真实成交滑点/冲击校准、实际拆股/分红现金账本、市场一致预期或最早业绩新闻。新增财报列并不自动产生可交易的预测信息。

## 检查与执行准备

- {input_checks['events']['source_fact_references_matched_raw']:,}条财报来源引用匹配原始SEC事实；全30股物理截断重算、缺失标记与期间匹配检查通过；9,000组标签价格端点检查通过。
- {fit_checks['fits_checked']}份主模型和{ext_checks['models_checked']}份扩展历史模型的哈希、特征顺序、训练边界、仅训练集标准化和恢复评分检查通过。CSV评分均无损保存/读取。
- {execution['tests_run']}项虚构数据/故障测试通过：旧离线回放、IBKR只读响应、订单生命周期和股票/现金仓位账本。它们不是券商真实成交证据。
- 历史离线回放再次运行新增成交0，原42笔虚拟成交未重复。当前订单状态原型区分未知提交、部分成交、重复ID、撤单竞争、恢复核对和成交更正；没有网络下单功能，外部事务持久化、佣金处理和真实重连适配器仍待集成。
- requirements.txt保存实际虚拟环境；ib_async 2.1.0可导入，pip check通过。其依赖将tzdata固定到2025.3，本轮实际日历和历史重算已验证。

## 下一步的研究重点

当前候选保留为研究用途。优先补充更可靠的历史股票池/退市和公告时点数据，检验预测是否在更广样本和新的未来时期持续成立；不要再靠扩大网络或不断搜索阈值换取一条好曲线。执行方向已有只读探测和离线测试，下一工程节点是经过身份核验的券商模拟联调，独立检验成交、持仓与现金账本。自动实盘不由某张回测表自动开启。

详细模型解释、标签、费用与重现命令见[主研究报告](RESEARCH_REPORT.md)。更早历史运行35/36，汇总运行37；所有完整结果均已保存，重跑不会自动开启2026行情或券商订单。
"""
    (OUT/"FINAL_REPORT.md").write_text(report,encoding="utf-8")
    v3.save_json(OUT/"final_report_summary.json",{"generated_at_utc":datetime.now(timezone.utc).isoformat(),
                   "new_annual_fits":len(fits)+len(extended_fits),"new_main_strategy_entries":48,"new_risk_strategy_entries":6,
                   "joint_entries":98,"gate_passes":int(risk_all.gate_all.sum()),"candidate_for_further_research":best_name,
                   "candidate_is_approved_for_trading":False,"2026_market_prices_accessed":False,"orders_sent":0,
                   "report_path":str(OUT/"FINAL_REPORT.md")})
    print(str(OUT/"FINAL_REPORT.md"))


if __name__ == "__main__":
    main()
