"""Fixed v11 signal-objective comparison; no training, downloads or broker access.

Run after 50_train_signal_objectives.py has saved its frozen plan, labels,
predictions and training summary. Completed case files are hash checked before
reuse. Existing v8 controls are read in place after their manifest is checked.
"""
import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
import sys
import time

import numpy as np
import pandas as pd

import profit_priority_strategy as strategy
import research_features as features
from h60_research_inputs import load_inputs, save, sha
from panel_config import ROOT, SYMBOLS

OLD = ROOT / 'data/experiments/h60_risk_execution_v8'
OUT = ROOT / 'data/experiments/h60_signal_objectives_v11'
NEW_SIGNALS = ('plain_magnitude', 'stopped_magnitude', 'stopped_rank')
ALL_SIGNALS = ('baseline_rank', *NEW_SIGNALS)
SCENARIOS = ('cost10', 'cost20', 'cost30_stop50', 'delayed_next_open',
             'phase1', 'phase4', 'exclude_NVDA')
TABLE_KEYS = ('daily', 'trades', 'positions', 'targets', 'events')
old_tools = importlib.import_module('42_evaluate_h60_risk_fixes')


def now():
    return datetime.now(timezone.utc).isoformat()


def relative(path):
    return Path(path).relative_to(ROOT).as_posix()


def file_record(path):
    return {'path': relative(path), 'size_bytes': path.stat().st_size, 'sha256': sha(path)}


def check_record(record):
    path = ROOT / record['path']
    if path.stat().st_size != int(record['size_bytes']) or sha(path) != record['sha256']:
        raise ValueError(f"Saved artifact changed: {record['path']}")


def verify_old_manifest():
    records = pd.read_csv(OLD / 'ARTIFACTS.csv').to_dict('records')
    for row in records:
        check_record(row)
    return {'manifest': file_record(OLD / 'ARTIFACTS.csv'), 'verified_files': len(records)}


def frame_read(path, key):
    try:
        frame = pd.read_csv(path, index_col='Date' if key in ('daily', 'positions') else None,
                            float_precision='round_trip')
    except pd.errors.EmptyDataError:
        return pd.DataFrame()
    if key in ('daily', 'positions'):
        frame.index = pd.to_datetime(frame.index)
    else:
        for name in ('Date', 'observation_date'):
            if name in frame:
                frame[name] = pd.to_datetime(frame[name])
    return frame


def read_old(case):
    result = {key: frame_read(OLD / 'backtests' / f'{case}_{key}.csv', key) for key in TABLE_KEYS}
    result['metrics'] = json.loads((OLD / 'backtests' / f'{case}_metrics.json').read_text(encoding='utf-8'))
    return result


def old_case(signal, scenario):
    if scenario in ('cost10', 'cost20'):
        prefix = 'stop_on_soft_off' if signal == 'baseline_rank' else signal
        return f'{prefix}_{scenario}'
    suffix = 'candidate' if signal == 'baseline_rank' else signal
    return f'stress_{scenario}_{suffix}'


def scenario_options(name, calendar, observations, score_index, final):
    kwargs = dict(mode='risk', stops=True, breaker=True, cost_bps=10, stop_extra_bps=10,
                  policy=replace(strategy.Policy(), soft_enabled=False))
    obs = observations
    if name == 'cost20':
        kwargs['cost_bps'] = 20
    elif name == 'cost30_stop50':
        kwargs.update(cost_bps=30, stop_extra_bps=50)
    elif name == 'delayed_next_open':
        kwargs.update(cost_bps=20, stop_extra_bps=50, delayed_stops=True)
    elif name in ('phase1', 'phase4'):
        phase = int(name[-1])
        obs = calendar[calendar.get_indexer(observations) + phase]
        obs = obs[obs.isin(score_index) & (obs < final)]
    elif name == 'exclude_NVDA':
        kwargs['excluded'] = ('NVDA',)
    elif name != 'cost10':
        raise ValueError(f'Unregistered scenario: {name}')
    return obs, kwargs


