"""报告第二轮固定实验及离线执行演练，只读取本地真实运行结果。"""

from datetime import datetime, timezone
import importlib
import json
from pathlib import Path

import pandas as pd

from panel_config import ROOT

OUT = ROOT / "data/experiments/automation_research_v2"
REPLAY = ROOT / "data/replays/offline_v1"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def markdown_table(headers, rows):
    def cell(value):
        return str(value).replace("|", "/").replace("\n", " ")
    return "\n".join(["| " + " | ".join(map(cell, headers)) + " |",
                       "| " + " | ".join(["---"] * len(headers)) + " |",
                       *["| " + " | ".join(map(cell, row)) + " |" for row in rows]])


def main():
    completion = read_json(OUT / "completion.json")
    fund = read_json(ROOT / "data/processed/fundamental_panel_v1.json")
    replay = read_json(REPLAY / "completion.json")
    runs = [read_json(path) for path in sorted(REPLAY.glob("run_*.json"))]
    comparison = pd.read_csv(OUT / "comparison_new12.csv", float_precision="round_trip").set_index("candidate")
    training = pd.read_csv(OUT / "training_summary.csv", float_precision="round_trip")
    bootstrap = read_json(OUT / "bootstrap_all44.json")
    assert len(comparison) == 12 and len(training) == 36 and len(training[["model", "year"]].drop_duplicates()) == 36
    assert completion["gate_passes"] == 0
    config = importlib.import_module("22_train_fundamental_comparison")
    model_labels = {"ridge_base": "岭回归/基础22列", "ridge_extended": "岭回归/扩展81列", "elastic_extended": "ElasticNet/扩展81列"}
    rows, pairs = [], []
    for label, kind, group, control in config.BASE_MODELS:
        for with_fund in (False, True):
            model = f"v2_{label}_{'fund' if with_fund else 'price'}"
            top5, top10 = comparison.loc[f"{model}_top5"], comparison.loc[f"{model}_top10"]
            rows.append([model_labels[label], "加16列财报输入" if with_fund else "原特征",
                         f"{top5.mean_rank_ic:.4f}", f"{top5.cagr:.2%}", f"{top5.max_drawdown:.2%}",
                         f"{top10.cagr:.2%}", f"{top10.max_drawdown:.2%}"])
        for top_k in (5,10):
            price = comparison.loc[f"v2_{label}_price_top{top_k}"]
            new = comparison.loc[f"v2_{label}_fund_top{top_k}"]
            pairs.append({"model": label, "top_k": top_k, "delta_cagr": new.cagr-price.cagr,
                          "delta_rank_ic": new.mean_rank_ic-price.mean_rank_ic,
                          "delta_max_drawdown": new.max_drawdown-price.max_drawdown,
                          "delta_information_ratio": new.information_ratio-price.information_ratio})
    pd.DataFrame(pairs).to_csv(OUT / "paired_feature_effects.csv", index=False)
    missing_rows = [[name, count, f"{count/fund['rows']:.2%}"] for name, count in fund["missing_counts"].items()]
    details = []
    gates = {"gate_cagr": "年化优势", "gate_information_ratio": "IR", "gate_positive_years": "年度一致性",
             "gate_drawdown": "回撤", "gate_rank_ic": "IC", "gate_stress": "成本压力", "gate_simultaneous_ci": "联合下界"}
    for strategy in config.STRATEGIES:
        name = strategy["id"]
        row = comparison.loc[name]
        details.append([name, f"{row.cagr:.2%}", f"{row.stress_cagr:.2%}", f"{row.information_ratio:.3f}",
                        f"{row.annual_traded_fraction:.2f}倍", "/".join(label for key, label in gates.items() if not row[key])])
    first = next(run for run in runs if run["new_fills"] > 0)
    reruns = [run for run in runs if run["new_fills"] == 0]
    warning_runs = int(training.warnings.ne("[]").sum())
    n = replay["final_snapshot"]
    report = f"""# 持续研究第二轮：加入财报信息，并接通离线执行流程

生成时间：{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S UTC}。本轮沿用最多45分钟上限；没有启用定时任务或后台无人值守服务。

**本轮最明确的进展是执行工程：冻结模型评分 → 目标仓位 → 下一交易日虚拟成交 → 资金/持仓核对 → 保存状态 → 重启后避免重复成交。训练方面完成了新的财报对照，但没有发现更可靠的交易优势。**

## 1. 实际完成的训练

30只股票的SEC公司财报数据已下载并保留原始JSON、请求记录和哈希。生成{fund['rows']:,}条财报股票日记录；和原面板按Date/symbol合并后，仍使用原75,240条共同完整价格样本，开发评分45,060条，没有因为财报缺失而删除股票。

三种模型×原特征/加入财报，共6个配置，每个按2020—2025六个开发年份拟合，**共36次实际训练，其中18次重现旧模型，18次是新的财报对照**。累计两轮共150次拟合，但训练次数本身不是有效性证据。每个评分又比较top5和top10，形成12个策略条目。

新增的16列是8个数值加8个缺失标记，不是16种独立财务指标。基础模型变为38列输入，扩展模型变为97列。参数、预登记矩阵在[固定研究设计](NEW_RESEARCH_DESIGN.md)和[计划JSON](plan.json)。

## 2. 财报如何避免提前使用

只允许 **filed < 观察日期** 的事实进入特征。因为没有精确的公开时刻，整个申报日都排除；最早在后续交易日使用，不能按季度或年度截止日提前使用。先按当时已公开事实筛选，再挑报告期间及当时已知版本。

余额表的分子分母必须同一期末和同一申报编号；年度利润率要求利润、营收同起止期间、同申报编号，年度期间限330—380日。资产同比的期间间距限330—400日，保留两期来源。

八个数值分别为负债/资产、权益/资产、资产同比、年度净利润率、年度利润/最新资产、年度经营现金流/最新资产，以及余额表与年报期末距观察日的天数。后两个利润/现金流资产比率允许期间不完全一致，明确是研究代理，不能叫精确同期ROA；age是距财务期末的天数，不能误解成距发布日的天数。

缺值及其原因保留；每年中位数填补和标准化只在该年的训练数据拟合，验证和开发数据不能决定填充值。训练期完全缺失的列保留为0并带缺失标记，不从未来借值。[原始特征元数据](../../processed/fundamental_panel_v1.json)

{markdown_table(['财报特征','缺失股票日','占财报面板比例'], missing_rows)}

30份companyfacts下载成功不代表所有指标完整。金融行业与非金融行业口径、缺值模式不同，缺失标记可能带有公司/行业身份信息；本轮不能把整体新增输入的效果全部归因于财务数值本身。SEC当前快照也不是完整历史版本数据库：原始JSON含2026事实，但历史特征排除观察日之后申报；2026行情留出集未取得或评价。[SEC官方API说明](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)

## 3. 同条件真实结果

仍预测下一开盘进入后的5个交易日超额收益名次，每5个交易日调仓。训练/验证标签必须在下一个时间段前成熟；开发持仓跨年连续计算。2020—2025早已参与研究，以下是开发回测，不是新独立测试。

下表均为买卖各10bp假设成本，供应商调整开盘价收益代理；top5各20%、top10各10%，无杠杆。回撤按每日开盘估值，非盘中极值。相同模型的top5/top10使用同一评分，所以Rank IC相同。

{markdown_table(['模型','输入','平均Rank IC','top5年化','top5回撤','top10年化','top10回撤'], rows)}

同池30股等权基准年化18.09%、最大回撤−31.44%；SPY年化15.18%、回撤−32.05%，都与前轮完全同区间同口径。

结果不支持这批财报比率改善当前5日排序：三个模型加入财报后，平均Rank IC全部下降。基础岭回归top5年化约从31.92%变为32.04%，但IC从0.0235降到0.0130；不能把约0.12个百分点的开发收益变化宣称为预测能力突破。扩展ElasticNet加入财报后年化从34.25%降到29.84%。

top10降低单只股票的目标比例，但没有一致降低回撤，而且本次12条目中对应top10年化均低于top5。更多股票不自动意味着更小的实际组合回撤，行业相关性和信号质量仍会影响结果。

{markdown_table(['策略','10bp年化','20bp年化','IR','年均买卖额/净值','未通过门槛'], details)}

年均买卖额/净值把每次实际交易额除以该时点交易前净值后累加，再除以年数；买入卖出均计，不除以2。它不是“平均持有多少倍杠杆”。费用按漂移后的实际净交易计算，含首建仓、末清仓。

旧32条目和新12条目共同做44条目的20日区块、2,000次max-t bootstrap；包含重复控制，不能称44个独立信号。临界值{bootstrap['critical_max_t']:.6f}，仍有**0/44通过全部既定门槛**。联合比较也不能抹去此前多轮试验、当前存续股票池和历史快照修订的影响。没有自动更换执行模型或开启2026留出评价。

完整数值：[新12策略](comparison_new12.csv)、[共同44条目](comparison_all44.csv)、[成对新增特征效果](paired_feature_effects.csv)、[36次训练明细](training_summary.csv)。本批捕获警告的训练次数为{warning_runs}，原始警告文本保留；18次控制的预测和top5回测均重现至绝对误差≤1e−12。独立核对财报来源、填补统计与虚拟成交账本的结果见[独立检查记录](INDEPENDENT_REVIEW.md)。

## 4. 离线执行闭环已经跑通什么

使用前轮冻结的2025年ElasticNet工程演练模型，hash写死并核验。模型训练标签截止2023-12-29，验证标签截止2024-12-31。读取历史特征时只读Date/symbol/X列，不把y或未来入场价格传给模型。它没通过研究准入，演练成功不改变这个事实。

历史范围2025-01-02—2025-02-14，初始虚拟资金10,000。实际首遍生成{first['observation_count']}批目标、{first['new_fills']}笔虚拟成交，核对{first['snapshot_count']}个交易日账户；期末净值{n['nav']:,.2f}，累计假设费用{n['cumulative_fees']:,.2f}。末日保留持仓，未另扣强制平仓费用。**这个短期数值只是账本核对结果，不是新增策略成绩或真实盈利。**

已完成{len(reruns)}次零新增成交的重复回放记录。独立进程重放相同批次，不新增成交、已处理键和交易事件。现金与持仓、目标、成交和处理键在单个state.json中原子提交；锁内重新读取状态，拒绝另一个实例用旧缓存覆盖。初始化标记可阻止丢失state后悄悄再造10,000资金。这个标记和本地锁不等于券商网络上的恰好执行一次。

每批目标先检查：历史模式、模型哈希、特征顺序、asof日期、权重非负、权重和≤1、每只目标≤20%；成交只在下一交易日，用当前模拟开盘报价检查全部价格有效。费用计入可投资资金，不允许借款。20%是目标/调仓后上限，之后价格漂移不会自动日内再平衡。

缺价、非有限值、错误日期、冲突批次键、损坏账本和状态缺失都会拒绝继续；待成交目标处理前不允许先封存同日快照。10项明确虚构的unittest验证这些故障路径；真实历史演练和虚构测试的证据分别记录。

代码：[离线执行器](../../../offline_execution.py)、[历史回放入口](../../../23_replay_execution.py)。结果：[回放完成记录](../../replays/offline_v1/completion.json)、[每日账户](../../replays/offline_v1/daily_account.csv)。价格和units都是供应商调整收益代理，不是当年的真实可成交报价或股票数量。

## 5. 一条命令运行当前离线流程

```powershell
Set-Location 'M:\\ml项目'
.\\.venv\\Scripts\\python.exe .\\24_run_offline_cycle.py
```

该命令依次从**已有快照**构建财报特征、训练或核对已完成的固定实验、运行历史目标/成交/核对、生成本报告；每阶段保存日志，失败就停止后续步骤。已有研究结果不会重复训练，相同历史成交批次不会再次成交。只接受historical_replay模式，不请求网络行情、不连接券商。

其他可单独运行的命令：

```powershell
.\\.venv\\Scripts\\python.exe -m unittest discover -s tests -p test_offline_execution.py -v
.\\.venv\\Scripts\\python.exe .\\22_train_fundamental_comparison.py
.\\.venv\\Scripts\\python.exe .\\23_replay_execution.py
.\\.venv\\Scripts\\python.exe .\\25_write_automation_report.py
```

21是已完成的SEC下载/准备入口；24在离线循环中直接调用fundamental_features.py，只读取缓存，不触发21的下载。模型、快照和实验计划冻结；新时期或新研究需要新配置和结果目录，不能删除完成标记来重复覆盖旧结果。

## 6. 距离正常全自动交易还差什么

当前已具备可重复运行的研究实验，以及离线目标—虚拟成交—账本闭环。尚未具备实时行情更新、真实时钟调度与延迟处理、券商模拟账户API、订单状态与部分成交处理、外部账户持仓对账、断线重连，以及实盘准入验证。当前本地幂等性不能代替这些工作。

下一步的训练应围绕一个新的可检验假设，例如财报变化/事件信息或更适合慢变化财务数据的预测周期；本次负结果并不证明所有基本面数据无用。下一步的执行工程应先验证券商模拟账户的只读行情/持仓接口和订单生命周期。两条线分别推进，不能由训练分数自动解锁真实下单。

本轮未新增依赖，未commit/push、未连接券商、未发出真实订单。不是已具备盈利证据的全自动交易系统，也没有暗中持续运行的后台服务。
"""
    (OUT / "RESEARCH_AND_EXECUTION_REPORT.md").write_text(report, encoding="utf-8")
    print(f"报告已生成：{OUT / 'RESEARCH_AND_EXECUTION_REPORT.md'}")


if __name__ == "__main__":
    __import__("sys").stdout.reconfigure(encoding="utf-8")
    main()
