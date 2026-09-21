# v12源码审阅同步

本次基于8b70778217cc2e0405cd20b68e4a3ba9f51b6cd9：固定原rank_60/81特征/Ridge，仅年度训练截止改变，10次实际新拟合、14条新回放、21条原控制复用。B未改善，未达30%净年化目标。没有修改交易策略、获取行情、使用2026或发送订单。

先读[报告](../../data/experiments/h60_training_cutoff_v12/REPORT.md)、[计划](../../data/experiments/h60_training_cutoff_v12/PLAN.md)、[训练身份和模型SHA](../../data/experiments/h60_training_cutoff_v12/TRAINING_DETAILS.md)、[全部差值](../../data/experiments/h60_training_cutoff_v12/pair_deltas.csv)、[审阅索引](../../REVIEW_INDEX.md)。

## Git内材料

52只读验证器、53训练、54固定评估、55汇总及对应测试，全部计划/身份/模型JSON契约、训练明细、35条结果与年度/成本/风险/选股汇总、每日权益、虚构回撤记录和检查结果均进入Git。旧源码、v5—v11实验及review_upload原清单保留。

[inventory.csv](inventory.csv)记录本轮源码/文档/材料路径、字节数、SHA256、生成与读取入口；[large_artifacts.csv](large_artifacts.csv)仅列新增Git外材料。清单不递归包含其自身。环境与依赖见[ENVIRONMENT.json](ENVIRONMENT.json)。

## 本地增量ZIP

- 路径：`M:/ml椤圭洰/review_bundles/20260921/review-v12-incremental-01.zip`
- 大小：5,921,311 bytes / 5.647002 MiB
- SHA256：`3b1593639730edeaa331069bfc0a5458e0bf853f28fe043f6b4370858a102d78`
- 57份材料，未压缩合计25,434,142 bytes；所有成员SHA256已逐一验证。
- 独立ZIP，可单独解压至项目根；不是分卷。**ZIP未上传GitHub**。

包括10个B年度模型、完整Date/symbol/A/B预测、14组逐笔成交/持仓/目标、逐日IC/选股明细及归因和虚构明细。没有重训或下载替换旧产物。全局精确排除规则沿用旧规则，仅追加v12逐路径项，不忽略整个data目录。

本ZIP是新增材料包，完整复核还需要原v5模型/行情快照和v8对照：保留[首次材料与ZIP](../ARTIFACTS.md)、[原ZIP清单](../bundles.json)、[v8—v11增量包](../sync_v8_v11_20260911/bundles.json)。当前包不重复打包旧行情；它们的对应输入身份见v12 INPUT_IDENTITY，读取入口只核对现有哈希，不补下载。

## 完成后复核

在项目根用现有虚拟环境：`python -B 52_verify_frozen_research.py`验证旧v11；`python 53_train_annual_cutoff.py`和`python 54_evaluate_training_cutoff.py --check-only`验证已完成v12，不新增训练或回放。52区分原生成提交与当前复核提交，验证器自身SHA另列。提交后再次实际执行并在交付回复报告新HEAD通过情况；不会为记录新HEAD而改写旧生成身份。

本次只进行普通commit/push，无强推；完整提交SHA及远端一致性在交付回复，避免将尚未生成的提交号写入自身哈希。未进入Git的大材料属于明确保留，不是丢失；没有未解决执行阻塞。真实paper/前瞻验证无新增，旧LEAN仍为人工阶段及自定义立即成交的历史代理。
