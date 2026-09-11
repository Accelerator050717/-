# 数据来源复核：2026-09-11 UTC

用户已确认目前没有订阅，本轮只完成本地接入口。没有购买、注册、登录、请求授权行情或2026市场数据。Python环境未安装norgatedata/wrds，标准路径未发现Norgate Updater；账号状态以用户答复为准，不从软件缺失推断账号不存在。

## 对上一轮说明的具体修正

**Norgate不提供退市原因、退市收益或退市后的事件。** 它可补历史成员及退市证券价格，但不能单独交付完整终止现金账本；最后交易价格不等于一定能成交的退出价。资本事件标志也不是支付明细。[官方FAQ](https://norgatedata.com/data-package-faq.php)、[厂商Python接口](https://pypi.org/project/norgatedata/)

| 来源 | 可用接口/内容 | 当前缺口 |
| --- | --- | --- |
| Norgate US Stocks Platinum/Diamond | database枚举在市/退市资产ID；price_timeseries、index_constituent_timeseries；major_exchange_listed_timeseries区分主板/OTC。 | 历史成员标志不自动给出公告时间；主板退至OTC不等于证券终止；终止支付需另一来源。无已授权会话。 |
| CRSP，经WRDS或授权交付 | PERMNO历史身份、收益/分配/退市资料及历史S&P500成员工具；Python/PostgreSQL或文件导出。 | 实际产品版本和权限未确认；退市收益可能缺失，不能补0。CIZ日收益已纳入退市影响，不可机械再添加一次。 |

依据：[Norgate内容](https://norgatedata.com/data-content-tables.php)、[WRDS访问方式](https://wrds-www.wharton.upenn.edu/pages/about/3-ways-use-wrds/)、[历史S&P500工具](https://wrds-www.wharton.upenn.edu/pages/classroom/the-sp-500/)、[WRDS CIZ事件研究示例](https://wrds-www.wharton.upenn.edu/pages/wrds-research/macros/run-an-event-study-ciz-format-macro/)。本轮没有见到真实授权导出的表，代码未假设某版本字段已经可读。

Norgate现行条款允许个人投资/交易，限制其他商业用途与再分发，不能扩张解读为任何自动执行或LLM使用情形均获许可。其三周试用仅覆盖两年历史，当前不能默认含2023 ATVI。[EULA](https://norgatedata.com/subscribe/eula.php)、[试用说明](https://norgatedata.com/freetrial.php)

WRDS校园权限限学术/非商业研究，不能推定为个人自动交易许可；其AI政策原则上限制将数据输入LLM，CRSP列有需供应商确认的受保护企业版本例外，当前会话适用资格未确认。因此不要把未来拿到的校园原始导出直接贴进聊天或推送仓库。[使用条款](https://wrds-www.wharton.upenn.edu/users/tou/)、[AI政策](https://wrds-www.wharton.upenn.edu/pages/about/ai-policy-on-chatgpt-and-other-generative-ai-tools/)

## 已用的公开最小案例

ATVI在2023年的停牌、现金权利和指数移除有公开一手文件。本轮只保存短事实和链接，假设股数为测试输入，没有采集行情或推断实际账户支付日。具体来源、时间规范化和股份适用边界见[FACTS.md](../../reference/universe_events/atvi_2023/FACTS.md)。公开个案能验证数据逻辑，不能替代完整股票池和退市总体覆盖。
