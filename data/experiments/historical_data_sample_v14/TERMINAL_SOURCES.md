# TWTR与SIVB/SIVBQ：真实终止与生命周期证据

本子样本实际取得9份HTTP成功快照：2份SEC submissions JSON、2份完整8-K PDF、Nasdaq停牌公告及4份S&P成员公告。另16次403/超时保留为失败记录，绝不把错误页计作数据。两份Web工具摘取支持SEC/OCC原页面可读但本地HTTP受阻的项目，明确标为`web_tool_extraction_not_original_HTTP_bytes`。所有全文、PDF和派生全文仅在`data/private/universe/v14_public_sources/`，不上传Git。

## 实际事件

|证券|事实|生效日期|本样本信息边界|
|---|---|---|---|
|SIVB|S&P500加入|2018-03-19开盘前|2018-03-09公告日纽约日末|
|SIVB|Nasdaq停牌|2023-03-10 08:35:18 ET|Nasdaq页面2023-03-10 16:45 EST；不能据此反推早盘已收到|
|SIVB|S&P500剔除|2023-03-15开盘前|2023-03-10公告日纽约日末|
|SIVB|Nasdaq停牌转为上市资格暂停|2023-03-28，源仅日期|2023-03-17发行人8-K日期末|
|SIVB→SIVBQ|OTC代码与交割标识变更|2023-03-28开业时|OCC 52179于2023-03-27发布，日期末边界|
|SIVB/SIVBQ|Nasdaq正式移除上市|2023-05-12交易时段开盘|Form25附件于2023-05-02，日期末边界|
|SIVBQ|旧普通股注销，无分配|2024-11-07，源仅日期|2024-11-08提交8-K日期末|
|TWTR|S&P500加入|2018-06-07开盘前|2018-06-04公告日纽约日末|
|TWTR|股份变为每股54.20美元现金权利|2022-10-27，源仅日期|8-K正式filing date为2022-10-31，采用其日末；另有OCC 10-28日期级交叉证据|
|TWTR|NYSE交易暂停|2022-10-28开盘前|所选发行人8-K的10-31日期末|
|TWTR|S&P500剔除|2022-11-01开盘前|2022-10-27公告日纽约日末|
|TWTR|NYSE正式移除上市|2022-11-08开业时|NYSE Form25于2022-10-28，日期末边界|

“开盘前/开业时”的CSV边界按纽约09:30查询约定编码，源文件未给真实实施秒数；日期级事项采用纽约日末。原始精度均保留。成员变更、可交易状态、法律权利终止分别处理。上述有限公告不能证明全部中间成员变更都已捕获。

## 核心原始来源

- [TWTR发行人8-K](https://www.sec.gov/Archives/edgar/data/1418091/000119312522272772/d411753d8k.htm)及[下载的同一发行人文书PDF副本](https://d18rn0p25nwr6d.cloudfront.net/CIK-0001418091/84881052-8f1d-4857-bda8-2fdb55ebce68.pdf)：CIK0001418091、普通股股类、现金权利与交易暂停。CDN副本不是SEC归档原字节；文书编号及关键正文与SEC页面交叉核对。
- [TWTR NYSE移除通知](https://www.sec.gov/Archives/edgar/data/876661/000087666122000890/ruleprovisionnotice.htm)与[OCC现金调整51250](https://infomemo.theocc.com/infomemos?number=51250)：OCC的期权现金交割不是用户持有普通股的到账记录，不能把期权T+2当普通股收款日。
- [Nasdaq停牌原公告](https://www.nasdaq.com/press-release/nasdaq-halts-svb-financial-group-2023-03-10)：106.04美元是停牌时报告的最后成交价，绝非停牌后可执行价格或保证退出价。
- [SIVB发行人2023-03-17文书](https://www.sec.gov/Archives/edgar/data/719739/000119312523073665/d485308d8k.htm)、[OCC代码变更52179](https://infomemo.theocc.com/infomemos?number=52179)、[Nasdaq Form25附件](https://www.sec.gov/Archives/edgar/data/719739/000135445723000327/sivbdelistreason.txt)：母公司普通股CIK0000719739，OCC列CUSIP78486Q101；SIVB/SIVBQ为同一旧普通股的ticker阶段。
- [SIVB最终8-K](https://www.sec.gov/Archives/edgar/data/719739/000119312524254186/d904756d8k.htm)及[实际取得PDF副本](https://d18rn0p25nwr6d.cloudfront.net/CIK-0000719739/d6ba0fc4-dbb4-4689-9d00-efe5318f4743.pdf)：旧普通股确实没有重组分配；新母公司权益提供给相应债权人，不得接续为旧普通股价格历史。
- 成员公告逐项URL、下载时间、HTTP结果、大小和SHA256保存在`terminal_http_sources.json`；事实映射见`terminal_source_facts.json`。

## 信息质量与现金边界

这是真实文件的事后取证，不是当年收到的快照。SEC JSON的`acceptanceDateTime`保留原字面值，未当作已验证的公众首次可得时刻。TWTR受理时间与filing date分属10月28日和31日，因此所选8-K采用更保守的31日日末。

两项真实源冲突被保留：TWTR2018原HTML表头错误写成S&P MIDCAP500，但标题和正文明确S&P500；官方修订PDF仅改表头，修订时刻未知。SIVB剔除公告把母公司描述为FDIC接管，发行人文书明确接管对象为银行子公司、母公司后来申请Chapter11；本样本只采用该公告的指数事件。

TWTR为符合合并条款的旧普通股产生54.20美元权利，不含利息，实际到账/扣税/账户费用没有证据，保持应收。SIVBQ“零分配”有实际文书依据，不是将缺失回收补0；但终止收益序列、最终可交易价格仍缺。v9不支持这种明确零分配注销，旁表标记unsupported，不伪装为现金收购。FDIC存款保障不属于上述母公司普通股。

格式、身份与最小字段检查已运行；信息边界仅足够支持所声明的保守样本查询；行情/总收益及结算不足；完整股票池覆盖不足。0训练、0策略回测、0券商连接和0订单。

## 复核与恢复

```powershell
.venv\Scripts\python.exe tools\collect_v14_terminal_sources.py
.venv\Scripts\python.exe tools\check_v14_terminal_sources.py
```

下载器复用已哈希快照，不覆盖原文件；失败记录保持失败。成功文件若缺失或内容变化即报错。Web摘取来源URL和捕获类型保留在本地JSON，不能由下载器伪造HTTP成功。丢失的全文需要从原本地备份恢复；新取回文书必须另建检索版本，不能冒充本轮同字节快照。

PDF字段复核使用`tools/extract_v14_terminal_pdfs.py`和带`pypdf`的Python。本轮使用Codex自带Python，不改项目环境依赖。该脚本比较已有提取文本，变化时拒绝覆盖；原PDF始终保留。`terminal_source_checks.json`记录实际检查和本地材料哈希。
