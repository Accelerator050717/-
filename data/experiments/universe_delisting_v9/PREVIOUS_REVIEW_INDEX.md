# 最新源码审阅入口

更新：2026-09-09 UTC，v8风控修复与H60执行统一。基线提交`9d98008d72f096c2c1fa33a998f000fe62c48bb5`；本轮代码和新实验保存在本地，未自动提交/推送。首次上传索引另存[历史索引](data/experiments/h60_risk_execution_v8/PREVIOUS_REVIEW_INDEX.md)。

**先读[本轮完整报告](data/experiments/h60_risk_execution_v8/FINAL_REPORT.md)。主候选净CAGR14.88%、收盘最大回撤17.74%，未达到最低30%收益目标，拒绝升级，不使用2026终测。** 目标仍为30%、争取50%；回撤优先约20%、30%是预算上沿；不加杠杆、不降低门槛。当前没有通过盈利验证的自动交易模型。

## 当前进度与身份

- 固定30只存续美股及SPY；新增训练0次，复用2016—2025十份H60 Ridge原模型/预测，81个原特征、alpha100、svd。哈希、训练观察和标签成熟日期见[TRAINING_RECORD](data/experiments/h60_risk_execution_v8/TRAINING_RECORD.json)。
- v6/v7非计划减仓现在只减少股数，target_vol接通SPY仓位公式；软减仓与硬暂停独立配置。原v7排名12缓冲、软恢复、冷却/趋势/调仓日复仓保留。
- 唯一主候选沿用最多8股、集中度约束、SPY波动缩仓、15%个股保护和20%硬暂停，仅关闭10%软减半。失败后没有追加参数或挑相位。原0/98未过全部统计门槛的记录不变。
- 新工程入口43使用2025 H60文件`data/experiments/extended_history_v5/2025_ridge_h60_price.joblib`，SHA256 `2c19480278678e72fb9303e4f615737abccfa2c7dac883893af36390c2365ece`。不是2026部署模型；旧23/m16演练及账本完整保留。
- [最新虚拟工程清单](data/experiments/h60_risk_execution_v8/ENGINEERING_STRATEGY_MANIFEST_v5.json)包含模型、特征、标签边界、风险参数、调仓日历和源码SHA256。[未启用paper清单](data/experiments/h60_risk_execution_v8/PAPER_ENGINEERING_MANIFEST.json)另用1,000美元预算/独立策略ID。两者都是工程配置，未冻结用于2026终测的候选。

## 优先阅读

| 主题 | 源码与记录 |
| --- | --- |
| 事前计划及验收 | [PLAN](data/experiments/h60_risk_execution_v8/PLAN.md)、[机器计划](data/experiments/h60_risk_execution_v8/plan.json)、[全部门槛](data/experiments/h60_risk_execution_v8/GATES.json) |
| 修复及实际历史影响 | [research_backtest](research_backtest.py)、[profit_priority_strategy](profit_priority_strategy.py)、[robust_strategy](robust_strategy.py)、[bug差值](data/experiments/h60_risk_execution_v8/bug_impact.csv)、[回归测试](tests/test_risk_fixes.py) |
| 固定比较与原输入 | [42](42_evaluate_h60_risk_fixes.py)、[h60_research_inputs](h60_research_inputs.py)、[INPUT_IDENTITY](data/experiments/h60_risk_execution_v8/INPUT_IDENTITY.json) |
| 全部结果、年度和压力 | [12条主要比较](data/experiments/h60_risk_execution_v8/comparison.csv)、[全部39条](data/experiments/h60_risk_execution_v8/all_results.csv)、[年度](data/experiments/h60_risk_execution_v8/annual_results.csv)、[15条压力](data/experiments/h60_risk_execution_v8/stress_comparison.csv)、[执行原因](data/experiments/h60_risk_execution_v8/trade_reason_summary.csv)、[逐笔/每日](data/experiments/h60_risk_execution_v8/backtests) |
| 共享策略和前瞻评分接口 | [H60Runtime](h60_strategy_runtime.py)、[协调器](h60_execution_cycle.py)、[原模型评分核对](data/experiments/h60_risk_execution_v8/FORWARD_SIGNAL_INTERFACE_CHECK.json) |
| 持久化与paper适配器 | [H60Executor](h60_execution.py)、[IBKR paper](h60_ibkr_paper.py)、[43入口](43_run_h60_simulation.py)、[配置模板](config/h60_paper.example.json)、[执行说明](data/experiments/h60_risk_execution_v8/EXECUTION_GUIDE.md) |
| 虚构执行及恢复证据 | [最新执行](data/experiments/h60_risk_execution_v8/execution_v5/completion.json)、[重复启动](data/experiments/h60_risk_execution_v8/execution_v5/REPEAT_RUN.json)、[持久状态](data/experiments/h60_risk_execution_v8/execution_v5/state.json)、[44故障入口](44_test_h60_recovery.py)、[三进程恢复](data/experiments/h60_risk_execution_v8/execution_faults_v2/completion.json)、[测试](data/experiments/h60_risk_execution_v8/TESTS.json) |
| 历史股票池/退市数据 | [实际可用性、许可、接口及代码改点](data/experiments/h60_risk_execution_v8/HISTORICAL_UNIVERSE_TASK.md) |
| 原训练及上轮反思 | [35](35_extend_historical_diagnostic.py)、[38](38_train_robust_strategy.py)、[39](39_evaluate_robust_strategy.py)、[40](40_evaluate_profit_priority.py)、[旧反思](data/experiments/strategy_reflection_20260909/REFLECTION_AND_RESULTS.md) |
| 原特征、标签和统计检验 | [research_features](research_features.py)、[research_horizons](research_horizons.py)、[research_evaluation](research_evaluation.py)、[旧v3报告](data/experiments/continuous_research_2h_v3/FINAL_REPORT.md) |

