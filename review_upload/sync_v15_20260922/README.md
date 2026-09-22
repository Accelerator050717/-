# v15 连续动态股票池试点同步材料

本轮基于`a3f9a5f221bb36258e7453a6e2b0b3a1f476dfbe`，保留此前结果与大文件清单。冻结设计、实际运行、结果及限制均在[data/experiments/dynamic_universe_pilot_v15](../../data/experiments/dynamic_universe_pilot_v15/)；审阅入口为[REVIEW_INDEX](../../REVIEW_INDEX.md)。

本清单只涵盖本轮明确路径：`tools/qc_v15*`、准备/只读验证/聚合/本材料清单生成脚本、`tests/test_qc_v15*`、v15实验目录、REVIEW_INDEX及本README。最终[files.json](files.json)记录每份本地材料的仓库路径、准确绝对路径、字节数和SHA256；它不自引用，也不把旧清单当作新增材料。

云项目为[Upgraded Violet Sardine，36834914](https://www.quantconnect.com/project/36834914)。[RUN_IDENTITIES](../../data/experiments/dynamic_universe_pilot_v15/RUN_IDENTITIES.json)记录六个固定主回测的ID、名称、引擎和结果传输身份；额外审计、失败及日志重复运行另看实验记录，不能把“六个参数组合”混作本轮总启动次数。模型训练0，不接IBKR、不启动Live/paper、不读取2026行情。

供应商原始候选、行情和事件留在许可云环境中使用，未导出为本地行情库或ZIP。云端原生回测保留代码快照、订单/成交、原生结果及受配额限制的日志；Git只保留源码、允许分享的聚合结果、身份、报告与公开事件短摘要。**完整辅助内存事件表不是永久备份，也没有证明可恢复本轮原始供应商快照。** 再运行会重新读取供应商当时版本，不能冒充本轮源快照；Free未写Object Store。

本轮新增大型模型/行情/完整预测材料：**0**；新增审阅数据ZIP：**0**。以前的大型材料、压缩包及原环境保持原位置。本轮生成的`cloud/main.py`和`audit_source.py`是本地准备/重建源码，实际云端执行身份以运行记录及AST核对为准，不能称为下载的源文件。

报告与索引完成后生成最终清单；此生成器不暂存、不提交、不上传：

```powershell
.\.venv\Scripts\python.exe -B tools/prepare_v15_review.py --preview
.\.venv\Scripts\python.exe -B tools/prepare_v15_review.py
.\.venv\Scripts\python.exe -B tools/prepare_v15_review.py --verify
.\.venv\Scripts\python.exe -B tools/verify_qc_v15_pilot.py
```

`--preview`只检查当前范围而不写清单；`--verify`会拒绝真实文件变化，但不会仅因正常commit改变HEAD而拒绝原材料。准备文件、聚合CSV与只读检查能帮助再次审阅，不代表模型盈利达标或实际券商执行已完成。
