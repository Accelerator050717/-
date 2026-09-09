# 最新源码审阅入口

本次只上传既有项目供下一轮任务规划，未训练、未改变策略、未下载行情、未启动交易。以下依据上传时的实际源码和保存记录整理；收益、测试和连接状态是已有结果，本次没有重新运行验证。

## 当前进度与模型身份

- 30只美股、SPY基准；价格/ETF输入、SEC财报和事件特征、多年度滚动训练、成本回测、离线执行与故障测试均有源码及记录。
- 研究基线为 **H60 Ridge＋SPY波动率仓位**。年度训练至Y−2，Y−1验证，Y年评分；标准化只在训练集拟合，未来标签按实际出场日剔除跨段样本。不是已经批准上线的模型。
- 最近v6/v7两版止损与恢复策略均未通过各自记录的盈利保留要求，未替换研究基线。最新状态：[strategy_status.json](data/experiments/strategy_reflection_20260909/strategy_status.json)。`deploy_eligible=false`是研究记录，尚未接入券商运行时开关。
- 最新H60年度文件：`data/experiments/extended_history_v5/2025_ridge_h60_price.joblib`，SHA256 `2c19480278678e72fb9303e4f615737abccfa2c7dac883893af36390c2365ece`。2016—2025模型及原始训练记录完整保留，模型二进制见审阅ZIP。
- **工程回放冻结模型与研究基线不同**：[23_replay_execution.py](23_replay_execution.py) 固定使用 `data/experiments/auto_research_45m_v1/2025/m16_elastic_rank.joblib`，SHA256 `5dc11e8e3280f29669aa990fac5e4dd264c683a08c64538add7369791485bea4`。它仅演练2025-01-02至02-14的本地历史执行，不表示选中了实盘模型。

## 优先阅读

| 主题 | 源码与记录 |
| --- | --- |
| 最新反思、失败方案和主要对照 | [完整反思与结果](data/experiments/strategy_reflection_20260909/REFLECTION_AND_RESULTS.md)、[10次训练明细](data/experiments/strategy_reflection_20260909/TRAINING_DETAILS.md)、[结果摘要](data/experiments/strategy_reflection_20260909/SUMMARY.json) |
| H60与较长历史 | [35](35_extend_historical_diagnostic.py)、[36](36_check_extended_history.py)、[20次训练](data/experiments/extended_history_v5/TRAINING_DETAILS.md)、[参数计划](data/experiments/extended_history_v5/plan.json) |
| 波动率仓位 | [research_backtest.py](research_backtest.py)、[34](34_research_risk_controls.py)、[v4计划](data/experiments/risk_controls_v4/plan.json) |
| ATR止损、组合清仓及恢复 | [robust_strategy.py](robust_strategy.py)、[profit_priority_strategy.py](profit_priority_strategy.py)、[v6设计](data/experiments/robust_strategy_v6/DESIGN.md)、[v7设计](data/experiments/profit_priority_v7/DESIGN.md) |
| 最近训练与评估入口 | [38](38_train_robust_strategy.py)、[39](39_evaluate_robust_strategy.py)、[40](40_evaluate_profit_priority.py)、[41汇总](41_summarize_strategy_revision.py) |
| 特征、标签及统计筛选 | [research_features.py](research_features.py)、[research_horizons.py](research_horizons.py)、[research_evaluation.py](research_evaluation.py)、[28及固定参数](28_train_multihorizon.py) |
| 财报可用时间与事件 | [fundamental_features.py](fundamental_features.py)、[research_event_features.py](research_event_features.py)、[21](21_prepare_fundamentals.py)、[26](26_prepare_event_features.py) |
| 离线执行、订单状态、IBKR只读 | [offline_execution.py](offline_execution.py)、[execution_order_state.py](execution_order_state.py)、[ibkr_readonly.py](ibkr_readonly.py)、[23](23_replay_execution.py)、[24](24_run_offline_cycle.py)、[29](29_check_ibkr_readiness.py)、[tests](tests) |
| 前轮完整研究 | [v1报告](data/experiments/auto_research_45m_v1/RESEARCH_REPORT.md)、[v2报告](data/experiments/automation_research_v2/RESEARCH_AND_EXECUTION_REPORT.md)、[v3主报告](data/experiments/continuous_research_2h_v3/FINAL_REPORT.md) |

所有各轮报告、设计、训练参数/边界、模型选择和体积合理的结果记录均保留在Git；大文件的缺失不是实验未做，见下方逐文件清单。

## 环境与运行顺序

