"""Fixed annual-cutoff A/B comparison, using saved predictions and unchanged v8 risk.

Run only after 53_train_annual_cutoff.py. This entry point never fits a model,
downloads prices, or accesses a broker. Completed cases are immutable and resumed
only after their inputs, implementation and output hashes pass verification.
"""
import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
import subprocess
import sys
import time

import numpy as np
import pandas as pd

import profit_priority_strategy as strategy
import research_features as features
from h60_research_inputs import PRIOR, load_inputs, save, sha
from panel_config import ROOT, SYMBOLS

previous = importlib.import_module('51_evaluate_signal_objectives')
auditor = importlib.import_module('42_evaluate_h60_risk_fixes')
OUT = ROOT / 'data/experiments/h60_training_cutoff_v12'
SCENARIOS = previous.SCENARIOS
CONFIGURATIONS = ('protected', 'simple_h60')
TABLE_KEYS = previous.TABLE_KEYS


def now():
    return datetime.now(timezone.utc).isoformat()


def record(path):
    return previous.file_record(Path(path))


def immutable_save(path, value):
    if path.exists():
        if json.loads(path.read_text(encoding='utf-8')) != value:
            raise ValueError(f'Immutable evaluation identity changed: {path.name}')
    else:
        save(path, value)


def full_history_check(result):
    """Account high water includes initial cash and never uses episode_peak."""
    daily = result['daily']
    expected = daily.equity / daily.equity.cummax().clip(lower=1.) - 1
    np.testing.assert_allclose(daily.drawdown, expected, rtol=1e-11, atol=1e-12)
    np.testing.assert_allclose(result['metrics']['max_drawdown'], expected.min(),
                               rtol=1e-11, atol=1e-12)
    episode = daily.equity / daily.episode_peak - 1
    return dict(full_history_drawdown_verified=True,
                full_history_drawdown=float(expected.min()),
                minimum_recorded_episode_drawdown=float(episode.min()),
                full_history_budget_exceeded=bool(expected.min() < -.30),
                account_high_water_never_reset=True)


def stop_slippage(trades):
    stopped = trades.loc[trades.reason.str.startswith('stop_')]
    return stopped.signed_units.abs() * stopped.proxy_fill * (
        1 / (1 - stopped.stop_extra_bps / 10000) - 1)


def annual_rows(case, result):
    rows, daily, trades = [], result['daily'], result['trades']
    previous_nav = daily.equity.shift(1, fill_value=1.)
    notional = trades.groupby('Date').signed_notional.apply(lambda s: s.abs().sum())
    daily_turnover = notional.reindex(daily.index, fill_value=0.) / previous_nav
    for year, part in daily.groupby(daily.index.year):
        start = daily.index.get_loc(part.index[0])
        initial = 1. if start == 0 else float(daily.equity.iloc[start - 1])
        year_trades = trades.loc[trades.Date.dt.year.eq(year)]
        fees, slip = float(year_trades.fee.sum()), float(stop_slippage(year_trades).sum())
        rows.append(dict(case=case, year=int(year),
                         return_net=float(part.equity.iloc[-1] / initial - 1),
                         volatility=float(part['return'].std(ddof=1) * np.sqrt(252)),
                         within_year_drawdown=float((part.equity / part.equity.cummax().clip(lower=initial) - 1).min()),
                         full_history_drawdown_min=float(part.drawdown.min()),
                         minimum_recorded_episode_drawdown=float((part.equity / part.episode_peak - 1).min()),
                         average_gross=float(part.gross.mean()),
                         turnover_two_way=float(daily_turnover.loc[part.index].sum()),
                         ordinary_fees_per_initial_nav=fees,
                         stop_slippage_per_initial_nav=slip,
                         explicit_cost_per_initial_nav=fees + slip,
                         explicit_cost_per_year_start_nav=(fees + slip) / initial,
                         stop_exits=int(year_trades.reason.str.startswith('stop_').sum()),
                         halts=int(result['events'].event.eq('portfolio_halt').loc[
                             result['events'].Date.dt.year.eq(year)].sum()) if len(result['events']) else 0))
    return rows


