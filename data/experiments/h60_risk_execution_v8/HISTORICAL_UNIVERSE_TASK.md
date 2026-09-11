# 独立数据任务：历史股票池、退市与许可

本轮已完成可用性和接口说明核查，没有购买订阅、登录、下载行情或扩充当前30股。2026价格仍未读取。本机环境没有`norgatedata`或`wrds`包，标准安装位置未发现Norgate Updater；这不等于证明用户没有任何订阅，只表示本轮没有已验证可调用的数据会话。

## 可落实的两条路径

| 来源 | 官方可提供的内容与接口 | 本轮确认的边界 |
| --- | --- | --- |
| Norgate US Stocks Platinum/Diamond | 退市证券、历史指数成员；Windows Updater配合Python。`database`枚举在市/退市资产；`price_timeseries`读取价格；`index_constituent_timeseries`读取逐日成员标志，用稳定assetid而非今天的ticker关联。 | 需有效对应订阅，当前无已验证安装/会话；“包含退市股”仍需核查收购现金、破产回收和最后一笔估值能否满足我们的退出账本。 |
| CRSP US Stock Database | 历史证券身份、日收益、公司行动和退市资料；可经有授权的WRDS Python/PostgreSQL接口或供应商文件交付读取。 | 本轮未验证用户/UCI的具体权限。应先确认所获产品及版本，再检查实际字段；不能假定旧版`RET`/`DLRET`就是新版表结构。 |

Norgate的官方覆盖和Python方法见[内容说明](https://norgatedata.com/data-content-tables.php)、[厂商Python包文档](https://pypi.org/project/norgatedata/)。其[现行许可](https://norgatedata.com/subscribe/eula.php)允许个人投资/交易用途，限制原始内容再分发；不能沿用这次Yahoo审阅ZIP的做法，把购买后的原始库直接传到GitHub或聊天。下一次采集前记录所适用许可版本及允许的使用/导出范围。

CRSP提供在市/退市历史，见[产品说明](https://indexes.morningstar.com/research-data-products/crsp-us-stock-databases)。WRDS提供[Python/PostgreSQL访问方式](https://wrds-www.wharton.upenn.edu/pages/about/3-ways-use-wrds/)，但[学术条款](https://wrds-www.wharton.upenn.edu/users/tou/)对学术/非商业用途有限制，[AI使用说明](https://wrds-www.wharton.upenn.edu/pages/about/ai-policy-on-chatgpt-and-other-generative-ai-tools/)也要求遵守各数据集约定；不能把校园研究权限直接推定为个人自动交易或LLM上传权限。没有获取、保存或展示账户凭据。

## 接入前的小样本验收

先取一个预定指数的一个固定历史月份，覆盖至少一个真实退市/并购案例和成员变更，输出`security_id,date,eligible_asof,announcement_time,effective_date,price_basis,tradeable,terminal_event,terminal_cash_or_return,source_version`。有效日期与公告可用时间必须分开：可投资列表只能使用决策时已经生效/可知的信息，不能提前用未来成员变化。

退市退出必须按来源明确含义计入最后现金或收益；未提供回收金额时保留未知及情景敏感性，不用最后价格无限前填，也不自动当成0%收益。CRSP不同版本可能已在日收益中包含退市收益；先检查字段标志，防止再乘一次造成双计。官方说明见[数据定义](https://www.crsp.org/crsp_pdf/crsp-us-stock-indexes-databases-data-descriptions-guide-crspaccess/)。

## 需要修改的明确位置（本轮不扩张策略）

- `panel_config.py: SYMBOLS`：改为按日期查询稳定证券ID的成员表，ticker仅用于当期展示与券商合约映射。
- `research_features.py: load_inputs/compute_features`：取消固定30列/每日必须30股的断言；按当日合法、已具备历史的成员计算截面秩，保留真实上市前空窗与内区间缺失区别。
- `research_horizons.py: build_targets/split_fold`及`35_extend_historical_diagnostic.py`：标签成熟不仅看价格行，还要处理持有期内退市/合并现金事件；组大小使用当日有效N，N不足时明确拒绝，不伪造价格补齐30股。
- `10_build_panel.py`、`12_train_ranker.py: check_groups`及固定`reshape(-1,len(SYMBOLS))`：改成逐日group sizes；样本数检查与NDCG/分位数均按当日可投资组定义。
- `28_train_multihorizon.py`及回测引擎：宽表可保留所有历史ID，但用资格/可交易掩码决定建仓；退市终止事件改变持仓、现金和估值，不能只丢掉某列。
- 执行模块：稳定ID与合约conId映射、拆股后的真实股数和保护数量、分红现金、并购退出需要独立公司行动账本；未知事件时保留原保护/阻断新增风险，不能拿调整OHLC直接下单。

优先下一步：核实并取得一种允许当前用途、含历史成员与退市处理材料的数据，然后完成上述小样本账本。未解决这项问题前，扩大今天仍存续的股票名单不能解决存续偏差；也不构成继续在同段历史筛参数的理由。
