# 最新源码审阅入口

最新更新：2026-09-21，**v12年度训练截止比较完成：10次新拟合、14次新回放；更新协议未改善，仍未达到30%净年化目标，不升级模型。** 先读[v12完整报告](data/experiments/h60_training_cutoff_v12/REPORT.md)、[事前计划](data/experiments/h60_training_cutoff_v12/PLAN.md)、[10次训练和全部模型SHA](data/experiments/h60_training_cutoff_v12/TRAINING_DETAILS.md)、[成对差值](data/experiments/h60_training_cutoff_v12/pair_deltas.csv)和[验收](data/experiments/h60_training_cutoff_v12/GATES.json)。

本轮基于8b70778217cc2e0405cd20b68e4a3ba9f51b6cd9完成单因素实验、必要检查和上传；没有获取行情、使用2026或发送真实/paper订单。[v12上传说明](review_upload/sync_v12_20260921/README.md)、[新增大文件路径/大小/哈希](review_upload/sync_v12_20260921/large_artifacts.csv)补充原[v8—v11清单](review_upload/sync_v8_v11_20260911/README.md)。旧结果及旧清单完整保留，精确提交以包含本文件的Git版本为准。

- 2016-01-05—2025-12-29、10bp普通单边成本：完整保护A净CAGR14.88%/全历史回撤17.74%，B13.69%/19.55%；同预算简单H60 A20.83%/21.15%，B18.22%/25.01%。共同2,453成熟日期Rank IC由0.1127降至0.0939。全部35条主/压力结果见[all_results](data/experiments/h60_training_cutoff_v12/all_results.csv)，14条B新结果及21条原A/SPY结果均核对账本；未用最好相位代替主结果。
- B保留原rank_60、81特征、Ridge(100,svd)，只改变年度部署前可用训练集；重新从完整面板筛选Date与exit_60均早于当年起点。2025训练78,300→85,860行，含1,830条原边界剔除行；全部75,240预测键保留。详见[53训练](53_train_annual_cutoff.py)、[独立检查](data/experiments/h60_training_cutoff_v12/INDEPENDENT_TRAINING_CHECK.json)。旧A协议不是泄漏错误，B上一年已纳入拟合，不能再称验证集。
- 运行/复核：现有`.venv\Scripts\python.exe`（Python3.12.2、requirements.txt，无新增依赖）。先[52旧v11只读验证](52_verify_frozen_research.py)，再53（完成后仅核验）、[54 --check-only](54_evaluate_training_cutoff.py)，[55汇总](55_summarize_annual_cutoff.py)只读原结果写报告。新计算须遵守冻结计划和预算，完成目录不覆盖。
- 52保留旧生成提交9d98008…及源码身份，用上传8b707…锚定原清单；当前复核提交/验证器哈希单列。703个唯一文件验证通过，提交号变化允许，真实源码或输入/模型/预测/结果变动仍拒绝。旧50源码和TRAINING_IDENTITY没有重写；**完成v11的只读复核请用52，旧50会因HEAD变化拒绝，不能作为当前复核命令**。
- 全账户30%预算按连续历史高水位，不随风险周期恢复重置。现有研究统计已独立核对；[虚构两次亏损/恢复](data/experiments/h60_training_cutoff_v12/drawdown_check/README.md)出现42.52%全历史回撤，证明20%周期暂停不是30%账户上限。未在主实验混入新风险控制。下一步唯一优先：[全账户高水位控制及收益代价](data/experiments/h60_training_cutoff_v12/NEXT_QUESTION.md)，停止沿训练截止继续扫参数。
- A、B均未达30%收益目标，B拒绝升级；无独立验证通过模型，无2026候选冻结；真实paper回报和前瞻业绩均无新增。v8工程配置及v10代理继续使用原模型，没有切换为B。

v11历史成果保留：[完整报告](data/experiments/h60_signal_objectives_v11/REPORT.md)、[30次训练](data/experiments/h60_signal_objectives_v11/TRAINING_DETAILS.md)、[42条结果](data/experiments/h60_signal_objectives_v11/all_results.csv)。v11比较学习目标，最佳新增净CAGR16.29%仍未达标；其NEXT_QUESTION已由本轮v12执行，旧文档保留当时状态。原v8/v9/v10、v5/v6/v7与0/98未过记录均保留。

## 保留的v10 LEAN迁移

v10 LEAN 研究代理迁移已通过。见[v10结果与限制](data/experiments/lean_migration_v10/REPORT.md)、[完整实际引擎比较](data/experiments/lean_migration_v10/engine_runs/h60_full_01/PARITY.json)及[运行命令](tools/lean_runtime/README.md)。