def paired_deltas(table):
    metrics = ('cagr', 'total_return', 'max_drawdown', 'annualized_vol', 'average_gross',
               'turnover_two_way_per_year', 'fee_per_initial_nav', 'stop_slippage_per_initial_nav',
               'explicit_total_cost_per_initial_nav', 'stop_exits', 'halts')
    rows = []
    for configuration in CONFIGURATIONS:
        for scenario in SCENARIOS:
            part = table.loc[table.configuration.eq(configuration) & table.scenario.eq(scenario)].set_index('protocol')
            if set(part.index) != {'A', 'B'}:
                raise ValueError('Every comparison must contain exactly one A and one B.')
            row = dict(configuration=configuration, scenario=scenario)
            for metric in metrics:
                row[f'A_{metric}'] = float(part.loc['A', metric])
                row[f'B_{metric}'] = float(part.loc['B', metric])
                row[f'delta_{metric}'] = float(part.loc['B', metric] - part.loc['A', metric])
            rows.append(row)
    return pd.DataFrame(rows)


def gates(table):
    protected = table.loc[table.configuration.eq('protected')].set_index(['protocol', 'scenario'])
    b = protected.loc['B']
    improvement = (bool(b.loc['cost10', 'cagr'] > protected.loc[('A', 'cost10'), 'cagr'])
                   and bool(b.loc['cost20', 'cagr'] > protected.loc[('A', 'cost20'), 'cagr'])
                   and bool(b.max_drawdown.ge(-.30).all()))
    main, stress = b.loc['cost10'], b.drop(index='cost10')
    if len(stress) != 6:
        raise ValueError('Exactly six fixed pressure/control-cost scenarios are required.')
    thresholds = dict(net_cagr_at_least_30=bool(main.cagr >= .30),
                      full_history_drawdown_within_30=bool(main.max_drawdown >= -.30))
    pressure_ok = bool(stress.total_return.gt(0).all() and stress.max_drawdown.ge(-.30).all())
    simple = table.loc[table.protocol.eq('B') & table.configuration.eq('simple_h60') & table.scenario.eq('cost10')].iloc[0]
    controls = table.loc[table.scenario.eq('cost10') & (
        (table.protocol.eq('B') & table.configuration.eq('simple_h60')) |
        (table.protocol.eq('control') & table.configuration.eq('simple_spy')))]
    if len(controls) != 2:
        raise ValueError('Both same-budget B simple H60 and reused SPY are required.')
    admissible = controls.loc[controls.max_drawdown.ge(-.30)]
    beats_controls = bool(len(admissible) and main.cagr > admissible.cagr.max())
    passed = all(thresholds.values()) and pressure_ok and beats_controls
    return dict(research_improvement=improvement,
                research_improvement_rule='Protected B CAGR exceeds A at both cost10 and cost20; all seven B full-history drawdowns remain within 30%.',
                protected_numerical_objectives=thresholds,
                protected_numerical_objectives_met=all(thresholds.values()),
                all_fixed_pressure_positive_and_drawdown_within_30=pressure_ok,
                beats_admissible_same_budget_simple_cagr=beats_controls,
                development_gate_passed=passed,
                preferred_drawdown_within_20=bool(main.max_drawdown >= -.20),
                aspiration_cagr_50=bool(main.cagr >= .50),
                protected_beats_same_protocol_simple_cagr=bool(main.cagr > simple.cagr),
                simple_diagnostic_only=True,
                independent_validation_passed=False, candidate_frozen_for_2026=False,
                prices_2026_accessed=False, model_promoted_to_lean_or_paper=False,
                decision='DEVELOPMENT_ONLY_REVIEW_REQUIRED' if passed else 'REJECT_NO_2026')


