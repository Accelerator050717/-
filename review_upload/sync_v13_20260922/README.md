# v13 连续资金风险状态：审阅材料同步

基线提交为 `3d02318a10266f91615714a77673d1d5f425f988`。本轮继续使用原 A 的模型和预测，新增模型拟合为 0。研究范围是“策略指定资金”的持续单位净值高水位，不代表已覆盖整个券商账户。最终实验结论以 [v13 报告](../../data/experiments/continuous_fund_risk_v13/REPORT.md)、[固定计划](../../data/experiments/continuous_fund_risk_v13/PLAN.md) 和 [审阅索引](../../REVIEW_INDEX.md) 为准。

运行时 HEAD 仍是上述基线，新增 v13 源码当时位于工作区；实际生成源码身份由 `EVALUATION_IDENTITY.json` 中的逐文件 SHA256 固定，并随本次普通提交上传。不能从基线提交号推断新脚本已存在，也不将上传后的提交号改写为原生成身份。

`tools/prepare_v13_sync.py` 只读取已经保存的文件、生成清单和增量 ZIP；不会训练、回放、获取行情或联系券商。应等全部实验与 SQLite 写入完成后运行。旧清单、旧成果和原排除规则保持不变，只在 `.gitignore` 追加本轮精确路径。

## 清单与 Git 外材料

- [inventory.csv](inventory.csv)：本轮新增/修改源码、测试、说明及全部 v13 产物的准确路径、大小、SHA256、生成入口和只读检查命令。
- [large_artifacts.csv](large_artifacts.csv)：留在本地的大型明细、SQLite 数据库、作用域标记及恢复所需侧文件；每行指向实际所在 ZIP。
- [bundles.json](bundles.json)：每个 ZIP 的完整路径、字节数、SHA256 和成员验证结果；**ZIP 本身不上传 GitHub**。
- [inventory_summary.json](inventory_summary.json)：数量、原清单哈希及打包时的基线提交。

每包为可独立解压的普通 ZIP，不是分卷：完整未压缩成员合计不超过 400 MiB，压缩后不超过 450 MiB；数据库与相应作用域标记/侧文件分组放在同一个包。每个成员在压缩后再次核对 SHA256，并确认源文件没有在打包过程中变化。大型成交、持仓和目标仓位沿用旧排除规则；计划、报告、汇总、每日权益和必要状态样例保留在 Git 中。

首次未完成的 `record_only/` 记录与 `PRE_FREEZE_IMPLEMENTATION_NOTES.json` 同样保留，不拿它冒充完成证据；完成证据读取报告指定的 `record_only_final/` 与 `engineering/final_verification/`。本轮包没有自动修复、清空或重新生成这些旧文件。

## 恢复依赖

将本轮 ZIP 解压到同一项目根目录，保持压缩包内相对路径。它们只保存 v13 新增产物。完整复核仍需以前保存的原 A 行情快照、面板、2016—2025 年度模型、预测及 v8 控制结果：见 [原 ZIP 清单](../bundles.json)、[最初材料说明](../ARTIFACTS.md) 和 [v8—v11 增量包](../sync_v8_v11_20260911/bundles.json)。对应冻结身份见 v13 `INPUT_IDENTITY.json`。

v12 B 模型没有升级，本轮不依赖它们进行预测。缺少原 A 文件时，应从原快照恢复并核对哈希，不能下载当前行情或重新训练替代原产物。每个清单条目提供 `tools/inspect_review_artifact.py` 的只读查看命令；SQLite 以原字节保留，查看工具不尝试打开数据库或触发自动恢复。

## 证据边界

这里的持久化执行验证只使用虚构 `VirtualBroker`。没有真实或 paper 订单，没有前瞻业绩，没有使用 2026 行情，也没有升级 LEAN。原执行器仍不支持在旧账本中直接更换 manifest，外部资金/公司行动适配和真实 paper 入口仍需独立完成。资金账本支持的事件不等于券商现金归属已经接通。

提交后由主任务普通 push 并核验完整远端 SHA；不将尚未产生的提交哈希写入本清单冒充验证结果。
