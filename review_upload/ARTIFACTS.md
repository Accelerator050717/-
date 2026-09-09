# 大型材料及恢复说明

本目录是上传清单，不是新实验。项目业务源码、策略和既有研究产物保持原字节；`.gitattributes`禁用行尾自动转换，避免已登记SHA256在克隆后失效。

- [inventory.csv](inventory.csv)：上传准备时现有项目文件的分类、字节数与SHA256；不枚举环境/缓存与生成的上传目录。
- [large_artifacts.csv](large_artifacts.csv)：Git外每个数据/模型大文件的准确本地路径、大小、SHA256、实验、生成入口、只读命令及ZIP。
- [bundles.json](bundles.json)：ZIP精确大小与SHA256。每包正常独立解压，无`.z01`分卷；每个不超过450MiB。
- [credential_scan.json](credential_scan.json)：必要的凭证文件名/常见令牌形式检查；不宣称能识别所有可能的敏感信息。

ZIP仅归档原文件，不重新生成价格、预测、模型或成绩。将全部包解压到项目根目录即可恢复原路径；已在本地的同名文件应先比对SHA256，避免覆盖用户的后续成果。每包含`REVIEW_BUNDLE_MANIFEST.json`，逐文件记录哈希；相同名字的包说明文件不属于业务数据。

## 依赖对应关系

| 研究 | 原始输入与中间材料 | 评分/模型/结果 | 原生成或读取入口（本轮未运行） |
| --- | --- | --- | --- |
| v5较长历史及H60基线 | `data/raw/extended_2012_2025`、`extended_history_v5/panel.csv`、`adjusted_opens.csv`、`spy_open.csv` | v5全部年度joblib、`all_scores.csv`、训练明细及backtests | 35生成/缓存，36核对 |
| v6集成与ATR止损 | 原v5面板、H60年度模型、原始OHLC；v6十个H20模型 | v6 `all_scores.csv`、每年scores/validation、backtests、JSON/CSV比较 | 38拟合/复用，39评估，41读取汇总 |
| v7精简风险规则 | v6保存的H60评分、同一44份扩展行情和v5调仓日程 | v7全部backtests、对照、压力、相位结果 | 40读取既有评分并评估，41汇总；没有新增拟合 |
| v1—v4研究 | 2015—2025股票/ETF快照、`research_panel_v1.csv`、财报/事件面板、SEC原始事实 | 全部原模型、完整预测及结果；Git保留计划、报告与合理大小汇总 | 14—22、26—28、31—37各自源码定义 |
| 冻结历史执行演练 | v1原特征面板、2015—2025快照、2025 `m16_elastic_rank.joblib` | `data/replays/offline_v1`虚拟状态、成交和核对记录 | 23历史回放；24串联会写账本，本轮未运行 |

上述路径中实验简称均位于`data/experiments/`。同一股票的不同快照不能拼接或互相替代：原JSON含参数、获取时间和SHA256，v5的`snapshot_overlap.csv`记录重叠快照差异。

## 只读检查

清单中的每一行都给出对应`tools/inspect_review_artifact.py`命令。此工具仅读取字节/哈希及CSV首行/JSON键，不载入pickle、不下载、不训练、不连接券商。例如：

```powershell
.\.venv\Scripts\python.exe tools/inspect_review_artifact.py "data/experiments/extended_history_v5/2025_ridge_h60_price.joblib"
.\.venv\Scripts\python.exe tools/inspect_review_artifact.py "data/experiments/robust_strategy_v6/all_scores.csv"
```

`generator_entrypoint`用于定位原生成逻辑，**不是本轮运行指令**。报告重建也可能写文件，部分训练脚本缺缓存时会训练或下载且保留原时间限制；审阅时先恢复原包并读取记录。原始模型必须与记录哈希一致后，才应在受信环境中进行后续加载。
