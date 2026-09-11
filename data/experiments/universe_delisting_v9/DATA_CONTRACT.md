# 本地历史股票池接入口

入口是`46_check_historical_universe.py`，核心逻辑在`historical_universe.py`。只读取本地规范化文件，不调用供应商API、不训练、不读取报价或连接券商。当前只用于数据边界检查，旧H60特征/标签/交易引擎仍使用原固定30股。

一个包包含`manifest.json`、`memberships.csv`、`events.csv`。可直接查看[虚构样本](../../fixtures/universe_delisting_v9)及[真实公开事件包](../../reference/universe_events/atvi_2023)。

| 文件/字段 | 含义与限制 |
| --- | --- |
| manifest：evidence_kind | synthetic_fixture、public_event_case或licensed_local_export，明确证据等级；许可导出须local_use_confirmed=true，程序不验证这项声明的法律充分性。 |
| manifest：sources、file_sha256 | 来源链接/版本/时间精度，以及两个CSV的准确字节哈希；修改输入需另建新快照，不更新旧结果的身份。 |
| security_id | 稳定的证券身份，不用今天的ticker连接所有历史；案例ID和供应商ID的命名空间需明确。 |
| effective_at | 事件生效边界，必须有时区。公开案例的“开盘前”规范化到开盘，不冒充准确法律生效时戳。 |
| available_at | 我们允许开始使用该记录的信息边界；日期级公告按纽约日末保守处理，真实发布时间保持null/date_only。 |
| memberships：universe、member | 指数/研究股票池标识，明确的0/1成员事实；事件未生效或尚未知时不能提前应用。没有历史记录时状态未知。 |
| events：kind | active、halt、cash_entitlement、unknown_terminal。指数成员与可交易状态分开，未知交易状态不允许新开仓。 |
| events：cash_per_share | 仅现金终止可填写，明确的0与未知不同；未知必须为空并用unknown_terminal。只支持符合条件的普通股现金权利。 |

表头与参考文件完全一致。现金权利、实际到账和收益序列分开：

`can_open`只是成员/证券状态两项数据条件的结果，不是订单授权；报价新鲜度、可用现金和策略风控仍由执行模块检查。

1. `TerminalLedger.apply`只处理已生效且已知事件。符合条件的原股份转成应收现金，不能立刻增加可用现金。未知回收金额保留未解决状态，不消掉持仓，也不计算收益。
2. `settle`必须收到明确的到账回报才释放现金。重复回报不重复入账；金额不符、部分支付、代扣税费需要单独对账，不能猜测。当前没有实盘或paper的到账记录。
3. `combined_return`只检查收益口径，绝不是成交报价。独立普通收益r和退市收益d按`(1+r)*(1+d)-1`合并；供应商日收益已经包含退市影响时，禁止再加d。缺d保持未知，不补0。

同一时点冲突记录、同证券多个完整现金终止、跨次读取的另一ID重复终止均拒绝；当前不支持隐式订正。重放时钟不得倒退，也不能展示持仓种入前的快照。异常应用不会部分修改已有账本。

## 已运行的命令

```powershell
Set-Location 'M:\ml项目'
.\.venv\Scripts\python.exe 46_check_historical_universe.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_historical_universe.py -v
.\.venv\Scripts\python.exe 46_check_historical_universe.py --package data/reference/universe_events/atvi_2023 --universe SP500_PARTIAL_CASE --asof 2023-10-16T09:30:00-04:00
```

默认示例在完成后重跑只核对源码/输入身份，不改写旧结果。`--package`读取规范化包，只输出记录数、成员/可开仓数量、证据等级与哈希，不打印授权库的原始行。把asof改为`2023-10-18T09:30:00-04:00`可比较指数移除后的结果。

## 接下来如何接授权文件

用户本轮确认暂时没有订阅。未来拿到导出后，原始文件先放被Git忽略的`data/private/universe/`，保留供应商原始格式、来源版本、截至日期和许可范围。先对照实际字段编写一个明确映射，生成上述规范化包，再核对成员变更和终止事件。不要在没有见过真实供应商导出的情况下硬编码列名或自动假设退市金额为0。

还缺完整历史成员、价格/总收益、终止支付/缺失标记和可用时间证据。Norgate包与CRSP格式的限制见[SOURCE_ASSESSMENT.md](SOURCE_ASSESSMENT.md)。原固定30股模块的改点仍见v8数据任务；本轮先建立接入口，没有宣称已经移除存续偏差。