- 实际LEAN引擎回放2511日/4951笔研究代理成交，原生进程退出0；每日权益与v8最大差5.60e-10美元。收益14.88%/回撤17.74%保持一致，仍未达到30%收益目标，不使用2026终测。
- 顺序：[47导出](47_prepare_lean_migration.py) → [LEAN事件与订单](lean_migration/main.py) / [共享策略适配](lean_migration/decision.py) → [48独立核对](48_compare_lean_migration.py) → [49汇总](49_summarize_lean_migration.py)。原策略代码保留未改；复用10份年度预测，新增训练0。
- [60日虚构冲击的真实引擎结果](data/experiments/lean_migration_v10/engine_runs/synthetic_risk_01/SYNTHETIC_CHECK.json)验证硬暂停/冷却/恢复；不能当成市场业绩或止损保证。
- 引擎固定上游提交加[本地退出兼容补丁](tools/lean_runtime/patches/native_shutdown_gil.patch)，运行时在`M:\quantconnect-lean-runtime\Lean`。实际身份、失败记录和本地材料见[报告](data/experiments/lean_migration_v10/REPORT.md)。通用盘中统计和一项可选并发分析存在限制，本轮用独立收盘账本核验。
- 当前LEAN入口是调整日线/碎股代理，尚未接原生美股公司行动、IBKR或持久化恢复。已保存记录中真实paper订单/实盘订单均0，无前瞻业绩；原生报价/公司行动适配仍是后续执行工程，v11训练未替换该入口。

### LEAN实际数据流

| 环节 | 实际源码行为 |
| --- | --- |
| 导入 | [47](47_prepare_lean_migration.py)读取原v5 `all_scores.csv`中的H60预测分数，导出`package.json`的`scores`、历史风险值、日历、策略参数和原调整行情的阶段CSV。训练与模型预测已在外部完成；模型SHA是身份记录，LEAN不重新训练或推理，也不导入现成目标仓位或交易清单。 |
| 生成决策 | [H60Decision](lean_migration/decision.py)按阶段接收价格，读取上一观察日分数及当时已知风险，调用共享`scheduled_weights`及`reduction_weights`，根据LEAN当前持仓、现金重新计算目标权重与买卖股数。止损、冷却和暂停状态也在本次回放中更新。 |
| 订单与成交 | [LeanLedger和模型](lean_migration/main.py)向LEAN提交`market_order`。项目自定义`H60ProxyFillModel`指定日线代理成交价并立即全额成交，`H60ProxyFeeModel`计费；LEAN订单引擎产生`OrderEvent`并更新现金、费用与持仓。不是默认真实撮合、真实券商回报或已下发的券商保护单。 |
| 事后核对 | [48](48_compare_lean_migration.py)才读取v8目标/交易/权益作为参照，与LEAN新生成账本比较，并逐笔关联真实引擎成交回调、重建现金和股数；参照交易不驱动LEAN决策。 |

OPEN 09:30／RANGE 12:00／CLOSE 16:00是人工阶段顺序，RANGE使用整日日线Low，不能解释为中午已知报价；调整价格和碎股仅用于与旧研究口径一致。[实际运行配置](data/experiments/lean_migration_v10/engine_runs/h60_full_01/executed_config.json)为`backtesting`、`live-mode=false`、本地文件数据源；[完成记录](data/experiments/lean_migration_v10/engine_runs/h60_full_01/completion.json)和[进程记录](data/experiments/lean_migration_v10/runtime/h60_full_01.run.json)对应2511日、4951笔历史代理成交及退出码0。

v11三组新模型及v12年度更新B均未通过收益门槛，未接入此LEAN入口。v8的[26笔虚构执行记录](data/experiments/h60_risk_execution_v8/execution_v5/completion.json)明确标记报价/成交虚构、真实paper成交0、前瞻观察0；它的持久化恢复功能尚未迁入LEAN。最近保留的[IBKR只读探测](data/experiments/h60_risk_execution_v8/IBKR_READINESS.json)为2026-09-09，未连接、未确认paper身份；本轮未重新探测，不能据旧记录推断此刻TWS状态。

当前具体缺口：原生美股报价/公司行动、真实paper运行入口、部分成交期间的持续保护、保护撤换窗口及长期断线补账。不能删除v10的历史模式限制后直接用于paper；v8原型已实现的功能也不等于LEAN集成已完成。

## 保留的v9数据接入口

