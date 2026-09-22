# 唯一诊断回放的长日志完整性问题

实际回放`3f5d23c2dd0ee166d0bbaa1699553c03`完成。按本次浏览器观察，`v16_log_bytes`为8704；保存的`DIAGNOSTIC_LOG.txt`去掉文件换行后只有8172个ASCII字符，末尾没有JSON闭合。这一已取得文件不能通过完整payload SHA校验，也不能因为账户终值一致而视作所有归因明细已完整保存。截断文件SHA256为`d0ebbeff2ba06736e9dd9c94341abcce317d69905d200d39b097a555ce035c51`；意图消息与已取得消息相差532字符。

独立核读本地LEAN提交`8ee075a39918f2df6fe9e0a5944e366fb60d10dc`：

- [QCAlgorithm.Log](https://github.com/QuantConnect/Lean/blob/8ee075a39918f2df6fe9e0a5944e366fb60d10dc/Algorithm/QCAlgorithm.cs#L2882)仅加时间前缀并入队，没有单条8192截断。
- [时间前缀实现](https://github.com/QuantConnect/Lean/blob/8ee075a39918f2df6fe9e0a5944e366fb60d10dc/Common/Extensions.cs#L89)采用`yyyy-MM-dd HH:mm:ss`再加一个空格，恰为20字符。**8172+20=8192**，支持云端某处存在单条上限的解释，但不是已经定位到具体存储、API或UI组件的证明。
- [结果处理](https://github.com/QuantConnect/Lean/blob/8ee075a39918f2df6fe9e0a5944e366fb60d10dc/Engine/Results/BaseResultsHandler.cs#L1322)将同一message放入LogPacket和LogStore；[SaveLogs](https://github.com/QuantConnect/Lean/blob/8ee075a39918f2df6fe9e0a5944e366fb60d10dc/Engine/Results/BaseResultsHandler.cs#L604)直接写出LogEntry.Message，没有这一单行截断。云端可以使用重写实现，所以本地源码不能保证实际下载必定完整。

官方[Backtesting Results](https://www.quantconnect.com/docs/v2/cloud-platform/backtesting/results)提供普通GUI的Download Logs途径。因此优先检查该既有下载是否比DOM更完整，并比较字节、JSON闭合和原payload SHA；这属于读取已运行结果，不是第二次回放。不能绕过此前Download Results的浏览器URL安全拦截，也不通过新回放补日志。

若只能取回前缀，允许把流式解压后**已经完整出现的JSON字段**与原生订单、月度runtime统计等独立证据核对；必须保留缺失字段，且明确完整LZMA结束校验和全payload SHA尚不能验证。不得补造截断尾部，或把重新序列化后的哈希冒充原哈希。月度runtime已经独立保存不受此单条日志尾部问题影响，但它自己的完整性也应单独核验。

此前文档说明Free每回测10KB总日志配额，并未在本次查到的官方文字中明确记载这条8192单行上限。因此本次应记录为实际观察到的输出完整性限制，而非事后宣称已事先验证所有输出限制。