def save_case(folder, result, identity_sha):
    folder.mkdir(parents=True, exist_ok=True)
    for key in TABLE_KEYS:
        result[key].to_csv(folder / f'{key}.csv', index=key in ('daily', 'positions'), date_format='%Y-%m-%d')
    save(folder / 'metrics.json', result['metrics'])
    files = [file_record(folder / f'{key}.csv') for key in TABLE_KEYS]
    files.append(file_record(folder / 'metrics.json'))
    # This marker is written last: partial output is never mistaken for completion.
    save(folder / 'complete.json', {'evaluation_identity_sha256': identity_sha, 'files': files})


def read_case(folder, identity_sha):
    marker = json.loads((folder / 'complete.json').read_text(encoding='utf-8'))
    if marker['evaluation_identity_sha256'] != identity_sha:
        raise ValueError(f'Case belongs to a different experiment: {folder.name}')
    for record in marker['files']:
        check_record(record)
    result = {key: frame_read(folder / f'{key}.csv', key) for key in TABLE_KEYS}
    result['metrics'] = json.loads((folder / 'metrics.json').read_text(encoding='utf-8'))
    return result


def annual_rows(case, result):
    rows, daily = [], result['daily']
    for year, part in daily.groupby(daily.index.year):
        start = daily.index.get_loc(part.index[0])
        initial = 1. if start == 0 else daily.equity.iloc[start - 1]
        rows.append(dict(case=case, year=int(year), return_net=float(part.equity.iloc[-1] / initial - 1),
                         volatility=float(part['return'].std(ddof=1) * np.sqrt(252)),
                         within_year_drawdown=float((part.equity / part.equity.cummax().clip(lower=initial) - 1).min()),
                         full_history_drawdown_min=float(part.drawdown.min()), average_gross=float(part.gross.mean())))
    return rows


def trade_diagnostics(case, result):
    trades = result['trades'].copy()
    trades['category'] = trades.reason
    mask = trades.reason.eq('daily_risk_reduce')
    trades.loc[mask, 'category'] = trades.loc[mask, 'risk_action'].map(
        {'cap': 'daily_cap', 'soft': 'soft_reduce', 'cap_and_soft': 'cap_and_soft'})
    reasons = []
    for category, part in trades.groupby('category', dropna=False):
        reasons.append(dict(case=case, category=category, orders=len(part),
                            buys=int(part.signed_units.gt(0).sum()),
                            traded_notional=float(part.signed_notional.abs().sum()), fees=float(part.fee.sum())))
    # Final liquidation makes each security's net cash flow an additive P&L
    # accounting attribution. It is not a leave-one-stock-out causal effect.
    contribution = []
    for symbol, part in trades.groupby('symbol'):
        contribution.append(dict(case=case, symbol=symbol,
                                 net_pnl_per_initial_nav=float(part.cash_change.sum()),
                                 ordinary_fees_per_initial_nav=float(part.fee.sum()),
                                 orders=len(part), stop_exits=int(part.reason.str.startswith('stop_').sum())))
    np.testing.assert_allclose(sum(row['net_pnl_per_initial_nav'] for row in contribution),
                               result['metrics']['total_return'], rtol=1e-9, atol=1e-10)
    return reasons, contribution


def label_columns(labels):
    aliases = {'plain': ('plain_net_excess',), 'stopped': ('stopped_net_excess',)}
    selected = {}
    for name, candidates in aliases.items():
        matches = [column for column in candidates if column in labels]
        if len(matches) != 1:
            raise ValueError(f'Expected one explicit {name} payoff column, got {matches}')
        selected[name] = matches[0]
    return selected


