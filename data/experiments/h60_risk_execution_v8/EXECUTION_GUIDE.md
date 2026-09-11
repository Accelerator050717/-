# H60模拟执行的当前边界与命令

当前研究候选未满足30%年化收益门槛，工程配置仅为测试。无实盘执行模式。旧`23_replay_execution.py`及m16账本保留，本轮入口使用已识别的H60模型。

## 已实现的共享路径

`score_feature_snapshot`读取固定顺序X并用哈希匹配的年度H60模型评分；`scheduled_weights`、`reduction_weights`、`DrawdownState`与`protection_floor`同时供研究和`H60Runtime`调用。`plan_open_cycle`先核对真实/虚构券商事实，撤单后重新核对再计算目标；实际止损若在撤单期间成交，会先更新持仓和冷却，避免同日买回。

`H60Executor`在SQLite事务中把批次、意图和策略时钟一起保存；`OrderState`负责成交ID去重、部分成交和状态合并。提交前先持久化attempted，超时或崩溃后以orderRef/permId、成交、佣金、现金和实际仓位核对，未知提交绝不重发。已提交买单保留剩余资金；撤单未确认的卖单保留可卖数量。计划卖单完成前不提交新买单。

保护仅覆盖已实际成交的本策略股数；部分买入增加相应数量的保护，保护卖单与其他未完成退出的合计数量不得超过持仓。无其他退出挂单时，保护数量等于实际持仓。调整保护/计划减仓采用“撤单—确认并核对—再提交”，**存在等待期间保护暂缺的窗口**，并非已解决原子OCA/撮合或停牌风险。失联时不能伪装保护已调整；未知状态不新开风险。

成交时戳决定止损冷却起点，不用重启收到旧回报的时间重新计算5天。部分建仓期间保护成交时，协调器撤销该股票的买入余单，等待确认期间保持预留，先核对撤单与成交竞争。已提交的批次在进程重启后复用原意图；同一决策不会再次生成订单。初始化标记防止丢失数据库后自动重置资金。外部持仓不被收编，外部现金变动会触发核对阻塞。公司行动自动账本尚未完成，未知事件直接阻断新意图。

## 本地可运行检查

在`M:\ml项目`下运行：

```powershell
.\.venv\Scripts\python.exe 42_evaluate_h60_risk_fixes.py
.\.venv\Scripts\python.exe 43_run_h60_simulation.py
.\.venv\Scripts\python.exe 44_test_h60_recovery.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe 43_run_h60_simulation.py --check-ibkr
```

42已有完成记录会核对计划/源文件哈希后保留结果，不重训；原计划有本轮截止时间，未完成实验不能在新会话偷偷追加。43默认用真实历史H60信号/历史风险输入与**虚构未复权报价/虚构成交**，16个交易日逐日持久化，完整重跑新增意图和成交均应为0。44通过三个真实操作系统子进程、两次刻意异常退出检验恢复；券商和资金仍完全虚构。

最新版产物为`execution_v5/`、`execution_faults_v2/`和`ENGINEERING_STRATEGY_MANIFEST_v5.json`。工程迭代记录保留：首版`execution/`；v2增加共享协调器、成交时点冷却与撤单竞争后重算目标，其重跑被时间核对拦截；v3先跳过已完成日期，修复重跑时钟回退；v4加入止损触发后撤销买入余单；v5核对清单与实际预算一致，并按阻塞行情请求完成后的时刻判断报价新鲜度。旧版源码分别保留在各`source_archive/`。这些工程迭代不是新策略候选，不改变39次研究结果。`execution_faults_v2/`对应当前未改动的核心账本/状态机，完整来源哈希保留。

虚拟工程预算10,000 USD，对应上述虚拟清单；未启用的paper工程清单是`PAPER_ENGINEERING_MANIFEST.json`，预算1,000 USD及独立策略ID。清单与执行配置预算不同会在任何券商调用前拒绝，避免把另一初始权益当作回撤分母。两个清单都是2025工程模型身份，均不是2026终测/部署候选冻结。

## IBKR的真实状态与最少用户操作

本轮只读检查保存在`IBKR_READINESS.json`；检查常用paper端口7497/4002，未发现监听，未完成握手、未确认paper账户、未测试行情权限，真实paper订单/成交0。不把离线测试或虚构SDK回报称作IBKR联调通过。

要解除当前连接阻塞，需要用户在本机启动并登录**Paper** TWS/Gateway，开启本地Socket API并确认端口。配置模板是`config/h60_paper.example.json`；复制到被Git忽略的`config/h60.paper.local.json`，确认独立paper预算（本适配器最高1000 USD、新买单最高250 USD）、非零clientId、已有策略股票列表和当天公司行动检查状态。期望DU账户仅通过`QUANT_IBKR_EXPECTED_ACCOUNT`本地环境变量读取，不写入模板或报告。端口号和readonly参数都不是paper身份的证明。

配置明确后可运行**只核对、不新下单**的恢复入口：

```powershell
.\.venv\Scripts\python.exe 43_run_h60_simulation.py --paper-reconcile config/h60.paper.local.json
```

`IBKRPaperAdapter`含受限LMT买卖/STP保护接口，实际报单流程使用相同`plan_open_cycle → submit_next → reconcile`；阻塞的行情请求完成后，调用方须更新UTC时钟再交给协调器/提交函数。现在没有后台循环或自动启动服务。没有可用于2026的已冻结有效模型和实时特征输入，因此未提供“启动即交易”的命令。paper联调还需验证真实回报时序、行情/数量精度、佣金/结算、公司行动及撤单保护窗口，不能通过把当前日期填进旧模型清单绕过。

研究估值是调整OHLC与碎股代理；执行仅接受券商实时未复权bid/ask及整股数量（支持情况从合约详情核对），不接受调整历史价格作为订单报价。订单报回分阶段、每个部分成交有独立execId，详见[IBKR Execution](https://www.interactivebrokers.com/docs/tws-api/ref/execution)；paper撮合限制见[IBKR Paper Trading](https://www.interactivebrokers.com/docs/tws-api/doc/notes-limitations/limitations/paper-trading)。当前本地测试不验证这些真实服务行为。
