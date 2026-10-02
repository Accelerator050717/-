# 固定30只存续股票本地原型恢复

本目录不是QC动态股票池实验，也不应作为部署验证。全部行情截至2025年；不访问券商或网络。

入口：`tools/research_v17_local.py`。环境复用根目录`.venv`及`requirements.txt`。

```powershell
.\.venv\Scripts\python.exe -B tools/research_v17_local.py --verify
```

`--verify`只校验`COMPLETE.json`中的源码、输入计划、模型、预测和结果身份；当前Git HEAD只作复核身份，不要求等于生成HEAD。默认入口发现COMPLETE后同样只验证，不能重新拟合覆盖。`--prepare-only`只在未完成的新运行准备计划/输入/历史特征检查，不训练。

- `PLAN.json`、`INPUT_IDENTITY.json`、`IMPLEMENTATION.json`：固定设计、旧输入SHA及本轮生成源码/依赖身份。
- `models/*.joblib`与同名JSON：10个实际训练模型、训练截止/样本哈希/模型哈希。
- `predictions.csv`：75,240个Date/symbol预测及标签成熟日期，约8.1MB；尾部未成熟标签留空，不删预测。
- `backtests/<case>/`：全部8组逐日权益、持仓、目标、交易及汇总。
- `results.csv`、`annual_results.csv`、`monthly_results.csv`、`security_contributions.csv`、`daily_ic.csv`与`annual_ic.csv`：允许审阅的派生分析。
- `DESCRIPTIVE_DIAGNOSTICS.json`：结果生成后的描述性贡献/成本差值；不是额外优化或回测。
- `REPORT.md`明确未执行备用选择规则的计划差异；没有修改已生成身份。

本地大文件完整材料位于`M:\ml项目\data\experiments\adaptive_strategy_research_v17\local_prototype`。原始行情与原H60材料仍在旧目录，按旧清单恢复；不把受限QC源行情加入本地包。新增未上传材料的最终路径、大小、SHA及审阅ZIP见本轮根审阅材料清单。

本轮本地包已生成：`M:\ml项目\review_bundles\v17_local_20261002.zip`，6,566,945字节（6.26MiB）。含10个模型、1份预测、8组交易/持仓/目标，共35份完整相对路径材料；没有原始行情。`LARGE_ARTIFACTS.csv`记录逐文件大小、SHA、实验和生成/读取命令；`ZIP_MANIFEST.json`记录ZIP完整SHA及原`COMPLETE.json`哈希。ZIP可独立解压至项目根目录，恢复这些精确路径。

```powershell
.\.venv\Scripts\python.exe -B tools/prepare_v17_local_bundle.py --verify
```

打包检查已逐项读取ZIP内容并对比原完成清单SHA、长度及CRC；没有修改原`COMPLETE.json`。生成工具遇到已有ZIP仅核验，内容不符时不会覆盖。