def signal_diagnostics(scores, labels):
    targets = label_columns(labels)
    columns = ['Date', 'symbol', *targets.values()]
    merged = scores.merge(labels[columns].rename(columns={value: f'{key}_payoff' for key, value in targets.items()}),
                          on=['Date', 'symbol'], how='left', validate='one_to_one')
    # A common matured-date sample avoids comparing signals on different tails.
    available = merged[['plain_payoff', 'stopped_payoff']].notna().all(axis=1)
    counts = merged.assign(available=available).groupby('Date').available.sum()
    mature_dates = counts.index[counts.eq(len(SYMBOLS))]
    rows = merged.loc[merged.Date.isin(mature_dates)].copy()
    if rows.empty or not np.isfinite(rows[[*ALL_SIGNALS, 'plain_payoff', 'stopped_payoff']]).all().all():
        raise ValueError('No complete finite common matured target sample.')
    daily, selection = [], []
    for date, part in rows.groupby('Date', sort=True):
        for signal in ALL_SIGNALS:
            score_rank = part[signal].rank(method='average')
            selected = part.sort_values([signal, 'symbol'], ascending=[False, True], kind='stable').head(8)
            for target in ('plain', 'stopped'):
                payoff = f'{target}_payoff'
                target_rank = part[payoff].rank(method='average')
                ic = float(score_rank.corr(target_rank))
                daily.append(dict(Date=date, signal=signal, target=target, rank_ic=ic,
                                  cross_section_count=len(part)))
                selection.append(dict(Date=date, signal=signal, target=target,
                                      selected_symbols='|'.join(selected.symbol), selected_count=len(selected),
                                      mean_top8_payoff=float(selected[payoff].mean()),
                                      mean_all30_payoff=float(part[payoff].mean()),
                                      top8_minus_all30=float(selected[payoff].mean() - part[payoff].mean())))
    daily = pd.DataFrame(daily)
    selection = pd.DataFrame(selection)
    summary = daily.groupby(['signal', 'target'], as_index=False).agg(
        mean_rank_ic=('rank_ic', 'mean'), valid_ic_dates=('rank_ic', 'count'), total_dates=('Date', 'size'))
    means = selection.groupby(['signal', 'target'], as_index=False).agg(
        mean_top8_payoff=('mean_top8_payoff', 'mean'), mean_all30_payoff=('mean_all30_payoff', 'mean'),
        mean_top8_minus_all30=('top8_minus_all30', 'mean'))
    summary = summary.merge(means, on=['signal', 'target'], validate='one_to_one')
    annual = daily.assign(year=daily.Date.dt.year).groupby(['signal', 'target', 'year'], as_index=False).agg(
        mean_rank_ic=('rank_ic', 'mean'), valid_ic_dates=('rank_ic', 'count'))
    daily.to_csv(OUT / 'signal_daily_ic.csv', index=False, date_format='%Y-%m-%d')
    selection.to_csv(OUT / 'top8_target_paths.csv', index=False, date_format='%Y-%m-%d')
    summary.to_csv(OUT / 'signal_diagnostics.csv', index=False)
    annual.to_csv(OUT / 'signal_annual_ic.csv', index=False)
    return summary


def gate_rows(table):
    simple = table.loc[table.signal.isin(('simple_h60', 'simple_spy')) & table.scenario.eq('cost10')]
    admissible = simple.loc[simple.max_drawdown.ge(-.30)]
    gates = {}
    for signal in NEW_SIGNALS:
        main = table.loc[table.signal.eq(signal) & table.scenario.eq('cost10')].iloc[0]
        stress = table.loc[table.signal.eq(signal) & ~table.scenario.eq('cost10')]
        assert len(stress) == 6
        tests = dict(cagr_at_least_30=bool(main.cagr >= .30), drawdown_within_30=bool(main.max_drawdown >= -.30),
                     beats_admissible_simple_net_cagr=bool(len(admissible) and main.cagr > admissible.cagr.max()),
                     all_fixed_stress_positive_and_drawdown_within_30=bool(stress.total_return.gt(0).all() and stress.max_drawdown.ge(-.30).all()))
        passed = all(tests.values())
        gates[signal] = {**tests, 'development_passed': passed,
                         'preferred_drawdown_within_20': bool(main.max_drawdown >= -.20),
                         'aspiration_cagr_50': bool(main.cagr >= .50),
                         'decision': 'DEVELOPMENT_ONLY_REVIEW_REQUIRED' if passed else 'REJECT_NO_2026'}
    passed_signals = [name for name, result in gates.items() if result['development_passed']]
    eligible = table.loc[table.signal.isin(passed_signals) & table.scenario.eq('cost10')]
    eligible = eligible.sort_values(['cagr', 'signal'], ascending=[False, True], kind='stable')
    return {'candidates': gates, 'selected_for_development_review': None if eligible.empty else eligible.iloc[0].signal,
            'selection_rule': 'Passing candidates only: cost10 CAGR descending, exact ties by signal ID ascending.',
            'independent_validation_passed': False, 'candidate_frozen_for_2026': False,
            'prices_2026_accessed': False, 'old_0_of_98_unchanged': True,
            'decision': 'DEVELOPMENT_ONLY_REVIEW_REQUIRED' if any(g['development_passed'] for g in gates.values()) else 'REJECT_NO_2026'}


