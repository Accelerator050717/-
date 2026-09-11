"""Summarize saved v8 outputs only. Does not simulate, fit, download or submit orders."""
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd

from panel_config import ROOT
from h60_research_inputs import save, sha

OUT=ROOT/'data/experiments/h60_risk_execution_v8'
LABELS={
    'stop_on_soft_on':'个股止损开／软减仓开',
    'stop_on_soft_off':'个股止损开／软减仓关（主候选）',
    'stop_off_soft_on':'个股止损关／软减仓开（诊断）',
    'stop_off_soft_off':'个股止损关／软减仓关（诊断）',
    'simple_h60':'简单H60／80%预算',
    'simple_spy':'SPY／80%预算',
}


def read(name):
    return json.loads((OUT/name).read_text(encoding='utf-8'))


def table(frame):
    rows=[list(map(str,frame.columns)),['---']*len(frame.columns),*frame.astype(str).values.tolist()]
    return '\n'.join('| '+' | '.join(row)+' |' for row in rows)


def percent(x):
    return f'{x:.2%}'


def label(name):
    for prefix,value in LABELS.items():
        if name.startswith(prefix+'_cost'):
            return value+'／'+name.split('_cost')[-1]+'bp'
    return name


def main():
    complete=read('completion.json'); gates=read('GATES.json'); tests=read('TESTS.json')
    execution=read('execution_v5/completion.json'); repeat=read('execution_v5/REPEAT_RUN.json')
    recovery=read('execution_faults_v2/completion.json'); probe=read('IBKR_READINESS.json')
    manifest=read('ENGINEERING_STRATEGY_MANIFEST_v5.json')
    assert not gates['development_passed'] and tests['passed'] and recovery['all_checks_passed']
    assert repeat['new_decisions']==0 and repeat['new_intents']==0 and repeat['new_fills']==0
    for path,digest in complete['source_sha256'].items():
        assert sha(ROOT/path)==digest
    for path,digest in manifest['source_sha256'].items():
        assert sha(ROOT/path)==digest
    for path,digest in recovery['source_sha256'].items():
        assert sha(ROOT/path)==digest
    for path,digest in tests['test_source_sha256'].items():
        assert sha(ROOT/path)==digest
    checks=read('RUN_CHECKS.json')
    assert len(checks)==complete['runs'] and all(c['ledger_passed'] and c['final_flat'] for c in checks.values())
    results=pd.read_csv(OUT/'all_results.csv').set_index('case')
    main_rows=pd.read_csv(OUT/'comparison.csv').set_index('case')
    stresses=pd.read_csv(OUT/'stress_comparison.csv').set_index('case')
    bugs=pd.read_csv(OUT/'bug_impact.csv')
    annual=pd.read_csv(OUT/'annual_results.csv')
    events=pd.read_csv(OUT/'trade_reason_summary.csv')
    paths=pd.read_csv(OUT/'stop_forward_paths.csv')
    chosen=main_rows.loc['stop_on_soft_off_cost10']
    soft_on=main_rows.loc['stop_on_soft_on_cost10']
    no_stop=main_rows.loc['stop_off_soft_off_cost10']
    controls=main_rows.loc[['simple_h60_cost10','simple_spy_cost10']]
    bug_table=pd.DataFrame({
        '同一H60的配置':bugs.pair.str.replace('bug_',''),
        '非计划买单旧→新':[f'{int(a)} → {int(b)}' for a,b in zip(bugs.old_buy_orders,bugs.fixed_buy_orders)],
        'CAGR旧→新':[f'{a:.3%} → {b:.3%}' for a,b in zip(bugs.old_cagr,bugs.fixed_cagr)],
        'CAGR差(百分点)':bugs.cagr_difference.map(lambda v:f'{v*100:+.4f}'),
        '收盘回撤旧→新':[f'{a:.3%} → {b:.3%}' for a,b in zip(bugs.old_drawdown,bugs.fixed_drawdown)],
        '年双向换手旧→新':[f'{a:.3f} → {b:.3f}' for a,b in zip(bugs.old_turnover,bugs.fixed_turnover)],
    })
    performance=pd.DataFrame({
        '固定配置／单边成本':[label(n) for n in main_rows.index],
        '累计净收益':main_rows.total_return.map(percent).to_list(),
        'CAGR':main_rows.cagr.map(percent).to_list(),
        '收盘最大回撤':main_rows.max_drawdown.map(percent).to_list(),
        '年化波动':main_rows.annualized_vol.map(percent).to_list(),
        '平均股票仓位':main_rows.average_gross.map(percent).to_list(),
        '年双向换手':main_rows.turnover_two_way_per_year.map(lambda v:f'{v:.2f}x').to_list(),
        '累计普通费用($)':main_rows.fees.map(lambda v:f'{v*10000:,.2f}').to_list(),
        '累计止损滑点($)':main_rows.stop_slippage_per_initial_nav.map(lambda v:f'{v*10000:,.2f}').to_list(),
    })
    names=[name for name in main_rows.index if name.endswith('cost10')]
    yearly=annual.loc[annual.case.isin(names)].pivot(index='year',columns='case',values='return_net').reindex(columns=names)
    yearly=yearly.map(percent).rename(columns={n:LABELS[n.rsplit('_cost',1)[0]] for n in names}).reset_index()
    stress_table=pd.DataFrame({'场景':stresses.index,'CAGR':stresses.cagr.map(percent),
                               '累计净收益':stresses.total_return.map(percent),'收盘最大回撤':stresses.max_drawdown.map(percent),
                               '硬暂停次数':stresses.halts.astype(int)}).reset_index(drop=True)
    event_table=events.loc[events.case.eq('stop_on_soft_off_cost10'),['category','orders','buys','traded_notional','fees']].copy()
    event_table['traded_notional']=event_table.traded_notional.map(lambda v:f'{v*10000:,.2f}')
    event_table['fees']=event_table.fees.map(lambda v:f'{v*10000:,.2f}')
    event_table.columns=['主候选直接执行原因','订单条数','买单数','累计交易额($)','普通费用($)']
    path_rows=[]
    for h in (5,20,60):
        values=paths[f'after_{h}_sessions'].dropna()
        path_rows.append(dict(观察窗口=f'{h}交易日',有效退出数=len(values),平均后续价格变化=percent(values.mean()),
                              中位后续价格变化=percent(values.median()),后续价格高于退出代理价比例=percent(values.gt(0).mean())))
    # Useful inspection tables, derived from saved outcomes only.
    pd.DataFrame(path_rows).to_csv(OUT/'stop_forward_summary.csv',index=False)
    old=results.loc['background_h60_full_budget']; spy=results.loc['background_spy_full']
    generated=datetime.now(timezone.utc).isoformat()
    report=f'''# H60风控修复、固定比较与模拟执行：本轮完整报告

结论：两项确认的代码问题已修复，39次固定历史重放完成。主候选未达到扣费长期CAGR至少30%的收益目标，也没有胜过同一事前风险预算下的简单H60，**拒绝升级，不使用2026终测**。此次不存在“完全放心”或已证明稳定盈利的自动交易模型。

报告生成：{generated}。基线提交`9d98008d72f096c2c1fa33a998f000fe62c48bb5`；当前修改保存在本地，代码身份以每文件SHA256记录。无新增训练、行情下载或真实账户订单。

## 1. 修复及真实历史影响

`daily_risk_reduce`现在调用只卖函数：按当前报价计算目标，再以已有持仓金额逐股封顶，费用从实际卖出额计算，所得留现金。昨日权重变化不再成为买入指令，已止损退出的零持仓不会重新开仓。v6/v7均已修复。虚构跳空回归与实际历史重放分别保留，不能相互替代。

`risk_inputs(..., policy.target_vol)`已接通，0.15默认值与原公式一致，改变参数确实改变仓位。公式`min(1, target_vol / SPY过去20日年化波动)`只调市场代理仓位，不承诺股票组合实现15%波动。软减仓、硬暂停是独立配置；v7原排名12保留缓冲、软恢复和冷却后的趋势/网格复仓继续保留。

同一原H60预测、普通成本10bp下的旧/新结果：

{table(bug_table)}

这里的v6是单H60修复对照，不是重算H20/H60集成。未调用17/18旧路径，也未重算百分位集成；对应旧问题保留为已知事项。v7完整规则CAGR由11.32%到12.16%，是此次历史路径上的实际影响；“没有错误买单”本身不保证收益提高，v6完整对照变化就很小。完整买入金额、累计收益和差值见[bug_impact.csv](bug_impact.csv)。

## 2. 固定比较与验收

[运行前计划](PLAN.md)与[机器计划/输入哈希](plan.json)在模拟前登记。唯一主候选为“止损开／软减仓关”；4格仅开关个股止损和软减仓，20%硬暂停及其余v7参数不变。无止损两格只作诊断，不替换成最终策略。

简单H60与SPY都使用事前固定80%总仓位上限、同一SPY波动缩仓和20%硬暂停/冷却/恢复，不根据全期结果调整仓位。80%来自原12%计划损失预算/15%保护距离。它们的集中度和实现波动不同：这叫相同事前预算，**不叫事后波动完全匹配**。简单H60基准回撤21.15%处于用户允许的20%—30%上沿档，主候选回撤17.74%在优先档；两者都须另外满足收益要求。

统一2016-01-05—2025-12-29；初始权益1对应10,000 USD，收盘权益、零息现金、无杠杆、调整OHLC/碎股研究代理。全部含首次建仓和最终开盘清仓成本。普通成本每边10/20bp，触发止损另加10bp滑点。换手为买卖金额之和/前一收盘权益，再按实际年数平均，包含末次退出；不是只计单边换手。费用列按初始10,000 USD缩放，是整个区间累计金额，不是每年收益拖累。

{table(performance)}

原100%仓位上限H60背景对照：CAGR {old.cagr:.2%}、累计{old.total_return:.2%}、收盘回撤{old.max_drawdown:.2%}；满仓SPY背景：{spy.cagr:.2%}/{spy.max_drawdown:.2%}。它们不混充同预算对照。当前固定比较没有方案同时达到30%长期净CAGR及不超过30%回撤；没有降低标准或增加杠杆。

![开发期收益与回撤](risk_return_comparison.png)

## 3. 保护措施的收益代价与年度表现

保留15%个股保护、单独关闭10%软减仓，CAGR从{soft_on.cagr:.2%}增至{chosen.cagr:.2%}，增加{(chosen.cagr-soft_on.cagr)*100:.2f}个百分点；回撤由{soft_on.max_drawdown:.2%}加深至{chosen.max_drawdown:.2%}。这支持“软减仓在这段历史拖累盈利”的局部假设，但不足以达标。

在软减仓关闭时，个股保护开/关的CAGR分别为{chosen.cagr:.2%}/{no_stop.cagr:.2%}，净差{(chosen.cagr-no_stop.cagr)*100:.2f}个百分点；回撤分别为{chosen.max_drawdown:.2%}/{no_stop.max_drawdown:.2%}。不据此把正式候选换为无止损；四格显示规则存在交互，不能把各条逐笔结果简单相加。

{table(event_table)}

计划调仓的目标本身可能包含SPY缩仓、软状态或恢复期影响；直接订单原因不是纯因果归属。`cap_and_soft`保留联合标记，不随意分摊。软规则的总影响用上述成对消融衡量。完整12条对照的原因明细在[trade_reason_summary.csv](trade_reason_summary.csv)，逐笔交易/现金/股数与每日权益均通过核对。

主候选基准硬暂停触发{int(chosen.halts)}次，个股退出{int(chosen.stop_exits)}次，其中开盘跳空{int(chosen.gap_stops)}次。基准没有触发某规则，不等于它失效或没有必要；高成本/延迟压力和虚构故障另检验其路径。

| 止损后股票路径（事后描述） | | | | |
{table(pd.DataFrame(path_rows))}

这些收益从止损代理成交价到随后股票收盘价计算，仅使用原快照中可见到2025年末的后续记录；尾部不足窗口的样本不补值。反弹并不等于取消止损后的组合收益，因为现金、替代持仓、权重和后续退出都改变。

每个自然年的实际净收益如下，不要求各年都达到30%；不是挑最好年份：

{table(yearly)}

[annual_results.csv](annual_results.csv)同时保留39条结果的年波动、年内回撤及全历史回撤。年内回撤重置仅供描述，不替代全账户历史回撤。

## 4. 固定压力，未选最优相位

{table(stress_table)}

高成本为普通30bp/止损额外50bp；延迟为触发后的下一开盘、普通20bp/额外50bp；相位只核对预定1和4；禁NVDA只限制交易，不重训。SPY不持NVDA也没有个股止损，对应相同输出仍完整列出。没有从相位中挑一个作为新的主策略。

主候选高成本压力回撤达到25.70%，超过约20%的优先目标但仍在30%预算上沿内；20%触发线不是成交/最大回撤保证。成本可改变暂停时点、恢复周期和后续持仓，结果不必单调。全部有限压力净累计收益为正且回撤在30%以内，仍不能抵消基础收益门槛失败。

## 5. 训练、执行和2026的真实状态

- 实际新增训练 **0次**。复用2016—2025十份年度H60 Ridge对应的原保存预测；模型alpha=100、solver=svd、81个原特征，哈希及实际训练/标签成熟截止见[TRAINING_RECORD.json](TRAINING_RECORD.json)。没有新模型容量、财报特征或周期搜索。
- 工程模型仅为2025年度H60，SHA256 `{manifest['model']['sha256']}`。最后训练观察日{manifest['model']['train_last_observation']}、训练标签退出{manifest['model']['train_last_label_exit']}、验证标签退出{manifest['model']['validation_last_label_exit']}；不是当前2026部署模型。
- 最新共享H60闭环：{execution['total_fills']}笔**虚构成交**、{execution['total_order_intents']}个持久化订单意图（含保护单，撤单另记事件）、16日状态重载核对。独立CLI完整重跑新增意图/成交均为0。另用3个真实操作系统进程、2次刻意中断验证超时和撤单成交竞争恢复。恢复后8股持仓对应8股保护、原买单仅提交一次。
- 真实IBKR检查时间{probe['checked_at_utc']}，状态`{probe['status']}`，阻塞`{probe.get('blocker')}`。真实paper订单0、真实paper成交0；前瞻业绩观测0。SDK响应测试全部虚构，不能写成联调成功。
- H60决策、目标、股数封顶和保护规则已共用；共享协调器在撤单确认后重算目标，并使用实际成交日期恢复冷却。部分建仓期间若保护成交，会撤销未成交的买入余单，核对期间继续预留资金和可卖数量。{tests['tests']}项已有及新增测试通过，只证明其覆盖的场景。[执行说明/命令](EXECUTION_GUIDE.md)、[工程清单](ENGINEERING_STRATEGY_MANIFEST_v5.json)、[恢复记录](execution_faults_v2/completion.json)提供具体证据。
- 2026价格本轮未读取/下载/用于选择或评估。开发区间2016—2025已反复使用，不独立。本轮唯一主要候选被拒绝，只封存工程测试配置，**未冻结任何用于2026终测的候选**。原0/98未过全部统计门槛的记录保持不变。

若未来通过新的预登记开发门槛，须先冻结唯一策略、少量对照与年度更新协议：模拟2026年初时训练只能用截至2024的观察且H60标签在2025年前成熟，2025验证标签在2026年前成熟；再一次性评估未消耗的2026。报告实际累计收益和样本长度，不靠短期年化宣布30%目标达成。本轮没有执行该训练/终测路径。

## 6. 阻塞与下一步

盈利阻塞来自当前信号/组合在固定成本和约束下的净收益不足；修复错误、减少软减仓已改善一部分，但主候选14.88%仍远低于30%，连较简单的20.83%对照也未达标。下一次应检验**新的可用信息或信号能否增加扣费收益**，而不是继续调整这四格或放弃全部保护。

唯一优先工作：完成一种许可合适、含历史成分与退市处理的股票池数据闭环，再登记一次有明确信号增量假设的比较。[独立数据任务](HISTORICAL_UNIVERSE_TASK.md)记录实际可用性、接口、许可及固定30股代码需要改动的位置；增加今天仍存续的股票不算解决偏差。

工程的具体外部阻塞是本机paper会话未就绪，随后还需确认独立预算、身份、实时行情权限、数量/价格精度和公司行动。保护单撤换窗口、真实订单回报时序与长期断线历史补齐尚未通过券商验证。用户最少操作及可运行的只读检查在执行说明中；没有后台交易服务，没有真实资金执行授权。

## 复现与文件

`42_evaluate_h60_risk_fixes.py`读取原输入和本目录固定计划；完成后再次运行只核对身份并保留结果。`43_run_h60_simulation.py`默认虚构报价执行，`44_test_h60_recovery.py`默认虚构券商进程故障测试，`45_summarize_h60_v8.py`只汇总保存结果。原v5/v6/v7及m16演练不覆盖。

本目录保留全部39次日权益、交易、持仓、目标和事件，完整预测仍使用原v5 `all_scores.csv`，准确哈希在[INPUT_IDENTITY.json](INPUT_IDENTITY.json)，没有用新数据替代。新文件一览及SHA256见[ARTIFACTS.csv](ARTIFACTS.csv)。本报告的费用、收益、回撤都来自实际保存输出。
'''
    # Avoid an extra malformed heading row before the legitimate table.
    report=report.replace('| 止损后股票路径（事后描述） | | | | |\n','止损后股票路径（事后描述）：\n\n')
    (OUT/'FINAL_REPORT.md').write_text(report,encoding='utf-8')
    summary=dict(generated_at_utc=generated,decision=gates['decision'],new_fits=0,reused_models=10,
        historical_runs=complete['runs'],candidate_metrics=chosen.to_dict(),
        development_passed=False,independent_validation_passed=False,prices_2026_accessed=False,
        engineering_evidence=dict(virtual_fills=execution['total_fills'],repeat_new_fills=repeat['new_fills'],
            actual_paper_fills=0,forward_observations=0,subprocess_faults_passed=True),
        external_blocker=probe.get('blocker'),next_priority='Licensed point-in-time universe and delisting data sample ledger; then preregister a signal-increment test')
    save(OUT/'FINAL_SUMMARY.json',summary)
    save(OUT/'VALIDATION_STATUS.json',dict(development_candidate='stop_on_soft_off',development_passed=False,
        frozen_candidate_for_holdout=None,engineering_manifest_only='ENGINEERING_STRATEGY_MANIFEST_v5.json',
        holdout_2026_market_data_accessed=False,holdout_run_count=0,annual_protocol='Y-2 training; label exit before Y-1; Y-1 validation labels exit before Y',
        previous_0_of_98_preserved=True,short_holdout_reporting='Cumulative return, period length, annualized estimate; no target certification from short annualization'))
    progress=read('PROGRESS.json')
    assert set(progress['completed'])==set(checks)
    progress.update(status='completed',research_completed_at_utc=complete['completed_at_utc'],
                    delivery_report_updated_at_utc=generated,decision=gates['decision'])
    save(OUT/'PROGRESS.json',progress)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    selected=main_rows.loc[names]
    tags=['Stop+soft','Stop only','Soft only*','Neither*','Simple H60','Scaled SPY']
    fig,axes=plt.subplots(1,2,figsize=(11,4.3))
    axes[0].bar(tags,selected.cagr*100,color=['#8193ae','#216c98','#c5ced8','#c5ced8','#cc914d','#748a76'])
    axes[0].axhline(30,color='#a64440',ls='--',label='Minimum target 30%')
    axes[0].axhline(50,color='#a64440',ls=':',label='Aspiration 50%')
    axes[0].set(ylabel='Net CAGR (%)',title='Development history: 2016–2025')
    axes[0].legend(fontsize=8)
    axes[1].bar(tags,-selected.max_drawdown*100,color=['#8193ae','#216c98','#c5ced8','#c5ced8','#cc914d','#748a76'])
    axes[1].axhline(20,color='#a64440',ls='--',label='Preferred drawdown 20%')
    axes[1].axhline(30,color='#a64440',ls=':',label='Budget upper edge 30%')
    axes[1].set(ylabel='Close maximum drawdown (%)',title='Same predeclared budget; realized risk differs')
    axes[1].legend(fontsize=8)
    for ax in axes:
        ax.tick_params(axis='x',labelrotation=30);ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True)
    fig.text(.5,.015,'* No individual stop: diagnostic only. Cash earns 0; costs 10bp/side + 10bp extra for stops.',ha='center',fontsize=8)
    fig.tight_layout(rect=(0,.06,1,1));fig.savefig(OUT/'risk_return_comparison.png',dpi=160);plt.close(fig)
    artifacts=[]
    for path in sorted(OUT.rglob('*')):
        if path.is_file() and path.name!='ARTIFACTS.csv' and '__pycache__' not in path.parts and 'paper_private' not in path.parts:
            artifacts.append(dict(path=path.relative_to(ROOT).as_posix(),size_bytes=path.stat().st_size,sha256=sha(path)))
    pd.DataFrame(artifacts).to_csv(OUT/'ARTIFACTS.csv',index=False)
    print(json.dumps(dict(report=str(OUT/'FINAL_REPORT.md'),decision=gates['decision'],artifacts=len(artifacts),new_fits=0),ensure_ascii=True,indent=2))


if __name__=='__main__':
    main()
