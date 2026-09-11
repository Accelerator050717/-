# H60 → LEAN：第一阶段迁移

本目录让已保存的 H60 预测通过 LEAN 订单与持仓账本执行，核对它是否保留原研究行为。研究结论仍是 `REJECT_NO_2026`。实际运行状态、差异及剩余事项见 [本轮报告](../data/experiments/lean_migration_v10/REPORT.md)。

## 运行顺序

在 `M:\ml项目` 使用原 `.venv\Scripts\python.exe`：

```powershell
.\.venv\Scripts\python.exe 47_prepare_lean_migration.py
```

该命令核验原始输入 SHA256，导出 `data/experiments/lean_migration_v10/input/package.json` 和本地阶段数据。重复运行只核验相同输入，不覆盖历史产物。LEAN 引擎运行命令见 `tools/lean_runtime/README.md`；成功运行后：

```powershell
.\.venv\Scripts\python.exe 48_compare_lean_migration.py --run-dir <本次引擎输出目录>
```

不通过直接报告 FAIL，不调整策略或容差来追平结果。引擎调试各次输出保留在不同目录。

## 数据怎么流动

1. `47_prepare_lean_migration.py` 读取原 v5 预测与行情，核对十份年度模型身份和标签成熟边界。它不训练模型。
2. `main.py` 的 `H60Phase` 把本地日线价格按 OPEN、RANGE、CLOSE 推送给 LEAN。
3. `decision.py` 使用原策略函数计算目标；以 LEAN 的实际持仓和现金计算买卖数量。它本身不维护一份替代成交账本。
4. `main.py` 提交引擎订单，接收 `OrderEvent`，记录引擎扣费、持仓与现金。
5. `48_compare_lean_migration.py` 将真实引擎输出与保存的 v8 账本比较，并从成交另行重建现金、股票数量和收盘权益。

`input/shared` 是本次导出的原策略代码快照，受 SHA256 检查；修改原策略不会悄悄改变已登记的迁移输入。原策略源码仍保留在项目根目录，不在这里重新维护第二套规则。

## 必须区分的价格口径

- 调整 OHLC + 碎股单位是原研究收益代理，初始 NAV 1 对应本次虚拟 10,000 USD。
- RANGE 的价格来自真实历史日线 Low；中午 12:00 是人工事件顺序，不是最低价实际发生时间。不能从本次记录推断真实盘中走势。
- 自定义成交/费用模型有意复现原日线假设。引擎账本是真的运行结果，但成交属于模拟，不是 IBKR 回报，也不是 LEAN 原生美股成交模型的验证。
- LEAN 通用图表/统计可能采样人工 RANGE 价格；它不表示实际盘中回撤。本轮指标统一从 `daily.csv` 的每日 CLOSE 引擎权益计算，原始引擎图表和统计仍保留供检查。
- 分红和拆股已反映于该调整价格代理，不能再记一次现金或股数。原生未复权美股、公司行动和真实券商数量精度需要下一阶段单独适配。
- 15% 止损是给定触发规则，跳空时仍按更差价格成交，不能保证最多只亏 15%。

## 范围

固定 30 股、原 H60 排序、成本及调仓日历；没有新增模型、自动寻参或杠杆。实时模式强制拒绝。没有券商登录信息，没有订单接口启用，没有读取 2026 行情。当前收益不足不会因迁移而变成验证成功。

参考：[LEAN 开源引擎](https://github.com/QuantConnect/Lean)、[预计算预测](https://www.quantconnect.com/docs/v2/writing-algorithms/importing-data/streaming-data/precomputed-ml-predictions)、[自定义成交模型](https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/trade-fills/key-concepts)。
