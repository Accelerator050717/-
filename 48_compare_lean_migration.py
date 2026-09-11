"""Compare actual LEAN engine ledgers with the frozen v8 research proxy ledger."""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from h60_research_inputs import sha, save
from panel_config import ROOT

OUT = ROOT / 'data/experiments/lean_migration_v10'
SCALE = 10000.
USD_TOL = .01
QTY_TOL = .000001
PRICE_TOL = .00000001
WEIGHT_TOL = .000000001


def read_csv(path, dated=False):
    try:
        return pd.read_csv(path, index_col='Date' if dated else None,
                           parse_dates=['Date'], float_precision='round_trip')
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def compare_run(run_dir):
    frozen = json.loads((OUT / 'REFERENCE_IDENTITY.json').read_text(encoding='utf-8'))
    reference = Path(frozen['directory'])
    for name, digest in frozen['files'].items():
        assert sha(reference / name) == digest, f'Frozen reference changed: {name}'
    prefix = 'stop_on_soft_off_cost10'
    baseline = {key: read_csv(reference / f'{prefix}_{key}.csv', key in ('daily','positions'))
                for key in ('daily','positions','trades','targets','events')}
    actual = {key: read_csv(run_dir / f'{key}.csv', key in ('daily','positions'))
              for key in baseline}
    completion = json.loads((run_dir / 'completion.json').read_text(encoding='utf-8'))
    # An output directory from unit tests alone is not an engine run.
    assert completion.get('engine') == 'LEAN', 'Actual LEAN completion marker is required.'
    assert completion.get('live_mode') is False, 'Live output cannot be used in this research comparison.'
    assert completion.get('status') == 'completed', 'LEAN did not complete.'
    assert not completion.get('engine_runtime_error'), 'LEAN reported an algorithm error.'
    run_record_path = OUT/'runtime'/f'{run_dir.name}.run.json'
    run_record=json.loads(run_record_path.read_text(encoding='utf-8'))
    assert run_record['validated_exit_code']==0 and run_record['process_exit_code']==0, 'Native process failed even if algorithm output exists.'
    assert run_record['algorithm_completion_check'] is True, 'Runner did not confirm algorithm completion.'
    assert sha(Path(run_record['log_path']))==run_record['log_sha256'], 'Engine log identity changed.'
    assert sha(run_dir/'executed_config.json')==run_record['config_sha256'], 'Executed config identity changed.'
    for source_record in run_record['algorithm_snapshots'].values():
        assert sha(Path(source_record['snapshot']))==source_record['sha256'], 'Executed algorithm snapshot changed.'
    runtime_patch = run_dir / 'lean_runtime.patch'
    repository_patch = ROOT / 'tools/lean_runtime/patches/native_shutdown_gil.patch'
    assert sha(runtime_patch)==run_record['source_patch_sha256'], 'Executed runtime patch identity changed.'
    assert sha(repository_patch)==run_record['source_patch_sha256'], 'Repository patch differs from the executed runtime patch.'
    assert completion.get('package_sha256') == sha(OUT/'input/package.json'), 'Engine used a different input package.'
    package=json.loads((OUT/'input/package.json').read_text(encoding='utf-8'))
    exported=json.loads((OUT/'input/EXPORT_IDENTITY.json').read_text(encoding='utf-8'))
    for name,digest in exported['exported_sha256'].items():
        assert sha(OUT/'input'/name)==digest, f'Frozen LEAN input changed: {name}'
    for name,digest in package['shared_source_sha256'].items():
        assert sha(OUT/'input'/package['shared_directory']/name)==digest, f'Executed shared strategy changed: {name}'
        assert sha(ROOT/name)==digest, f'Current shared strategy differs from the frozen engine input: {name}'
    checks, differences = [], []

    def check(name, passed, **details):
        checks.append(dict(check=name, passed=bool(passed), **details))

    def numeric(name, expected, observed, tolerance):
        a, b = np.asarray(expected, float), np.asarray(observed, float)
        if a.shape != b.shape:
            check(name, False, expected_shape=list(a.shape), actual_shape=list(b.shape))
            return
        error = np.abs(a-b)
        valid = np.isfinite(a).all() and np.isfinite(b).all()
        maximum = float(error.max()) if error.size and valid else (0. if not error.size else None)
        passed = valid and (not error.size or maximum <= tolerance)
        check(name, passed, max_abs_error=maximum, tolerance=tolerance)
        if not passed:
            for index in np.argwhere((error > tolerance) | ~np.isfinite(error))[:20]:
                idx = tuple(index)
                differences.append(dict(check=name,index=list(map(int,index)),
                    expected=float(a[idx]) if np.isfinite(a[idx]) else None,
                    actual=float(b[idx]) if np.isfinite(b[idx]) else None))

    daily, positions, trades = actual['daily'], actual['positions'], actual['trades']
    names = list(baseline['positions'].columns)
    for key in ('daily','positions'):
        check(f'{key}.calendar', actual[key].index.equals(baseline[key].index))
    check('positions.symbol_order', list(positions.columns) == names)
    dates_equal = daily.index.equals(baseline['daily'].index) and positions.index.equals(daily.index)
    if not dates_equal or list(positions.columns) != names:
        return dict(status='FAIL', checks=checks, differences=differences)
    for field in ('cash','equity','open_equity','fees','cumulative_fees','invested','episode_peak'):
        numeric(f'daily.{field}', baseline['daily'][field] * SCALE, daily[field], USD_TOL)
    numeric('daily.gross', baseline['daily'].gross, daily.gross, WEIGHT_TOL)
    for field in ('paused','soft'):
        check(f'daily.{field}', baseline['daily'][field].equals(daily[field]))
    numeric('positions.units', baseline['positions'] * SCALE, positions, QTY_TOL)
    check('trades.count', len(baseline['trades']) == len(trades), expected=len(baseline['trades']), actual=len(trades))
    for key in ('targets','events'):
        check(f'{key}.count', len(baseline[key]) == len(actual[key]), expected=len(baseline[key]), actual=len(actual[key]))
    # Simultaneous orders in one batch may use a different tied-stock order.
    def keyed(frame):
        frame = frame.copy()
        frame['side'] = np.sign(frame.signed_units).astype(int)
        frame['risk_action'] = frame.risk_action.fillna('')
        keys = ['Date','reason','risk_action','symbol','side']
        check('trades.unique_batch_keys', not frame.duplicated(keys).any())
        return frame.set_index(keys).sort_index()
    gold_trades, engine_trades = keyed(baseline['trades']), keyed(trades)
    check('trades.batch_identity', gold_trades.index.equals(engine_trades.index))
    if gold_trades.index.equals(engine_trades.index):
        for field in ('signed_notional','fee','cash_change'):
            numeric(f'trades.{field}', gold_trades[field] * SCALE, engine_trades[field], USD_TOL)
        numeric('trades.signed_units', gold_trades.signed_units * SCALE, engine_trades.signed_units, QTY_TOL)
        numeric('trades.proxy_fill', gold_trades.proxy_fill, engine_trades.proxy_fill, PRICE_TOL)
        check('trades.observation_date', gold_trades.observation_date.fillna('').equals(engine_trades.observation_date.fillna('')))
    if len(baseline['targets']) == len(actual['targets']):
        for field in ('Date','observation_date','reason','reduce_only'):
            check(f'targets.{field}', baseline['targets'][field].fillna('').equals(actual['targets'][field].fillna('')))
        numeric('targets.weights', baseline['targets'][names], actual['targets'][names], WEIGHT_TOL)
    if len(baseline['events']) and len(baseline['events']) == len(actual['events']):
        for field in ('Date','event'):
            check(f'events.{field}', baseline['events'][field].equals(actual['events'][field]))
        numeric('events.equity', baseline['events'].equity*SCALE, actual['events'].equity, USD_TOL)

    # Rebuild the engine cash and holdings independently from its actual fills.
    cash_change = trades.groupby('Date').cash_change.sum().reindex(daily.index, fill_value=0)
    numeric('engine.cash_ledger', SCALE + cash_change.cumsum(), daily.cash, USD_TOL)
    unit_change = trades.pivot_table(index='Date', columns='symbol', values='signed_units', aggfunc='sum', fill_value=0)
    unit_change = unit_change.reindex(index=daily.index, columns=names, fill_value=0)
    numeric('engine.position_ledger', unit_change.cumsum(), positions, QTY_TOL)
    numeric('engine.trade_notional', trades.signed_units * trades.proxy_fill, trades.signed_notional, USD_TOL)
    numeric('engine.trade_cash', -trades.signed_notional-trades.fee, trades.cash_change, USD_TOL)
    numeric('engine.trade_fee', trades.signed_notional.abs() * .001, trades.fee, USD_TOL)
    fees = trades.groupby('Date').fee.sum().reindex(daily.index, fill_value=0)
    numeric('engine.daily_fees', fees, daily.fees, USD_TOL)
    close = {}
    for symbol in names:
        frame = pd.read_csv(OUT / 'input/bars' / f'{symbol}.csv', float_precision='round_trip')
        frame = frame.loc[frame.phase.eq('CLOSE')]
        close[symbol] = pd.Series(frame.value.to_numpy(), index=pd.to_datetime(frame.timestamp).dt.normalize())
    prices = pd.DataFrame(close).reindex(daily.index)
    numeric('engine.close_equity', daily.cash + (positions * prices).sum(axis=1), daily.equity, USD_TOL)
    check('engine.no_borrowing', daily.cash.ge(-USD_TOL).all())
    check('engine.no_shorting', positions.ge(-QTY_TOL).all().all())
    check('engine.final_flat', positions.iloc[-1].abs().le(QTY_TOL).all())
    reductions = trades.loc[trades.reason.eq('daily_risk_reduce')]
    check('engine.risk_reduce_no_buys', reductions.signed_units.le(0).all(), buy_orders=int(reductions.signed_units.gt(0).sum()))
    check('engine.no_2026', daily.index.max() < pd.Timestamp('2026-01-01'))

    # Independently connect each exported trade to an actual LEAN fill callback.
    # v10 intentionally uses immediate full fills; partial fills are not this proxy's contract.
    order_events = pd.read_csv(run_dir/'order_events.csv', float_precision='round_trip')
    filled = order_events.loc[order_events.status.eq('FILLED')].set_index(['order_id','event_id'])
    recorded = trades.set_index(['lean_order_id','lean_event_id'])
    recorded.index.names = filled.index.names
    unique = filled.index.is_unique and recorded.index.is_unique
    check('engine.fill_keys_unique', unique)
    check('engine.order_event_keys_unique', not order_events.duplicated(['order_id','event_id']).any())
    check('engine.only_expected_order_statuses', order_events.status.isin(['SUBMITTED','FILLED']).all())
    check('engine.trade_order_counts', len(recorded)==len(filled)==completion['lean_fill_count']==completion['lean_order_count'],
          trade_rows=len(recorded), filled_event_rows=len(filled), recorded_orders=completion['lean_order_count'])
    keys_equal = unique and recorded.index.sort_values().equals(filled.index.sort_values())
    check('engine.trade_fill_identity', keys_equal)
    if keys_equal:
        linked = recorded.join(filled, rsuffix='_event').sort_index()
        numeric('engine.fill_callback_units', linked.signed_units, linked.fill_quantity, QTY_TOL)
        numeric('engine.fill_callback_price', linked.proxy_fill, linked.fill_price, PRICE_TOL)
        numeric('engine.fill_callback_fee', linked.fee, linked.fee_event, USD_TOL)
        actual_time = pd.to_datetime(linked.utc_time, utc=True).dt.tz_convert('America/New_York')
        check('engine.fill_session_date', actual_time.dt.strftime('%Y-%m-%d').eq(linked.Date.dt.strftime('%Y-%m-%d')).all())
        expected_clock = linked.phase.map({'OPEN':'09:30:00','RANGE':'12:00:00'})
        check('engine.fill_phase_clock_including_dst', actual_time.dt.strftime('%H:%M:%S').eq(expected_clock).all())
        check('engine.fill_callbacks_chronological', pd.to_datetime(filled.utc_time, utc=True).is_monotonic_increasing)

    # Compare stage order before any sorting by symbol hides a cross-stage move.
    stage_order = {'stop_gap':0, 'portfolio_flat':1, 'final_liquidation':1,
                   'scheduled':2, 'daily_risk_reduce':2, 'stop_intraday':3}
    check('engine.trade_reasons_known', trades.reason.isin(stage_order).all())
    expected_phase = np.where(trades.reason.eq('stop_intraday'), 'RANGE', 'OPEN')
    check('engine.trade_reason_phase', trades.phase.eq(expected_phase).all())
    check('engine.trade_dates_chronological', trades.Date.is_monotonic_increasing)
    staged = trades.assign(stage=trades.reason.map(stage_order))
    check('engine.cross_stage_order', staged.groupby('Date').stage.apply(lambda x:x.is_monotonic_increasing).all())
    cash_after_fill = SCALE + trades.cash_change.cumsum()
    check('engine.no_intraday_borrowing', cash_after_fill.ge(-USD_TOL).all(),
          minimum_post_fill_cash=float(cash_after_fill.min()))

    audit = pd.read_csv(run_dir/'observation_audit.csv')
    executed = pd.to_datetime(audit.execution_date)
    observed = pd.to_datetime(audit.observation_date)
    window_end = pd.to_datetime(audit.risk_window_end)
    expected_observations = pd.DatetimeIndex(package['observations'])
    calendar = pd.DatetimeIndex(package['calendar'])
    expected_executions = calendar[calendar.get_indexer(expected_observations)+1]
    check('engine.observation_audit_count', len(audit)==completion['scheduled_decisions']==len(expected_observations))
    check('engine.observation_audit_unique', not audit.execution_date.duplicated().any())
    check('engine.observation_audit_schedule', pd.DatetimeIndex(executed).equals(expected_executions)
          and pd.DatetimeIndex(observed).equals(expected_observations))
    check('engine.observation_strictly_before_execution', observed.lt(executed).all())
    check('engine.risk_window_ends_at_observation', window_end.equals(observed))

    actual_returns = daily.equity / daily.equity.shift(1,fill_value=SCALE) - 1
    years = (daily.index[-1]-daily.index[0]).days/365.25
    metrics = dict(first_date=str(daily.index[0].date()), final_date=str(daily.index[-1].date()),
        sessions=len(daily), trades=len(trades), final_equity_usd=float(daily.equity.iloc[-1]),
        total_return=float(daily.equity.iloc[-1]/SCALE-1),
        cagr=float((daily.equity.iloc[-1]/SCALE)**(1/years)-1),
        max_drawdown=float((daily.equity/daily.equity.cummax().clip(lower=SCALE)-1).min()),
        annualized_vol=float(actual_returns.std(ddof=1)*np.sqrt(252)),
        average_gross=float(daily.gross.mean()), total_fees_usd=float(trades.fee.sum()),
        stop_exits=int(trades.reason.str.startswith('stop_').sum()),
        gap_stops=int(trades.reason.eq('stop_gap').sum()))
    evidence_names=('daily.csv','positions.csv','trades.csv','targets.csv','events.csv',
                    'order_events.csv','observation_audit.csv','completion.json','executed_config.json',
                    'lean_runtime.patch')
    identity = {name:sha(run_dir/name) for name in evidence_names}
    return dict(status='PASS' if all(r['passed'] for r in checks) else 'FAIL', checks=checks,
                differences=differences, engine_metrics=metrics, engine_output_sha256=identity,
                engine_run_directory=str(run_dir), native_run_record_sha256=sha(run_record_path),
                comparator_sha256=sha(Path(__file__)),
                runtime_patch_sha256=sha(repository_patch),
                new_fits=0, prices_2026_accessed=False,
                profitability_decision='REJECT_NO_2026',
                evidence='Actual LEAN order engine with explicit adjusted daily-bar research fill proxy; not broker integration')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',type=Path,required=True)
    args=parser.parse_args()
    result=compare_run(args.run_dir.resolve())
    save(args.run_dir / 'PARITY.json', result)
    pd.DataFrame(result['checks']).to_csv(args.run_dir/'parity_checks.csv',index=False)
    save(OUT/'LATEST_COMPARISON.json',dict(run_directory=str(args.run_dir.resolve()),
                                         parity_sha256=sha(args.run_dir/'PARITY.json'),status=result['status']))
    print(json.dumps({k:v for k,v in result.items() if k in ('status','engine_metrics')},indent=2))
    raise SystemExit(0 if result['status']=='PASS' else 1)


if __name__=='__main__':
    main()
