# v16损失归因复核入口

本目录保留原v15 B10的只读证据、一次允许的观察性诊断和派生归因。主结论见`REPORT.md`；冻结策略边界见`PLAN.md`。不是新盈利策略，不训练模型，不启用交易或2026行情。

本地环境沿用项目`.venv`，Python 3.12。以下只读取已保存的产物，不访问行情或启动云回测：

聚合/核对脚本使用Python标准库。可选图表重建为`.\.venv\Scripts\python.exe -B tools/plot_v16_attribution.py`，复用项目已锁定的matplotlib 3.11.1和Windows微软雅黑字体；非Windows环境可直接审阅已保存PNG，不影响金额复核。

```powershell
.\.venv\Scripts\python.exe -B tools/analyze_v16_original.py
.\.venv\Scripts\python.exe -B tools/recover_qc_v16_partial_log.py --input data/experiments/momentum_loss_attribution_v16/DIAGNOSTIC_LOG.txt --out data/experiments/momentum_loss_attribution_v16
.\.venv\Scripts\python.exe -B tools/summarize_qc_v16_attribution.py --input data/experiments/momentum_loss_attribution_v16/DIAGNOSTIC_RECOVERED_FIELDS.json --runtime-stats data/experiments/momentum_loss_attribution_v16/DIAGNOSTIC_RUNTIME_STATS.json --partial-evidence --out data/experiments/momentum_loss_attribution_v16
.\.venv\Scripts\python.exe -B tools/check_v16_financial_links.py
.\.venv\Scripts\python.exe -B tools/check_v16_original_replay.py
.\.venv\Scripts\python.exe -B tools/check_v16_source_identity.py
.\.venv\Scripts\python.exe -B tools/write_v16_report.py
.\.venv\Scripts\python.exe -B tools/prepare_v16_review.py --verify
```

**本次日志确实截断，必须使用上面的`--partial-evidence`流程。** 观察器打算输出8704字节，但浏览器取得单条消息8172字符；流式解出17596/18339字节，LZMA没有读到EOF，完整SHA不能验证。恢复器只保存语法完整的顶层字段：133个SID、167个证券年度记录、41个非零公司行动汇总、年度区间排名及12条重点持仓均完整；尾部C10元数据和月份预期哈希未取回。不能给截断日志补尾巴并称作原始完整返回。原截断字节、恢复前缀、严格字段及证据边界在`DIAGNOSTIC_RECOVERY_CHECK.json`中。

24个月的普通可读Runtime财务字符串另外完整保留。`B/C`为B10/C10月末权益，`F/D/S/R`为B10费用、分红、拆股零股现金及残差。月初权益取前月月末，首月为100000；月度价格损益=权益变化+费用−分红−零股现金−记录残差。金额没有为压缩而取整。证券年度稀疏表保存完整浮点价格损益及费用，缺少公司行动汇总行表示该SID年度没有观察到对应现金，净损益由分量相加。原始观察器的日归因公式为`期末持仓市值−期初持仓市值−买卖净金额+分红+零股现金−费用`，因此跨年持仓的未实现盈亏也归到相应年份。

`FINANCIAL_CROSS_CHECK.json`单独核对全部24个原B10月末UI金额（最大差0.00004608301美元，在显示四舍五入内）、C10的2022年末83250.21788及期末102799.62699、月度连乘、167个年度记录到133个SID总额，以及TOP/KALA/NTRB的独立Research SID和动量。**这些实际数值核对通过，与完整传输SHA未验证是两项不同结论。** C10尾部`all_checks_pass`未观察到，保留null，不冒充已通过。

原生UI订单/交易记录具有显示精度；`original_*`文件不冒充完整精度行情或原生日线。原生Trade采用FIFO逐成交配对，`original_flat_intervals.csv`再聚合同一证券从零仓到零仓的区间。其退出年度表不能代替自然年度盯市结果。

表中`latest_observed_ticker`是兼容列名，实际来自引擎`Symbol.Value`，可能保留原映射代码，不能直接认作当日交易所ticker。身份以SID连接，UI后来名称与历史名称的区别见独立核对；例如FB/META同一SID的更名已经由[v14实际云检查](../historical_data_sample_v14/cloud_free_20260922/REPORT.md)确认。重点买卖保留日期和当时名称，SQ不因UI后来显示XYZ而被视为另一证券。

云项目`36839440`与原项目`36834914`分开。`cloud/v15_core.py`是原策略的云UI读回，可执行AST与v15相同；`cloud/main.py`仅增加观察；`cloud/qc_v16_c10_reference.py`用原C10既有19笔成交重建同收盘参考权益，不提交新订单。浏览器传输造成的行尾/格式差异单独保留在源码身份里。

`SOURCE_IDENTITY_CHECK.json`实际证明三个运行字节SHA均等于对应UI读回转换为LF后再追加一个LF的哈希；observer及core已报告的运行AST与冻结源码一致。C10 helper未单独报告运行AST，保留这一差别；其运行字节哈希精确匹配上述格式变换。该项身份复核不冒充完整日志传输SHA通过。

供应商RAW OHLCV、完整映射和原始公司行动仍在许可云环境内。只导出允许的损益、模拟交易解释和摘要。观察器完整逐日辅助表若只存在运行内存，不能称为永久备份；实际保留字段和省略项见诊断输出及报告。不要因为有恢复命令就再次运行历史回测；本轮最多一次B10观察重放。

费用、股息及TWTR强制退出均是LEAN研究记账；付款时间和最终权利验证边界见`EVENT_AND_MISSING_CHECKS.md`。原v15、H60和v13产物不修改。
