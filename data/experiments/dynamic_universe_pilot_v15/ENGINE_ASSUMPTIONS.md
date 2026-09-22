# v15 引擎口径与资料核对

核对日期：2026-09-22。本页解释固定PLAN的实现依据，不是新的选股或成本设计。实际云端版本及运行结果以本轮运行身份和报告为准；以下本地参考源码为LEAN提交`8ee075a39918f2df6fe9e0a5944e366fb60d10dc`，路径`M:\quantconnect-lean-runtime\Lean`。文档和源码核对不替代实际云端门槛。

## 时间、股票范围与原生订单

- `SecurityReference.SecurityType == ST00000001`表示普通股；配合`HasFundamentalData`定义本轮平台Fundamental覆盖的普通股范围，不代表S&P500、全部美国证券或完整OTC。筛选只按当时提供的RAW价格及美元成交额，稳定SID破同分。[分类源码](https://github.com/QuantConnect/Lean/blob/8ee075a39918f2df6fe9e0a5944e366fb60d10dc/Common/Data/Fundamental/Generated/SecurityReference.cs#L86)
- `Fundamental.Time`与`EndTime`相差一天；引擎把T日数据推迟到T+1交付，明确用于防止前视。保存观察时间、EndTime、回调/决策时间，不把今日下载或历史引擎时间当原始公告接收证明。[Fundamental.ForDate](https://github.com/QuantConnect/Lean/blob/8ee075a39918f2df6fe9e0a5944e366fb60d10dc/Common/Data/Fundamental/Fundamental.cs#L79)、[订阅工厂](https://github.com/QuantConnect/Lean/blob/8ee075a39918f2df6fe9e0a5944e366fb60d10dc/Engine/DataFeeds/Enumerators/Factories/BaseDataCollectionSubscriptionEnumeratorFactory.cs#L72)
- 纯日线回测的定时事件可能到下一数据slice才触发，而且Scheduled事件先于OnData更新。本轮SPY盘后分钟订阅仅供应实际16:05时钟；收盘估值须按当天交易所正常收盘，包括提前收市日，不能用16:05盘后价。[调度规则及执行顺序](https://www.quantconnect.com/docs/v2/writing-algorithms/scheduled-events)
- 原生Equity日线MOO使用后续合法TradeBar的Open，拒绝同根、旧数据；日线回报时间可能是当日收盘。另存价格所代表的开盘时刻与引擎接收时刻，不能混称真实9:30成交回报。SPY分钟订阅仍用原生MOO，成交回报频率与其他日线证券不同。[EquityFillModel源码](https://github.com/QuantConnect/Lean/blob/8ee075a39918f2df6fe9e0a5944e366fb60d10dc/Common/Orders/Fills/EquityFillModel.cs#L482)、[官方成交规则](https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/trade-fills/supported-models/equity-model)
- 允许自定义费用模型，保持原生成交模型。MOO实际费用按成交开盘价计算10/20bp，并用OrderEvent逐笔核对，不能以当日Close误计费用。费用模型也会被用于事前购买力估算，因此估计与实际成交核对必须区分。[引擎费用调用](https://github.com/QuantConnect/Lean/blob/8ee075a39918f2df6fe9e0a5944e366fb60d10dc/Brokerages/Backtesting/BacktestingBrokerage.cs#L343)
- Equity现金账户默认是1倍SecurityMarginModel及延迟结算；CashBuyingPowerModel要求货币对接口，不能直接套到Equity。提交和成交前均检查购买力，未成交卖单不能当现有现金。本轮采用PLAN固定两阶段MOO及即时结算研究假设，保持1倍/整股/90%预算，并核验现金、仓位和拒单；不保证跳空时一定足额成交。[默认模型](https://github.com/QuantConnect/Lean/blob/8ee075a39918f2df6fe9e0a5944e366fb60d10dc/Common/Brokerages/DefaultBrokerageModel.cs#L291)、[提交检查](https://github.com/QuantConnect/Lean/blob/8ee075a39918f2df6fe9e0a5944e366fb60d10dc/Engine/TransactionHandlers/BrokerageTransactionHandler.cs#L937)、[MOO资金缓冲说明](https://www.quantconnect.com/docs/v2/writing-algorithms/trading-and-orders/order-types/market-on-open-orders)

## 公司行动与账本

- Warning只记录，不产生策略退出信号。当前原生回测对Delisted构造MarketOrder，按`security.Price`最新缓存价全部清仓，`OrderFee.Zero`，绕过正常费用模型。单列日期、持仓、金额和零费；这不是最终清算回收或真实到账证明。同时间生成并处理的引擎强平，不能套用策略MOO的严格先提交后成交时间检查。[Warning不操作](https://github.com/QuantConnect/Lean/blob/8ee075a39918f2df6fe9e0a5944e366fb60d10dc/Brokerages/Backtesting/BacktestingBrokerage.cs#L525)、[原生清算](https://github.com/QuantConnect/Lean/blob/8ee075a39918f2df6fe9e0a5944e366fb60d10dc/Engine/TransactionHandlers/BrokerageTransactionHandler.cs#L1566)
- RAW持仓分红直接计入现金。源码明确未正确模拟实际支付日；本轮称LEAN现金入账口径。动量使用SplitAdjusted价格收益，分红只在实际持仓现金记账，不再叠加总收益价格。[分红源码](https://github.com/QuantConnect/Lean/blob/8ee075a39918f2df6fe9e0a5944e366fb60d10dc/Common/Securities/SecurityPortfolioManager.cs#L789)、[公司行动文档](https://www.quantconnect.com/docs/v2/writing-algorithms/securities/asset-classes/us-equity/corporate-actions)
- RAW拆股改变股数和成本；整股截断留下的碎股由引擎现金补差。独立现金核对必须计入该补差，并保留其价格代理口径。公司行动已由引擎处理，策略不能再重复调整实际持仓。[拆股及碎股现金](https://github.com/QuantConnect/Lean/blob/8ee075a39918f2df6fe9e0a5944e366fb60d10dc/Common/Securities/SecurityPortfolioManager.cs#L819)
- 退出当期股票池不表示已有持仓或权利消失。未知缺价只能标记并保留估值限制，不能补出成交；原生终止清算的未核实回收需另列保守情景。两年开发历史不构成独立验证。

## Free环境保存边界

官方目前明确Free组织不能写Object Store；付费但无派生数据导出协议的组织也不自动具有下载权。不能把Object Store写入作为免费试点前提，也不能用日志、转换格式或私有Git绕过原始数据限制。[Object Store访问及导出限制](https://www.quantconnect.com/docs/v2/cloud-platform/object-store)、[数据许可](https://www.quantconnect.com/docs/v2/cloud-platform/datasets/licensing)

供应商原始候选、行情、映射/事件在许可云环境中处理。云端回测保留引擎代码快照、订单及原生结果；Git保存代码、运行身份、允许分享且不能还原数据的聚合检查与报告。未实际持久化的附加内存旁表不能称已备份；若Free无法保存补充账本，应在交付中明确说明。

官方`Debug`每条最多200字符且有浏览器限流；聚合JSON应使用`Log`并控制总量，不能假设长Debug完整保留。当前文档按组织等级限定日志总量；本地`Controls`默认10000字节/回测仅是参考默认值，不证明当前云组织配额。运行结果须检查摘要完整性，不以分块刷Debug或日志导出原始数据规避限制。[当前日志说明](https://www.quantconnect.com/docs/v2/writing-algorithms/logging)、[本地默认控制值](https://github.com/QuantConnect/Lean/blob/8ee075a39918f2df6fe9e0a5944e366fb60d10dc/Common/Packets/Controls.cs#L142)
