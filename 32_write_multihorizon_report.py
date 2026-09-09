"""把保存的真实结果整理为模型对照、逐次训练明细和研究图；不重新训练。"""
import importlib
import json
from datetime import datetime, timezone

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

runner = importlib.import_module("28_train_multihorizon")
OUT = runner.OUTPUT


def table(frame):
    rows = [[str(value).replace("|","/").replace("\n"," ") for value in row] for row in frame.itertuples(index=False,name=None)]
    return "\n".join(["| " + " | ".join(frame.columns) + " |", "| " + " | ".join(["---"]*len(frame.columns)) + " |",
                      *["| " + " | ".join(row) + " |" for row in rows]])


def fmt(frame, percentages=(), decimals=(), integers=()):
    result = frame.copy()
    for c in percentages:
        result[c] = result[c].map(lambda x:f"{x:.2%}" if pd.notna(x) else "—")
    for c in decimals:
        result[c] = result[c].map(lambda x:f"{x:.4f}" if pd.notna(x) else "—")
    for c in integers:
        result[c] = result[c].map(lambda x:str(int(x)) if pd.notna(x) else "—")
    return result


def main():
    complete = json.loads((OUT/"completion.json").read_text(encoding="utf-8"))
    comparison = pd.read_csv(OUT/"comparison_new48.csv",float_precision="round_trip")
    all_comparison = pd.read_csv(OUT/"comparison_all92.csv",float_precision="round_trip")
    native = pd.read_csv(OUT/"native_ranking_metrics.csv",float_precision="round_trip")
    fits = pd.read_csv(OUT/"training_summary.csv",float_precision="round_trip")
    costs = json.loads((OUT/"cost_metrics_all92.json").read_text(encoding="utf-8"))
    boot = json.loads((OUT/"bootstrap_all92.json").read_text(encoding="utf-8"))
    checks = json.loads((OUT/"INPUT_CHECKS.json").read_text(encoding="utf-8"))
    fit_checks = json.loads((OUT/"FIT_CHECKS.json").read_text(encoding="utf-8"))
    readiness = json.loads((runner.ROOT/"data/broker_readiness/latest.json").read_text(encoding="utf-8"))
    holding = pd.read_csv(OUT/"holding_diagnostics/comparison.csv",float_precision="round_trip")
    warnings = fits.loc[fits.warnings.ne("[]")]
    main5 = comparison.loc[comparison.top_k.eq(5)].set_index("model")
    main10 = comparison.loc[comparison.top_k.eq(10)].set_index("model")
    intrinsic = native.loc[native["sample"].eq("all_horizons_mature")].set_index("candidate")
    model_rows = []
    for config in runner.MODELS:
        name = config["id"]
        row5,row10 = main5.loc[name],main10.loc[name]
        model_rows.append({"model":name,"kind":config["kind"],"horizon":config["horizon"],"input":config["feature_group"],
                           "features":len(runner.features_for(config)),"native_IC_common_dates":intrinsic.loc[name,"mean_rank_ic"],
                           "IC5_full_dates":row5.mean_rank_ic,"top5_CAGR":row5.cagr,"top10_CAGR":row10.cagr,
                           "top5_max_drawdown":row5.max_drawdown,"top5_IR":row5.information_ratio,
                           "top5_cost20_CAGR":row5.stress_cagr,"top5_gate":row5.gate_all,"top10_gate":row10.gate_all})
    models = pd.DataFrame(model_rows).sort_values(["horizon","kind","input"])
    models.to_csv(OUT/"model_comparison24.csv",index=False)
    summary_table = table(fmt(models,percentages=["top5_CAGR","top10_CAGR","top5_max_drawdown","top5_cost20_CAGR"],
                              decimals=["native_IC_common_dates","IC5_full_dates","top5_IR"]))
    (OUT/"MODEL_COMPARISON.md").write_text("# 24组模型的完整对照\n\nprice=81价格/ETF列；fund=97列；full=125列；base=22列。所有主交易每5个交易日调仓，费用为单边10bp；cost20单独注明。native IC按各自预测周期、共同成熟日期比较，IC5则全部用同一1502日的5日标签。\n\n"+summary_table+"\n",encoding="utf-8")

    columns = ["model","year","feature_count","train_rows","validation_rows","train_last_exit","validation_last_exit",
               "validation_native_ndcg5","n_iter","best_iteration","attempted_iterations","fit_seconds","control","max_control_score_difference","warnings"]
    details = fmt(fits[columns].sort_values(["model","year"]),decimals=["validation_native_ndcg5","fit_seconds","max_control_score_difference"],
                  integers=["n_iter","best_iteration","attempted_iterations"]).fillna("—")
    (OUT/"TRAINING_DETAILS.md").write_text("# 144次年度训练明细\n\n每行对应实际保存的模型和record.json。n_iter为ElasticNet迭代次数；best_iteration为排序树所选树轮数；attempted_iterations含提前停止等待轮数。验证指标基于该模型本征H，不能跨H当作相同预测任务比较。没有显示成收益的训练误差，也没有伪造训练准确率。\n\n"+table(details)+"\n",encoding="utf-8")

    pairs = []
    for h in (5,20,60):
        for kind in ("ridge","elastic","ranker"):
            price = main5.loc[f"v3_{kind}_h{h}_price"]
            full = main5.loc[f"v3_{kind}_h{h}_full"]
            pairs.append({"kind":kind,"horizon":h,"contrast":"full_minus_price",
                          "IC5_delta":full.mean_rank_ic-price.mean_rank_ic,"CAGR_delta":full.cagr-price.cagr,
                          "drawdown_delta":full.max_drawdown-price.max_drawdown})
        for left,right in (("base","price"),("price","fund"),("fund","full")):
            a,b = main5.loc[f"v3_elastic_h{h}_{left}"],main5.loc[f"v3_elastic_h{h}_{right}"]
            pairs.append({"kind":"elastic","horizon":h,"contrast":f"{right}_minus_{left}",
                          "IC5_delta":b.mean_rank_ic-a.mean_rank_ic,"CAGR_delta":b.cagr-a.cagr,
                          "drawdown_delta":b.max_drawdown-a.max_drawdown})
    pairs = pd.DataFrame(pairs)
    pairs.to_csv(OUT/"feature_ablation_effects.csv",index=False)

    fig, axes = plt.subplots(1,3,figsize=(15,4.3),sharey=True)
    colors = ["#687d99","#196b9e","#db9135","#197d61"]
    for ax,h in zip(axes,(5,20,60)):
        ordered = models.set_index("model").loc[[f"v3_elastic_h{h}_{g}" for g in ("base","price","fund","full")]]
        x = np.arange(4)
        ax.bar(x,ordered.IC5_full_dates,color=colors)
        ax.axhline(0,color="#444",lw=.8)
        ax.axhline(.03,color="#ad4444",ls="--",lw=1,label="Prespecified IC gate")
        ax.set_xticks(x,["Base22","Price81","+Fund16","+Event28"],rotation=22)
        ax.set_title(f"ElasticNet, trained on H={h}")
        for i,value in enumerate(ordered.IC5_full_dates):
            ax.text(i,value +(.001 if value>=0 else -.003),f"{value:.3f}",ha="center",fontsize=9)
    axes[0].set_ylabel("Mean daily Rank IC vs SAME 5-session label")
    fig.suptitle("Information ablation on common 2020-2025 development dates; not an independent test",fontsize=12)
    fig.tight_layout()
    fig.savefig(OUT/"feature_ablation.png",dpi=170)
    plt.close(fig)

    best_new = comparison.sort_values(["information_ratio","candidate"],ascending=[False,True]).iloc[0]
    eq = pd.read_csv(OUT/"equity_all92.csv",float_precision="round_trip",index_col="Date",parse_dates=["Date"])
    names = list(dict.fromkeys([best_new.candidate,"v3_elastic_h5_price_top5","benchmark_equal","benchmark_spy"]))
    fig,axes = plt.subplots(2,1,figsize=(11,7.2),sharex=True,gridspec_kw={"height_ratios":[2,1]})
    for name in names:
        axes[0].plot(eq.index,eq[name],label=name)
        peak = eq[name].cummax().clip(lower=1)
        axes[1].plot(eq.index,100*(eq[name]/peak-1),label=name)
    axes[0].set_yscale("log")
    axes[0].set_ylabel("NAV, starting cash = 1 (log scale)")
    axes[1].set_ylabel("Drawdown (%)")
    axes[0].set_title("Annual walk-forward development; 10bp each side; adjusted-open research proxy")
    axes[0].legend(fontsize=8,loc="upper left")
    for ax in axes:
        ax.grid(alpha=.2)
    fig.tight_layout()
    fig.savefig(OUT/"development_equity.png",dpi=160)
    plt.close(fig)

    compact = comparison[["candidate","cagr","max_drawdown","information_ratio","mean_rank_ic","stress_cagr","gate_all"]].sort_values("information_ratio",ascending=False)
    gates = [c for c in all_comparison if c.startswith("gate_") and c!="gate_all"]
    gate_counts = pd.DataFrame({"gate":gates,"passes_in_92":[int(all_comparison[g].sum()) for g in gates]})
    holding_view = holding[["candidate","cost_bps","cagr","max_drawdown","period_count","matched_equal_cagr","matched_spy_cagr"]]
    sample_ranges = native[["horizon","sample","rows","dates","first_observation","last_observation","last_exit"]].drop_duplicates().sort_values(["sample","horizon"])
    top = best_new
    verdict = ("尚无条目通过全部既定研究门槛，2026行情保持封存，不能据此声称策略取得质的飞跃。" if complete["gate_passes"]==0 else
               f"有{complete['gate_passes']}条目通过开发门槛，唯一候选为{complete['selected_candidate']}；是否得到新留出支持须另读冻结留出结果，开发筛选不等于交易许可。")
    report = f"""# 第三轮连续研究：预测周期、财报事件和执行准备

{verdict}

本轮上限为2026-09-09 05:03:07—07:03:07 UTC，中途用户恢复后沿用原预算；最终完成时间另见session_completion.json。训练截止06:45:07 UTC。这里报告实际完成的工作，不把预算当作已经运行的时长。

## 实际训练了什么

24个配置×2020—2025六个年度，共{len(fits)}次实际拟合，保存全部模型、逐次记录、验证评分、开发评分和排序树学习曲线。其中{int(fits.control.notna().sum())}次直接复现旧控制；累计前三轮拟合为{150+len(fits)}次，包含重复控制。此次训练调用耗时合计{fits.fit_seconds.sum()/60:.2f}分钟，不等同于总墙钟时间。存在警告的拟合数：{len(warnings)}，原文保留在训练明细。

三个预测周期为5、20、60交易日。Ridge alpha=100；ElasticNet alpha=.001、l1_ratio=.15；LambdaRank最多1000轮、31叶、按各自H的验证NDCG提前停止。固定随机种子42，不在开发年上挑超参数。输入分别为基础22列、价格/ETF81列、加财务水平后的97列、再加本次事件后的125列。18个主矩阵配置加6个ElasticNet输入消融。

每个年度训练使用Y-2及以前，验证使用Y-1，评分使用Y；训练/验证标签各自的退出日期必须严格早于下一段。填补和标准化只在训练行拟合。价格、成交量、波动率、行业/债券ETF状态以外，本轮加入财务同比变化、报告公开后的交易日计时和修改申报事件。SEC来源说明见[官方API文档](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)。

股票池仍是30只今天选定的存续股票，原始行情2015—2025；没有把增加标签或财报列称为新增股票行情。训练共同面板75,240行，开发评分45,060行/1,502日，2020-01-02—2025-12-22。

## 结果口径与主要比较

所有48个主策略都每5个交易日调仓，次日开盘成交，top5/top10等权、只做多、无杠杆。单边10bp=成交金额的0.10%，20bp压力测试=0.20%；费用按实际净买卖金额收取，包含初建仓、最终清仓。不同预测H没有改变主交易日程。2015—2025已经反复用于开发，年度向前验证不使这些年份重新变成独立测试。

同池等权CAGR {costs['benchmark_equal']['cagr']:.2%}、最大回撤{costs['benchmark_equal']['max_drawdown']:.2%}；SPY CAGR {costs['benchmark_spy']['cagr']:.2%}、最大回撤{costs['benchmark_spy']['max_drawdown']:.2%}。这些都是特定历史、固定成本和调整开盘价代理下的研究结果，不是实际账户收益。

本轮按IR最高的开发条目为 `{top.candidate}`：CAGR {top.cagr:.2%}，最大回撤{top.max_drawdown:.2%}，IR {top.information_ratio:.3f}，统一5日Rank IC {top.mean_rank_ic:.4f}。是否通过全部门槛：{bool(top.gate_all)}。不能只看它的最高历史收益宣布最强。

{table(fmt(compact.head(12),percentages=['cagr','max_drawdown','stress_cagr'],decimals=['information_ratio','mean_rank_ic']))}

![开发期净值和回撤](development_equity.png)

全部24组模型对照见[MODEL_COMPARISON.md](MODEL_COMPARISON.md)，全部48条新策略和92条联合结果见comparison_new48.csv、comparison_all92.csv。它们包含重复控制，不能称92个独立策略。逐年主动收益、每条门槛、同时下界均在CSV中，不只展示胜者。

## 更多信息是否有效

下面用ElasticNet四层输入进行成对比较；新增信息对统一5日交易IC的影响可以直接比较。Ridge/排序树本轮只有price与full，不能独立归因财务水平或事件的贡献。

![信息消融](feature_ablation.png)

{table(fmt(pairs,percentages=['CAGR_delta','drawdown_delta'],decimals=['IC5_delta']))}

CAGR_delta和drawdown_delta为比例之差，阅读时用百分点；回撤差为正表示回撤较浅。对应结论仅限这组样本、特征定义和固定参数。财报公开事件并不等于最早的业绩新闻，也没有包含市场一致预期和真实业绩惊喜。不能由某组财报输入失效推断所有基本面或新闻都没有价值。

## 长周期标签与低频交易的区别

本征IC按模型训练的H计算；主门槛仍用共同5日IC。各H成熟日期如下，尾部未来尚未发生的标签不补值，但仍允许仅用X评分。共同成熟日期的本征IC单列在模型表中；长周期重叠标签不是独立样本。

{table(sample_ranges)}

预先固定的4个持有H日诊断（各含10/20bp）如下。每行使用自身相同日程的等权/SPY基准；不参加92条目冠军选择。

{table(fmt(holding_view,percentages=['cagr','max_drawdown','matched_equal_cagr','matched_spy_cagr']))}

## 如何处理多次尝试与不稳定性

联合92条目使用相同日期、20交易日循环区块bootstrap、2,000次共同重采样、seed20260907。max-t一侧95%同时下界检验的是相对同池等权的日主动收益均值。它考虑此列族的共同尝试与相关性，不能消除此前自适应研究、存续股票池和行情修订偏差。

各单项通过数量：

{table(gate_counts)}

调仓起点五种相位、30bp、禁止选NVDA但不重训、逐股P&L贡献及5/20/60日bootstrap区块敏感性保存在robustness目录。诊断不反过来更换最好的日程或放宽门槛。

## 检查证据

- 事件数据{checks['events']['rows']:,}行，{checks['events']['source_fact_references_matched_raw']:,}条来源引用匹配SEC原始事实，财务变化和事件时钟各{checks['events']['financial_change_cells_recomputed']:,}个单元格重算一致，缺失标记完整。
- 全30股过去日期物理截断重算通过；9,000个价格端点核对通过。filed严格早于观察日；不是按财季截止日提前使用财报。
- {fit_checks['fits_checked']}份保存模型复核哈希、特征顺序、各H训练/验证边界、训练中位数/均值/方差、预测恢复与排序树早停位置。完整性：{fit_checks['complete_144']}。
- 所有评分CSV用round_trip读取，保存前后逐值相同；旧控制在1e-12内复现，避免极小浮点漂移改变排序并列。

## 向自动交易推进了什么

真实本机IBKR探测结果：`{readiness['status']}`，paper身份确认：{readiness['paper_account_confirmed']}，订单发送：0。阻塞项：`{readiness.get('blocker')}`。目前没有可用TWS/IBGateway API会话；没有伪装成已连通的模拟交易。使用的ib_async 2.1.0是第三方Python客户端；ib_async依赖约束使tzdata从2026.3变为2025.3，requirements.txt已保存实际环境，pip check通过。历史保存日期与本轮标签端点复核通过。

新增只读就绪脚本29_check_ibkr_readiness.py，核对本机监听、API握手、账户身份、服务器时间、仓位和开放订单快照；账户标识和金额脱敏，超时保持未知。端口或readonly参数本身不证明paper身份。连接要求参考[IBKR官方说明](https://www.interactivebrokers.com/docs/tws-api/doc/connectivity/establishing-an-api-connection)。

订单状态原型execution_order_state.py处理提交不确定、部分成交、重复回报、撤单与迟到成交、恢复核对和成交更正隔离。全部是虚构事件的离线测试，不是真实券商认证；没有网络下单方法，也尚未整合外部事务日志、佣金账本和重连适配器。IBKR可能重复发送状态，成交更正ID也有特殊规则，分别依据[订单状态说明](https://www.interactivebrokers.com/docs/tws-api/doc/order-management/order-status/introduction)和[ExecID说明](https://www.interactivebrokers.com/docs/tws-api/doc/order-management/execution-details/exec-id-behavior)。

旧历史回放闭环保留；真实行情刷新、成交价格/分红账本、市场冲击、账户级资金限制和券商模拟运行仍待贯通。当前没有启用真实订单或常驻自动服务。即使之后接通paper，模拟成交也不能代替实盘成交验证，见[IBKR paper差异](https://www.interactivebrokers.com/docs/tws-api/doc/notes-limitations/limitations/paper-trading)。

## 文件与复现

项目解释器为 `M:\\ml项目\\.venv\\Scripts\\python.exe`。

```powershell
.\\.venv\\Scripts\\python.exe 28_train_multihorizon.py
.\\.venv\\Scripts\\python.exe 30_validate_research_inputs.py
.\\.venv\\Scripts\\python.exe 30_validate_research_inputs.py --fits
.\\.venv\\Scripts\\python.exe 31_research_robustness_v3.py
.\\.venv\\Scripts\\python.exe 32_write_multihorizon_report.py
.\\.venv\\Scripts\\python.exe -m unittest discover -s tests -v
.\\.venv\\Scripts\\python.exe 29_check_ibkr_readiness.py
```

28发现完整结果后不重复训练。输入准备26/27复用已有SEC和价格快照；绝不自动下载2026或发送订单。新实验必须使用新目录和登记设计，不能覆盖这次结果；原始时间预算不会被重跑延长。

关键记录：DESIGN.md、plan.json、TRAINING_DETAILS.md、training_log.jsonl、各年份joblib/评分/curve、INPUT_CHECKS.json、FIT_CHECKS.json、backtests逐笔交易/逐期/逐日文件、robustness诊断和session_completion.json。
"""
    (OUT/"RESEARCH_REPORT.md").write_text(report,encoding="utf-8")
    runner.save_json(OUT/"report_summary.json",{"generated_at_utc":datetime.now(timezone.utc).isoformat(),
                     "annual_fits":len(fits),"control_reproduction_fits":int(fits.control.notna().sum()),
                     "fits_with_warnings":len(warnings),"gate_passes":complete["gate_passes"],
                     "best_new_development_candidate":top.candidate,"selected_candidate":complete["selected_candidate"],
                     "report_path":str(OUT/"RESEARCH_REPORT.md")})
    print(json.dumps({"fits":len(fits),"gate_passes":complete['gate_passes'],"best_new":top.candidate},indent=2))


if __name__ == "__main__":
    main()