## 环境与运行顺序

解释器`M:\ml项目\.venv\Scripts\python.exe`，Python3.12.2，依赖见[requirements.txt](requirements.txt)，本轮无新增依赖。先看报告、计划和代码；克隆缺原大文件时，先按下方ZIP清单恢复并核对SHA256。

```powershell
Set-Location 'M:\ml项目'
.\.venv\Scripts\python.exe 42_evaluate_h60_risk_fixes.py
.\.venv\Scripts\python.exe 43_run_h60_simulation.py
.\.venv\Scripts\python.exe 44_test_h60_recovery.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe 45_summarize_h60_v8.py
```

42完成后核对固定身份并保留结果，不拟合；43默认虚构报价/券商并复用持久状态；44使用虚构券商做跨进程故障；45只汇总保存结果。它们不下载行情或连接实际券商。不要为审阅运行旧03—41整条链，部分脚本会下载、训练或改写旧输出。

只读IBKR探测：`.\.venv\Scripts\python.exe 43_run_h60_simulation.py --check-ibkr`。paper恢复核对命令及最少配置步骤见执行说明；没有后台交易服务或实盘模式。

## 收益口径与证据边界

统一2016-01-05—2025-12-29、初始10,000美元、收盘估值、最终开盘清仓、零息现金、无杠杆；研究采用调整OHLC/碎股收益代理。主要普通单边10/20bp，止损额外10bp，压力另列。费用是全区间累计金额，换手计双向交易额。

10bp下：修正后止损开/软减仓开12.16% CAGR、15.37%回撤；主候选14.88%/17.74%；同一事前80%预算简单H60为20.83%/21.15%，SPY为9.75%/17.57%。事前预算相同不表示实现波动相同。主候选约十年累计净收益299.39%；高成本压力11.29% CAGR/25.70%回撤。全部属于反复使用的开发历史，不能宣布独立验证通过。

非计划减仓旧版确实产生买单：v7完整99笔→0，CAGR11.32%→12.16%，回撤15.37%不变。其他配置改善或下降均保留。SPY缩仓分子15%不是组合波动15%的承诺，20%硬暂停也不是最大回撤20%的保证。

73项测试只覆盖对应虚构场景；H60工程26笔成交全为虚构，重跑新增意图/成交0。3个真实OS进程、2次刻意中断验证恢复，但券商和资金仍虚构。真实paper回报0、前瞻业绩0。保护单撤换存在暂缺窗口，尚未验证真实撮合与长期断线补账。

## 2026与未完成事项

- 市场原快照截止2025年末，本轮未读取/下载/评估2026行情。候选失败，不消耗终测。原SEC全量快照含2026后续事实，历史特征按公开日期过滤；不能泛称项目从未见过任何2026信息，本轮未用财报模型。
- [IBKR实际探测](data/experiments/h60_risk_execution_v8/IBKR_READINESS.json)时间2026-09-09 08:30:52 UTC：常用paper端口7497/4002无监听，未握手、未确认paper身份、未查询行情权限、订单0。未对所有自定义端口作结论。
- 盈利不足，存续偏差/退市覆盖及独立验证未解决。唯一优先下一步是建立许可合适的历史股票池/退市数据样本闭环，再预登记新的信号增量实验，不继续在这四格历史上调阈值。
- 工程仍需Paper TWS/Gateway登录、隔离身份/预算、实时报价权限、精度及公司行动确认。当前年度模型不能直接产生2026信号；自动公司行动账本、保护撤换窗口、真实回报时序及长期断线恢复待验证。
- 未调用17/18，稳定实验身份/运行时间混用的旧问题未改；未重算H20/H60百分位集成，理论同分浮点问题未改，均未污染本轮单H60结果。

## 大型材料与复现

原大文件仍在`M:\ml项目\data\...`，精确路径、大小、SHA256、实验及命令见[旧大文件清单](review_upload/large_artifacts.csv)。[独立ZIP清单](review_upload/bundles.json)对应本地`M:\ml项目\review_bundles\20260909\`，每个不超过450MiB，保留原相对路径。v5/v6/v7模型、预测、行情没有删除、重训或用新数据替换。

本轮产物在`data/experiments/h60_risk_execution_v8/`：39次逐笔/每日、全部失败方案、SQLite账本和故障记录；预测复用原v5 all_scores.csv，对应身份在INPUT_IDENTITY。新文件的大小/SHA256见[ARTIFACTS](data/experiments/h60_risk_execution_v8/ARTIFACTS.csv)。本地v8新工作尚未进入原GitHub提交或旧审阅ZIP。