v9更新：2026-09-11 UTC（洛杉矶09-10），本地历史股票池/终止事件接入口。见[v9本轮结果](data/experiments/universe_delisting_v9/REPORT.md)、[输入契约与命令](data/experiments/universe_delisting_v9/DATA_CONTRACT.md)、[来源复核](data/experiments/universe_delisting_v9/SOURCE_ASSESSMENT.md)。

- 用户确认暂时没有订阅；本轮完成[46入口](46_check_historical_universe.py)、[核心模块](historical_universe.py)与[13项检查](tests/test_historical_universe.py)，没有采购或连接供应商/券商。
- 真实ATVI公开事件＋假设10股得到应收950美元、可用现金0；没有真实账户收款证据或收益计算。[实际输出](data/experiments/universe_delisting_v9/completion.json)、[事件表](data/experiments/universe_delisting_v9/atvi_event_timeline.csv)分别记录。
- 两个时间边界控制成员变化，停牌/终止单独控制交易资格；未知终止不补0，已含退市收益不重复相加。Norgate不提供退市收益/退市后事件，来源复核修正了旧说明。
- 完整授权股票池、退市总体覆盖及旧代码的动态股票池接入仍未完成；没有消除存续偏差。本轮训练0、策略回测0、交易0，2026未使用。v8研究结论与所有原产物保留。
- 默认运行：`.\.venv\Scripts\python.exe 46_check_historical_universe.py`。原授权数据未来放入被Git忽略的`data/private/universe/`，不直接上传原始授权库。v9接口、公开案例及限制均列入本次同步清单。

## 保留的v8策略与执行审阅

v8更新于2026-09-09 UTC。同步前审阅基线提交`9d98008d72f096c2c1fa33a998f000fe62c48bb5`；v8—v11同步后的版本以本次上传记录为准。首次上传索引另存[历史索引](data/experiments/h60_risk_execution_v8/PREVIOUS_REVIEW_INDEX.md)。

**先读[本轮完整报告](data/experiments/h60_risk_execution_v8/FINAL_REPORT.md)。主候选净CAGR14.88%、收盘最大回撤17.74%，未达到最低30%收益目标，拒绝升级，不使用2026终测。** 目标仍为30%、争取50%；回撤优先约20%、30%是预算上沿；不加杠杆、不降低门槛。当前没有通过盈利验证的自动交易模型。

## v8进度与身份（历史记录）

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

## v8环境与运行顺序（历史复现）

解释器`M:\ml项目\.venv\Scripts\python.exe`，Python3.12.2，依赖见[requirements.txt](requirements.txt)；LEAN另需上述运行时与兼容补丁。以下为历史复现命令，本次上传不执行。先看报告、计划和代码；克隆缺原大文件时，先按下方ZIP清单恢复并核对SHA256。

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
- 盈利不足，存续偏差/退市覆盖及独立验证未解决。v8当时建议先补历史股票池/退市样本；v9已完成本地接入口，授权总体数据仍缺。当前下一轮问题以上方v11 [NEXT_QUESTION](data/experiments/h60_signal_objectives_v11/NEXT_QUESTION.md)为准，本次上传不执行研究或继续调阈值。
- 工程仍需Paper TWS/Gateway登录、隔离身份/预算、实时报价权限、精度及公司行动确认。当前年度模型不能直接产生2026信号；自动公司行动账本、保护撤换窗口、真实回报时序及长期断线恢复待验证。
- 未调用17/18，稳定实验身份/运行时间混用的旧问题未改；未重算H20/H60百分位集成，理论同分浮点问题未改，均未污染本轮单H60结果。

## 大型材料与复现

原大文件仍在`M:\ml项目\data\...`，精确路径、大小、SHA256、实验及命令见[旧大文件清单](review_upload/large_artifacts.csv)。[独立ZIP清单](review_upload/bundles.json)对应本地`M:\ml项目\review_bundles\20260909\`，每个不超过450MiB，保留原相对路径。v5/v6/v7模型、预测、行情没有删除、重训或用新数据替换。

v8产物在`data/experiments/h60_risk_execution_v8/`：39次逐笔/每日、全部失败方案、SQLite账本和故障记录；预测复用原v5 all_scores.csv，对应身份在INPUT_IDENTITY。文件的大小/SHA256见[ARTIFACTS](data/experiments/h60_risk_execution_v8/ARTIFACTS.csv)。旧审阅ZIP只代表首次上传；v8—v11本次进入Git或额外审阅ZIP的范围以新上传清单为准。
