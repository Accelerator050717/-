# 最新源码审阅入口

## v17已完成研究（2026-10-02；没有合格候选，停止本轮搜索）

**本轮目标为扣成本净年化20%—30%，30%以上为进阶；完整历史回撤优先20%以内、30%为预算。没有值得升级的候选。** 旧报告“至少30%、争取50%”保留当时记录，不再作为本轮唯一标准。基线`de51b46adf082a7708701cd2a209d44ade83fa8d`；[事前PLAN](data/experiments/adaptive_strategy_research_v17/PLAN.md)的18个独特策略/成本配置已全部完成：本地8个、云端10个。实际完成回放20次（本地8＋云端12，含两次重复），另保留两次早期云失败；不是22个独特策略。2026封存，无Live/paper/券商订单、资金操作或付费。

优先读[本轮总报告](data/experiments/adaptive_strategy_research_v17/REPORT.md)、[真实动态池报告](data/experiments/adaptive_strategy_research_v17/cloud/REPORT.md)、[全部云端比较](data/experiments/adaptive_strategy_research_v17/cloud/comparison/results.csv)、[年度/月度](data/experiments/adaptive_strategy_research_v17/cloud/comparison/annual.csv)及[运行尝试账](data/experiments/adaptive_strategy_research_v17/cloud/attempt_ledger.csv)。云访问和账户验证已经恢复，早期阻塞记录不是当前限制。

| 2022—2023动态池，单边10bp | 累计收益 | 净年化 | 全历史收盘回撤 | 判断 |
| --- | --- | --- | --- | --- |
| 同池100股等权 | −2.73% | −1.38% | 26.61% | 简单对照，收益未达标 |
| SPY 90%预算 | +2.80% | +1.39% | 22.16% | 最好预算内控制，非达标策略 |
| 20日动量前10 | −21.33% | −11.31% | 42.84% | 拒绝 |
| 63日趋势跳过最近20日 | −2.25% | −1.13% | 37.56% | 拒绝 |
| 年度Ridge前10 | −13.70% | −7.11% | 42.23% | 拒绝 |
| 同中期趋势＋45%/90%仓位 | −5.96% | −3.03% | 32.68% | 最浅回撤失败组，仅作20bp诊断 |
| 同Ridge＋45%/90%仓位 | −18.57% | −9.77% | 38.92% | 拒绝 |

| 已完成20bp成本检查 | 末值美元 | 累计收益 | 净年化 | 全历史收盘回撤 |
| --- | --- | --- | --- | --- |
| 同池100股等权 | 96,525.29 | −3.47% | −1.75% | 26.87% |
| SPY 90%预算 | 102,534.50 | +2.53% | +1.26% | 22.27% |
| 中期趋势＋45%/90%仓位（失败诊断） | 92,123.76 | −7.88% | −4.02% | 33.49% |

