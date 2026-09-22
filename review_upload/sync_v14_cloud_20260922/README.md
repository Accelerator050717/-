# v14 Free云端实测同步材料

2026-09-22，基于`ad702085698f88fed3e4c74ceecc75f2272fbe58`。只新增本次云端数据验收，不改模型或策略，不覆盖此前v8—v14产物/清单。

- [实测报告](../../data/experiments/historical_data_sample_v14/cloud_free_20260922/REPORT.md)、[事前计划](../../data/experiments/historical_data_sample_v14/cloud_free_20260922/PLAN.md)、[运行记录](../../data/experiments/historical_data_sample_v14/cloud_free_20260922/RUN_STATUS.json)。
- [冻结材料路径、大小、SHA256](../../data/experiments/historical_data_sample_v14/cloud_free_20260922/CLOUD_EVIDENCE_IDENTITY.json)覆盖原/补充源码、验证器、准备notebook、云主入口保护、执行身份及两份真实云统计。路径相对仓库根目录，本地根目录为`M:\ml项目`。
- [本次提交文件清单](files.json)补充报告和索引的大小/哈希；清单自身不自引用。文件以本次Git提交为锚点，不把旧清单误作本次结果。
- [离线复核结果](../../data/experiments/historical_data_sample_v14/cloud_free_20260922/VERIFICATION.json)与云API执行结果分开。当前HEAD变化允许，真正源文件或结果变化仍会拒绝。

原始供应商行情、完整候选/SID集合、公司行动金额和事件序列在[QC项目36832711](https://www.quantconnect.com/project/36832711)的Research进程内使用，**未导出至本地/对象存储/Git/ZIP**。内存记录会随节点停止丢失；供应商后续可能修订，重查不能冒充原始收到快照。Git留存的是不可重建源数据的检查统计，不包含永久源快照证明。

新增大型本地材料：**0**；新增审阅数据ZIP：**0**；没有本次新增但因体积被排除的训练模型、行情或交易明细。以前的本地大文件、v14公开文书快照和各轮ZIP保持原位置及原清单。

恢复：在项目根运行`.\.venv\Scripts\python.exe -B tools/verify_qc_v14_cloud_evidence.py`检查已保存摘要，无网络请求。再次云查询须在合法Free Research环境使用固定日期的源码；准备notebook的四个code cell依次为原源码/调用/补充源码/调用，均不包含输出，不能将它误认为已下载的执行notebook。实际云运行合并为两个源+调用cell，AST一致性与运行时hash另见RUN_IDENTITY。

无需新依赖、费用或券商登录。数据完整性后续验收仍须在云内进行；导出或扩大许可用途需单独核实。