def selection_pairs(results):
    """Compare actual target/holding sets, including divergent pause schedules."""
    rows, summary = [], []
    for configuration in CONFIGURATIONS:
        for scenario in SCENARIOS:
            pair = {p: results[f'{p}_{configuration}_{scenario}'] for p in ('A', 'B')}
            targets = {p: r['targets'].loc[r['targets'].reason.eq('scheduled')].set_index('Date') for p, r in pair.items()}
            for frame in targets.values():
                if frame.index.duplicated().any():
                    raise ValueError('More than one planned target on the same date.')
            dates = targets['A'].index.union(targets['B'].index).sort_values()
            scheduled_rows = []
            for date in dates:
                weights = {p: targets[p].loc[date, SYMBOLS].astype(float) if date in targets[p].index else None for p in ('A', 'B')}
                selected = {p: set(w.index[w.gt(1e-12)]) if w is not None else set() for p, w in weights.items()}
                common = weights['A'] is not None and weights['B'] is not None
                row = dict(configuration=configuration, scenario=scenario, Date=date,
                           A_has_scheduled_target=weights['A'] is not None,
                           B_has_scheduled_target=weights['B'] is not None,
                           A_symbols='|'.join(sorted(selected['A'])), B_symbols='|'.join(sorted(selected['B'])),
                           shared_symbols=len(selected['A'] & selected['B']),
                           changed_symbols=len(selected['A'] ^ selected['B']),
                           target_weight_l1=float((weights['A'] - weights['B']).abs().sum()) if common else np.nan,
                           sets_differ=selected['A'] != selected['B'])
                scheduled_rows.append(row)
            rows.extend(scheduled_rows)
            a, b = pair['A']['positions'], pair['B']['positions']
            pd.testing.assert_index_equal(a.index, b.index)
            # These are adjusted-price fractional-unit holdings, not broker share counts.
            changed_holdings = (a.gt(1e-12) != b.gt(1e-12)).any(axis=1)
            frame = pd.DataFrame(scheduled_rows)
            common = frame.A_has_scheduled_target & frame.B_has_scheduled_target
            summary.append(dict(configuration=configuration, scenario=scenario,
                                scheduled_dates_union=len(frame), common_scheduled_dates=int(common.sum()),
                                schedules_differ_dates=int((~common).sum()),
                                different_selected_set_dates=int(frame.sets_differ.sum()),
                                common_date_mean_weight_l1=float(frame.loc[common, 'target_weight_l1'].mean()),
                                common_date_mean_changed_symbols=float(frame.loc[common, 'changed_symbols'].mean()),
                                actual_holdings_set_differs_days=int(changed_holdings.sum()),
                                actual_holdings_set_differs_fraction=float(changed_holdings.mean())))
    return pd.DataFrame(rows), pd.DataFrame(summary)


