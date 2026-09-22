# v16 Free观测结果保存边界

2026-09-22实际核读QuantConnect官方文档；以下是平台限制，不是已经下载成功的证据。v16不升级、不写Object Store、不导出供应商原始行情。

|途径|本次核实的限制|v16用途|
|---|---|---|
|回测日志|Free每次10KB、滚动24小时3MB|紧凑的归因总额、逐月/逐证券派生损益和核对摘要；预留引擎日志空间，不逐行情记录|
|自定义图表|Free最多10个series，每个4000点|少量具有正常时间轴含义的权益/损益/现金分配曲线；不把记录编码成虚假价格点|
|Runtime Statistics|最多50项，名称/值各最多200字符，编码值忽略|少量可读的终值、残差、数量检查；不作为分块数据传输|
|原生Results/Orders|官方界面提供运行统计、图表、Overview、Orders的结果下载|优先复用原运行订单与成交记录；下载打不开时记录工具/界面阻塞，不绕过URL策略|
|Object Store|Free不具备写权限；下载另受Institution及派生数据协议限制|本轮不依赖该途径，不把内存观察器当作永久归档|

直接来源：[Resources](https://www.quantconnect.com/docs/v2/cloud-platform/organizations/resources)、[Backtesting Results](https://www.quantconnect.com/docs/v2/cloud-platform/backtesting/results)、[Runtime Statistics](https://www.quantconnect.com/docs/v2/writing-algorithms/statistics/runtime-statistics)、[2026-09-17官方文档更改说明](https://www.quantconnect.com/docs/v2/meta/change-log)、[Object Store](https://www.quantconnect.com/docs/v2/cloud-platform/object-store)。

官方Object Store说明将“算法产生的结果值”经图表/Results或配额内日志保存列为替代方法；[Logging](https://www.quantconnect.com/docs/v2/writing-algorithms/logging)和[读取日志API说明](https://www.quantconnect.com/docs/v2/cloud-platform/api-reference/backtest-management/read-backtest/logs)同时明确不允许经日志导出数据集信息。两者应共同遵守：允许的账户损益和交易解释，不等于获得完整RAW OHLCV、证券映射或全候选表的再分发许可。更详细的成交价格优先在原生Orders/Trades中核验。

实现建议：先在云内计算完整归因，将必要派生摘要按重要性输出；总自定义日志预算留在约8.5KB以内，计入每行前缀/时间戳后再验收。编码或压缩不会改变内容权限：不能隐藏输出供应商RAW价格、原始美元成交额或事件源字段，也不能通过假时间轴或多次变换字段运行规避限制。若压缩允许分享的账户归因摘要，仍须记录明文schema、完整性哈希、解码后字段范围及实际日志字节数，不能宣称因此获得数据导出权限。若摘要超限，保留总额、逐月、重点来源和明确剩余缺项，不能声称未保存的完整逐证券记录已经可恢复。图表和日志仍需实际检查可读、行数完整、身份对应；文档允许不等于这次浏览器已成功取得。

原生订单包含多少小数位、Trade表采用何种区间划分，以及下载/复制是否完整，应在实际读取后单独验证。若本轮采用页面显示的四舍五入数值，必须标注该精度，并用原运行精确汇总核对残差；不能将金额显示精度冒充原成交完整精度。
