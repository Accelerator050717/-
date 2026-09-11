# v8—v11源码与实际结果同步

本目录是2026-09-11 UTC的增量上传记录，目标为私有仓库`Accelerator050717/-`的`main`。同步前本地与远端均为`9d98008d72f096c2c1fa33a998f000fe62c48bb5`，没有远端新历史；只整理、提交和推送当前成果。没有训练、运行回测、生成新行情或连接交易账户。

## 阅读入口

- [最新REVIEW_INDEX](../../REVIEW_INDEX.md)：真实进度、LEAN预测到订单/成交的数据流、paper与前瞻证据边界。
- [v8报告](../../data/experiments/h60_risk_execution_v8/FINAL_REPORT.md)：风控修复、固定39条比较、共享H60执行入口及虚构恢复测试。
- [v9报告](../../data/experiments/universe_delisting_v9/REPORT.md)：本地历史股票池/终止接口、公开ATVI案例、许可和覆盖限制。
- [v10报告](../../data/experiments/lean_migration_v10/REPORT.md)：真实LEAN引擎的历史研究代理、64项一致性检查、人工阶段和成交模型限制。
- [v11报告](../../data/experiments/h60_signal_objectives_v11/REPORT.md)：30次既有训练、21条新增固定回放、全部失败方案。上述数字是上传前的研究成果，本次新增训练/回放均0。

## 哪些内容进入Git

全部当前业务源码、42—51入口、执行模块、测试、依赖、模板、LEAN算法/成交模型、原生运行及比较脚本。v8—v11的设计、计划、身份、模型JSON合同、训练明细、系数、报告、完整结果汇总、年度/压力、每日权益、故障与一致性检查及合理大小的运行配置均保留。v9全部公开案例、LEAN小型虚构输入也保留。

[inventory.csv](inventory.csv)列出当前修改/新增源码及v8—v11的每个实际文件、字节数、SHA256与`git/large`分类。它不重列所有已提交的旧项目文件，也不包含自身上传元数据，避免递归哈希。[PRE_PUSH_CHECKS.json](PRE_PUSH_CHECKS.json)记录实际暂存完整性检查；依赖快照见[DEPENDENCIES.json](DEPENDENCIES.json)。

## 哪些材料仍在本地

[large_artifacts.csv](large_artifacts.csv)逐文件列出准确路径、大小、SHA256、对应实验、原生成入口和只读命令。沿用原规则：模型二进制、完整预测、较大标签表、逐笔/仓位/目标明细、实际行情阶段CSV等不直接提交Git。恢复SQLite与标记成对保留；大型编译日志也归档。没有删除或替换任何原产物。

新增材料另在本地独立ZIP：`M:\ml项目\review_bundles\20260911\review-v8-v11-incremental-01.zip`。精确大小、哈希和文件数量见[bundles.json](bundles.json)。所有成员SHA256已逐一核验，无分卷，可独立解压；该ZIP没有上传Git，也没有作为GitHub附件发布。它只包含v8—v11增量，原v5行情、面板和10份H60模型仍依赖[首次上传ZIP清单](../bundles.json)。不要把旧ZIP说成已经包含v8—v11。

恢复时按原相对路径解压到项目根目录；本地同名文件先核对哈希，避免覆盖后续工作。上传的`ARTIFACTS.csv`/输入身份会引用Git外文件，克隆后缺少这些文件是有意的大文件排除，不代表报告或源码丢失。审阅者可先读源码、配置摘要和CSV/JSON汇总；完整数值复算需要取得本地ZIP及旧输入包。

## 字节身份与运行边界

原`review_upload/inventory.csv`是业务代码使用的旧输入身份基准，保持原字节；旧上传清单和ZIP均保留。各实验内原报告/计划/模型/预测也没有重写。[FROZEN_ARTIFACT_CHECKS.json](FROZEN_ARTIFACT_CHECKS.json)记录原清单核验：v10清单引用的根README/REVIEW_INDEX因后续v11及本次说明更新而不同，属于明确的文档演进；原引擎/策略源码及实验产物仍按原哈希核对。旧报告中的`git_head`、未推送状态和根文档哈希均是写作时快照。

LEAN完整`input/package.json`和`smoke_input/package.json`含大量预测与历史风险数组，留在ZIP；[LEAN_PACKAGE_SUMMARY.json](LEAN_PACKAGE_SUMMARY.json)保留实际参数、字段规模、输入文件和包哈希，不能当作可直接运行的替代包。实际运行配置与自定义成交模型源码在Git中。原生LEAN/.NET环境位于项目外，不复制到Git；固定上游提交、补丁及构建命令见[运行说明](../../tools/lean_runtime/README.md)。

本次只读取文件和Git。文档中的训练/回放/执行命令用于定位生成流程，**不是本次已执行的命令**。含截至日的冻结脚本不能未经新计划改成继续训练；真实paper与前瞻结果仍为已保存记录中的0，本次没有重新探测账户状态。

只读单文件检查示例：

```powershell
.\.venv\Scripts\python.exe tools/inspect_review_artifact.py "data/experiments/h60_signal_objectives_v11/scores.csv"
```

上传整理工具为[prepare_v8_v11_sync.py](../../tools/prepare_v8_v11_sync.py)，仅处理文件/哈希/归档，未调用研究模块；它追加精确忽略路径，保留新增私有目录与paper本地配置排除规则。常见令牌与选定配置字段检查见[credential_scan.json](credential_scan.json)，不展示凭证值。
