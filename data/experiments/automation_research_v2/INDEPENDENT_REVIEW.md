# 第二批独立复查

本复查没有训练模型、修改其他人的实现、改变门槛或读取 2026 行情。采用已保存的真实 SEC 数据、模型和离线回放记录进行独立重算。

## 财务数据与日期

- 从 1,946 个申报事件的 provenance，用独立日期二分查找重建全部 75,420 行、8 个财务值，数值最大差为 0；8 个缺值标记全部一致。
- 11,781 个被引用的事实都能在对应原始 SEC JSON 中找到相同 tag、unit、accn、start/end、filed、value；原始文件哈希全部匹配元数据。
- 被使用事实均满足 period end ≤ filed，申报日当日不进入特征；次日才可在交易日上被选中。检查了实际申报日及其后一天的边界。
- 资产负债表比率使用相同 end/accn；全年利润率及配套现金流使用相同 start/end/accn，年度为 330—380 日的 10-K 或 10-K/A。
- 资产同比间隔为 330—400 日；report age 按财务期末计算。后来的重列申报不会让旧业绩期末变近。

这是今天 Companyfacts 快照经过历史 filed 过滤后的近似重建，不能证明原始版本没有被删除或改写。下载了 30 家公司的事实不代表每个指标完整：负债/资产缺 19,060 行、年度利润率缺 12,710 行。银行会计、概念口径、公开覆盖与公司重组也影响可比性。

## 训练填充与尺度

独立重新选择每个开发年份之前已经成熟的训练标签行，检查所有 36 个模型文件哈希、训练行数和最晚标签退出日。18 个含基本面 pipeline 的训练中位数与独立逐列中位数完全相同；全部 36 个 StandardScaler 的 mean/variance 与相应训练矩阵重算完全相同。没有发现从验证或开发年份借用填充值或标准化统计。

本批不存在整列训练期全缺失的实际情况；keep_empty_features=True 的防御性设置不等于此分支已经被真实数据触发。基本面缺失标记可能包含行业及披露覆盖差异，改善或恶化不能自动归因于某个财务比率的经济作用。

## 离线执行

对真实行情驱动的历史回放记录，独立从 42 条虚拟成交重建现金、持仓与费用，并用原始调整开盘价重建 30 个每日 NAV：现金最大差 1.38e-12、持仓最大差 3.55e-15、NAV 最大差 3.64e-12、成交代理价格差 0。6 次目标持仓均与冻结模型重新预测的 top5 一致，执行日期确为原交易日历的下一 session。

首遍新增 6 个已处理批次、42 条虚拟成交、126 个事件；第二遍新增成交、批次与事件均为 0，两遍最终快照相同。最后 NAV 为 10,663.639736246103，累计假设费用 61.02580985209978，仍持有股票，没有末尾清仓费。因此不能直接与强制清仓的同区间回测终值比较，更不能把这段开发历史涨幅当策略验证。

代码检查确认每次金融变更在锁内重读磁盘状态，意图、成交、费用和账户状态一起原子提交；同 key 不同意图被拒绝。我指出的“快照先于待成交目标而产生过时 NAV”边界已修正：到期目标未成交时不能封存快照，快照已封存后不能插入新成交。另有 initialized 标记，避免丢失旧账本后静默重新初始化资金。

实现方另记录 10 项明确使用虚构输入的单元测试通过，覆盖拒绝异常请求、重复键、乱序快照、双实例状态重读和旧账本丢失等边界。本独立复查没有重复运行这些测试。它们与上面基于真实历史行情的 42 条虚拟成交、30 个 NAV 重建是两类证据，都不是真实券商交易验证。

范围仍为本地离线工程回放：asof 是纽约交易日期及内部 open/close 阶段，并未验证实时 9:30 调度、DST 时间戳或行情报价年龄。20% 上限施加于目标及调仓后持仓；随后市价漂移不等于保持每天精确 20%。没有券商请求、真实成交、外部双写恢复或券商网络幂等保证。

## 结果解释

本批结果文件显示 0/44 个策略条目通过全部门槛。44 包含旧条目和重复控制，不能称 44 个独立方法。加基本面后三种模型的平均 Rank IC 均下降；top10 降低了成交量，但并非所有配置都改善回撤。应分别报告信息变化与仓位规则变化，避免只选择一个较好的收益格子。

本复查重点是财报日期、原始数值、训练统计和离线状态；没有再次执行前批已验证的 bootstrap 算法或重训模型。

## 可机器读取的记录

```json
{
  "reviewed_at_utc": "2026-09-09T04:55:35.326885+00:00",
  "fundamental_rows_reconstructed": 75420,
  "fundamental_value_columns": 8,
  "missing_indicator_columns": 8,
  "filing_events": 1946,
  "referenced_facts_found_in_raw": 11781,
  "max_fundamental_value_error": 0.0,
  "models_checked": 36,
  "fundamental_imputers_checked": 18,
  "max_training_median_error": 0.0,
  "max_training_scaler_mean_error": 0.0,
  "max_training_scaler_variance_error": 0.0,
  "model_hashes_all_match": true,
  "offline_virtual_fills": 42,
  "offline_batches": 6,
  "offline_snapshots": 30,
  "offline_cash_reconstruction_error": 1.3820056210533949e-12,
  "offline_units_reconstruction_error": 3.552713678800501e-15,
  "offline_nav_reconstruction_error": 3.637978807091713e-12,
  "offline_raw_price_error": 0.0,
  "offline_second_run_new_fills": 0,
  "offline_second_run_new_events": 0,
  "source_sha256": {
    "fundamental_features.py": "321f2408b33c39990a911f4efb5d513531f261b090c209da5e15bf4fddc76aa5",
    "offline_execution.py": "7b36ae3f445b19d8d6e08f545a5e13d16eb1958e47e9d1a6c8c7f1c22566e439",
    "22_train_fundamental_comparison.py": "c0f9debc92ba2a9faf936da1ad316ab3f4d6ae861a9969a0768c3fa9730adbb7",
    "data/processed/fundamental_panel_v1.csv": "0ce3aa88efcd26fa24dba2efac27aa4bc5b11676c1a67226a95fe838dadc8232",
    "data/processed/fundamental_provenance_v1.jsonl": "f060d568771beeb8ae1e9d1f97aa2031cffb768a57cbcb584e2d1ebd1cb9ac48",
    "data/experiments/automation_research_v2/plan.json": "d4bd06ef171c0e85c6b7b7f21105b9009ebfab542bf366b8fd4f0920cd98baf7",
    "data/experiments/automation_research_v2/training_summary.csv": "80cfd81943816a91877f5783d0f379c418aaf9086cf33f695185c781a71c4344",
    "data/experiments/automation_research_v2/comparison_new12.csv": "bd2413387995ffade52799add7c84e621e2e6d8c543d99844672891526fd0d79",
    "data/replays/offline_v1/state.json": "0c9993559d5975d49ea589a224aa19d2072a62cd9eeb9dd0cfaa51691d67d2bf"
  }
}
```