def markdown_table(headers, records):
    def cell(value):
        return str(value).replace('|', '/').replace('\n', ' ')
    lines = ['| ' + ' | '.join(headers) + ' |', '| ' + ' | '.join('---' for _ in headers) + ' |']
    lines += ['| ' + ' | '.join(cell(value) for value in row) + ' |' for row in records]
    return '\n'.join(lines)


def write_report(table, annual, diagnostic, gates, training):
    pretty = {'baseline_rank': '原H60名次', 'plain_magnitude': '未止损净超额收益幅度',
              'stopped_magnitude': '保护后净超额收益幅度', 'stopped_rank': '保护后净超额收益名次',
              'simple_h60': '简单H60/80%预算', 'simple_spy': 'SPY/80%预算'}
    main = table.loc[table.scenario.eq('cost10')]
    rows = [[pretty.get(row.signal, row.signal), f'{row.total_return:.2%}', f'{row.cagr:.2%}',
             f'{row.max_drawdown:.2%}', f'{row.annualized_vol:.2%}', f'{row.average_gross:.2%}',
             f'{row.turnover_two_way_per_year:.2f}', f'{10000 * row.fee_per_initial_nav:.2f}',
             f'{10000 * row.stop_slippage_per_initial_nav:.2f}'] for row in main.itertuples()]
    stress_rows = [[pretty.get(row.signal, row.signal), row.scenario, f'{row.total_return:.2%}',
                    f'{row.cagr:.2%}', f'{row.max_drawdown:.2%}'] for row in table.loc[~table.scenario.eq('cost10')].itertuples()]
    gate_table = [[pretty[signal], item['cagr_at_least_30'], item['drawdown_within_30'],
                   item['beats_admissible_simple_net_cagr'], item['all_fixed_stress_positive_and_drawdown_within_30'],
                   item['decision']] for signal, item in gates['candidates'].items()]
    yearly = annual.loc[annual.case.isin(main.case)].pivot(index='year', columns='case', values='return_net')
    annual_rows_display = [[year, *[f'{yearly.loc[year, case]:.2%}' for case in main.case]] for year in yearly.index]
    diag_rows = [[pretty[row.signal], row.target, f'{row.mean_rank_ic:.4f}', int(row.valid_ic_dates),
                  f'{row.mean_top8_payoff:.2%}', f'{row.mean_top8_minus_all30:.2%}'] for row in diagnostic.itertuples()]
    conclusion = ('没有新增方案同时通过本轮收益、风险和固定压力条件，拒绝升级。'
                  if gates['decision'] == 'REJECT_NO_2026' else
                  '至少一个新增方案通过本轮开发筛选，但这不是独立验证；需审阅后才可讨论唯一候选冻结。')
    best = main.loc[main.signal.isin(NEW_SIGNALS)].sort_values(['cagr', 'signal'], ascending=[False, True]).iloc[0]
    baseline = main.loc[main.signal.eq('baseline_rank')].iloc[0]
    report = f'''# H60目标对齐研究：固定v11结果

{conclusion} 2026行情没有读取；没有券商连接或订单。目标仍为扣费长期CAGR至少30%、争取50%，回撤优先20%以内、上沿30%，不加杠杆、不降低标准。

本轮新增 **{training['new_fits']}次实际拟合**，复用原H60 **10份年度模型及已保存预测**；新增 **21次固定组合回放**，另复用 **21条v8原控制结果**。所有复用文件先核对原ARTIFACTS哈希。训练次数是过程记录，不是有效样本数或进步证据。

## 实验问什么

固定81个历史价格/ETF特征、H60、Ridge参数和v8风控，仅比较收益目标的幅度/名次及路径保护。模型过去只学习终点的相对强弱，而实际持仓途中可能被15%保护退出。新标签问的是：让模型学习带保护的路径收益，能否改善未改变的组合策略。完整定义与运行前约束见[PLAN.md](PLAN.md)、[plan.json](plan.json)。

保护后的单笔标签仍是路径代理；组合还会排名淘汰、调仓、暂停和限制现金，标签收益不是组合收益。幅度与名次的训练损失单位不同，不能比较原始MSE判断谁更强。止损价也不是成交或最大损失保证。

## 完整开发区间

2016-01-05—2025-12-29（相位压力按预先固定起点变化）；初始权益1对应10,000 USD，收盘权益、零息现金、调整OHLC和碎股研究代理，含首次建仓和最后开盘清仓。普通交易每边10bp，止损额外10bp；资金成本不借款。累计普通费用和止损滑点按10,000 USD起始资金展示，覆盖整个区间。

{markdown_table(['配置', '累计净收益', 'CAGR', '收盘回撤', '波动', '平均仓位', '年双向换手', '普通费用USD', '止损滑点USD'], rows)}

新增方案中开发CAGR最高者为“{pretty[best.signal]}”：{best.cagr:.2%}，回撤{best.max_drawdown:.2%}；相对原H60名次的CAGR差为{100 * (best.cagr - baseline.cagr):+.2f}个百分点。此描述没有将它自动选为部署模型；逐项验收如下，失败项全部保留。

{markdown_table(['新增方案', 'CAGR≥30%', '回撤≤30%', '胜同预算简单对照', '全部固定压力通过', '决定'], gate_table)}

简单对照与候选共享事前80%风险预算、SPY波动缩仓和20%硬暂停，集中度和个股退出不同，不称实现波动相同。即使某方案开发年化超过30%，反复使用的2016—2025也不是独立证据；既有0/98统计门槛未被撤销。

## 各年真实收益

{markdown_table(['年', *[pretty[s] for s in main.signal]], annual_rows_display)}

不要求每个自然年达到30%；年内结果不能替代完整区间。全部年度波动、年内回撤和全历史回撤见[annual_results.csv](annual_results.csv)。

## 全部固定成本与压力

{markdown_table(['配置', '预登记场景', '累计净收益', 'CAGR', '收盘回撤'], stress_rows)}

cost20为普通每边20bp/止损额外10bp；cost30_stop50为30/50bp；delayed_next_open为20/50bp并延后到下一开盘；phase1/4不搜索最佳相位；exclude_NVDA只禁止该股交易，不重训。每条成本会改变风险状态路径，因此更高成本不保证回撤单调增加。

## 信号与路径诊断

只在四个信号共有且完整成熟的标签日期比较；并列名次取平均，top8评分同分按股票代码固定破同分。plain/stopped为同期限未保护/保护路径净收益减去同期SPY毛收益。训练标签固定普通10bp/止损额外10bp，不随各压力回放费用重新训练；gross字段只去除普通费用，保护成交仍包括额外滑点。下表是重叠60日单笔路径的描述性平均，不能年化成策略业绩，也不是实际持仓组合。

{markdown_table(['信号', '评价目标', '平均Rank IC', '有效日数', 'top8平均路径收益', 'top8减全30股'], diag_rows)}

[逐日IC](signal_daily_ic.csv)、[年度IC](signal_annual_ic.csv)、[top8路径选择记录](top8_target_paths.csv)均保留。日内价格顺序不可完全由OHLC知道；训练和验证必须等标签成熟，短期退出不能借机放松时间边界。

## 交易来源、训练身份与执行边界

[trade_reason_summary.csv](trade_reason_summary.csv)区分计划调仓、日常只减仓上限、止损和暂停等直接原因；这些不是规则的独立因果贡献。[stock_contributions.csv](stock_contributions.csv)按最终清仓后的个股净现金流分摊P&L，不能解释为删掉该股后的组合收益。每个新增回放保留daily/trades/positions/targets/events/metrics及完成文件哈希；[RUN_CHECKS.json](RUN_CHECKS.json)验证现金、股数、费用、收盘权益、最终清仓以及非计划买单为0。

[training_summary.csv](training_summary.csv)保存逐次训练记录；[TRAINING_RECORD.json](TRAINING_RECORD.json)记录实际次数与复用模型身份；[EVALUATION_IDENTITY.json](EVALUATION_IDENTITY.json)冻结计划、来源、预测、标签和代码身份。没有新训练的控制不计作拟合。

本轮使用现有Python研究引擎，沿用已通过LEAN迁移一致性检查的策略函数；本轮新增方案没有单独完成LEAN原生行情/公司行动验证或券商paper联调。新增真实paper回报0、真实账户订单0、独立前瞻业绩0，工程回放不能证明盈利。

## 阻塞与下一步

当前仍是存续30股、静态行业代理、可修订调整价格；完整历史股票池/退市数据仍未获得。2016—2025参与过多轮开发，不能再包装为独立终测。若本轮不达标，应保留目标对齐结果并优先取得具有历史股票池/退市覆盖的新证据来源，而非继续调止损或容量直到历史变好；若开发筛选通过，也先审阅唯一候选和冻结协议，2026仍封存。

报告基于本轮已完成产物，生成时间{now()}。
'''
    (OUT / 'REPORT.md').write_text(report, encoding='utf-8')


