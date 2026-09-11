# LEAN 迁移第一阶段：固定研究口径已通过

完成日期：2026-09-11 UTC（洛杉矶 09-10）。原项目成果保留；未提交或推送 Git。

**实际 LEAN 引擎已跑完原 H60 主候选的十年历史，逐笔成交、仓位、现金、费用及收盘权益通过预登记容差。** 这是研究代理的迁移成功，尚未迁移到原生美股/券商执行，也没有提升候选的盈利结论。

## 原结果与实际引擎结果

唯一比较为 v8 `stop_on_soft_off_cost10`，2016-01-05—2025-12-29；初始 NAV 1 映射为虚拟 10,000 USD。原排序、30 股股票池、最多 8 股、名次 12 保留、集中度约束、SPY 波动缩仓、15% 保护、20% 硬暂停及恢复保留；软减半关闭。手续费 10 bp，止损额外滑点 10 bp，现金收益 0，不借款。

| 指标 | 原 v8 账本 | LEAN 实际研究回放 |
|---|---:|---:|
| 交易日 | 2,511 | 2,511 |
| 成交笔数 | 4,951 | 4,951 |
| 最终权益（USD） | 39,939.27415271533 | 39,939.27415271494 |
| 全期累计净收益 | 299.3927% | 299.3927% |
| 净复合年化 | 14.8807% | 14.8807% |
| 收盘最大回撤 | 17.7389% | 17.7389% |
| 年化波动 | 12.5901% | 12.5901% |
| 平均仓位 | 69.7737% | 69.7737% |
| 普通手续费总额（USD） | 2,103.34875 | 2,103.34875 |
| 止损退出 / 其中跳空 | 146 / 33 | 146 / 33 |
| 非计划减仓买单 | 0 | 0 |
| 末次清仓 | 是 | 是 |

最大逐日权益差 `5.60e-10 USD`，最大现金差 `2.26e-9 USD`，最大股数差 `2.86e-11`，最大成交价差 `5.68e-14`。均远低于事前阈值，未放宽容差。普通手续费之外，止损滑点通过更差成交价计入净收益，不要把手续费列误作全部成本。

真实引擎成交分解：计划调仓 4,331 笔，日常只减仓 466 笔，跳空止损 33 笔，日内日线代理止损 113 笔，末次清仓 8 笔。目标表 595 行，评分观察日志 502 行。

核心证据：[完整比较](engine_runs/h60_full_01/PARITY.json)、[逐项核对](engine_runs/h60_full_01/parity_checks.csv)、[每日账本](engine_runs/h60_full_01/daily.csv)、[成交](engine_runs/h60_full_01/trades.csv)、[原始订单回报](engine_runs/h60_full_01/order_events.csv)、[年度收益](engine_runs/h60_full_01/yearly_close_equity.csv)、[运行退出与身份](runtime/h60_full_01.run.json)。完整引擎回放约 61 秒，进程退出码 0；不是仅运行 Python 模拟器得出的结果。

## 风险恢复的独立工程场景

原主候选这十年没有触发组合硬暂停，单靠历史对齐不能验证该分支。另用 8 个明确虚构的 SIM 证券、60 个虚构交易日，实际运行同一个 LEAN 适配器：40 笔引擎成交，退出码 0。

- 虚构 50% 开盘跳空后，2019-03-29 触发硬暂停。
- 2019-05-02 满足冷却、趋势及计划调仓条件后恢复，目标仓位先 40%，恢复期后 80%。
- 最终清仓，现金 5,977.642343359563 USD；与测试契约的差约 `4.27e-11 USD`。

[实际引擎核对](engine_runs/synthetic_risk_01/SYNTHETIC_CHECK.json)、[事件记录](engine_runs/synthetic_risk_01/events.csv)、[预先生成的虚构契约](synthetic_input/EXPECTED_SYNTHETIC.json)。这不是另一段市场业绩。该冲击也说明：20% 是暂停触发阈值，跳空可能在系统响应前把损失带到阈值以外，不能当成最大损失保证。

另有 [10 个虚构契约测试](unit_tests.txt)，覆盖重复/乱序事件、缺失/非有限行情、未来评分和风险数据不影响当前订单、跳空时只减不增、止损后不在同一开盘重开、暂停/冷却/恢复。完整 Python 控制器回归另存 [这里](synthetic_controller_regression/RESULT.json)，它与真实 LEAN 引擎证据明确区分。

## 实现与真实运行条件

