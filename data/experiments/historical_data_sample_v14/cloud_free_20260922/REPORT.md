# v14 QuantConnect Free云端实测

2026-09-22；基于`ad702085698f88fed3e4c74ceecc75f2272fbe58`。**已在登录的Free组织内实际运行，退市股历史行情、按历史日期变化的候选范围、更名及公司行动均有真实返回。样本接口可用，不等于完整收益研究数据已验收。**

## 实际运行及复用

- 云项目：[Virtual Yellow-Green Frog](https://www.quantconnect.com/project/36832711)，`research.ipynb`。Community R-MICRO；实际内核Foundation-Py-Default，Python 3.11.14，项目自动构建显示LEAN 2.5.0.0.18116。
- 复用原`tools/qc_v14_cloud_check.py`的全部六个固定窗口；补充脚本只查预登记的AAPL公司行动窗口及四个历史候选窗口。[PLAN](PLAN.md)先于数据运行登记。
- 实际执行两个数据检查单元、一个不查询数据的源码身份单元。共**30次History/UniverseHistory调用，30次完成、0次API查询异常；34条日线、10条更名/退市/分红/拆股事件**。SID解析不计作行情查询。
- 第一次编辑器加载及kernel发现失败；停止/重开Research节点、重建代码会话、手动选择Research Server Collection后接通。曾尝试界面Legacy选项，但实际选中并运行的是Default内核，不能把恢复归因于Legacy。项目设置已恢复Foundation Default。没有出现付费门槛或进行购买。
- 云端输入去除了部分注释/调整换行，并在末尾调用函数。运行时保存实际cell SHA256；去除顶层说明/调用后的AST与本地两份源码一致。Python 3.12本地AST多出的空`type_params`字段在比较时明确标准化。不是把准备好的notebook冒充实际运行结果。
- 原始OHLCV、完整成员名单、SID值和公司行动金额只在云内存中检查。Git仅保存代码、非重建型统计、身份及报告；不导出供应商原始数据。准备的[notebook](v14_readonly_checks.ipynb)没有输出，真实输出另存下列两个JSON。

## 六证券实际结果

价格请求RAW、日频、正常时段、`fill_forward=False`、禁止初始化价格种子。所有34条bar的重复EndTime、非有限值、非法OHLCV及2026记录计数均0。

| 案例 | 请求起点→终点边界 | 日线数 | 更名事件 | 退市Warning / Delisted | 筛选输出记录 / 含该SID记录 |
|---|---|---:|---:|---:|---:|
| AAPL | 2020-12-14→12-24 | 8 | 0 | 0 / 0 | 8 / 8 |
| TSLA | 2020-12-14→12-24 | 8 | 0 | 0 / 0 | 8 / 8 |
| FB/META | 2022-06-06→06-14 | 6 | 1 | 0 / 0 | 6 / 6 |
| TWTR | 2022-10-24→11-04 | 4 | 0 | 1 / 1 | 9 / 4 |
| SIVB | 2023-03-06→04-04 | 4 | 0 | 1 / 1 | 21 / 4 |
| ATVI | 2023-10-09→10-20 | 4 | 0 | 1 / 1 | 9 / 4 |

原始统计：[ORIGINAL_RESULTS.json](ORIGINAL_RESULTS.json)。FB于2022-06-08与META于2022-06-10解析出的SID相同，且跨更名窗口真实返回6条bar及1条SymbolChangedEvent，身份连续性不只是“能生成一个ID”。

原脚本输出键`requested_end_exclusive`保留，**键名不构成所有数据类型的过滤语义保证**。本地LEAN对应历史过滤按`start < EndTime <= end`；bar的Time/EndTime及交易所时区须另行区分。不能用“返回4条”推断窗口内其他所有交易日都可交易，也不能补齐停牌时段价格。

## 历史范围确实随日期变化

补充检查在筛选前统计全部候选输入，只在云内临时保留SID集合。这里是`add_universe(selector)`对应的历史Fundamental筛选输入，**不是S&P500指数成员表，也不是已证明完整的美股可交易证券表**。未加`has_fundamental_data`过滤，不能直接拿文档Morningstar覆盖数量或排除规则替代本次实际范围。

| 单日请求起日D（终点D+1） | 候选数 / 唯一SID | TWTR存在 | SIVB存在 | 两目标筛选后的输出记录 |
|---|---:|---|---|---:|
| 2022-10-24 | 9,892 / 9,892 | 是 | 是 | 1 |
| 2022-11-02 | 9,854 / 9,854 | 否 | 是 | 1 |
| 2023-03-06 | 9,704 / 9,704 | 否 | 是 | 1 |
| 2023-04-03 | 9,693 / 9,693 | 否 | 否 | 0 |

TWTR两日输入集合149个移出、111个新增；SIVB两日152个移出、141个新增，数量差与上表一致。**2023-04-03的筛选结果为0，仍有9,693个真实候选输入**，不是整日行情缺失。以后不能把空筛选输出等同于平台没有当天数据。

四个窗口候选输入合计39,143条，SID重复0、2026记录0。全部Time在请求起日范围，EndTime在次日边界；必须按可用时钟安排后续决策，不能拿D日完整观测在D日开盘选股。这个引擎时间约定不等于有独立证据的原始公告/供应商收取时间，也不证明历史版本未修订。

## 公司行动、停牌与终止的边界

固定AAPL 2020-08-03→2020-09-04：1条Dividend，2条Split（Warning和SplitOccurred各1）。实测字段：Dividend有symbol/time/end_time/distribution/reference_price；Split有symbol/time/end_time/type/split_factor/reference_price。实际记录金额/价格没有导出。

- 拆股发生日期与苹果公开披露的2020-08-31拆股后交易起日一致。
- Dividend事件日期与公开支付日2020-08-13**不一致**；这不是数据自动错误，说明引擎分红事件与股东现金到账是不同事实。不能据此释放可用现金。[苹果原公告](https://www.apple.com/newsroom/2020/07/apple-reports-third-quarter-results/)
- 更名：实测有SymbolChangedEvent且FB/META同SID。完整发行生命周期、所有历史ticker/交易所映射尚未验收。
- 退市：TWTR/SIVB/ATVI均实际取得Warning/Delisted。它们不是公告接收证据，也不是股东终止收益或清算付款证明；不把Delisting中的价格代理当终止现金。
- 停牌：本轮没有取得单独的交易所停牌原因/恢复交易事件流。停牌期间没有bar与引擎退市事件不能混称；仍保留先前v14公开监管/发行人证据。
- SIVBQ的OTC后续、破产回收、换股/部分支付、实际结算资金均未建立。SIVB 2024注销证据仍是原公开旁表中的事实，不能用本轮2023退市事件替代。

完整统计：[SUPPLEMENT_RESULTS.json](SUPPLEMENT_RESULTS.json)。无终止收益补0、无虚构成交或支付日、无后见之明卖出。

## 四项验收分开判断

| 项目 | 结论 | 限制 |
|---|---|---|
| 格式与身份 | **样本有限通过** | 6案例/34bar、有效SID衔接、四日无重复；非全库审计 |
| 相应历史决策的信息时间 | **限定可用** | 已观察到Time/EndTime边界，可据其制定保守研究时钟；原公告、原始收到快照、修订历史仍未证明 |
| 是否足够支持完整收益研究 | **尚不足** | 短窗接入口成功；连续价格覆盖、退市收益/现金/OTC及异常处理未验收 |
| 完整历史股票池覆盖 | **未建立** | 四日动态范围和退市前存在性成立；不等于全历史、指数成员或全市场完备 |

能支持下一轮**云内历史股票池构建与连续数据验收**，还不能直接替换本地30股数据、训练新模型或把旧模型套到新增股票。原30股存续偏差和最低30%净年化目标均未解决。本轮训练/策略回测/券商连接/真实及paper订单均0，2026行情继续封存；实际请求窗口最晚至2023年，未检验2025全年的覆盖。

## 唯一下一步与恢复

下一步唯一优先：**在同一Free云Research环境中，另立固定计划构建一个连续历史区间的动态证券范围，并把证券身份、价格缺口、终止权利/未知现金逐项接到v9的验收语义。** 原始数据继续留云内，不能因私有Git就导出。先验收，后决定任何训练；本轮不继续扩大样本。

现在无需用户购买或升级。尚存阻塞是完整覆盖和终止现金证据，不是本次免费历史API权限。若未来必须把供应商源记录接回本地，需要独立核实允许该用途的导出许可；当前Free读取结果没有赋予再分发权。[许可说明](https://www.quantconnect.com/docs/v2/cloud-platform/datasets/licensing)

复现：打开上述云项目的research.ipynb，确认Default研究内核；按原检查和补充检查各运行一次。或将准备notebook中的两份源码与调用单元放入新Research项目。只执行Research，不点Backtest/Live；`cloud_main_guard.py`在本次项目中阻止初始化交易策略。所有请求日期固定，不使用相对今天的bars-count历史调用。

本地只读复核（不导入AlgorithmImports、不访问网络、不重查行情）：

```powershell
.\.venv\Scripts\python.exe -B tools/verify_qc_v14_cloud_evidence.py
.\.venv\Scripts\python.exe -B 60_check_historical_sample.py --verify-local
```

[RUN_STATUS](RUN_STATUS.json)区分失败的内核启动尝试与成功数据调用；[执行身份](RUN_IDENTITY.json)保存实际云源码hash与AST身份；[材料清单](../../../../review_upload/sync_v14_cloud_20260922/README.md)说明本地/云端保留边界。此前冻结的v14公开样本、v8—v13产物及清单不覆盖。

环境恢复参考：[QC打开/停止Research](https://www.quantconnect.com/docs/v2/cloud-platform/research/getting-started)、[官方Python Foundation选项](https://www.quantconnect.com/docs/v2/cloud-platform/projects/package-environments)。只读数据成功与自动构建都不是策略回测、paper运行或前瞻业绩。