Python 3.12.2；原解释器 `M:\ml项目\.venv\Scripts\python.exe`。依赖版本见 [requirements.txt](requirements.txt)。本次未重新安装。`.venv`不上传；新环境后续可使用 `py -3.12 -m venv .venv`、`.\.venv\Scripts\python.exe -m pip install -r requirements.txt`。

**本轮审阅无需运行研究脚本。** 先读本索引和最新报告；如要读大文件，将审阅ZIP独立解压到克隆仓库根目录，保留`data/...`路径，再按清单比对SHA256。只读预览示例：

```powershell
.\.venv\Scripts\python.exe tools/inspect_review_artifact.py "data/experiments/extended_history_v5/all_scores.csv"
```

既有生成依赖顺序：03—13教学/行情/初始模型 → 14—20价格与ETF研究 → 21—22财报研究 → 26—28事件与多周期研究 → 34仓位诊断 → 35—36扩展历史 → 38—39 v6 → 40 v7 → 41最新汇总。具体输入与命令见 [材料说明](review_upload/ARTIFACTS.md) 和原源码；本次均未执行。

许多脚本缺少缓存时会训练、下载或重写输出；22/28/35等还保留原研究时限。23/24会修改本地模拟账本，29会探测本机券商会话。它们不是“只读审阅”命令，不要为浏览仓库运行整个流程。[.env.example](.env.example)只列已有只读身份核验变量，项目不会自动加载该文件。

## 当前收益与估值口径

同一2016-01-05至2025-12-29、普通买卖单边10bp、止损额外10bp的保存结果：旧H60波动率仓位年化27.46%/收盘最大回撤−27.69%；v6完整规则5.96%/−17.16%；v7完整规则11.32%/−15.37%。这是反复使用的开发区间，非独立终测。此前98条候选的全部统计门槛通过数仍为0；不能把后续风险诊断当成已通过该统计检验。

价格为供应商调整OHLC收益代理，碎股、零息现金、无杠杆，包含建仓/末次清仓成本。2020—2025旧报告的34.77%/−20.75%使用另一时间范围和开盘估值，不能直接拼接比较。离线工程回放保留最终持仓，未计最终强制清仓费，也不能与策略回测NAV混用。日线止损触价成交、滑点和现金规则均是假设，止损价格不保证实际成交价。

## 2026、IBKR与未完成事项

- 现有市场快照请求`end=2026-01-01`且不含该日；2026市场行情未进入现有训练/策略比较。本次只读取原文件字节作清单与归档。SEC原始全量快照包含2026后续事实，历史特征按`filed < 观察日`过滤，不能声称所有2026信息从未读取。
- 最近保存的IBKR检查时间为 **2026-09-09 05:54:14 UTC**：[latest.json](data/broker_readiness/latest.json)。结果`not_connected`、未握手、未确认paper身份、订单0。本轮没有重新探测，因此这不是实时连接状态。
- 最近[历史回放记录](data/replays/offline_v1/completion.json)累计42笔**本地虚拟成交**，重跑新增0；没有券商模拟或真实成交证据。IBKR代码目前是只读探测，订单状态模块仍为原型。
- [49项测试记录](data/experiments/strategy_reflection_20260909/TESTS.json)来自上一轮虚构行情/故障检查，本次未复跑；不能替代券商集成测试。
- 未解决：历史股票池与退市覆盖、公告真实可用时间、独立前瞻验证、真实报价/公司行动现金账本、券商paper联调与重连/成交核对，以及实盘账户、资金和损失约束。下一轮任务应由审阅结果决定。

## Git外的大型材料

原文件仍在 `M:\ml项目\data\...`，没有删除、重训或用新行情替代。精确路径、字节数、SHA256、对应实验、原生成入口、只读命令与ZIP映射见 [large_artifacts.csv](review_upload/large_artifacts.csv)。[bundles.json](review_upload/bundles.json)列出每个独立ZIP的位置、大小与SHA256；ZIP放在本地 `M:\ml项目\review_bundles\20260909\`，不进入Git，每个不超过450MiB。

各ZIP使用正常独立ZIP格式，保留原相对路径，可分别解压；一个实验的依赖可能跨包，完整恢复应解压清单列出的全部包。Git保留原行情元数据和实验参数，包内文件与清单逐项哈希核对；完整恢复覆盖当前v5/v6/v7及主要历史对照和冻结回放材料。仓库不含真实凭证、虚拟环境或缓存。审阅此私有仓库需要已获授权的GitHub连接。