- 五个选股候选全部亏损且回撤超过30%。Ridge比同池等权年化低5.73个百分点、回撤高15.63个百分点；中期趋势比等权年化只高0.25个百分点、回撤却高10.95个百分点。固定趋势仓位分别降低趋势/Ridge回撤4.88/3.32个百分点，却损失年化1.90/2.66个百分点。停止这些失败规则上的容量、周期或阈值追加，不把2023反弹单独当作成功。
- [云策略](tools/qc_v17_research.py)与[特征/标签](tools/qc_v17_features.py)在[独立Free项目37249270](https://www.quantconnect.com/project/37249270)根据历史普通股候选、连续20日成交额中位数和稳定SID形成100股动态池；累计183个SID。它生成训练样本、预测、目标和原生MOO订单，原生Equity模型成交，没有导入本地30股预测或既定成交。初始10万美元、整股、零息、月度决定、下一开盘减仓/再下一开盘增仓，末次清仓含费；同常规90%事前预算不等于相同实际风险。
- 云端8个固定特征、年度StandardScaler＋Ridge(alpha100,svd)，下一月决策收盘间SplitAdjusted收益的横截面名次标签；2022/2023各3450/4645训练行，标签终点严格早于部署年1月1日。[完整模型参数与SHA](data/experiments/adaptive_strategy_research_v17/cloud/cases/ridge_cost10/FITS.json)和[同模型/预测配对](data/experiments/adaptive_strategy_research_v17/cloud/comparison/COMPARISON.json)保存。信号组共同要求127个历史价格点，等权保留历史不足的池内证券；与旧v15的差异包含股票池、资格与引擎版本，不能叫纯选池或模型提升。
- **实际拟合总计16次：本地10次＋云端6次；独特模型12个：本地10年度＋云端2年度。** 云6次来自Ridge、只改输出的同配置重放、同信号风险组各2次，同年度模型哈希一致；不是6套独特候选模型。云10个独特配置由7个10bp主配置及3个20bp检查组成；12次完成还包括一次同配置观测重放、一次参数界面错启的等权20bp重复，后者不算新策略或拟合。两次暖机失败均0拟合/0订单，完整记录保留。正常提交不改写原生成身份，旧H60模型只作输入核验，未用于新动态信号。
- 每个完成云组有24月、501次连续收盘统计，最终空仓、工程账本门槛通过；**完整日频权益尚未独立下载，云回撤没有被本地独立重算。完整云预测向量、完整逐证券损益也未归档，只有哈希/模型/摘要，哈希不是原产物。** 六条终止标签端点仍未解决、未填0；训练名次仅在可解析端点上形成，不能宣称完整消除存续偏差。退市现金、分红事件及换股/分拆权利仍有代理或覆盖限制，原始供应商记录留在许可云内。[数据边界](data/experiments/adaptive_strategy_research_v17/cloud/REPORT.md)、[独立审阅](data/experiments/adaptive_strategy_research_v17/INDEPENDENT_REVIEW.md)分开工程与经济事实。
- **本地固定30只存续股仅为备用开发原型。** [本地报告](data/experiments/adaptive_strategy_research_v17/local_prototype/REPORT.md)与[8组结果](data/experiments/adaptive_strategy_research_v17/local_prototype/results.csv)保留：Ridge10bp年化20.11%但回撤31.24%；加趋势仓位18.40%/21.30%，20bp变16.40%/21.41%，低于同池等权17.26%。未达标。75,240条预测保留450条未成熟尾部；NVDA占候选净利润31.37%。它是2016—2025调整价/碎股、五日调仓代理，不能和云端动态结果混为一组公平比较。
- [本地源码](tools/research_v17_local.py)复用费用/现金求解，不修改旧引擎；[COMPLETE](data/experiments/adaptive_strategy_research_v17/local_prototype/COMPLETE.json)冻结模型、预测及结果。未执行备用选择分支与根PLAN不一致已披露，实际唯一合格本地候选使选择不受影响。跨年度高水位不重置；本地独立核对59输入、10模型、全部预测及8账本不代表真实券商执行验证。
- [本轮上传材料](review_upload/sync_v17_20261002/README.md)和[35份大文件清单](data/experiments/adaptive_strategy_research_v17/local_prototype/LARGE_ARTIFACTS.csv)保存准确路径/大小/SHA/入口。本地审阅ZIP`M:\ml项目\review_bundles\v17_local_20261002.zip`为6,566,945字节（6.26MiB），[ZIP身份](data/experiments/adaptive_strategy_research_v17/local_prototype/ZIP_MANIFEST.json)及35项SHA/CRC通过；不含原始行情。只读核验：`.\.venv\Scripts\python.exe -B tools/research_v17_local.py --verify`，包核验：`.\.venv\Scripts\python.exe -B tools/prepare_v17_local_bundle.py --verify`，云恢复见[README](data/experiments/adaptive_strategy_research_v17/cloud/README.md)。

**唯一下一步：把同一历史动态池管线连续扩展并验收到2016—2025完整开发区间，保留足够早的暖机和成熟训练历史，冻结等权/SPY及本轮失败规则作为对照。** 三项20bp预登记检查已完成，失败诊断仍不达标；本轮停止追加模型与阈值，不据结果继续调这两年。2022—2023已经属于开发历史，不是独立验证；没有真实paper或前瞻业绩。v13持续资金记账基础保留、其研究风控不替代原A；v10历史代理限制、完整公司行动、真实paper入口、部分成交持续保护及长期断线补账缺口均未自动解决。

## v16历史结果（保留当时结论；后续授权与当前进展以上方v17为准）

最新更新：2026-09-22，**v16已解释原B10的54,078.72美元净亏损：UPST/KALA/AMC/TOP/NTRB合计21,851.11美元，17/24个月亏损；原规则保留为失败基准。** 本轮基于`138d2bf8ddf81f484c95c5e8cffa3dbab66fb07b`，只完成损失归因，没有改策略。优先读[v16“钱亏在哪里”报告](data/experiments/momentum_loss_attribution_v16/REPORT.md)、[完整月度损益](data/experiments/momentum_loss_attribution_v16/monthly_pnl.csv)、[逐证券精度汇总](data/experiments/momentum_loss_attribution_v16/security_total_pnl.csv)、[12个重点持仓](data/experiments/momentum_loss_attribution_v16/priority_entries.csv)。

- 价格损益−53,783.161美元，加分红2,009.72及零股现金0.000884917，减费用2,305.282651，期末权益45,921.277233917004。逐日归因残差约5e−12美元；它证明引擎金额桥接，不证明真实付款和所有历史报价均已认证。TOP净亏4,246.14074；TWTR两段净亏955.76583，已计终止现金与名义权利只差46.62美元，不能重复入账；8个普通缺价日B持仓均0，其后续选择影响金额未知。
- [冻结PLAN](data/experiments/momentum_loss_attribution_v16/PLAN.md)与[最终回放前身份](data/experiments/momentum_loss_attribution_v16/FINAL_PRE_REPLAY_IDENTITY.json)先于唯一诊断回放。[新云项目36839440](https://www.quantconnect.com/project/36839440)，回测`3f5d23c2dd0ee166d0bbaa1699553c03`；原项目36834914/原B10不改。新旧终值、年度、费用、成交额相同，458订单显示字段逐行相同、133证券价格损益独立对应：[原生订单核对](data/experiments/momentum_loss_attribution_v16/INDEPENDENT_NATIVE_ORDER_CHECK.json)、[逐股核对](data/experiments/momentum_loss_attribution_v16/INDEPENDENT_ORIGINAL_REPLAY_CHECK.md)。
- [观察器](tools/qc_v16_attribution_observer.py)导入原v15核心，仍从历史Fundamental和20日SplitAdjusted价格信号生成目标/MOO订单，原生EquityFillModel成交；没有导入H60预测或既定成交来冒充B。C10参考模块只用原C10已有成交重建同收盘月度参考，不下新订单。KALA的12.79%是成交额/回报时权益，不是已验证9:30实际仓位；[时点及权重口径](data/experiments/momentum_loss_attribution_v16/WEIGHT_AND_TIMING_REVIEW.md)单列。
- 实际新增诊断回放1、固定只读History请求9、模型拟合0、Live/paper/券商订单0、付费0，2026行情未读。TOP/KALA/NTRB买前大涨与成交异动已经实际查询，但为事后选取案例，不能估计全体概率或直接证明新过滤盈利。日志尾被截断，完整payload SHA未验证；完整出现的财务字段、24个月Runtime与原运行的独立金额核对分别保存，不伪造完整备份。
- **唯一下一轮问题：固定20日成交额中位数选池，相比原单日成交额选池，能否改善同一动量规则？** 最小两池×10/20bp对照、其余条件不变，失败标准见[v16报告](data/experiments/momentum_loss_attribution_v16/REPORT.md#7-唯一下一轮问题本轮不执行)。本轮没有启动该比较。30%净年化/争取50%及30%回撤预算均未达到，2022—2023仍为开发历史，没有升级模型或打开2026。
- [只读复核命令](data/experiments/momentum_loss_attribution_v16/README.md)支持本地恢复已保存的派生记录；[本轮材料清单](review_upload/sync_v16_20260922/README.md)保留路径/大小/SHA256。无新大型模型、预测或ZIP；供应商原始行情仍在许可云内。v15旧记录、原A/H60、v13资金基础和v10历史代理限制均保留；完整公司行动、真实paper入口、部分成交持续保护及长期断线补账仍未完成。

## v15历史结果（保留当时结论；下一步由上方v16取代）

最新更新：2026-09-22，**v15已完成2022—2023连续24个月动态股票池及6个固定QuantConnect Free原生基准，流程有限通过，全部未达到收益目标；实际分拆/换股权利和8个RAW日线缺口仍限制经济收益验收。** 基于`a3f9a5f221bb36258e7453a6e2b0b3a1f476dfbe`。先读[v15完整报告](data/experiments/dynamic_universe_pilot_v15/REPORT.md)、[冻结PLAN](data/experiments/dynamic_universe_pilot_v15/PLAN.md)、[六组结果](data/experiments/dynamic_universe_pilot_v15/results.csv)、[逐月范围/时间](data/experiments/dynamic_universe_pilot_v15/monthly_universe.csv)、[验收边界](data/experiments/dynamic_universe_pilot_v15/ACCEPTANCE_LIMITS.md)。

| 2022—2023固定基准 | 10bp：累计 / 年化 / 回撤 | 20bp：累计 / 年化 / 回撤 |
|---|---|---|
| 当期池100股等权 | -7.15% / -3.64% / 25.14% | -7.71% / -3.94% / 25.51% |
| 20日动量前10等权 | -54.08% / -32.25% / 58.33% | -55.92% / -33.63% / 59.85% |
| SPY | +2.80% / +1.39% / 22.16% | +2.53% / +1.26% / 22.27% |

- 范围是历史Fundamental覆盖普通股，最近已交付交易日RAW价>$5、美元成交额前100、SID破同分；不是S&P500或完整全美股/OTC。24月累计320个SID，748次新增含初始100、648次移出。50,100证券日中49,977有bar、99已终止后缺价、24原分类未知；事后证据解释16项，另8项在实际RAW History单日及相邻控制中仍缺。详见[缺价返回](data/experiments/dynamic_universe_pilot_v15/MISSING_PRICE_RESULTS.json)、[32条周边记录的聚合控制](data/experiments/dynamic_universe_pilot_v15/MISSING_PRICE_CONTROLS.json)。不补价、不事后删股。
- [v15算法](tools/qc_v15_dynamic_pilot.py)从原生历史Fundamental/行情生成选择与目标，再生成MOO订单，成交由原生EquityFillModel产生。**没有导入H60预测、既定目标或成交记录**；原v10仍是独立历史代理，限制未解除。月首16:05决定，后续两阶段开盘卖/买，100,000美元、90%事前预算、整股、零息、即时结算研究假设；收盘权益含现金股息，末次清仓含费。
- 三个实际A终止持仓现金代理合计2,395.30美元；B两档TWTR分别5,969.58/5,915.80，均为引擎缓存价零费强平，非核实付款。T/WBD、DHR/VLTO分拆及XLNX/AMD换股未完整承接；不能用碎股现金残差证明经济影响很小。引擎收益与[一手法律权利](data/experiments/dynamic_universe_pilot_v15/TERMINAL_EVENT_EVIDENCE.md)分别保存，A精确可投资收益仍未定。
- [新云项目36834914](https://www.quantconnect.com/project/36834914)保留原v14项目。正式6组同引擎`2.5.0.0.18116`、同AST；实际11次启动中10次完成（3 audit、7收益执行含A10补日志重跑），另1初始化失败，均留[尝试记录](data/experiments/dynamic_universe_pilot_v15/RUN_ATTEMPTS.json)。[6组运行ID及复制指纹](data/experiments/dynamic_universe_pilot_v15/RUN_IDENTITIES.json)、[A10完全相同汇总核对](data/experiments/dynamic_universe_pilot_v15/A10_REPEAT_CHECK.json)、[本地验证](data/experiments/dynamic_universe_pilot_v15/VERIFICATION.json)可复核。
- 本轮训练0、H60迁移0、券商连接/Live/paper/真实订单0、付费0，2026行情封存。2022—2023是开发试点，2025全年及2016—2025连续覆盖仍未验收；30%净年化/争取50%与30%回撤预算不变，没有升级任何模型。原A及v13持续资金基础保持，v13风控仍为研究状态。
- 本地复核：`.\.venv\Scripts\python.exe -B tools/verify_qc_v15_pilot.py`；只汇总现存产物：`.\.venv\Scripts\python.exe -B tools/summarize_qc_v15_pilot.py`。云运行与32KiB源码准备见[v15 README](data/experiments/dynamic_universe_pilot_v15/README.md)。供应商源记录只在QC许可环境使用；完整辅助内存账本未持久化，原生订单/代码/日志留云。无新增大型模型或ZIP，[本轮材料清单](review_upload/sync_v15_20260922/README.md)不替换旧v8—v14清单。

**唯一下一步：预登记同一连续管线的公司行动/缺价验收补丁，再扩展至明确训练/开发区间。** 限本轮真实持仓的承接权利及8个缺价日，之后才登记少量模型比较；不再追加本轮参数搜索，也不回到零散接口展示。真实paper入口、部分成交持续保护、保护撤换窗口及长期断线补账仍未完成。

## v14云读取历史结果（保留当时结论）

最新更新：2026-09-22，**v14已在登录的QuantConnect Free云Research实际完成历史数据检查：30次查询全部完成，34条日线、10条事件；退市股历史行情及按历史日期变化的候选范围确实可读。** 本次基于`ad702085698f88fed3e4c74ceecc75f2272fbe58`。先读[云实测报告](data/experiments/historical_data_sample_v14/cloud_free_20260922/REPORT.md)、[运行状态](data/experiments/historical_data_sample_v14/cloud_free_20260922/RUN_STATUS.json)、[原检查返回](data/experiments/historical_data_sample_v14/cloud_free_20260922/ORIGINAL_RESULTS.json)及[补充返回](data/experiments/historical_data_sample_v14/cloud_free_20260922/SUPPLEMENT_RESULTS.json)。

- [云项目](https://www.quantconnect.com/project/36832711)使用Community R-MICRO、Foundation-Py-Default。TWTR与SIVB固定窗口各取得4条真实RAW日线及Warning/Delisted事件；FB/META同SID且有更名事件；AAPL取得分红和拆股记录。
- 四个历史窗口的筛选前候选数为9,892、9,854、9,704、9,693。TWTR/SIVB在各自前窗口存在、后窗口消失，证明不是今天存续名单。它是历史Fundamental筛选输入，不是S&P500成分表，也未证明全美股/OTC覆盖。观察Time与EndTime跨日，不能在当日开盘提前使用整日输入。
- 四项结论分别为：格式/身份**样本有限通过**；信息时间**限定可用，缺原始接收版本证据**；完整收益研究**尚不足**；完整历史股票池**未建立**。停牌原因/恢复流、OTC延续、终止回收和可用现金仍缺。分红事件日期不等于公开支付日，退市事件也不等于现金到账。
- 原[云检查源码](tools/qc_v14_cloud_check.py)保持不变；[补充源码](tools/qc_v14_cloud_supplement.py)只查固定2020/2022/2023窗口。[只读验证器](tools/verify_qc_v14_cloud_evidence.py)验证云源码AST、本地摘要哈希及浏览器复制一致性，不要求当前HEAD等于生成时HEAD。运行：`.\.venv\Scripts\python.exe -B tools/verify_qc_v14_cloud_evidence.py`。
- 新增训练/策略回测/券商连接/真实或paper订单/购买均0，2026行情继续封存；没有验证2025全年覆盖。供应商源记录留在云内；Git只包含代码、允许分享的非重建型摘要和身份。无新增大文件或ZIP，见[材料说明](review_upload/sync_v14_cloud_20260922/README.md)。原A及v13资金基础保持，v13新风控不升级，旧研究产物和清单不覆盖。

**唯一下一步：在同一Free云环境另立固定计划，验收连续历史区间的动态证券范围、行情衔接及终止持仓处理，然后再决定训练。** 当前免费权限已足够完成本次样本读取，无需购买；接口通过不等于已消除30股存续偏差或达到30%净年化目标。

## v14先前公开样本（保留当时状态）

先前更新：2026-09-22，**v14取得真实历史事件小样本并接通原v9入口；尚不够进行可信收益研究或消除存续偏差。** 该阶段基于`a8cf66223c0d88b3d78dada3ff3f355c6eaf8730`，新增训练/策略回测/行情下载/券商连接/订单均0，未读取2026行情。原A不变；v13持续资金记账保留，新风控仍为研究状态。

优先阅读[v14报告](data/experiments/historical_data_sample_v14/REPORT.md)、[预登记计划](data/experiments/historical_data_sample_v14/PLAN.md)、[四项验收及实际数量](data/experiments/historical_data_sample_v14/CHECKS.json)、[原字段映射](data/experiments/historical_data_sample_v14/SOURCE_MAPPING.md)、[独立复核](data/experiments/historical_data_sample_v14/INDEPENDENT_REVIEW.md)。

- 六个固定案例：AAPL、TSLA、FB/META、SIVB/SIVBQ、TWTR及旧ATVI参考。取得13份成功HTTP历史文书/元数据快照和2份明确标识的Web摘取；错误页不计成功资料。新增5个成员变化、2条同证券别名衔接，停牌/剔除/上市移除/OTC/最终注销分别保存。
- 格式与本地身份**有限通过**；信息时间**限定查询可用**；收益研究和完整股票池**不通过**。16条新增事实日期证据缺失0，但15条无核实的盘中发布时间、全部缺原始接收快照/完整修订历史。不是完整S&P500名单，也不是完整历史可交易股票池。
- 原有AAPL/META各1508条2020—2025行情通过哈希/日历/字段检查；其余4案例无本地完整行情。TWTR假设10股产生542美元应收、0可用现金；SIVB2024旧股无分配有证据，但核销类型暂unsupported。缺失收益不补0、不假设最后一根行情可提前准确卖出。
- [60验收入口](60_check_historical_sample.py)复用未修改的[historical_universe](historical_universe.py)与[46](46_check_historical_universe.py)；[规范化事实包](data/reference/universe_events/v14_public_sample/manifest.json)保留旁表与限制。当前环境直接运行`.\.venv\Scripts\python.exe -B 60_check_historical_sample.py --verify-local`；新Git克隆去掉该选项只能核对公开事实及结果，完整源验证需找回本地同哈希文件。详见[运行/恢复说明](data/experiments/historical_data_sample_v14/REPORT.md#复现与恢复)。
- [QuantConnect路线](data/experiments/historical_data_sample_v14/QUANTCONNECT_ROUTE.md)、[Norgate路线](data/experiments/historical_data_sample_v14/NORGATE_ROUTE.md)在该阶段按官方资料检查，当时未登录。其后QC Free登录与[云检查](data/experiments/historical_data_sample_v14/cloud_free_20260922/REPORT.md)已实际完成，取代旧“仅准备、未运行”状态；旧状态JSON作为历史记录保留。云可读不等于可导出/再分发，学术订阅未验证。
- [v14本地材料清单](review_upload/sync_v14_20260922/README.md)列路径、大小、SHA256和来源/恢复方式；原始全文及派生全文无再分发授权，不上传Git或对外ZIP。旧v8—v13模型、预测、研究记录和清单保持。

原有目标仍为至少30%净年化、争取50%，回撤优先20%附近/预算30%。本轮未测收益，不宣布目标达成；历史30股结果依然存在存续偏差。下方LEAN仍为历史代理：导入预测，内部产生订单并由自定义即时成交模型产生代理成交；没有真实paper回报或前瞻业绩。原生报价/公司行动、真实paper入口、部分成交持续保护、保护撤换窗口、长期断线补账缺口未改变。

## v13历史结果（保留，未升级）

最新更新：2026-09-22，**v13持续策略资金高水位完成固定比较：本地资金连续性基础补齐，但本方案风控价值门槛未通过，盈利仍未达到30%净年化目标。** 本轮基于提交`3d02318a10266f91615714a77673d1d5f425f988`，原A模型/预测不变；新增拟合0次，复用10份年度模型和21条控制结果，新增14次全局控制回放及2次完整只记录一致性核对。不升级模型，不追加阈值搜索。

先读[v13完整报告](data/experiments/continuous_fund_risk_v13/REPORT.md)、[冻结计划](data/experiments/continuous_fund_risk_v13/PLAN.md)、[全部35条结果](data/experiments/continuous_fund_risk_v13/all_results.csv)、[14组成对差值](data/experiments/continuous_fund_risk_v13/pair_deltas.csv)、[年度结果](data/experiments/continuous_fund_risk_v13/annual_results.csv)及[验收判定](data/experiments/continuous_fund_risk_v13/GATES.json)。

| 2016—2025主场景，普通单边10bp | 原控制净年化→全局控制 | 原控制累计收益→全局控制 | 全历史最大回撤原→新 |
| --- | --- | --- | --- |
| 完整保护A | 14.88% → 12.90% | 299.39% → 235.88% | 17.74% → 18.68% |
| 简单H60诊断 | 20.83% → 17.92% | 560.93% → 418.29% | 21.15% → 19.41% |

完整保护年化少1.98个百分点，回撤反而加深0.94个百分点，故拒绝升级；简单配置回撤有所改善但损失收益，且缺完整个股保护，只作诊断。目标仍为扣成本长期年化最低30%、争取50%，回撤优先约20%、30%为预算。本轮开发区间处于30%回撤范围内不构成未来保证，也不是独立验证。没有使用2026行情或发送真实/paper订单。

### v13资金范围、工程与风险口径

- 管理范围是**该自动策略连续管理的指定资金**，不是整个IBKR账户。`scope_id`、币种、归属和股票范围独立于模型SHA与进程ID；换年、重启和模型元数据交接不重置累计高点。资金事件按份额/单位净值处理，费用、分红和利息进入收益；不明差额、迟到/冲突事实停止新增风险。[资金契约](data/experiments/continuous_fund_risk_v13/ENGINEERING_CONTRACT.md)、[虚构事件样例](data/experiments/continuous_fund_risk_v13/FUND_EVENT_EXAMPLE.json)。
- 原`episode_peak`仍用于既有周期暂停；新的单位净值高水位持续保存。本次唯一方案按累计亏损10%缩至40%总仓位、20%暂停、25%进入需复核停机，保留原周期规则；恢复要求冷却、趋势、调仓日、已确认空仓及剩余预算，最多25%仓位。精确优先级、恢复亏损预算及触发时点以冻结PLAN为准，不能当作获准的实盘额度。
- [只记录检查](data/experiments/continuous_fund_risk_v13/RECORD_ONLY_CHECK.json)对两种配置各2511日，核对原目标、交易、持仓、现金和权益数值一致。SQLite事务关联事件去重游标、风险状态和策略检查点；[真实进程中断/恢复的虚构证据](data/experiments/continuous_fund_risk_v13/engineering/final_verification/CONTINUITY_REPORT.json)、[测试记录](data/experiments/continuous_fund_risk_v13/TESTS.json)、[边界检查](data/experiments/continuous_fund_risk_v13/BOUNDARY_CHECKS.json)与[独立工程复核](data/experiments/continuous_fund_risk_v13/INDEPENDENT_ENGINEERING_REVIEW.md)分别保存。
- 历史比较按**每日收盘高水位**；虚构执行账本保留**每次可信估值高水位**。附加离线控制周期接线会读取实际已核对现金/股数并持久化同一控制器，但估值频率尚未与历史逐条等价，不能声称已迁成真实paper策略。[执行说明](data/experiments/continuous_fund_risk_v13/engineering/README.md)。
- 仓位预算用成交前NAV估计，费用可能使成交后比例略高于重新计算的上限；[明确标为虚构的费用边界诊断](data/experiments/continuous_fund_risk_v13/ENGINEERING_LIMITATIONS.md)差5.38bp仓位。跳空、部分成交与退出延迟仍可能突破预算；不能把触发视为立即全部成交。
- 资金账本支持模型元数据延续，**旧执行账本的实际模型清单仍不可原地替换**。券商入提款导入、迟到成交/佣金重建、真实模型迁移、多币种、原生美股报价/公司行动、真实paper运行入口、部分成交期间持续保护、保护撤换窗口、长期断线补账仍待完成。两库可核对恢复不是跨库原子事务；LEAN历史模式限制保持不变，真实paper回报和前瞻业绩均无新增。

### v13优先源码与复核

| 内容 | 入口 |
| --- | --- |
| 独立资金事件、份额、高水位及事务 | [strategy_fund_journal.py](strategy_fund_journal.py)、[资金测试](tests/test_v13_fund_journal.py) |
| 固定全局状态机与历史适配器 | [h60_global_control.py](h60_global_control.py)、[h60_global_research.py](h60_global_research.py)、[研究恢复](tests/test_v13_research_continuity.py) |
| 执行事实桥及离线阶段接线 | [h60_fund_risk_bridge.py](h60_fund_risk_bridge.py)、[h60_fund_control_cycle.py](h60_fund_control_cycle.py)、[56虚构进程检查](56_check_fund_continuity.py) |
| 原交易不变检查、固定比较与报告 | [57只记录检查](57_check_fund_recording.py)、[58固定评估](58_evaluate_continuous_risk.py)、[59汇总](59_summarize_continuous_risk.py) |
| 暂停、空仓、恢复及交易原因 | [暂停区间](data/experiments/continuous_fund_risk_v13/pause_intervals.csv)、[恢复区间](data/experiments/continuous_fund_risk_v13/recovery_intervals.csv)、[交易原因](data/experiments/continuous_fund_risk_v13/trade_reason_summary.csv) |

环境仍为项目`.venv` Python3.12.2及[requirements.txt](requirements.txt)，无新增依赖。已恢复本地大材料后，在项目根目录用以下命令检查已完成产物，不重复训练或历史回放；59仅重新生成报告。

```powershell
.\.venv\Scripts\python.exe -B 52_verify_frozen_research.py
.\.venv\Scripts\python.exe -B 57_check_fund_recording.py
.\.venv\Scripts\python.exe -B 58_evaluate_continuous_risk.py --check-only
.\.venv\Scripts\python.exe -B 59_summarize_continuous_risk.py
```

本轮完整SQLite事件链、交易/目标/持仓明细按原规则保留本地并打包，见[v13上传说明](review_upload/sync_v13_20260922/README.md)、[准确路径/大小/SHA256及入口](review_upload/sync_v13_20260922/large_artifacts.csv)、[ZIP清单](review_upload/sync_v13_20260922/bundles.json)。它们补充旧v8—v12材料，不替换原A行情、模型或预测。一次冻结前记账尝试及其表示层检查中止记录也保留，没有算作第三次完成对照或新的风控候选。

**下一步唯一优先：取得合法可用、包含退市股和历史成员变化的点时股票池样本，通过[v9数据契约](data/experiments/universe_delisting_v9/DATA_CONTRACT.md)及[现有接入口](46_check_historical_universe.py)验收。** 完整授权数据仍缺，30股存续偏差未消除；停止追加本轮风控阈值或训练截止搜索，风险基础补齐不等于盈利能力补齐。

## v12历史结果（已完成，保留当时结论）

v12历史更新：2026-09-21，**年度训练截止比较完成：10次新拟合、14次新回放；更新协议未改善，仍未达到30%净年化目标，不升级模型。** 见[v12完整报告](data/experiments/h60_training_cutoff_v12/REPORT.md)、[事前计划](data/experiments/h60_training_cutoff_v12/PLAN.md)、[10次训练和全部模型SHA](data/experiments/h60_training_cutoff_v12/TRAINING_DETAILS.md)、[成对差值](data/experiments/h60_training_cutoff_v12/pair_deltas.csv)和[验收](data/experiments/h60_training_cutoff_v12/GATES.json)。

本轮基于8b70778217cc2e0405cd20b68e4a3ba9f51b6cd9完成单因素实验、必要检查和上传；没有获取行情、使用2026或发送真实/paper订单。[v12上传说明](review_upload/sync_v12_20260921/README.md)、[新增大文件路径/大小/哈希](review_upload/sync_v12_20260921/large_artifacts.csv)补充原[v8—v11清单](review_upload/sync_v8_v11_20260911/README.md)。旧结果及旧清单完整保留，精确提交以包含本文件的Git版本为准。

- 2016-01-05—2025-12-29、10bp普通单边成本：完整保护A净CAGR14.88%/全历史回撤17.74%，B13.69%/19.55%；同预算简单H60 A20.83%/21.15%，B18.22%/25.01%。共同2,453成熟日期Rank IC由0.1127降至0.0939。全部35条主/压力结果见[all_results](data/experiments/h60_training_cutoff_v12/all_results.csv)，14条B新结果及21条原A/SPY结果均核对账本；未用最好相位代替主结果。
- B保留原rank_60、81特征、Ridge(100,svd)，只改变年度部署前可用训练集；重新从完整面板筛选Date与exit_60均早于当年起点。2025训练78,300→85,860行，含1,830条原边界剔除行；全部75,240预测键保留。详见[53训练](53_train_annual_cutoff.py)、[独立检查](data/experiments/h60_training_cutoff_v12/INDEPENDENT_TRAINING_CHECK.json)。旧A协议不是泄漏错误，B上一年已纳入拟合，不能再称验证集。
- 运行/复核：现有`.venv\Scripts\python.exe`（Python3.12.2、requirements.txt，无新增依赖）。先[52旧v11只读验证](52_verify_frozen_research.py)，再53（完成后仅核验）、[54 --check-only](54_evaluate_training_cutoff.py)，[55汇总](55_summarize_annual_cutoff.py)只读原结果写报告。新计算须遵守冻结计划和预算，完成目录不覆盖。
- 52保留旧生成提交9d98008…及源码身份，用上传8b707…锚定原清单；当前复核提交/验证器哈希单列。703个唯一文件验证通过，提交号变化允许，真实源码或输入/模型/预测/结果变动仍拒绝。旧50源码和TRAINING_IDENTITY没有重写；**完成v11的只读复核请用52，旧50会因HEAD变化拒绝，不能作为当前复核命令**。
- 全账户30%预算按连续历史高水位，不随风险周期恢复重置。现有研究统计已独立核对；[虚构两次亏损/恢复](data/experiments/h60_training_cutoff_v12/drawdown_check/README.md)出现42.52%全历史回撤，证明20%周期暂停不是30%账户上限。未在主实验混入新风险控制。v12当时提出的[持续高水位控制及收益代价](data/experiments/h60_training_cutoff_v12/NEXT_QUESTION.md)已由上方v13回答；停止沿训练截止继续扫参数。
- A、B均未达30%收益目标，B拒绝升级；无独立验证通过模型，无2026候选冻结；真实paper回报和前瞻业绩均无新增。v8工程配置及v10代理继续使用原模型，没有切换为B。

v11历史成果保留：[完整报告](data/experiments/h60_signal_objectives_v11/REPORT.md)、[30次训练](data/experiments/h60_signal_objectives_v11/TRAINING_DETAILS.md)、[42条结果](data/experiments/h60_signal_objectives_v11/all_results.csv)。v11比较学习目标，最佳新增净CAGR16.29%仍未达标；其NEXT_QUESTION已由本轮v12执行，旧文档保留当时状态。原v8/v9/v10、v5/v6/v7与0/98未过记录均保留。

## 保留的v10 LEAN迁移

v10 LEAN 研究代理迁移已通过。见[v10结果与限制](data/experiments/lean_migration_v10/REPORT.md)、[完整实际引擎比较](data/experiments/lean_migration_v10/engine_runs/h60_full_01/PARITY.json)及[运行命令](tools/lean_runtime/README.md)。

- 实际LEAN引擎回放2511日/4951笔研究代理成交，原生进程退出0；每日权益与v8最大差5.60e-10美元。收益14.88%/回撤17.74%保持一致，仍未达到30%收益目标，不使用2026终测。
- 顺序：[47导出](47_prepare_lean_migration.py) → [LEAN事件与订单](lean_migration/main.py) / [共享策略适配](lean_migration/decision.py) → [48独立核对](48_compare_lean_migration.py) → [49汇总](49_summarize_lean_migration.py)。原策略代码保留未改；复用10份年度预测，新增训练0。
- [60日虚构冲击的真实引擎结果](data/experiments/lean_migration_v10/engine_runs/synthetic_risk_01/SYNTHETIC_CHECK.json)验证硬暂停/冷却/恢复；不能当成市场业绩或止损保证。
- 引擎固定上游提交加[本地退出兼容补丁](tools/lean_runtime/patches/native_shutdown_gil.patch)，运行时在`M:\quantconnect-lean-runtime\Lean`。实际身份、失败记录和本地材料见[报告](data/experiments/lean_migration_v10/REPORT.md)。通用盘中统计和一项可选并发分析存在限制，本轮用独立收盘账本核验。
- 当前LEAN入口是调整日线/碎股代理，尚未接原生美股公司行动、IBKR或持久化恢复。已保存记录中真实paper订单/实盘订单均0，无前瞻业绩；原生报价/公司行动适配仍是后续执行工程，v11训练未替换该入口。

### LEAN实际数据流

| 环节 | 实际源码行为 |
| --- | --- |
| 导入 | [47](47_prepare_lean_migration.py)读取原v5 `all_scores.csv`中的H60预测分数，导出`package.json`的`scores`、历史风险值、日历、策略参数和原调整行情的阶段CSV。训练与模型预测已在外部完成；模型SHA是身份记录，LEAN不重新训练或推理，也不导入现成目标仓位或交易清单。 |
| 生成决策 | [H60Decision](lean_migration/decision.py)按阶段接收价格，读取上一观察日分数及当时已知风险，调用共享`scheduled_weights`及`reduction_weights`，根据LEAN当前持仓、现金重新计算目标权重与买卖股数。止损、冷却和暂停状态也在本次回放中更新。 |
| 订单与成交 | [LeanLedger和模型](lean_migration/main.py)向LEAN提交`market_order`。项目自定义`H60ProxyFillModel`指定日线代理成交价并立即全额成交，`H60ProxyFeeModel`计费；LEAN订单引擎产生`OrderEvent`并更新现金、费用与持仓。不是默认真实撮合、真实券商回报或已下发的券商保护单。 |
| 事后核对 | [48](48_compare_lean_migration.py)才读取v8目标/交易/权益作为参照，与LEAN新生成账本比较，并逐笔关联真实引擎成交回调、重建现金和股数；参照交易不驱动LEAN决策。 |

OPEN 09:30／RANGE 12:00／CLOSE 16:00是人工阶段顺序，RANGE使用整日日线Low，不能解释为中午已知报价；调整价格和碎股仅用于与旧研究口径一致。[实际运行配置](data/experiments/lean_migration_v10/engine_runs/h60_full_01/executed_config.json)为`backtesting`、`live-mode=false`、本地文件数据源；[完成记录](data/experiments/lean_migration_v10/engine_runs/h60_full_01/completion.json)和[进程记录](data/experiments/lean_migration_v10/runtime/h60_full_01.run.json)对应2511日、4951笔历史代理成交及退出码0。

v11三组新模型及v12年度更新B均未通过收益门槛，未接入此LEAN入口。v8的[26笔虚构执行记录](data/experiments/h60_risk_execution_v8/execution_v5/completion.json)明确标记报价/成交虚构、真实paper成交0、前瞻观察0；它的持久化恢复功能尚未迁入LEAN。最近保留的[IBKR只读探测](data/experiments/h60_risk_execution_v8/IBKR_READINESS.json)为2026-09-09，未连接、未确认paper身份；本轮未重新探测，不能据旧记录推断此刻TWS状态。

当前具体缺口：原生美股报价/公司行动、真实paper运行入口、部分成交期间的持续保护、保护撤换窗口及长期断线补账。不能删除v10的历史模式限制后直接用于paper；v8原型已实现的功能也不等于LEAN集成已完成。

## 保留的v9数据接入口

v9更新：2026-09-11 UTC（洛杉矶09-10），本地历史股票池/终止事件接入口。见[v9本轮结果](data/experiments/universe_delisting_v9/REPORT.md)、[输入契约与命令](data/experiments/universe_delisting_v9/DATA_CONTRACT.md)、[来源复核](data/experiments/universe_delisting_v9/SOURCE_ASSESSMENT.md)。

- 用户确认暂时没有订阅；本轮完成[46入口](46_check_historical_universe.py)、[核心模块](historical_universe.py)与[13项检查](tests/test_historical_universe.py)，没有采购或连接供应商/券商。
- 真实ATVI公开事件＋假设10股得到应收950美元、可用现金0；没有真实账户收款证据或收益计算。[实际输出](data/experiments/universe_delisting_v9/completion.json)、[事件表](data/experiments/universe_delisting_v9/atvi_event_timeline.csv)分别记录。
- 两个时间边界控制成员变化，停牌/终止单独控制交易资格；未知终止不补0，已含退市收益不重复相加。Norgate不提供退市收益/退市后事件，来源复核修正了旧说明。
- 完整授权股票池、退市总体覆盖及旧代码的动态股票池接入仍未完成；没有消除存续偏差。本轮训练0、策略回测0、交易0，2026未使用。v8研究结论与所有原产物保留。
- 默认运行：`.\.venv\Scripts\python.exe 46_check_historical_universe.py`。原授权数据未来放入被Git忽略的`data/private/universe/`，不直接上传原始授权库。v9接口、公开案例及限制均列入本次同步清单。

## 保留的v8策略与执行审阅

v8更新于2026-09-09 UTC。同步前审阅基线提交`9d98008d72f096c2c1fa33a998f000fe62c48bb5`；v8—v11同步后的版本以本次上传记录为准。首次上传索引另存[历史索引](data/experiments/h60_risk_execution_v8/PREVIOUS_REVIEW_INDEX.md)。

**先读[本轮完整报告](data/experiments/h60_risk_execution_v8/FINAL_REPORT.md)。主候选净CAGR14.88%、收盘最大回撤17.74%，未达到最低30%收益目标，拒绝升级，不使用2026终测。** 目标仍为30%、争取50%；回撤优先约20%、30%是预算上沿；不加杠杆、不降低门槛。当前没有通过盈利验证的自动交易模型。

## v8进度与身份（历史记录）

- 固定30只存续美股及SPY；新增训练0次，复用2016—2025十份H60 Ridge原模型/预测，81个原特征、alpha100、svd。哈希、训练观察和标签成熟日期见[TRAINING_RECORD](data/experiments/h60_risk_execution_v8/TRAINING_RECORD.json)。
- v6/v7非计划减仓现在只减少股数，target_vol接通SPY仓位公式；软减仓与硬暂停独立配置。原v7排名12缓冲、软恢复、冷却/趋势/调仓日复仓保留。
- 唯一主候选沿用最多8股、集中度约束、SPY波动缩仓、15%个股保护和20%硬暂停，仅关闭10%软减半。失败后没有追加参数或挑相位。原0/98未过全部统计门槛的记录不变。
- 新工程入口43使用2025 H60文件`data/experiments/extended_history_v5/2025_ridge_h60_price.joblib`，SHA256 `2c19480278678e72fb9303e4f615737abccfa2c7dac883893af36390c2365ece`。不是2026部署模型；旧23/m16演练及账本完整保留。
- [最新虚拟工程清单](data/experiments/h60_risk_execution_v8/ENGINEERING_STRATEGY_MANIFEST_v5.json)包含模型、特征、标签边界、风险参数、调仓日历和源码SHA256。[未启用paper清单](data/experiments/h60_risk_execution_v8/PAPER_ENGINEERING_MANIFEST.json)另用1,000美元预算/独立策略ID。两者都是工程配置，未冻结用于2026终测的候选。

## 优先阅读

| 主题 | 源码与记录 |
| --- | --- |
| 事前计划及验收 | [PLAN](data/experiments/h60_risk_execution_v8/PLAN.md)、[机器计划](data/experiments/h60_risk_execution_v8/plan.json)、[全部门槛](data/experiments/h60_risk_execution_v8/GATES.json) |
| 修复及实际历史影响 | [research_backtest](research_backtest.py)、[profit_priority_strategy](profit_priority_strategy.py)、[robust_strategy](robust_strategy.py)、[bug差值](data/experiments/h60_risk_execution_v8/bug_impact.csv)、[回归测试](tests/test_risk_fixes.py) |
| 固定比较与原输入 | [42](42_evaluate_h60_risk_fixes.py)、[h60_research_inputs](h60_research_inputs.py)、[INPUT_IDENTITY](data/experiments/h60_risk_execution_v8/INPUT_IDENTITY.json) |
| 全部结果、年度和压力 | [12条主要比较](data/experiments/h60_risk_execution_v8/comparison.csv)、[全部39条](data/experiments/h60_risk_execution_v8/all_results.csv)、[年度](data/experiments/h60_risk_execution_v8/annual_results.csv)、[15条压力](data/experiments/h60_risk_execution_v8/stress_comparison.csv)、[执行原因](data/experiments/h60_risk_execution_v8/trade_reason_summary.csv)、[逐笔/每日](data/experiments/h60_risk_execution_v8/backtests) |
| 共享策略和前瞻评分接口 | [H60Runtime](h60_strategy_runtime.py)、[协调器](h60_execution_cycle.py)、[原模型评分核对](data/experiments/h60_risk_execution_v8/FORWARD_SIGNAL_INTERFACE_CHECK.json) |
| 持久化与paper适配器 | [H60Executor](h60_execution.py)、[IBKR paper](h60_ibkr_paper.py)、[43入口](43_run_h60_simulation.py)、[配置模板](config/h60_paper.example.json)、[执行说明](data/experiments/h60_risk_execution_v8/EXECUTION_GUIDE.md) |
| 虚构执行及恢复证据 | [最新执行](data/experiments/h60_risk_execution_v8/execution_v5/completion.json)、[重复启动](data/experiments/h60_risk_execution_v8/execution_v5/REPEAT_RUN.json)、[持久状态](data/experiments/h60_risk_execution_v8/execution_v5/state.json)、[44故障入口](44_test_h60_recovery.py)、[三进程恢复](data/experiments/h60_risk_execution_v8/execution_faults_v2/completion.json)、[测试](data/experiments/h60_risk_execution_v8/TESTS.json) |
| 历史股票池/退市数据 | [实际可用性、许可、接口及代码改点](data/experiments/h60_risk_execution_v8/HISTORICAL_UNIVERSE_TASK.md) |
| 原训练及上轮反思 | [35](35_extend_historical_diagnostic.py)、[38](38_train_robust_strategy.py)、[39](39_evaluate_robust_strategy.py)、[40](40_evaluate_profit_priority.py)、[旧反思](data/experiments/strategy_reflection_20260909/REFLECTION_AND_RESULTS.md) |
| 原特征、标签和统计检验 | [research_features](research_features.py)、[research_horizons](research_horizons.py)、[research_evaluation](research_evaluation.py)、[旧v3报告](data/experiments/continuous_research_2h_v3/FINAL_REPORT.md) |

## v8环境与运行顺序（历史复现）

解释器`M:\ml项目\.venv\Scripts\python.exe`，Python3.12.2，依赖见[requirements.txt](requirements.txt)；LEAN另需上述运行时与兼容补丁。以下为历史复现命令，本次上传不执行。先看报告、计划和代码；克隆缺原大文件时，先按下方ZIP清单恢复并核对SHA256。

```powershell
Set-Location 'M:\ml项目'
.\.venv\Scripts\python.exe 42_evaluate_h60_risk_fixes.py
.\.venv\Scripts\python.exe 43_run_h60_simulation.py
.\.venv\Scripts\python.exe 44_test_h60_recovery.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe 45_summarize_h60_v8.py
```

42完成后核对固定身份并保留结果，不拟合；43默认虚构报价/券商并复用持久状态；44使用虚构券商做跨进程故障；45只汇总保存结果。它们不下载行情或连接实际券商。不要为审阅运行旧03—41整条链，部分脚本会下载、训练或改写旧输出。

只读IBKR探测：`.\.venv\Scripts\python.exe 43_run_h60_simulation.py --check-ibkr`。paper恢复核对命令及最少配置步骤见执行说明；没有后台交易服务或实盘模式。

## 收益口径与证据边界

统一2016-01-05—2025-12-29、初始10,000美元、收盘估值、最终开盘清仓、零息现金、无杠杆；研究采用调整OHLC/碎股收益代理。主要普通单边10/20bp，止损额外10bp，压力另列。费用是全区间累计金额，换手计双向交易额。

10bp下：修正后止损开/软减仓开12.16% CAGR、15.37%回撤；主候选14.88%/17.74%；同一事前80%预算简单H60为20.83%/21.15%，SPY为9.75%/17.57%。事前预算相同不表示实现波动相同。主候选约十年累计净收益299.39%；高成本压力11.29% CAGR/25.70%回撤。全部属于反复使用的开发历史，不能宣布独立验证通过。

非计划减仓旧版确实产生买单：v7完整99笔→0，CAGR11.32%→12.16%，回撤15.37%不变。其他配置改善或下降均保留。SPY缩仓分子15%不是组合波动15%的承诺，20%硬暂停也不是最大回撤20%的保证。

73项测试只覆盖对应虚构场景；H60工程26笔成交全为虚构，重跑新增意图/成交0。3个真实OS进程、2次刻意中断验证恢复，但券商和资金仍虚构。真实paper回报0、前瞻业绩0。保护单撤换存在暂缺窗口，尚未验证真实撮合与长期断线补账。

## 2026与未完成事项

- 市场原快照截止2025年末，本轮未读取/下载/评估2026行情。候选失败，不消耗终测。原SEC全量快照含2026后续事实，历史特征按公开日期过滤；不能泛称项目从未见过任何2026信息，本轮未用财报模型。
- [IBKR实际探测](data/experiments/h60_risk_execution_v8/IBKR_READINESS.json)时间2026-09-09 08:30:52 UTC：常用paper端口7497/4002无监听，未握手、未确认paper身份、未查询行情权限、订单0。未对所有自定义端口作结论。
- 盈利不足，存续偏差/退市覆盖及独立验证未解决。v8当时建议先补历史股票池/退市样本；v9已完成本地接入口，授权总体数据仍缺。当前下一步以上方v13审阅入口为准；旧v11 [NEXT_QUESTION](data/experiments/h60_signal_objectives_v11/NEXT_QUESTION.md)保留当时状态，已由v12回答。
- 工程仍需Paper TWS/Gateway登录、隔离身份/预算、实时报价权限、精度及公司行动确认。当前年度模型不能直接产生2026信号；自动公司行动账本、保护撤换窗口、真实回报时序及长期断线恢复待验证。
- 未调用17/18，稳定实验身份/运行时间混用的旧问题未改；未重算H20/H60百分位集成，理论同分浮点问题未改，均未污染本轮单H60结果。

## 大型材料与复现

原大文件仍在`M:\ml项目\data\...`，精确路径、大小、SHA256、实验及命令见[旧大文件清单](review_upload/large_artifacts.csv)。[独立ZIP清单](review_upload/bundles.json)对应本地`M:\ml项目\review_bundles\20260909\`，每个不超过450MiB，保留原相对路径。v5/v6/v7模型、预测、行情没有删除、重训或用新数据替换。

v8产物在`data/experiments/h60_risk_execution_v8/`：39次逐笔/每日、全部失败方案、SQLite账本和故障记录；预测复用原v5 all_scores.csv，对应身份在INPUT_IDENTITY。文件的大小/SHA256见[ARTIFACTS](data/experiments/h60_risk_execution_v8/ARTIFACTS.csv)。旧审阅ZIP只代表首次上传；v8—v11本次进入Git或额外审阅ZIP的范围以新上传清单为准。
