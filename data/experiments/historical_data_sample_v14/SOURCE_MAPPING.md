# 从实际原始字段到v9的最小映射

原始字节保存在本地忽略目录，事实JSON、规范化CSV/旁表另存；没有用规范化结果覆盖来源。供应商授权查询为0，本包来源是公开一手事件证据，不是假称厂商数据库导出。

|实际来源与原字段|规范化处理|仍然不能证明|
|---|---|---|
|S&P公告的发布日期、Effective Date、Index Name、Action、Company Name、Ticker|原v9 memberships.csv；只记录S&P500局部事件|完整指数历史、全部中间变更、可交易状态|
|Tesla 11月16日初告与11月30日最终实施公告|初告保留旁证；最终公告生成12月21日开盘边界的加入事件；12月1日的非成员checkpoint是公告后的状态推断，单独计数，不是假造剔除事件|准确公告秒数、原始接收快照；公告前成员状态仍unknown|
|Apple 2024 10-K封面股类、代码、登记交易所|securities.json项目本地证券身份|2012—2025每一天的上市/指数成员/交易状态|
|Meta发行人公告Class A、FB、META、生效日期、CUSIP不变|同一项目证券ID的ticker_changes.json；有公告信息才解析新旧代码|数值CUSIP、全生命周期、旧代码被其他发行人复用后的任意拼接|
|Nasdaq停牌公告的08:35:18 ET和页面16:45 EST发布时间|v9 halt；发生与可得时刻分开；原文最后成交价仅保留为事实|早盘已收到消息、停牌后可成交价、最后可保证卖价|
|SIVB SEC/发行人8-K、Form25、OCC 52179|暂停、正式上市移除、OTC代码/市场变更分别进入lifecycle.json；不映射为证券最终终止|OTC持续行情、当日首笔成交、可执行报价|
|SEC submissions中的CIK、accessionNumber、filingDate、acceptanceDateTime|发行人身份与文书关联；受理原字面值保留，保守以filing date日末作为信息边界|CIK不是证券ID；受理字符串不是已验证的首次公众可得时刻|
|TWTR8-K现金对价和合格普通股范围|v9 cash_entitlement=54.20；股份转应收；停牌事件另存|账户收款日期、扣税/费用、总收益序列|
|SIVB2024注销且旧普通股无分配|明确金额0有文件依据；旁表unsupported_zero_distribution_cancellation，阻止用于完整收益核算|不能伪装为cash_entitlement=0、零元已到账或最后卖价；新重组股票不接到旧股|

日期级公告统一采用纽约日末保守信息边界；“开盘前”按09:30查询边界约定，法律生效仅日期的事项取日期末。它们是明确约定，不是测得的实施秒数。原字段的精度、来源日期、正文位置、冲突和理由保留在identity_source_facts.json / terminal_source_facts.json。

S&P两项原始冲突没有静默清洗：Twitter加入公告的错误表头按同一文件标题/正文解读，并保存修订说明；SIVB指数剔除公告仅提供成员变更，母公司与银行子公司关系采用发行人文件。修订出现时间和完整修订范围未知。

本地命名空间quantml-public的ID用于固定案例关联，不能冒充厂商全球永久标识。TSLA公告甚至没有给出精确法律股类标识，已列限制；AAPL、META成员缺证不自动填成True。两份ticker变化使用明确同一证券证据，不能仅因字符串相同就合并证券。

v9 KINDS只支持active/halt/cash_entitlement/unknown_terminal，本轮核心库完全未改。旁表扩充保留了未支持事实，但没有把它变成新的交易引擎。所有样本均training_ready=false；本轮不生成投资收益、不把不可估值旧账面数量当有效资产。
