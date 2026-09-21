"""Summarize frozen v12 files only; no fit, replay, download or broker imports."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'data/experiments/h60_training_cutoff_v12'


def read(name):
    return json.loads((OUT/name).read_text(encoding='utf-8'))


def table(headers, rows):
    return '\n'.join(['| '+' | '.join(headers)+' |','| '+' | '.join('---' for _ in headers)+' |']+
                     ['| '+' | '.join(str(v).replace('|','/') for v in row)+' |' for row in rows])


def main():
    completion=read('evaluation_complete.json')
    assert completion['new_strategy_runs']==14 and completion['new_fits']==10
    for item in completion['files']:
        path=ROOT/item['path']
        with path.open('rb') as handle:
            digest=hashlib.file_digest(handle,'sha256').hexdigest()
        if digest!=item['sha256'] or path.stat().st_size!=item['size_bytes']:
            raise ValueError(f'Frozen evaluation artifact changed: {item["path"]}')
    frame=lambda name:pd.read_csv(OUT/name,float_precision='round_trip')
    results, pairs, annual=map(frame,['all_results.csv','pair_deltas.csv','annual_results.csv'])
    fits,ic,selection=map(frame,['training_summary.csv','signal_diagnostics.csv','selection_summary.csv'])
    gates,checks=read('GATES.json'),read('RUN_CHECKS.json')
    frozen,independent=read('V11_READ_ONLY_VERIFICATION.json'),read('INDEPENDENT_TRAINING_CHECK.json')
    fict=read('drawdown_check/FICTIONAL_summary.json')
    mains=results.loc[results.scenario.eq('cost10')].set_index('case')
    order=['A_protected_cost10','B_protected_cost10','A_simple_h60_cost10','B_simple_h60_cost10','control_simple_spy_cost10']
    names=['A完整保护','B完整保护','A简单H60（诊断）','B简单H60（诊断）','SPY同预算控制']
    for case in results.case:
        np.testing.assert_allclose(np.prod(1+annual.loc[annual.case.eq(case),'return_net']),
                                   results.loc[results.case.eq(case),'final_equity'].iloc[0],rtol=1e-12)
    main_rows=[]
    for case,name in zip(order,names):
        r=mains.loc[case]
        main_rows.append([name,f'{r.cagr:.2%}',f'{r.total_return:.2%}',f'{r.max_drawdown:.2%}',
                          f'{r.annualized_vol:.2%}',f'{r.average_gross:.2%}',f'{r.turnover_two_way_per_year:.3f}',
                          f'{r.fee_per_initial_nav*10000:.2f}',f'{r.stop_slippage_per_initial_nav*10000:.2f}',
                          int(r.stop_exits),int(r.halts)])
    pressure=[]
    for r in pairs.itertuples():
        pressure.append([r.configuration,r.scenario,f'{r.A_cagr:.2%}',f'{r.B_cagr:.2%}',
                         f'{100*r.delta_cagr:+.2f}',f'{r.A_total_return:.2%}',f'{r.B_total_return:.2%}',
                         f'{r.A_max_drawdown:.2%}',f'{r.B_max_drawdown:.2%}'])
    spyrows=[[r.scenario,f'{r.cagr:.2%}',f'{r.total_return:.2%}',f'{r.max_drawdown:.2%}']
             for r in results.loc[results.configuration.eq('simple_spy')].itertuples()]
    year=annual.loc[annual.case.isin(order)].pivot(index='year',columns='case',values='return_net')
    years=[[int(y),*[f'{year.loc[y,c]:.2%}' for c in order]] for y in year.index]
    a,b=mains.loc[order[0]],mains.loc[order[1]]
    sa,sb=mains.loc[order[2]],mains.loc[order[3]]
    sel=selection.loc[selection.configuration.eq('protected') & selection.scenario.eq('cost10')].iloc[0]
    icindex=ic.set_index('protocol')
    icannual=frame('signal_annual_ic.csv').pivot(index='year',columns='protocol',values='mean_rank_ic')
    trainrows=[[int(r.year),int(r.A_train_rows),int(r.train_rows),int(r.added_rows),int(r.former_validation_rows),
                int(r.newly_mature_boundary_rows),r.train_last_observation,r.train_last_exit,f'{r.fit_seconds:.3f}',r.warnings]
               for r in fits.itertuples()]
    details='# v12十次实际年度训练\n\n仅10次新拟合，复用10份A模型及原预测；固定原rank_60、81特征、Ridge(alpha=100, solver="svd")。没有验证集评分或调参；旧上一年已纳入拟合。\n\n'
    details+=table(['部署年','A训练行','B训练行','新增行','原留出期行','原边界剔除行','B最后X','B最后标签退出','拟合秒','警告'],trainrows)
    details+=f'\n\n合计拟合耗时{fits.fit_seconds.sum():.6f}秒，单次最小{fits.fit_seconds.min():.6f}、最大{fits.fit_seconds.max():.6f}秒；这是model.fit计时，不是整轮运行耗时。十次警告均为空。历史起点全部2013-05-22。完整日期、训练键SHA、A/B模型身份见[training_summary.csv](training_summary.csv)。\n\n'
    details+=table(['部署年','原A模型SHA256','新B模型SHA256'],[[int(r.year),r.A_model_sha256,r.model_sha256] for r in fits.itertuples()])
    details+='\n\n模型文件位于`models/<年>_mature_rank60.joblib`（保留本地审阅ZIP），同名JSON在Git，记录完整feature_order及训练契约。scores.csv保存Date/symbol/A/B。生成HEAD与新源码哈希见GENERATION_CONTEXT.json；稳定身份不混入当前HEAD。\n\n独立检查器重新按完整面板筛选，核对均值、方差、样本量、模型参数与从保存模型推理的预测；全部10年最大误差0。75,240条A键/值精确保留，1,650条未成熟尾部预测保留，未追加拟合。见[INDEPENDENT_TRAINING_CHECK.json](INDEPENDENT_TRAINING_CHECK.json)。\n'
    (OUT/'TRAINING_DETAILS.md').write_text(details,encoding='utf-8')
    report=f'''# v12：年度训练截止固定比较结果

**未改善、未达到目标，拒绝升级。** 在相同原rank_60目标、81特征、Ridge参数和交易规则下，使用每次部署前全部成熟标签的B协议，使完整保护候选净CAGR从{a.cagr:.2%}降至{b.cagr:.2%}，下降{100*(a.cagr-b.cagr):.2f}个百分点；全历史收盘最大回撤从{a.max_drawdown:.2%}变为{b.max_drawdown:.2%}。简单H60诊断同样从{sa.cagr:.2%}降至{sb.cagr:.2%}。本轮固定检验不支持“训练更新滞后是主要收益瓶颈”，停止沿截止、窗口或更新频率继续扫参数。

新增训练 **10次**、固定B回放 **14次**，复用 **10份A年度模型/原预测和21条v8控制结果**。没有重训旧模型、改变策略、获取行情、使用2026、发送真实或paper订单或升级LEAN模型。生成基线为8b70778217cc2e0405cd20b68e4a3ba9f51b6cd9；本轮新源码哈希和快照单独保存，不能把基线提交冒充已包含本轮代码。

## 固定设计与身份

事前[PLAN.md](PLAN.md)及[plan.json](plan.json)在第一次B拟合前登记。A使用原Y-1年开始前成熟标签，上一年留出且未重拟合，是合法协议。B从完整原面板重新按Date及exit_60均早于Y年1月1日、X/rank_60完整筛选；每年新增7,500—7,590行，其中1,830行原来跨越train/valid边界。训练起点、标签、特征顺序、30股与年度频率固定，Scaler只拟合当年B训练样本。

2025年A训练78,300行、B85,860行；B最后X为2024-10-03、最后标签退出为2024-12-31。预测键与A完全一致：75,240行/2,508日，包括1,650条未成熟尾部样本。旧上一年纳入拟合后不再称该模型验证集。[训练明细和全部模型SHA](TRAINING_DETAILS.md)、[输入身份](INPUT_IDENTITY.json)、[独立重算检查](INDEPENDENT_TRAINING_CHECK.json)。

## 完整2016—2025开发结果

基准区间2016-01-05—2025-12-29，调仓日历、初始NAV=1、收盘估值、零息现金、末次开盘清仓均同v8。普通交易单边10bp，止损额外10bp。下表费用按初始10,000 USD换算，为整个区间累计普通手续费与额外止损滑点，不是某年成本。碎股与调整OHLC是原研究代理，尚非券商可成交报价和真实股数。

{table(['配置','净CAGR','累计净收益','全历史回撤','年化波动','平均仓位','年双向换手','普通费用USD','止损滑点USD','止损数','硬暂停数'],main_rows)}

完整保护A→B：累计收益差{100*(b.total_return-a.total_return):+.2f}个百分点，CAGR差{100*(b.cagr-a.cagr):+.2f}个百分点，回撤差{100*(b.max_drawdown-a.max_drawdown):+.2f}个百分点（更负代表更深）。简单A→B：累计收益差{100*(sb.total_return-sa.total_return):+.2f}个百分点，CAGR差{100*(sb.cagr-sa.cagr):+.2f}个百分点，回撤差{100*(sb.max_drawdown-sa.max_drawdown):+.2f}个百分点。[全部差值](pair_deltas.csv)含仓位、换手、费用、止损和暂停差异。

保护配置保持8股/排名12缓冲/集中度、SPY波动缩仓、15%个股止损、20%周期硬暂停和恢复，软减仓关闭。简单H60共享事前80%预算及SPY缩仓/硬暂停，缺少完整个股保护，仅作为诊断；不能升级为成品。target_vol=.15控制SPY波动缩仓，不保证股票组合实现15%波动。

## 全部成对压力与SPY控制

{table(['配置','固定场景','A CAGR','B CAGR','差值pp','A累计收益','B累计收益','A全历史回撤','B全历史回撤'],pressure)}

{table(['SPY固定场景','CAGR','累计收益','全历史回撤'],spyrows)}

cost20为20/10bp，cost30_stop50为30/50bp，delayed_next_open为20/50bp并延后止损至次日开盘；无个股止损的简单配置因此与cost20相同。phase1/4仅使用预登记偏移，禁NVDA仅排除交易。B相位4虽高于B主场景，仍低于同相位A，不能代替主方案或事后选择最优相位。全部35条主/压力结果均累计收益为正，收盘最深回撤{results.max_drawdown.min():.2%}、开盘最深{results.open_max_drawdown.min():.2%}、同日各股Low同时发生的保守压力代理最深{results.low_stress_drawdown.min():.2%}，未越过30%；Low代理不是实际同时可成交路径。[all_results.csv](all_results.csv)保留全部失败和控制。

## 各自然年表现

{table(['年',*names],years)}

不要求每年达到30%；以上年份全部保留，不挑最优年份。[annual_results.csv](annual_results.csv)覆盖35配置×10年，包含年度收益、波动、平均仓位、双向换手、费用/滑点、年内及全历史回撤、止损和暂停次数。逐年净收益连乘已核对各全程最终权益。

## 信号、选股与交易变化

在同一{int(icindex.loc['A','mature_dates'])}个完整成熟日期，平均Rank IC为A={icindex.loc['A','mean_rank_ic']:.6f}、B={icindex.loc['B','mean_rank_ic']:.6f}，差{icindex.loc['B','mean_rank_ic']-icindex.loc['A','mean_rank_ic']:+.6f}。B仅在{int((icannual.B>icannual.A).sum())}/10年的平均IC高于A。H60重叠标签存在相关性，未把每日IC当独立观测声称显著。剩余55个预测日仅不参与标签诊断，交易预测并未删除。[逐年IC](signal_annual_ic.csv)、[汇总](signal_diagnostics.csv)。

主保护配置有{int(sel.common_scheduled_dates)}个共同计划调仓日，其中{int(sel.different_selected_set_dates)}日的选股集合不同，平均权重L1差{sel.common_date_mean_weight_l1:.4f}；集合对称差平均{sel.common_date_mean_changed_symbols:.3f}个股票（买入和卖出集合都计入）。实际持仓集合在{int(sel.actual_holdings_set_differs_days)}日不同。止损{int(a.stop_exits)}→{int(b.stop_exits)}、硬暂停{int(a.halts)}→{int(b.halts)}；20bp下B另触发硬暂停，风控状态路径因此也变了。费用与换手都有变化，不能将收益差全归因于训练损失、某笔止损或后续反弹。[selection_summary.csv](selection_summary.csv)、[交易原因](trade_reason_summary.csv)、本地逐笔和目标记录保留。

## 验收与结论边界

- 研究改善：{gates['research_improvement']}；预登记要求protected在10/20bp都胜A且全部B回撤合格。两成本下CAGR均下降。
- 最低30% CAGR：{gates['protected_numerical_objectives']['net_cagr_at_least_30']}；30%全历史收盘回撤预算：{gates['protected_numerical_objectives']['full_history_drawdown_within_30']}。主场景回撤优先20%条件成立，但收益未达标。
- 六条固定压力累计正收益且回撤合格：{gates['all_fixed_pressure_positive_and_drawdown_within_30']}；胜同预算合格简单对照：{gates['beats_admissible_same_budget_simple_cagr']}。
- 决定：**{gates['decision']}**。不降低30%/争取50%收益目标，不加杠杆。全部2016—2025已经反复参与开发，既有0/98未通过记录保留；此处没有独立验证成功，无唯一候选冻结、无2026终测。

## 回撤口径及只读复核修复

现有research simulate从连续收盘权益及初始1计算累计高水位，35条结果均独立核对；未使用可重置的episode_peak代替账户高水位。episode恢复会重置，所以20%硬暂停只管理风险周期，不代表账户回撤最多20%或30%。

短小[虚构连续亏损/恢复检查](drawdown_check/README.md)使用实际未改策略，发生2次30%跳空、2次暂停和2次恢复。最深周期回撤{fict['minimum_reported_episode_drawdown']:.2%}，全历史回撤却为{fict['full_history_max_drawdown']:.2%}；第二次恢复时周期几乎归零，全账户亏损仍在。独立累计与JSON保存高水位后接续一致。它验证统计口径，不是已实现的线上全账户控制或长期断线恢复保证；新simulate调用会重新从1开始。相关测试与虚构数据均保留，未混入主实验结果。

[52只读入口](../../../52_verify_frozen_research.py)保留旧v11生成HEAD=9d98008…与源码身份，并用上传8b707…中的原清单作锚点。当前复核HEAD与验证器自身哈希另列，提交变化本身不拒绝；六个生成源码、输入、40份模型、预测及结果哈希仍严格核对。实际703个唯一文件通过，6项测试覆盖普通后续提交、源码/输入/模型/预测/结果变动、缺失大型材料及身份篡改；默认运行不写文件、不反序列化模型、不训练。旧50保持冻结，已完成v11应使用52复核，不再以50作为只读入口。见[V11_READ_ONLY_VERIFICATION.json](V11_READ_ONLY_VERIFICATION.json)。

## 下一步唯一优先工作与工程现状

**独立设计并验证“持久化全账户高水位”的风险控制及其收益代价**：以保留的A为研究基线，明确资金流入流出、重启/换模型、高水位连续性与提前减仓/退出/恢复。先登记单独实验再运行，不将本轮20%周期暂停误认为30%账户上限，也不承诺跳空永不突破预算。本轮不实施此新控制。它解决风险约束缺口，本身不能解决目前不到30%的盈利证据；B的信号IC和两配置收益均下降，不支持靠多纳入一年数据继续提升。之后若追求收益突破，需要新证据支持的信息/决策假设，而非沿同一截止继续扫参数。

v8只减仓、持久化意图、未知提交先核对及止损后撤买余单均保留；v10仍由冻结预测生成目标及订单，使用人工阶段和自定义立即全额成交，仅是历史研究代理。未替换v10模型、未删除模式限制、没有真实paper或前瞻记录新增。

具体工程缺口仍是原生美股报价/公司行动、真实paper运行入口、部分成交期间持续保护、保护撤换窗口及长期断线补账；v8原型功能不能自动算作LEAN已具备。v9本地历史股票池接口已完成，完整授权历史股票池/退市覆盖仍缺，30股存续偏差没有解决。本轮无新增外部阻塞，所有固定工作可用原本地数据完成。

## 复核命令及材料

在项目根目录使用现有Python3.12.2虚拟环境，依赖仍为requirements.txt，无新增安装。安全阅读顺序：52旧实验只读检查 → 53已完成训练身份检查 → 54 --check-only → 55重写汇总（不重做实验）。全新缺失产物时53最多10拟合、54最多14回放，必须保留事前计划且遵守原预算，不覆盖完成目录；当冻结预算过期时新计算会停止。

```powershell
.\\.venv\\Scripts\\python.exe -B 52_verify_frozen_research.py
.\\.venv\\Scripts\\python.exe 53_train_annual_cutoff.py
.\\.venv\\Scripts\\python.exe 54_evaluate_training_cutoff.py --check-only
.\\.venv\\Scripts\\python.exe -B tools/check_v12_training_artifacts.py
.\\.venv\\Scripts\\python.exe -m unittest discover -s tests -p test_v12*.py -v
```

本轮12项v12边界/统计/门槛测试、6项v11只读复核测试，实际A/B35条现金/股数/费用/末次清仓账本核对，独立10年Scaler与预测检查通过；实际测试命令输出见TESTS.json。依赖、旧大文件及新增模型/预测/逐笔明细通过审阅清单恢复；最新路径、大小、SHA及ZIP见[本次上传说明](../../../review_upload/sync_v12_20260921/README.md)。旧报告和旧清单未改写。

标签成熟决定训练能否合法看到答案：例如2024年12月末的H60记录，其退出价格在2025年才出现，不能用于2025年初训练；2024年10月初记录则已结束，可使用。更多合法样本只保证信息时点正确，并不保证更有效；这轮真实失败排除了一个看似合理的改进方向，也留下了可复核的原因。
'''
    (OUT/'REPORT.md').write_text(report,encoding='utf-8')
    (OUT/'NEXT_QUESTION.md').write_text('''# 下一步唯一优先：全账户风险高水位与恢复协议

v12单因素检验不支持年度训练更新滞后是主要收益瓶颈，停止沿截止、训练窗口或更新频率继续扫参数；保留A为研究参照，B不升级。

下一轮单独预登记全账户高水位控制及收益代价实验：用户30%预算按连续账户高水位，不能随周期恢复、进程重启或换模型重置。需明确资金流调整、持久化身份、提前缩仓/退出及恢复，保留个股保护和跳空压力；测试必须包括多次亏损恢复以及保存后接续。具体阈值尚未选择或试验，不借本次结果反向调优。

这项工作补风险约束，不承诺提高CAGR；目前A/B都未达到扣费长期30%收益目标。虚构42.52%回撤示例已说明仅周期暂停不足，但不会把新增控制混入本轮训练截止结果。2026仍封存、不升级LEAN/paper、不发订单。完整授权历史股票池和执行缺口保持原记录。
''',encoding='utf-8')
    print('Frozen v12 report and training details written; zero new fits/replays.')


if __name__=='__main__':
    main()