- [47](../../../47_prepare_lean_migration.py) 导出原输入并核验 SHA256；[main](../../../lean_migration/main.py) 处理 LEAN 事件、订单和回报；[decision](../../../lean_migration/decision.py) 调用原共享策略函数；[48](../../../48_compare_lean_migration.py) 独立重建账本并比较；[49](../../../49_summarize_lean_migration.py) 汇总已存在结果。
- 原 `profit_priority_strategy.py`、`research_backtest.py`、`robust_strategy.py` 和 v8/v9 研究结果没有因迁移而改写。
- 实际新增训练 **0 次**。复用原 v5 十个年度 H60 Ridge 预测集合；十份模型身份/81 特征顺序/alpha=100/solver=svd/标签成熟边界见 [INPUT_IDENTITY](INPUT_IDENTITY.json)。没有把旧 2025 模型当成 2026 部署模型。
- 本机 Docker Desktop 的 socket 故障未通过重置系统解决；改用已安装的 .NET 10.0.400、CPython 3.12.2 和现有虚拟环境，直接编译运行开源引擎，没有使用付费 CLI 或云账户。
- 引擎上游提交 `8ee075a39918f2df6fe9e0a5944e366fb60d10dc`，**加一份本地 Python 退出兼容补丁**。真实源码/补丁/二进制身份见 [运行环境](runtime/RUNTIME_IDENTITY.json) 和 [补丁](../../../tools/lean_runtime/patches/native_shutdown_gil.patch)，不是未经修改的上游二进制。
- 使用引擎已有 `data-feed-workers-count=1` 避免 Windows Python.NET 初始化时的锁冲突；退出补丁只抑制一个由解释器关闭过程管理的 GIL 守卫终结器，仍完整执行 Python shutdown。没有修改订单、费用、行情或策略逻辑。

从固定源码重建和新建一次独立输出的具体命令见 [运行说明](../../../tools/lean_runtime/README.md)；已有结果只需执行：

```powershell
.\.venv\Scripts\python.exe 47_prepare_lean_migration.py
.\.venv\Scripts\python.exe 48_compare_lean_migration.py --run-dir data/experiments/lean_migration_v10/engine_runs/h60_full_01
.\.venv\Scripts\python.exe 49_summarize_lean_migration.py
```

已保留失败调试记录：smoke02 数据线程死锁；smoke03 手续费估算调用适配问题；smoke04 结束属性命名问题；smoke05 策略完成但原生进程关闭崩溃；smoke06 策略和退出均正常。这些是工程调试，未改变候选或搜索交易参数。

## 必须保留的边界与问题

1. **这是调整价格/碎股/日线止损研究代理。** OPEN/RANGE/CLOSE 的时钟为人工排序；RANGE 引用原日线 Low，不是中午实际报价。没有证明原生美股订单、停牌、真实盘中成交或公司行动处理已经完成。分红/拆股已包含在原调整收益代理内，不能再记一次。
2. LEAN 通用统计可能采样 RANGE 的人工价格。本报告指标完全来自每日 CLOSE 的实际引擎权益。全量日志中还捕获了一次可选 `PortfolioMarginUsageAnalysis` 并发枚举错误，以及缺少可选利率文件和 1e-12 数量精度提示；原始日志保留，未用这些通用统计替代收盘核验。可选并发分析问题尚未修复，不影响已逐笔重建的账本，但不能宣称引擎日志零异常。
3. 当前入口不包含 v8 虚构执行器的持久化意图/重启恢复协议；它是历史回放。真实 IBKR paper 回报 **0**，真实资金订单 **0**，前瞻业绩 **0**。没有连接券商。
4. 本轮没有读取、下载或评估 2026 行情；没有新增策略选择或独立验证。股票池存续偏差、历史/退市数据库授权仍未解决，v9 本地接入口保留。
5. 年化 14.88% 未达到用户最低 30% 的收益目标；`REJECT_NO_2026` 不变。迁移通过不等于盈利通过。

下一步唯一优先工作：**建立 LEAN 原生美股数据与公司行动适配，把研究收益代理转换成可交易价格和数量，再用固定案例核对。** 该步骤通过前，不把当前 H60 代理入口接到 IBKR。盈利信号的改进另需预登记研究，不能借迁移挑选历史结果。

外部可重建运行时位于 `M:\quantconnect-lean-runtime\Lean`，诊断工具位于 `M:\quantconnect-lean-runtime\diagnostics`，未放进本项目 Git。原模型和行情仍在原路径；新输入包、所有回放和失败记录位于本实验目录。详见 [文件清单](ARTIFACTS.csv)。