def build_artifacts():
    paths = [path for path in OUT.rglob('*') if path.is_file() and path.name != 'ARTIFACTS.csv'
             and path.suffix not in ('.log', '.tmp')]
    paths.append(Path(__file__).resolve())
    pd.DataFrame([file_record(path) for path in sorted(set(paths))]).to_csv(OUT / 'ARTIFACTS.csv', index=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-only', action='store_true', help='Freeze/check inputs without new strategy runs.')
    parser.add_argument('--deadline-utc', help='Stop before starting another case at this UTC ISO timestamp.')
    args = parser.parse_args()
    plan_path = OUT / 'plan.json'
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    deadline = datetime.fromisoformat(args.deadline_utc or plan['deadline_utc'])
    if deadline.tzinfo is None:
        raise ValueError('Deadline requires an explicit UTC offset.')
    if sha(OUT / 'PLAN.md') != plan['design_sha256']:
        raise ValueError('Registered experiment design changed.')
    expected_candidates = {'plain_magnitude': 'plain_net_excess', 'stopped_magnitude': 'stopped_net_excess',
                           'stopped_rank': 'stopped_net_rank'}
    if plan['candidates'] != expected_candidates or plan['costs'] != [10, 20]:
        raise ValueError('Unexpected candidate or cost matrix.')
    if plan['fixed_stress'] != list(SCENARIOS[2:]):
        raise ValueError('Unexpected preregistered stress matrix.')
    if (plan['cagr_floor'], plan['drawdown_ceiling'], plan['cagr_aspiration'], plan['preferred_drawdown']) != (.30, .30, .50, .20):
        raise ValueError('Profit/risk acceptance thresholds changed.')
    training_complete = json.loads((OUT / 'TRAINING_COMPLETE.json').read_text(encoding='utf-8'))
    for name, digest in training_complete['outputs_sha256'].items():
        if sha(OUT / name) != digest:
            raise ValueError(f'Frozen training output changed: {name}')
    training_identity = json.loads((OUT / 'TRAINING_IDENTITY.json').read_text(encoding='utf-8'))
    if training_identity['plan_sha256'] != sha(plan_path):
        raise ValueError('Training and evaluation refer to different plans.')
    for name, digest in training_identity['source_sha256'].items():
        if sha(ROOT / name) != digest:
            raise ValueError(f'Frozen training/strategy implementation changed: {name}')
    old_manifest = verify_old_manifest()
    bars, spy_bars, spy, original, observations, final, input_identity = load_inputs()
    if str(final.date()) != '2025-12-29' or str((bars['Open'].index[bars['Open'].index.get_loc(observations[0]) + 1]).date()) != '2016-01-05':
        raise ValueError('Unexpected fixed evaluation interval.')
    old_plan = json.loads((OLD / 'plan.json').read_text(encoding='utf-8'))
    if old_plan['input_identity'] != input_identity:
        raise ValueError('v11 and reused v8 controls have different source data/model identity.')
    policy = asdict(replace(strategy.Policy(), soft_enabled=False))
    if old_plan['candidate'] != policy or plan['policy'] != policy or plan['input_identity'] != input_identity:
        raise ValueError('The v8 fixed risk policy changed.')
    scores = pd.read_csv(OUT / 'scores.csv', parse_dates=['Date'], float_precision='round_trip')
    labels = pd.read_csv(OUT / 'labels.csv', parse_dates=['Date', 'entry_date', 'exit_60', 'stopped_exit_date'],
                         float_precision='round_trip')
    training_table = pd.read_csv(OUT / 'training_summary.csv', float_precision='round_trip')
    if scores.duplicated(['Date', 'symbol']).any() or labels.duplicated(['Date', 'symbol']).any():
        raise ValueError('Duplicate stock/date keys in frozen predictions or labels.')
    if scores.Date.max() >= pd.Timestamp('2026-01-01') or labels.Date.max() >= pd.Timestamp('2026-01-01'):
        raise ValueError('2026 observation data are not allowed in this experiment.')
    if labels.exit_60.max() >= pd.Timestamp('2026-01-01') or labels.stopped_exit_date.max() >= pd.Timestamp('2026-01-01'):
        raise ValueError('A future target crossed the sealed 2026 boundary.')
    if not labels[['plain_net_excess', 'stopped_net_excess']].notna().all(axis=1).equals(labels.exit_60.notna()):
        raise ValueError('Payoff availability and common label maturity differ.')
    wide = {}
    for signal in ALL_SIGNALS:
        frame = scores.pivot(index='Date', columns='symbol', values=signal).reindex(columns=SYMBOLS)
        pd.testing.assert_index_equal(frame.index, original.index)
        if not np.isfinite(frame).all().all():
            raise ValueError(f'Missing or non-finite scores: {signal}')
        wide[signal] = frame
    pd.testing.assert_frame_equal(wide['baseline_rank'], original, check_exact=True)
    label_columns(labels)
    source_paths = ['51_evaluate_signal_objectives.py', '42_evaluate_h60_risk_fixes.py',
                    'profit_priority_strategy.py', 'research_backtest.py', 'h60_research_inputs.py', 'research_features.py']
    fixed = {'plan_sha256': sha(plan_path), 'policy': policy, 'source_files': [file_record(ROOT / p) for p in source_paths],
             'score_file': file_record(OUT / 'scores.csv'), 'label_file': file_record(OUT / 'labels.csv'),
             'training_file': file_record(OUT / 'training_summary.csv'), 'old_artifacts': old_manifest,
             'training_complete': file_record(OUT / 'TRAINING_COMPLETE.json'),
             'training_identity': file_record(OUT / 'TRAINING_IDENTITY.json'),
             'input_identity': input_identity, 'new_signals': list(NEW_SIGNALS), 'scenarios': list(SCENARIOS),
             'new_runs': 21, 'reused_control_runs': 21, 'prices_2026_accessed': False}
    identity_path = OUT / 'EVALUATION_IDENTITY.json'
    if identity_path.exists():
        if json.loads(identity_path.read_text(encoding='utf-8')) != fixed:
            raise ValueError('Immutable evaluation inputs/code differ; do not overwrite completed research.')
    else:
        save(identity_path, fixed)
    identity_sha = sha(identity_path)
    if (OUT / 'evaluation_complete.json').exists():
        complete = json.loads((OUT / 'evaluation_complete.json').read_text(encoding='utf-8'))
        if complete['evaluation_identity_sha256'] != identity_sha:
            raise ValueError('Completion marker identity differs.')
        for row in pd.read_csv(OUT / 'ARTIFACTS.csv').to_dict('records'):
            check_record(row)
        print('Complete fixed v11 evaluation verified; no runs repeated, no reports rewritten.')
        return
    if args.check_only:
        print('Frozen v11/v8 inputs and predictions verified. No new strategy runs.')
        return
    results, metadata, checks = {}, [], {}
    for signal in ('baseline_rank', 'simple_h60', 'simple_spy'):
        for scenario in SCENARIOS:
            case = f'{signal}_{scenario}'
            previous_case = old_case(signal, scenario)
            result = read_old(previous_case)
            checks[case] = old_tools.audit(result, spy_bars if signal == 'simple_spy' else bars)
            if result['metrics']['risk_reduction_buy_orders'] != 0:
                raise AssertionError('Reused control has a nonplanned buy.')
            results[case] = result
            metadata.append(dict(case=case, signal=signal, scenario=scenario, origin='reused_v8', original_case=previous_case,
                                 **result['metrics']))
    for signal in NEW_SIGNALS:
        for scenario in SCENARIOS:
            case = f'{signal}_{scenario}'
            folder = OUT / 'backtests' / case
            if (folder / 'complete.json').exists():
                result = read_case(folder, identity_sha)
            else:
                if deadline is not None and datetime.now(timezone.utc) >= deadline:
                    save(OUT / 'EVALUATION_PROGRESS.json', {'status': 'deadline', 'completed_cases': list(results), 'updated_at_utc': now()})
                    raise TimeoutError('Budget ended; completed cases retained for exact resume.')
                obs, kwargs = scenario_options(scenario, bars['Open'].index, observations, wide[signal].index, final)
                start = time.perf_counter()
                result = strategy.simulate(wide[signal], bars, spy, features.SECTOR_PROXY, obs, final, **kwargs)
                old_tools.enrich(result)
                result['metrics']['runtime_seconds'] = time.perf_counter() - start
                old_tools.audit(result, bars)
                save_case(folder, result, identity_sha)
            checks[case] = old_tools.audit(result, bars)
            if result['metrics']['risk_reduction_buy_orders'] != 0:
                raise AssertionError('Nonplanned risk reduction increased a position.')
            results[case] = result
            metadata.append(dict(case=case, signal=signal, scenario=scenario, origin='new_v11', original_case='', **result['metrics']))
            pd.DataFrame(metadata).to_csv(OUT / 'all_results.csv', index=False)
            save(OUT / 'EVALUATION_PROGRESS.json', {'status': 'running', 'completed_cases': list(results), 'updated_at_utc': now()})
            print(f'{case}: CAGR={result["metrics"]["cagr"]:.3%}, DD={result["metrics"]["max_drawdown"]:.3%}', flush=True)
    table = pd.DataFrame(metadata)
    table.to_csv(OUT / 'all_results.csv', index=False)
    table.loc[table.scenario.isin(('cost10', 'cost20'))].to_csv(OUT / 'comparison.csv', index=False)
    table.loc[~table.scenario.isin(('cost10', 'cost20'))].to_csv(OUT / 'stress_comparison.csv', index=False)
    annual, reason_rows, contribution = [], [], []
    for case, result in results.items():
        annual.extend(annual_rows(case, result))
        reasons, stocks = trade_diagnostics(case, result)
        reason_rows.extend(reasons)
        contribution.extend(stocks)
    annual = pd.DataFrame(annual)
    annual.to_csv(OUT / 'annual_results.csv', index=False)
    pd.DataFrame(reason_rows).to_csv(OUT / 'trade_reason_summary.csv', index=False)
    pd.DataFrame(contribution).to_csv(OUT / 'stock_contributions.csv', index=False)
    pd.DataFrame({case: result['daily'].equity for case, result in results.items()}).to_csv(OUT / 'equity.csv')
    diagnostics = signal_diagnostics(scores, labels)
    gates = gate_rows(table)
    save(OUT / 'GATES.json', gates)
    save(OUT / 'RUN_CHECKS.json', checks)
    new_fits = len(training_table)
    if 'status' in training_table:
        new_fits = int(training_table.status.eq('trained').sum())
    if new_fits != training_complete['new_fits'] or new_fits != 30:
        raise ValueError('Actual fit records do not match the fixed 30-fit experiment.')
    training = {'new_fits': new_fits, 'summary': file_record(OUT / 'training_summary.csv'),
                'reused_annual_models': input_identity['models'], 'reused_annual_model_count': 10,
                'new_strategy_runs': 21, 'reused_control_runs': 21,
                'note': 'New fits from saved training records; controls are reused rather than retrained.'}
    save(OUT / 'TRAINING_RECORD.json', training)
    write_report(table, annual, diagnostics, gates, training)
    save(OUT / 'EVALUATION_PROGRESS.json', {'status': 'complete', 'completed_cases': list(results), 'updated_at_utc': now()})
    save(OUT / 'evaluation_complete.json', {'completed_at_utc': now(), 'evaluation_identity_sha256': identity_sha,
                                           'new_strategy_runs': 21, 'reused_control_runs': 21, 'new_fits': new_fits,
                                           'all_ledgers_checked': True, 'prices_2026_accessed': False, 'orders_sent': 0,
                                           'gates': gates})
    build_artifacts()
    print(json.dumps(gates, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
