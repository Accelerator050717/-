"""Fourteen fixed v13 global-risk replays; no fitting, data downloads or orders.

Requires completed record-only/continuity evidence and the separately frozen
plan. Reuses original A controls after hash verification. Commit HEAD is recorded
as provenance, never used as an immutable experiment identity.
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

import h60_global_research as engine
from h60_global_control import GlobalPolicy
from h60_research_inputs import load_inputs, save, sha
from panel_config import ROOT
from profit_priority_strategy import Policy
import research_features as features
from strategy_fund_journal import FundJournal

previous = importlib.import_module('51_evaluate_signal_objectives')
v12 = importlib.import_module('54_evaluate_training_cutoff')
auditor = importlib.import_module('42_evaluate_h60_risk_fixes')
OUT = ROOT / 'data/experiments/continuous_fund_risk_v13'
SCENARIOS = previous.SCENARIOS
CONFIGURATIONS = ('protected', 'simple_h60')
TABLE_KEYS = previous.TABLE_KEYS
DEADLINE = '2026-09-22T15:56:34+00:00'


def now():
    return datetime.now(timezone.utc).isoformat()


def immutable_save(path, value):
    if path.exists():
        if json.loads(path.read_text(encoding='utf-8')) != value:
            raise ValueError('Frozen evaluation identity changed: ' + str(path))
    else:
        save(path, value)


def pause_intervals(case, result):
    """Count closing-state paused sessions, including a trigger close."""
    daily = result['daily']
    episode = daily.paused.astype(bool)
    global_pause = daily.get('global_paused', pd.Series(False, index=daily.index)).astype(bool)
    rows = []
    for kind, mask in (('episode', episode), ('global', global_pause), ('any', episode | global_pause)):
        start = None
        for i, paused in enumerate(mask.to_numpy()):
            if paused and start is None:
                start = i
            if start is not None and (not paused or i == len(mask) - 1):
                end = i if paused else i - 1
                rows.append(dict(case=case, pause_kind=kind,
                    start_date=str(daily.index[start].date()), end_date=str(daily.index[end].date()),
                    paused_sessions=end-start+1,
                    calendar_span_days=(daily.index[end]-daily.index[start]).days+1,
                    ongoing_at_final_close=bool(end == len(mask)-1)))
                start = None
    return rows


def recovery_intervals(case, result):
    events, daily = result['events'], result['daily']
    if events.empty or 'event' not in events or 'unit_nav' not in daily:
        return []
    rows = []
    resumes = events.loc[events.event.eq('global_resume')]
    endings = events.loc[events.event.isin(['global_pause', 'global_review_lock', 'global_normal'])]
    for _, resume in resumes.iterrows():
        later = endings.loc[endings.Date.ge(resume.Date)]
        if len(later):
            end = later.iloc[0]
            end_date, end_reason = end.Date, end.event
        else:
            end_date, end_reason = daily.index[-1], 'end_of_development_interval'
        segment = daily.loc[(daily.index >= resume.Date) & (daily.index <= end_date)]
        anchor, peak = float(resume.unit_nav), float(resume.high_water_nav)
        low = min(anchor, float(segment.unit_nav.min()))
        last = float(segment.unit_nav.iloc[-1])
        rows.append(dict(case=case, resume_date=str(resume.Date.date()),
            end_date=str(pd.Timestamp(end_date).date()), end_reason=end_reason,
            sessions=len(segment), resume_unit_nav=anchor, preserved_high_water_nav=peak,
            recovery_floor=float(resume.recovery_floor), minimum_actual_unit_nav=low,
            minimum_return_since_resume=low/anchor-1, end_return_since_resume=last/anchor-1,
            end_cumulative_drawdown=last/peak-1,
            remaining_budget_high_water_fraction_at_resume=(anchor-.70*peak)/peak,
            minimum_remaining_budget_high_water_fraction=(low-.70*peak)/peak,
            ended_in_new_pause=end_reason in ('global_pause', 'global_review_lock')))
    return rows


def risk_metrics(case, result):
    daily, events, positions = (result[key] for key in ('daily', 'events', 'positions'))
    event = events.event if 'event' in events else pd.Series(dtype=str)
    global_pause = daily.get('global_paused', pd.Series(False, index=daily.index)).astype(bool)
    flat = positions.abs().le(1e-12).all(axis=1)
    intervals = pause_intervals(case, result)
    any_intervals = [r for r in intervals if r['pause_kind'] == 'any']
    global_intervals = [r for r in intervals if r['pause_kind'] == 'global']
    fund = result.get('fund_state')
    values = dict(episode_halts=int(event.eq('portfolio_halt').sum()),
        global_pauses=int(event.eq('global_pause').sum()),
        global_review_locks=int(event.eq('global_review_lock').sum()),
        global_resumes=int(event.eq('global_resume').sum()),
        global_reductions=int(event.eq('global_reduce').sum()),
        global_budget_breaches=int(event.eq('global_budget_breach').sum()),
        global_paused_days=int(global_pause.sum()),
        any_paused_days=int((daily.paused.astype(bool) | global_pause).sum()),
        cumulative_flat_days=int(flat.sum()), flat_days_excluding_final=int(flat.iloc[:-1].sum()),
        longest_pause_sessions=max((r['paused_sessions'] for r in any_intervals), default=0),
        longest_pause_calendar_days=max((r['calendar_span_days'] for r in any_intervals), default=0),
        longest_global_pause_sessions=max((r['paused_sessions'] for r in global_intervals), default=0),
        terminal_risk_mode=str(daily.global_mode.iloc[-1]) if 'global_mode' in daily else 'ORIGINAL_EPISODE_ONLY',
        final_cumulative_drawdown=float(daily.drawdown.iloc[-1]),
        final_preserved_high_water=float(daily.equity.cummax().clip(lower=1.).iloc[-1]),
        full_history_budget_exceeded=bool(daily.drawdown.min() < -.30),
        daily_count=len(daily), flat_fraction=float(flat.mean()))
    reductions = result['trades'].loc[result['trades'].reason.isin(
        ['daily_risk_reduce', 'global_risk_reduce', 'global_flat'])]
    values['all_nonplanned_risk_buy_orders'] = int(reductions.signed_units.gt(1e-12).sum())
    if values['all_nonplanned_risk_buy_orders']:
        raise AssertionError('Nonplanned risk change increased a position.')
    if fund is not None:
        values.update(persisted_fund_max_drawdown=float(fund['max_drawdown']),
                      persisted_fund_high_water=float(fund['high_water_nav']))
    return values


def full_history_check(result):
    check = v12.full_history_check(result)
    check['strategy_fund_high_water_never_reset'] = check.pop('account_high_water_never_reset')
    check['risk_scope_is_whole_broker_account'] = False
    daily = result['daily']
    if 'unit_nav' in daily:
        expected_peak = daily.unit_nav.cummax().clip(lower=1.)
        expected_dd = daily.unit_nav / expected_peak - 1
        np.testing.assert_allclose(daily.high_water_nav, expected_peak, rtol=1e-11, atol=1e-12)
        np.testing.assert_allclose(daily.cumulative_fund_drawdown, expected_dd, rtol=1e-11, atol=1e-12)
        np.testing.assert_allclose(daily.unit_nav, daily.equity, rtol=1e-11, atol=1e-12)
        if result.get('fund_state'):
            state = result['fund_state']
            np.testing.assert_allclose([state['equity'], state['unit_nav'], state['high_water_nav'], state['max_drawdown']],
                [daily.equity.iloc[-1], daily.unit_nav.iloc[-1], expected_peak.iloc[-1], expected_dd.min()],
                rtol=1e-10, atol=1e-11)
            if state.get('blocked'):
                raise AssertionError('Completed simulation has unreconciled fund facts.')
        check['unitized_fund_and_persisted_high_water_verified'] = True
    return check


def gates(table):
    protected = table.loc[table.configuration.eq('protected')].set_index(['variant', 'scenario'])
    if set(protected.index) != {(variant, scenario) for variant in ('original', 'global') for scenario in SCENARIOS}:
        raise ValueError('Exactly two protected variants across seven fixed scenarios are required.')
    old, new = protected.loc['original'], protected.loc['global']
    main, original = new.loc['cost10'], old.loc['cost10']
    improvement = float(main.max_drawdown - original.max_drawdown)
    cagr_change = float(main.cagr - original.cagr)
    stress = new.drop(index='cost10')
    dd_delta = stress.max_drawdown - old.drop(index='cost10').max_drawdown
    checks = dict(main_drawdown_improves_at_least_3pp=bool(improvement >= .03-1e-12),
        main_cagr_cost_no_more_than_2pp=bool(cagr_change >= -.02-1e-12),
        all_six_stress_drawdowns_within_30=bool(stress.max_drawdown.ge(-.30-1e-12).all()),
        no_stress_drawdown_worse_more_than_2pp=bool(dd_delta.ge(-.02-1e-12).all()))
    objectives = dict(net_cagr_at_least_30=bool(main.cagr >= .30),
        full_history_drawdown_within_30=bool(main.max_drawdown >= -.30))
    return dict(risk_value_gate_passed=all(checks.values()), risk_value_conditions=checks,
        protected_main_drawdown_improvement_pp=100*improvement,
        protected_main_cagr_change_pp=100*cagr_change,
        protected_numerical_objectives=objectives,
        protected_numerical_objectives_met=all(objectives.values()),
        preferred_drawdown_within_20=bool(main.max_drawdown >= -.20),
        aspiration_cagr_50=bool(main.cagr >= .50),
        simple_configuration_diagnostic_only=True, independent_validation_passed=False,
        prices_2026_accessed=False, new_fits=0, model_promoted_to_lean_or_paper=False,
        decision='DEVELOPMENT_ONLY_REVIEW_REQUIRED' if all(objectives.values()) else 'REJECT_NO_2026',
        no_future_drawdown_guarantee=True)


def paired_deltas(table):
    metrics = ('cagr', 'total_return', 'max_drawdown', 'annualized_vol', 'average_gross',
        'turnover_two_way_per_year', 'fee_per_initial_nav', 'stop_slippage_per_initial_nav',
        'explicit_total_cost_per_initial_nav', 'stop_exits', 'episode_halts', 'global_pauses',
        'global_review_locks', 'global_resumes', 'global_paused_days', 'any_paused_days',
        'cumulative_flat_days', 'flat_days_excluding_final', 'longest_pause_sessions')
    rows = []
    for configuration in CONFIGURATIONS:
        for scenario in SCENARIOS:
            pair = table.loc[table.configuration.eq(configuration) & table.scenario.eq(scenario)].set_index('variant')
            if set(pair.index) != {'original', 'global'}:
                raise ValueError('A pair must contain one original and one global-control result.')
            row = dict(configuration=configuration, scenario=scenario)
            for metric in metrics:
                row['original_'+metric] = float(pair.loc['original', metric])
                row['global_'+metric] = float(pair.loc['global', metric])
                row['delta_'+metric] = float(pair.loc['global', metric] - pair.loc['original', metric])
            rows.append(row)
    return pd.DataFrame(rows)


def check_no_trigger(original, new):
    events = new['events']
    triggered = bool(len(events) and events.event.str.startswith('global_').any())
    if not triggered:
        for key in TABLE_KEYS:
            # CSV represents empty optional text fields as NA. This is a
            # serialization normalization, never a tolerance on numeric facts.
            left, right = new[key][original[key].columns].copy(), original[key].copy()
            for frame in (left, right):
                for column in frame.select_dtypes(include=['object', 'string']).columns:
                    frame[column] = frame[column].mask(frame[column].eq(''), np.nan)
            pd.testing.assert_frame_equal(left, right,
                                          check_exact=True, check_dtype=False)
    return dict(global_triggered=triggered, no_trigger_exact_original_trajectory_verified=not triggered)


def save_case(folder, result, identity_sha):
    folder.mkdir(parents=True, exist_ok=True)
    for key in TABLE_KEYS:
        result[key].to_csv(folder / (key+'.csv'), index=key in ('daily', 'positions'), date_format='%Y-%m-%d')
    save(folder/'metrics.json', result['metrics'])
    save(folder/'state.json', result['fund_state'])
    files = [previous.file_record(p) for p in sorted(folder.iterdir()) if p.is_file() and p.name != 'complete.json']
    immutable_save(folder/'complete.json', dict(evaluation_identity_sha256=identity_sha, files=files))


def read_case(folder, identity_sha):
    marker = json.loads((folder/'complete.json').read_text(encoding='utf-8'))
    if marker['evaluation_identity_sha256'] != identity_sha:
        raise ValueError('Completed case has a different evaluation identity.')
    for row in marker['files']:
        previous.check_record(row)
    result = {key: previous.frame_read(folder/(key+'.csv'), key) for key in TABLE_KEYS}
    result['metrics'] = json.loads((folder/'metrics.json').read_text(encoding='utf-8'))
    result['fund_state'] = json.loads((folder/'state.json').read_text(encoding='utf-8'))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-only', action='store_true')
    parser.add_argument('--deadline-utc', default=DEADLINE)
    args = parser.parse_args()
    deadline = datetime.fromisoformat(args.deadline_utc)
    if deadline.tzinfo is None:
        raise ValueError('Deadline must include timezone.')
    deadline = min(deadline, datetime.fromisoformat(DEADLINE))
    plan_path, proof_path = OUT/'plan.json', OUT/'RECORD_ONLY_CHECK.json'
    engineering_path = OUT/'engineering/final_verification/CONTINUITY_REPORT.json'
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    proof = json.loads(proof_path.read_text(encoding='utf-8'))
    engineering = json.loads(engineering_path.read_text(encoding='utf-8'))
    if (plan['design_sha256'] != sha(OUT/'PLAN.md') or
            plan['record_only_check_sha256'] != sha(proof_path) or
            plan['engineering_check_sha256'] != sha(engineering_path)):
        raise ValueError('Plan was not frozen against the completed foundation evidence.')
    registered = datetime.fromisoformat(plan['registered_at_utc'])
    if registered < datetime.fromisoformat(proof['completed_at_utc']):
        raise ValueError('Plan must be frozen after record-only validation.')
    if proof['record_only_historical_replays'] != 2 or proof['new_fits'] != 0 or engineering.get('equality') is not True:
        raise ValueError('Required record-only/actual subprocess continuity evidence is incomplete.')
    for name, value in proof['source_sha256'].items():
        if sha(ROOT/name) != value:
            raise ValueError('Recording evidence source has changed: '+name)
    for row in proof['files']:
        previous.check_record(row)
    old_manifest = previous.verify_old_manifest()
    bars, spy_bars, spy, scores, observations, final, inputs = load_inputs()
    policy = asdict(replace(Policy(), soft_enabled=False))
    risk_policy = asdict(GlobalPolicy())
    old_plan = json.loads((previous.OLD/'plan.json').read_text(encoding='utf-8'))
    if old_plan['input_identity'] != inputs or old_plan['candidate'] != policy:
        raise ValueError('Reused old control input/policy identity mismatch.')
    if (plan['input_identity'] != inputs or plan['policy'] != policy or
            plan['risk_policy'] != risk_policy or plan['scenarios'] != list(SCENARIOS)):
        raise ValueError('Frozen v13 single-factor specification mismatch.')
    for key, expected in (('cagr_floor', .30), ('cagr_aspiration', .50), ('drawdown_ceiling', .30),
                          ('preferred_drawdown', .20), ('new_fits', 0), ('new_runs', 14)):
        if plan.get(key, expected) != expected:
            raise ValueError('Preregistered budget or objective differs: '+key)
    if str(final.date()) != '2025-12-29' or scores.index.max() >= pd.Timestamp('2026-01-01'):
        raise ValueError('Forbidden data boundary.')
    sources = ('58_evaluate_continuous_risk.py', 'h60_global_research.py', 'h60_global_control.py',
        'strategy_fund_journal.py', '51_evaluate_signal_objectives.py', '54_evaluate_training_cutoff.py',
        '42_evaluate_h60_risk_fixes.py', 'profit_priority_strategy.py', 'research_backtest.py',
        'h60_research_inputs.py', 'research_features.py')
    fixed = dict(plan_sha256=sha(plan_path), source_sha256={p:sha(ROOT/p) for p in sources},
        input_identity=inputs, old_artifacts=old_manifest, record_only=previous.file_record(proof_path),
        engineering=previous.file_record(engineering_path), configurations=list(CONFIGURATIONS),
        scenarios=list(SCENARIOS), new_runs=14, reused_control_runs=21, new_fits=0,
        initial_equity=1., cash_interest=0., valuation='adjusted close historical research proxy',
        prices_2026_accessed=False)
    identity_path = OUT/'EVALUATION_IDENTITY.json'
    if args.check_only and not identity_path.exists():
        print('Foundation, frozen plan and original inputs verified; no writes or replays.')
        return
    immutable_save(identity_path, fixed)
    identity_sha = sha(identity_path)
    complete_path = OUT/'evaluation_complete.json'
    if complete_path.exists():
        complete = json.loads(complete_path.read_text(encoding='utf-8'))
        if complete['evaluation_identity_sha256'] != identity_sha:
            raise ValueError('Evaluation completion identity mismatch.')
        for row in complete['files']:
            previous.check_record(row)
        print('Completed fixed v13 results verified; no writes or replays.')
        return
    if args.check_only:
        print('Frozen evaluation identity verified; no writes or replays.')
        return
    if not (OUT/'EVALUATION_RUN.json').exists():
        save(OUT/'EVALUATION_RUN.json', dict(started_at_utc=now(), generation_git_head=subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(), deadline_utc=deadline.isoformat()))
    results, metadata, checks = {}, [], {}
    for configuration in (*CONFIGURATIONS, 'simple_spy'):
        signal = 'baseline_rank' if configuration == 'protected' else configuration
        for scenario in SCENARIOS:
            case = 'original_'+configuration+'_'+scenario
            old_case = previous.old_case(signal, scenario)
            result = previous.read_old(old_case)
            result['metrics'].update(risk_metrics(case, result))
            checks[case] = {**auditor.audit(result, spy_bars if configuration == 'simple_spy' else bars),
                            **full_history_check(result)}
            results[case] = result
            metadata.append(dict(case=case, variant='original', configuration=configuration,
                scenario=scenario, origin='reused_v8', original_case=old_case, **result['metrics']))
    for configuration in CONFIGURATIONS:
        for scenario in SCENARIOS:
            case = 'global_'+configuration+'_'+scenario
            folder = OUT/'backtests'/case
            if (folder/'complete.json').exists():
                result = read_case(folder, identity_sha)
            else:
                if datetime.now(timezone.utc) >= deadline:
                    save(OUT/'EVALUATION_PROGRESS.json', dict(status='deadline', completed_cases=list(results), updated_at_utc=now()))
                    raise TimeoutError('Budget ended; complete results and resumable fund state retained.')
                obs, kwargs = previous.scenario_options(scenario, bars['Open'].index, observations, scores.index, final)
                if configuration == 'simple_h60':
                    kwargs.update(mode='simple_h60', stops=False)
                folder.mkdir(parents=True, exist_ok=True)
                journal_path = folder/'fund.sqlite'
                scope_id = 'v13-managed-capital-'+case
                start = time.perf_counter()
                result = engine.simulate(scores, bars, spy, features.SECTOR_PROXY, obs, final, **kwargs,
                    global_control=True, journal_path=journal_path, scope_id=scope_id,
                    create_journal=not journal_path.exists() and not Path(str(journal_path)+'.scope.json').exists(),
                    model_versions={m['year']:m['sha256'] for m in inputs['models']})
                auditor.enrich(result)
                result['metrics'].update(risk_metrics(case, result))
                result['metrics']['runtime_seconds'] = time.perf_counter()-start
                auditor.audit(result, bars)
                full_history_check(result)
                journal = FundJournal(journal_path, dict(scope_id=scope_id, currency='USD',
                    owner='isolated_h60_research_capital', universe=list(scores.columns)))
                chain = journal.verify()
                journal.close()
                save(folder/'JOURNAL_CHECK.json', chain)
                save_case(folder, result, identity_sha)
            original = results['original_'+configuration+'_'+scenario]
            checks[case] = {**auditor.audit(result, bars), **full_history_check(result), **check_no_trigger(original, result)}
            results[case] = result
            metadata.append(dict(case=case, variant='global', configuration=configuration, scenario=scenario,
                origin='new_v13', original_case='', **result['metrics']))
            pd.DataFrame(metadata).to_csv(OUT/'all_results.csv', index=False)
            save(OUT/'EVALUATION_PROGRESS.json', dict(status='running', completed_cases=list(results), updated_at_utc=now()))
            print(f'{case}: CAGR={result["metrics"]["cagr"]:.3%}; DD={result["metrics"]["max_drawdown"]:.3%}; '+
                  f'global pauses={result["metrics"]["global_pauses"]}; flat={result["metrics"]["cumulative_flat_days"]}', flush=True)
    table = pd.DataFrame(metadata)
    table.to_csv(OUT/'all_results.csv', index=False)
    paired_deltas(table).to_csv(OUT/'pair_deltas.csv', index=False)
    annual, pauses, recoveries, reasons, stocks = [], [], [], [], []
    for case, result in results.items():
        annual.extend(v12.annual_rows(case, result))
        pauses.extend(pause_intervals(case, result))
        recoveries.extend(recovery_intervals(case, result))
        reason, contribution = previous.trade_diagnostics(case, result)
        reasons.extend(reason)
        stocks.extend(contribution)
    pd.DataFrame(annual).to_csv(OUT/'annual_results.csv', index=False)
    pd.DataFrame(pauses).to_csv(OUT/'pause_intervals.csv', index=False)
    pd.DataFrame(recoveries, columns=['case','resume_date','end_date','end_reason','sessions','resume_unit_nav',
        'preserved_high_water_nav','recovery_floor','minimum_actual_unit_nav','minimum_return_since_resume',
        'end_return_since_resume','end_cumulative_drawdown','remaining_budget_high_water_fraction_at_resume',
        'minimum_remaining_budget_high_water_fraction','ended_in_new_pause']).to_csv(OUT/'recovery_intervals.csv', index=False)
    pd.DataFrame(reasons).to_csv(OUT/'trade_reason_summary.csv', index=False)
    pd.DataFrame(stocks).to_csv(OUT/'stock_contributions.csv', index=False)
    pd.DataFrame({case:r['daily'].equity for case,r in results.items()}).to_csv(OUT/'equity.csv')
    gate = gates(table)
    save(OUT/'GATES.json', gate)
    save(OUT/'RUN_CHECKS.json', checks)
    save(OUT/'EVALUATION_PROGRESS.json', dict(status='complete', completed_cases=list(results), updated_at_utc=now()))
    names = ('all_results.csv','pair_deltas.csv','annual_results.csv','pause_intervals.csv','recovery_intervals.csv',
             'trade_reason_summary.csv','stock_contributions.csv','equity.csv','GATES.json','RUN_CHECKS.json')
    records = [previous.file_record(OUT/name) for name in names]
    records += [previous.file_record(p) for p in sorted((OUT/'backtests').rglob('*')) if p.is_file()]
    pd.DataFrame(records).to_csv(OUT/'EVALUATION_ARTIFACTS.csv', index=False)
    save(complete_path, dict(completed_at_utc=now(), evaluation_identity_sha256=identity_sha,
        new_strategy_runs=14, reused_control_runs=21, new_fits=0, original_models_reused=10,
        all_ledgers_checked=True, prices_2026_accessed=False, orders_sent=0, gates=gate, files=records))
    print(json.dumps(gate, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
