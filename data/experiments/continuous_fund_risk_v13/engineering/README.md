# v13 持续资金状态与执行检查

这里所有报价、成交、股票数量、收益及故障均为 **虚构工程场景**，只使用本地 `VirtualBroker`。没有真实账户、paper 账户或前瞻收益证据。

## 检查范围

`h60_fund_risk_bridge.py` 把原 `H60Executor` 已核对的成交 ID、实际数量、成交时刻和佣金写入持续资金账本；同一个 SQLite 事务记录已处理事件与完整执行/运行状态检查点。资金范围显式绑定 `scope_id`、`execution_strategy_id`、USD、股票范围和初始指定预算，不包含券商账户其他交易、持仓或负债。

两个 SQLite 文件不是跨库原子事务。若执行账本先提交后进程退出，重新启动必须核对 `VirtualBroker` 的事实，再重放尚未入资金账本的事件；未完成时，检查点摘要不一致阻止新增风险。已经入账的成交/佣金 ID 不会重复入账。没有资金状态时，不能把已有执行历史接入新建资金账本来重新设高点。

同一套 `GlobalRisk.cap` 对离线目标和新增买单设置仓位上限。HALTED/REVIEW_LOCKED 不准新增买入。止损部分成交后，原 v8 的撤销买入余单路径继续执行；等待撤单确认时保留资金与可卖股数预留。触发暂停不代表仓位已卖出。

## 实际保存的检查结果

- `final_verification/CONTINUITY_REPORT.json` 是当前最终源码的结果；根目录同名报告是实现期间首次运行，保留原记录。
- 三条运行路径：不中断、资金事务之前 `os._exit(73)`、资金事务之后 `os._exit(74)`。后两条通过新子进程重新启动。
- 三条路径的目标、订单/成交、现金、实际持仓、H60Runtime 状态、单位净值、高水位和风险模式完全相同。
- 虚构买入 3 股后跳空至 70，仅有 1 股保护卖单成交：仍保留 2 股 AAPL；实际单位净值为 0.990963；不能把暂停写成全部成交。无关 `FOREIGN` 持仓 17 股保持不变。
- `tests/test_v13_execution_continuity.py` 还检查源状态与检查点之间的差异、提交超时不重发、原运行时目标一致性、不同策略身份隔离、未知资金变动阻止新增风险、报价改变先重新估值、控制器上限及止损后撤买入余单。

## 复现命令

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -p test_v13_execution_continuity.py -v
.venv\Scripts\python.exe 56_check_fund_continuity.py --output data/experiments/continuous_fund_risk_v13/engineering/new_check
```

第二条命令必须使用新的输出目录，避免覆盖已有证据。SQLite、作用域标记和完整检查点样例与 JSON 输出一起保留本地，按审阅材料清单打包。

## 明确限制

持续资金账本允许同一资金范围登记新的模型版本，保留高水位。原 `H60Executor` 仍拒绝原地更换冻结 manifest；本轮没有把这个拒绝绕过。需要实际换模型时，执行适配器的交接与审批边界仍须另行实现。

现有执行器初始预算不支持外部现金流、分红或利息自动归属；本轮账本独立支持并测试它们，旧执行器遇到不明现金仍阻断，不能把账本功能称为券商现金适配已完成。旧时刻才到达的事实、佣金更正及长断线补账仍需要显式重建/复核，不自动重设资金状态。

完整工程覆盖限于本地虚构场景。原生报价/公司行动、真实 paper 运行入口、部分成交期间持续保护、保护撤换窗口和长期断线补账仍未完成；LEAN 仍是既有历史研究代理。

## 后续补充：自动控制状态推进

此前 bridge 只记录调用方提供的风险模式，独立审阅已如实指出这个缺口。新增独立 `h60_fund_control_cycle.py` 后，`close` 在明确的美东收盘时点核对实际持仓、现金及成交，调用同一个 `GlobalRisk.observe`；`resume_open` 仅在后续符合条件的开盘调用 `try_resume`，要求上一已完成交易日趋势、计划调仓日、原周期状态允许、实际空仓且无未完成订单。它不发送或撤销任何订单。

完整 runtime manifest 的摘要必须匹配执行账本冻结身份，日历和调仓观察日期直接取自该 manifest，避免周期暂停的日期索引与累计控制使用不同起点。成交事件、实际估值、推进后的风险模式和控制决策游标在一个资金账本事务中保存；重启重复同一收盘只刷新对账检查点，不再触发一次暂停或重设高水位。相同决策出现冲突事实会阻断。

新增证据保存在 `automatic_control/`，复现命令：

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -p test_v13_control_cycle.py -v
.venv\Scripts\python.exe tools/check_v13_control_cycle.py --output data/experiments/continuous_fund_risk_v13/engineering/new_automatic_control
```

这仅补齐本地虚构适配器的自动模式推进，不把原先未接通的时点改写成已经完成。旧 `CONTINUITY_REPORT.json` 及冻结历史实验源码未改变。

**估值口径仍有明确差别：**资金账本高水位记录所有可信估值，历史固定实验按收盘高水位评估。开盘或盘中暂创新高，可能让工程适配器更早触发回撤控制。新模块拒绝在 NORMAL/REDUCED/RECOVERY 的普通持仓开盘走恢复入口，但没有抹除账本此前的真实高点。因此本轮不宣称完整历史交易路径与实际执行估值完全一致；统一生产估值与控制节奏仍是部署前缺口。
