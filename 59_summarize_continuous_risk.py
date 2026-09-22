"""Summarize completed frozen v13 artifacts; never replay, fit or submit orders."""
import importlib
import json
from pathlib import Path

import pandas as pd

from panel_config import ROOT
from h60_research_inputs import sha,save

OUT=ROOT/'data/experiments/continuous_fund_risk_v13'


def table(headers, rows):
    return '\n'.join(['| '+' | '.join(headers)+' |','| '+' | '.join(['---']*len(headers))+' |']+
                     ['| '+' | '.join(map(str,row))+' |' for row in rows])


def pct(value):
    return f'{100*float(value):.2f}%'


def pp(value):
    return f'{100*float(value):+.2f}'


def main():
    completion=json.loads((OUT/'evaluation_complete.json').read_text(encoding='utf-8'))
    for record in completion['files']:
        if sha(ROOT/record['path'])!=record['sha256']:
            raise ValueError('Frozen result changed: '+record['path'])
    results=pd.read_csv(OUT/'all_results.csv',float_precision='round_trip')
    pairs=pd.read_csv(OUT/'pair_deltas.csv',float_precision='round_trip')
    annual=pd.read_csv(OUT/'annual_results.csv',float_precision='round_trip')
    recoveries=pd.read_csv(OUT/'recovery_intervals.csv',float_precision='round_trip')
    gates=completion['gates']
    checks=json.loads((OUT/'RUN_CHECKS.json').read_text(encoding='utf-8'))
    mainrows=results.loc[results.scenario.eq('cost10')].set_index('case')
    protected=mainrows.loc['global_protected_cost10']
    simple=mainrows.loc['global_simple_h60_cost10']
    mainpairs=pairs.loc[pairs.scenario.eq('cost10')].set_index('configuration')
    plan=json.loads((OUT/'plan.json').read_text(encoding='utf-8'))
    newly=results.loc[results.variant.eq('global')]
    previous=importlib.import_module('51_evaluate_signal_objectives')
    mode_days=[];drawdowns=[]
    for row in results.itertuples():
        daily=(pd.read_csv(OUT/'backtests'/row.case/'daily.csv',index_col='Date',parse_dates=['Date'],float_precision='round_trip')
               if row.variant=='global' else previous.read_old(row.original_case)['daily'])
        trough=daily.drawdown.idxmin();prefix=daily.loc[:trough]
        peak=prefix.equity.idxmax() if prefix.equity.max()>=1 else None
        drawdowns.append(dict(case=row.case,peak_date=str(peak.date()) if peak is not None else 'INITIAL_CAPITAL',
            trough_date=str(trough.date()),peak_equity=max(1.,float(prefix.equity.max())),
            trough_equity=float(daily.loc[trough,'equity']),maximum_drawdown=float(daily.drawdown.min())))
        if row.variant=='global':
            for mode,count in daily.global_mode.value_counts().items():
                mode_days.append(dict(case=row.case,mode=mode,closing_sessions=int(count)))
    pd.DataFrame(drawdowns).to_csv(OUT/'drawdown_locations.csv',index=False)
    pd.DataFrame(mode_days).to_csv(OUT/'risk_mode_days.csv',index=False)
    dd_main=table(['配置','历史高点日','最大回撤谷底日','高点→谷底净值'],[
        [r['case'],r['peak_date'],r['trough_date'],f"{r['peak_equity']:.4f} → {r['trough_equity']:.4f}"]
        for r in drawdowns if r['case'] in ('original_protected_cost10','global_protected_cost10')])
    performance=table(['配置','净年化','累计收益','全历史最大回撤','年化波动','平均仓位','双边年换手','总显性成本/初始资金'],[
        [name,pct(r.cagr),pct(r.total_return),pct(-r.max_drawdown),pct(r.annualized_vol),pct(r.average_gross),
         f'{r.turnover_two_way_per_year:.2f}倍',pct(r.explicit_total_cost_per_initial_nav)]
        for name,r in [(('保护/原' if k=='original_protected_cost10' else
                       '保护/全局' if k=='global_protected_cost10' else
                       '简单H60/原' if k=='original_simple_h60_cost10' else
                       '简单H60/全局' if k=='global_simple_h60_cost10' else 'SPY/原'),r)
                      for k,r in mainrows.iterrows()]])
    comparison=table(['配置','场景','原→新年化','年化差pp','原→新最大回撤','回撤改善pp','新30%年化/30%回撤'],[
        [r.configuration,r.scenario,f'{pct(r.original_cagr)} → {pct(r.global_cagr)}',pp(r.delta_cagr),
         f'{pct(-r.original_max_drawdown)} → {pct(-r.global_max_drawdown)}',pp(r.delta_max_drawdown),
         ('达到' if r.global_cagr>=.30 else '未达到')+'/'+('范围内' if r.global_max_drawdown>=-.30 else '越过')]
        for r in pairs.itertuples()])
    occupancy=table(['配置/场景','减仓状态触发','全局暂停/复核锁/恢复','新方案周期暂停','空仓日原→新*','最长全局暂停','期末状态'],[
        [f'{r.configuration}/{r.scenario}',int(r.global_reductions),
         f'{int(r.global_pauses)}/{int(r.global_review_locks)}/{int(r.global_resumes)}',int(r.episode_halts),
         f'{int(results.loc[results.case.eq("original_"+r.configuration+"_"+r.scenario),"flat_days_excluding_final"].iloc[0])} → {int(r.flat_days_excluding_final)}',
         int(r.longest_global_pause_sessions),r.terminal_risk_mode] for r in newly.itertuples()])
    yearly=annual.loc[annual.case.isin(mainrows.index)].pivot(index='year',columns='case',values='return_net')
    order=['original_protected_cost10','global_protected_cost10','original_simple_h60_cost10','global_simple_h60_cost10','original_simple_spy_cost10']
    year_table=table(['年','保护原','保护全局','简单原','简单全局','SPY原'],[[int(y)]+[pct(row[k]) for k in order] for y,row in yearly.iterrows()])
    recovery_text=('固定历史区间未发生全局恢复，不能据此声称历史已验证恢复后的盈利或连续亏损预算。两轮亏损/恢复的逻辑由明确标注的虚构测试验证。'
                   if recoveries.empty else table(['配置','恢复日','结束/原因','恢复段交易日*','恢复后最深亏损','本恢复段结束回撤','恢复时剩余预算pp'],[
        [r.case,r.resume_date,f'{r.end_date}/{r.end_reason}',int(r.sessions),pct(r.minimum_return_since_resume),pct(r.end_cumulative_drawdown),
         f'{100*r.remaining_budget_high_water_fraction_at_resume:.2f}'] for r in recoveries.itertuples()]))
    triggered=sum(bool(v.get('global_triggered')) for k,v in checks.items() if k.startswith('global_'))
    untriggered=[k for k,v in checks.items() if k.startswith('global_') and not v.get('global_triggered')]
    pause_count=int(newly.global_pauses.sum()); lock_count=int(newly.global_review_locks.sum())
    status='通过' if gates['risk_value_gate_passed'] else '未通过'
    numerical='开发数值达到，仍未独立验证' if gates['protected_numerical_objectives_met'] else '未达到'
    text=f'''# v13 持续策略资金高水位：实际结果

**固定全局控制的风控价值门槛{status}；30%净年化及30%回撤组合目标{numerical}。不升级 A、不恢复 v12 B、不追加风控参数搜索。**

完整保护主场景净年化 {pct(protected.cagr)}，累计收益 {pct(protected.total_return)}，全历史最大回撤 {pct(-protected.max_drawdown)}。相对原策略年化变化 {pp(mainpairs.loc['protected','delta_cagr'])} 个百分点，最大回撤改善 {pp(mainpairs.loc['protected','delta_max_drawdown'])} 个百分点（负值是恶化）。简单 H60 是诊断，不具备完整个股保护，不能替代成品。

## 做了什么，依据是什么

新增模型拟合 **0 次**，复用原 A **10 份年度模型**及同一预测。新增全局历史回放 **14 次**，旧结果复用 **21 条**（14条A配对、7条SPY），另完成 **2次只记录历史一致性核对**。冻结前一次记账尝试已到末日但未完成全套验证，原数据库及中止原因保留在 `record_only/`，不计为新控制试验；CSV空文本表示修正后从完成账本恢复验证，没有重算或替换行情。

冻结时间 `{plan['registered_at_utc']}`；[PLAN](PLAN.md)、[机器计划](plan.json)、[输入身份](INPUT_IDENTITY.json)、[评估身份](EVALUATION_IDENTITY.json)、[运行记录](EVALUATION_RUN.json)分列源文件、模型和输入哈希及生成提交。完成后核验不把当前 Git HEAD 当输入，不冒充新训练。原 v8—v12、v5—v7 和0/98未过记录保留。

资金范围是**该自动策略持续管理的指定资金**，不是整个 IBKR 账户。外部持仓、现金和债务没有全账户归集。`scope_id`和独立身份标记固定；模型SHA与进程ID另记；重启、跨年和模型元数据变更不重置份额、高水位或亏损。

## 主结果与全部固定压力

{performance}

成本已扣入收益；“总显性成本/初始资金”是十年普通费用及止损附加滑点的累计金额，**不是年费率或年化收益扣减百分点**。普通单边10bp，止损附加10bp；高成本和延迟按冻结方案。价格是原调整OHLC/碎股代理，零现金利息，初始净值1，末次开盘清仓，收盘估值。主区间2016-01-05—2025-12-29；不同固定相位沿原日历，不选择最优相位。

{comparison}

全部35条详细结果：[all_results.csv](all_results.csv)；14组成对差值：[pair_deltas.csv](pair_deltas.csv)。全历史30%预算逐条检查，不用周期内或年度内回撤代替。新14条有 {int(newly.full_history_budget_exceeded.sum())} 条超过30%；原A14条有 {int(results.loc[results.variant.eq('original') & results.configuration.isin(['protected','simple_h60']),'full_history_budget_exceeded'].sum())} 条超过。回撤改善不会自然保证年化目标；本段开发数据未超过预算也不是未来保证。

## 暂停、空仓和恢复的代价

{occupancy}

*空仓日排除强制期末清仓日；原始累计空仓数、任何暂停/周期暂停/全局暂停天数、最长交易日和日历日跨度均在all_results。暂停计数包含触发收盘；实际清仓通常下一开盘，二者不能混为一谈。全局 HALTED共 {pause_count} 次、复核锁共 {lock_count} 次；期末已锁定的场景不会自动重设高点解锁。*

触发过新控制的场景 {triggered}/14。完全未触发的场景：{', '.join(untriggered) if untriggered else '无'}；未触发时才逐值证明全部原目标、交易、现金、持仓和权益不变，不能拿“无变化”作为风险改善证据。没有全局暂停不等于没有10%减仓影响。

{recovery_text}

恢复段交易日包括恢复当天和结束当天；减仓状态触发次数不是卖出订单数。长时间处于有限恢复仓位也有机会成本，不能只看是否空仓。完整区间见 [pause_intervals.csv](pause_intervals.csv)、[recovery_intervals.csv](recovery_intervals.csv)。若靠长期空仓压低回撤，应结合这些时间成本而非仅看回撤。风险减仓和股票止损、计划调仓分别见 [trade_reason_summary.csv](trade_reason_summary.csv)；历史交易明细与事件链留在可恢复账本及审阅ZIP。

主配置最大回撤的实际位置如下。两条资金路径的高点可能不同；不能仅凭平均仓位更低推断各自的历史高点回撤也更浅。各模式持续天数见[risk_mode_days.csv](risk_mode_days.csv)，完整高点/谷底见[drawdown_locations.csv](drawdown_locations.csv)。

{dd_main}

## 年度结果

{year_table}

全部场景每年波动、平均仓位、双边换手、费用、年度及全历史回撤见 [annual_results.csv](annual_results.csv)。上表是完整年度序列，不能挑获利年份替代完整开发区间。

## 工程证据及仍未完成的范围

- [只记录检查](RECORD_ONLY_CHECK.json)：两种配置各2511日，原五张核心表数值一致，现金/股数/收盘权益及完整累计高水位独立复核。CSV空文本与NA只做表示归一，数值不四舍五入。
- [事务及资金契约](ENGINEERING_CONTRACT.md)：唯一资金事件去重、哈希链和SQLite事务衔接已处理事实/估值/风险/策略检查点。入提款改变份额；费用、分红、利息改变实际单位净值；未知差额及迟到/冲突事实停新增风险。不存在自动从初始资金重建来绕过亏损。
- [进程证据](engineering/final_verification/CONTINUITY_REPORT.json)：真正子进程在提交前/后中止并恢复，与连续运行的目标、订单/成交、现金、股数、运行时和高水位相同；虚构跳空部分卖出后真实剩余2股保留，别的策略17股未接管。虚构数据不是paper回报。
- 新历史适配器完整连接同一 `GlobalRisk` 的观察、减仓、暂停、有限恢复；[边界证据](BOUNDARY_CHECKS.json)覆盖开盘上涨跳空仓位限制、最后清仓费用触发以及模型元数据交接。持续风险状态独立于原`episode_peak`，原文件未重写。
- 旧 v8 未知提交先核对、去重、只减仓不买入、止损后取消买入余单保留；[旧回归](OLD_REGRESSION_TESTS.json)通过。最终测试及附加离线控制接线情况见 [TESTS.json](TESTS.json)及[执行说明](engineering/README.md)。
- 附加的 `h60_fund_control_cycle.py` 在本地虚构执行中按明确收盘/开盘阶段，从已核对的实际余额与持仓自动调用同一控制器，并将事实、状态转换和决定游标一起提交；它不发出或撤销订单。执行账本保留每次可信估值高点，而冻结历史研究按每日收盘高点；正常持仓阶段不调用恢复OPEN。两者尚非完整交易路径等价，此估值频率差异列为部署前接线缺口，不能拿离线工程通过宣告paper就绪。
- [限制](ENGINEERING_LIMITATIONS.md)：仓位上限使用成交前已知NAV；费用可使成交后比例略高于重新计算的上限，虚构诊断差5.38bp，不声称精确冲击损失保证。日线收盘触发有跳空/成交延迟，不能保证30%不会突破。
- 独立风险账本支持模型版本元数据延续；旧执行账本的实际模型清单仍不可原地替换，会拒绝而非偷偷新建资金历史。券商资金事件导入、真实模型迁移、迟到佣金重建、多币种、原生公司行动、真实paper入口、部分成交持续保护/保护撤换窗口和长期断线补账仍未完成。两个数据库间可核对恢复，不宣称分布式原子提交。

真实paper回报 **0新增**；真实/ paper订单 **0**；前瞻业绩 **无**。LEAN仍是人工阶段与自定义立即成交的历史研究代理，没有修改其模式限制或接入新控制。2026行情 **未使用**，没有冻结通过终测的候选。

## 三项判断与停止决定

1. **工程**：已完成本地连续资金账本、事务/进程恢复、只记录历史一致性和本轮固定研究控制；执行达到的具体层级以上述证据为准，不等于整个券商系统已经就绪。
2. **风控价值**：预登记门槛{status}。完整保护主场景需回撤改善≥3pp且年化代价≤2pp，并要求六个压力回撤≤30%、较原规则恶化≤2pp。实际逐条布尔结果见[GATES.json](GATES.json)。失败后没有调阈值或换最好年份。
3. **盈利目标**：{numerical}。净年化30%最低目标、50%争取目标不降低。2016—2025已反复开发，本轮不是独立验证，工程通过不等于盈利验证通过。

**下一步唯一优先工作：取得一份合法可用、包含退市股及历史成员变化的点时股票池样本，并通过既有v9接口验收。** 当前30只存续股票限制信号结论的可信度；完整授权数据仍缺。风险基础与盈利能力分别推进，不能再用追加风控阈值或重复训练旧样本补收益缺口。取得可用样本后才另行预登记预测信息研究；本轮到此停止，不启动下一实验。

## 复核与本地材料

环境沿用 `.venv` Python3.12.2 / requirements.txt，没有新增依赖。项目根目录执行：

```powershell
.\\.venv\\Scripts\\python.exe -B 52_verify_frozen_research.py
.\\.venv\\Scripts\\python.exe -B 57_check_fund_recording.py
.\\.venv\\Scripts\\python.exe -B 58_evaluate_continuous_risk.py --check-only
.\\.venv\\Scripts\\python.exe -B 59_summarize_continuous_risk.py
.\\.venv\\Scripts\\python.exe -B -m unittest discover -s tests -p "test_v13*.py" -v
```

已完成目录中57/58先核对哈希，不重复历史回放。首次独立复算需恢复原A行情/模型/预测及v8控制包，再保留当前冻结目录，使用明确新研究目录；不要删除风险状态强行从初始资金启动。`56_check_fund_continuity.py --output <新目录>`只跑虚构工程场景。风险SQLite及大交易/目标/持仓明细保留本地；[新增材料清单](../../../review_upload/sync_v13_20260922/large_artifacts.csv)和[独立ZIP清单](../../../review_upload/sync_v13_20260922/bundles.json)给出准确路径、大小、SHA256及入口。

旧周期高点是“这一轮恢复之后”的参照；持续资金高点是同一笔钱自开始以来、扣除外部入提款影响后的真实最高单位净值。前者能解释一次暂停，后者才能揭示连续失败累计损失。新增风控改变了暴露路径，因此更早缩仓既可能减少损失，也可能错过修复；必须用配对结果判断，不能从规则名字推断更安全或更赚钱。
'''
    (OUT/'REPORT.md').write_text(text,encoding='utf-8')
    save(OUT/'SUMMARY_CHECK.json',dict(new_fits=0,original_models=10,new_control_replays=14,
        reused_controls=21,record_only_complete_replays=2,preserved_pre_freeze_attempts=1,
        risk_value_gate_passed=gates['risk_value_gate_passed'],numerical_objectives_met=gates['protected_numerical_objectives_met'],
        global_triggered_scenarios=triggered,global_pauses=pause_count,review_locks=lock_count,
        report_sha256=sha(OUT/'REPORT.md'),new_orders_real_or_paper=0,prices_2026_accessed=False))
    print('Report generated from completed hash-verified results; no new replay or fitting.')


if __name__=='__main__':
    main()