def signal_diagnostics(scores, panel):
    needed = panel[['Date', 'symbol', 'rank_60', 'exit_60']]
    if needed.duplicated(['Date', 'symbol']).any():
        raise ValueError('Duplicate label keys.')
    merged = scores.merge(needed, on=['Date', 'symbol'], how='left', validate='one_to_one')
    mature = merged.rank_60.notna() & merged.exit_60.notna() & merged.exit_60.lt('2026-01-01')
    counts = merged.assign(mature=mature).groupby('Date').mature.sum()
    dates = counts.index[counts.eq(len(SYMBOLS))]
    sample = merged.loc[merged.Date.isin(dates)]
    if sample.empty or not np.isfinite(sample[['A', 'B', 'rank_60']]).all().all():
        raise ValueError('Rank IC requires finite A/B predictions on common fully mature dates.')
    rows = []
    for date, part in sample.groupby('Date', sort=True):
        target = part.rank_60.rank(method='average')
        for protocol in ('A', 'B'):
            rows.append(dict(Date=date, protocol=protocol, rank_ic=float(part[protocol].rank(method='average').corr(target)),
                             cross_section_count=len(part)))
    daily = pd.DataFrame(rows)
    if not np.isfinite(daily.rank_ic).all():
        raise ValueError('Undefined Rank IC (constant scores or labels).')
    summary = daily.groupby('protocol', as_index=False).agg(mean_rank_ic=('rank_ic', 'mean'), mature_dates=('Date', 'size'))
    annual = daily.assign(year=daily.Date.dt.year).groupby(['protocol', 'year'], as_index=False).agg(
        mean_rank_ic=('rank_ic', 'mean'), mature_dates=('Date', 'size'))
    summary['prediction_dates'] = scores.Date.nunique()
    summary['unmatured_prediction_dates_retained'] = scores.Date.nunique() - len(dates)
    return daily, summary, annual


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-only', action='store_true')
    parser.add_argument('--deadline-utc', default='2026-09-21T20:50:37+00:00')
    args = parser.parse_args()
    deadline = datetime.fromisoformat(args.deadline_utc) if args.deadline_utc else None
    if deadline is not None and deadline.tzinfo is None:
        raise ValueError('Deadline needs a timezone.')
    plan_path = OUT / 'plan.json'
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    training = json.loads((OUT / 'TRAINING_COMPLETE.json').read_text(encoding='utf-8'))
    if training['new_fits'] != 10:
        raise ValueError('The fixed B protocol requires exactly ten new annual fits.')
    for name, digest in training['outputs_sha256'].items():
        if sha(OUT / name) != digest:
            raise ValueError(f'Frozen training output changed: {name}')
    training_identity = json.loads((OUT / 'TRAINING_IDENTITY.json').read_text(encoding='utf-8'))
    if training_identity['plan_sha256'] != sha(plan_path):
        raise ValueError('Training and evaluation plan differ.')
    for name, digest in training_identity['source_sha256'].items():
        if sha(ROOT / name) != digest:
            raise ValueError(f'Frozen training source changed: {name}')
    old_manifest = previous.verify_old_manifest()
    bars, spy_bars, spy, original, observations, final, input_identity = load_inputs()
    saved_inputs = json.loads((OUT / 'INPUT_IDENTITY.json').read_text(encoding='utf-8'))
    if saved_inputs != input_identity:
        raise ValueError('Training and evaluation input identities differ.')
    old_plan = json.loads((previous.OLD / 'plan.json').read_text(encoding='utf-8'))
    policy = asdict(replace(strategy.Policy(), soft_enabled=False))
    if old_plan['input_identity'] != input_identity or old_plan['candidate'] != policy:
        raise ValueError('Reused v8 controls do not match input/policy identity.')
    if plan.get('policy', policy) != policy or plan.get('scenarios', list(SCENARIOS)) != list(SCENARIOS):
        raise ValueError('Preregistered policy/scenario matrix differs.')
    for key, expected in (('cagr_floor', .30), ('drawdown_ceiling', .30), ('cagr_aspiration', .50), ('preferred_drawdown', .20)):
        if plan.get(key, expected) != expected:
            raise ValueError(f'Preregistered objective changed: {key}')
    if str(final.date()) != '2025-12-29' or str(bars['Open'].index[bars['Open'].index.get_loc(observations[0]) + 1].date()) != '2016-01-05':
        raise ValueError('Unexpected replay interval.')
    scores = pd.read_csv(OUT / 'scores.csv', parse_dates=['Date'], float_precision='round_trip')
    if scores.duplicated(['Date', 'symbol']).any() or list(scores.columns) != ['Date', 'symbol', 'A', 'B']:
        raise ValueError('Unexpected prediction key/schema.')
    if scores.Date.max() >= pd.Timestamp('2026-01-01'):
        raise ValueError('2026 prices and predictions are excluded.')
    wide = {}
    for protocol in ('A', 'B'):
        frame = scores.pivot(index='Date', columns='symbol', values=protocol).reindex(columns=SYMBOLS)
        pd.testing.assert_index_equal(frame.index, original.index)
        if not np.isfinite(frame).all().all():
            raise ValueError(f'Incomplete prediction panel: {protocol}')
        wide[protocol] = frame
    pd.testing.assert_frame_equal(wide['A'], original, check_exact=True)
    source_paths = ('54_evaluate_training_cutoff.py', '51_evaluate_signal_objectives.py',
                    '42_evaluate_h60_risk_fixes.py', 'profit_priority_strategy.py',
                    'research_backtest.py', 'h60_research_inputs.py', 'research_features.py')
    fixed = dict(plan_sha256=sha(plan_path), policy=policy, source_files=[record(ROOT / p) for p in source_paths],
                 scores=record(OUT / 'scores.csv'), training_complete=record(OUT / 'TRAINING_COMPLETE.json'),
                 training_identity=record(OUT / 'TRAINING_IDENTITY.json'), training_summary=record(OUT / 'training_summary.csv'),
                 old_artifacts=old_manifest, input_identity=input_identity, scenarios=list(SCENARIOS),
                 configurations=list(CONFIGURATIONS), new_runs=14, reused_control_runs=21,
                 initial_equity=1., cash_interest=0., valuation='adjusted close', prices_2026_accessed=False)
    identity_path = OUT / 'EVALUATION_IDENTITY.json'
    if args.check_only and not identity_path.exists():
        print('Frozen training/predictions and v8 controls verified; no files written or runs repeated.')
        return
    immutable_save(identity_path, fixed)
    identity_sha = sha(identity_path)
    complete_path = OUT / 'evaluation_complete.json'
    if complete_path.exists():
        complete = json.loads(complete_path.read_text(encoding='utf-8'))
        if complete['evaluation_identity_sha256'] != identity_sha:
            raise ValueError('Evaluation completion identity differs.')
        for row in complete['files']:
            previous.check_record(row)
        print('Completed fixed v12 evaluation verified; no runs repeated or output rewritten.')
        return
    if args.check_only:
        print('Frozen v12 evaluation inputs and source identity verified; no runs repeated.')
        return
    if not (OUT / 'EVALUATION_RUN.json').exists():
        save(OUT / 'EVALUATION_RUN.json', dict(started_at_utc=now(), generation_git_head=subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            note='Commit metadata is provenance, not immutable experiment identity.'))
    results, metadata, checks = {}, [], {}
    for configuration in (*CONFIGURATIONS, 'simple_spy'):
        old_signal = 'baseline_rank' if configuration == 'protected' else configuration
        for scenario in SCENARIOS:
            protocol = 'control' if configuration == 'simple_spy' else 'A'
            case = f'{protocol}_{configuration}_{scenario}'
            old_case = previous.old_case(old_signal, scenario)
            result = previous.read_old(old_case)
            checks[case] = {**auditor.audit(result, spy_bars if configuration == 'simple_spy' else bars),
                            **full_history_check(result)}
            if result['metrics']['risk_reduction_buy_orders'] != 0:
                raise AssertionError('Reused result has a nonplanned buy.')
            results[case] = result
            metadata.append(dict(case=case, protocol=protocol, configuration=configuration, scenario=scenario,
                                 origin='reused_v8', original_case=old_case, **result['metrics']))
    for configuration in CONFIGURATIONS:
        for scenario in SCENARIOS:
            case = f'B_{configuration}_{scenario}'
            folder = OUT / 'backtests' / case
            if (folder / 'complete.json').exists():
                result = previous.read_case(folder, identity_sha)
            else:
                if deadline is not None and datetime.now(timezone.utc) >= deadline:
                    save(OUT / 'EVALUATION_PROGRESS.json', dict(status='deadline', completed_cases=list(results), updated_at_utc=now()))
                    raise TimeoutError('Budget ended; verified completed cases retained for exact resume.')
                obs, kwargs = previous.scenario_options(scenario, bars['Open'].index, observations, wide['B'].index, final)
                if configuration == 'simple_h60':
                    kwargs.update(mode='simple_h60', stops=False)
                start = time.perf_counter()
                result = strategy.simulate(wide['B'], bars, spy, features.SECTOR_PROXY, obs, final, **kwargs)
                auditor.enrich(result)
                result['metrics']['runtime_seconds'] = time.perf_counter() - start
                auditor.audit(result, bars)
                full_history_check(result)
                previous.save_case(folder, result, identity_sha)
            checks[case] = {**auditor.audit(result, bars), **full_history_check(result)}
            if result['metrics']['risk_reduction_buy_orders'] != 0:
                raise AssertionError('Nonplanned reduction increased a position.')
            results[case] = result
            metadata.append(dict(case=case, protocol='B', configuration=configuration, scenario=scenario,
                                 origin='new_v12', original_case='', **result['metrics']))
            pd.DataFrame(metadata).to_csv(OUT / 'all_results.csv', index=False)
            save(OUT / 'EVALUATION_PROGRESS.json', dict(status='running', completed_cases=list(results), updated_at_utc=now()))
            print(f'{case}: CAGR={result["metrics"]["cagr"]:.3%}; full-history DD={result["metrics"]["max_drawdown"]:.3%}', flush=True)
    table = pd.DataFrame(metadata)
    table.to_csv(OUT / 'all_results.csv', index=False)
    paired_deltas(table).to_csv(OUT / 'pair_deltas.csv', index=False)
    annual, reasons, contribution = [], [], []
    for case, result in results.items():
        annual.extend(annual_rows(case, result))
        reason, stocks = previous.trade_diagnostics(case, result)
        reasons.extend(reason)
        contribution.extend(stocks)
    pd.DataFrame(annual).to_csv(OUT / 'annual_results.csv', index=False)
    pd.DataFrame(reasons).to_csv(OUT / 'trade_reason_summary.csv', index=False)
    pd.DataFrame(contribution).to_csv(OUT / 'stock_contributions.csv', index=False)
    pd.DataFrame({case: result['daily'].equity for case, result in results.items()}).to_csv(OUT / 'equity.csv')
    selection, selection_summary = selection_pairs(results)
    selection.to_csv(OUT / 'paired_selections.csv', index=False, date_format='%Y-%m-%d')
    selection_summary.to_csv(OUT / 'selection_summary.csv', index=False)
    panel = pd.read_csv(PRIOR / 'panel.csv', usecols=['Date', 'symbol', 'rank_60', 'exit_60'],
                        parse_dates=['Date', 'exit_60'], float_precision='round_trip')
    ic_daily, ic_summary, ic_annual = signal_diagnostics(scores, panel)
    ic_daily.to_csv(OUT / 'signal_daily_ic.csv', index=False, date_format='%Y-%m-%d')
    ic_summary.to_csv(OUT / 'signal_diagnostics.csv', index=False)
    ic_annual.to_csv(OUT / 'signal_annual_ic.csv', index=False)
    gate = gates(table)
    save(OUT / 'GATES.json', gate)
    save(OUT / 'RUN_CHECKS.json', checks)
    save(OUT / 'EVALUATION_PROGRESS.json', dict(status='complete', completed_cases=list(results), updated_at_utc=now()))
    output_names = ('all_results.csv', 'pair_deltas.csv', 'annual_results.csv', 'trade_reason_summary.csv',
                    'stock_contributions.csv', 'equity.csv', 'paired_selections.csv', 'selection_summary.csv',
                    'signal_daily_ic.csv', 'signal_diagnostics.csv', 'signal_annual_ic.csv', 'GATES.json', 'RUN_CHECKS.json')
    records = [record(OUT / p) for p in output_names]
    for path in sorted((OUT / 'backtests').rglob('*')):
        if path.is_file():
            records.append(record(path))
    pd.DataFrame(records).to_csv(OUT / 'EVALUATION_ARTIFACTS.csv', index=False)
    save(complete_path, dict(completed_at_utc=now(), evaluation_identity_sha256=identity_sha,
                            new_strategy_runs=14, reused_control_runs=21, new_fits=10,
                            all_ledgers_checked=True, prices_2026_accessed=False, orders_sent=0,
                            gates=gate, files=records))
    print(json.dumps(gate, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
