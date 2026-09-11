"""Summarize already completed LEAN migration runs; never rerun an engine or fit."""
import csv
import json

import numpy as np
import pandas as pd

from h60_research_inputs import save, sha
from panel_config import ROOT

OUT=ROOT/'data/experiments/lean_migration_v10'


def synthetic_check():
    run=OUT/'engine_runs/synthetic_risk_01'
    fixture=OUT/'synthetic_input'
    expected=json.loads((fixture/'EXPECTED_SYNTHETIC.json').read_text(encoding='utf-8'))
    completion=json.loads((run/'completion.json').read_text(encoding='utf-8'))
    native=json.loads((OUT/'runtime/synthetic_risk_01.run.json').read_text(encoding='utf-8'))
    assert native['validated_exit_code']==native['process_exit_code']==0
    assert completion['status']=='completed' and completion['engine_runtime_error'] is None
    assert completion['engine']=='LEAN' and completion['live_mode'] is False
    assert completion['package_sha256']==sha(fixture/'package.json')
    frozen=json.loads((fixture/'EXPORT_IDENTITY.json').read_text(encoding='utf-8'))
    for name,digest in frozen['exported_sha256'].items():
        assert sha(fixture/name)==digest
    events=pd.read_csv(run/'events.csv')
    assert events[['Date','event']].to_dict('records')==[
        {'Date':r['Date'],'event':r['event']} for r in expected['events']]
    np.testing.assert_allclose(events.equity,[r['equity'] for r in expected['events']],rtol=0,atol=.01)
    targets=pd.read_csv(run/'targets.csv')
    names=list(completion['final_engine_quantities'])
    scheduled=targets.loc[targets.reason.eq('scheduled')].copy()
    scheduled['gross']=scheduled[names].sum(axis=1)
    resumed=scheduled.loc[scheduled.Date.ge(expected['expected_resume_date'])]
    np.testing.assert_allclose(resumed.gross.iloc[0],expected['expected_recovery_gross'],rtol=0,atol=1e-9)
    np.testing.assert_allclose(resumed.gross.iloc[-1],expected['expected_restored_gross'],rtol=0,atol=1e-9)
    np.testing.assert_allclose(completion['final_engine_cash'],expected['expected_final_cash'],rtol=0,atol=.01)
    assert completion['final_engine_quantities']==expected['expected_final_quantities']
    trades=pd.read_csv(run/'trades.csv')
    np.testing.assert_allclose(trades.fee.sum(),expected['expected_fees'],rtol=0,atol=.01)
    save(run/'SYNTHETIC_CHECK.json',dict(status='PASS',fictional_market_data=True,
        actual_lean_engine=True, native_exit_code=native['process_exit_code'],
        sessions=completion['sessions'],fills=completion['lean_fill_count'],events=expected['events'],
        recovery_gross=float(resumed.gross.iloc[0]),restored_gross=float(resumed.gross.iloc[-1]),
        final_cash=completion['final_engine_cash'],cash_error=completion['final_engine_cash']-expected['expected_final_cash'],
        final_flat=True,package_sha256=completion['package_sha256'],
        actual_data_sha256={p.name:sha(p) for p in run.glob('*.csv')},
        native_run_sha256=sha(OUT/'runtime/synthetic_risk_01.run.json'),
        interpretation='Invented 50% opening gap exceeds the20% halt threshold before action; not a loss guarantee or market performance'))


def main():
    synthetic_check()
    full=OUT/'engine_runs/h60_full_01'
    parity=json.loads((full/'PARITY.json').read_text(encoding='utf-8'))
    assert parity['status']=='PASS' and all(c['passed'] for c in parity['checks'])
    for name,digest in parity['engine_output_sha256'].items():
        assert sha(full/name)==digest
    inputs=json.loads((OUT/'input/EXPORT_IDENTITY.json').read_text(encoding='utf-8'))
    for name,digest in inputs['stable_identity']['source_hashes'].items():
        assert sha(ROOT/name)==digest, f'Original strategy/input reader changed: {name}'
    m=parity['engine_metrics']
    daily=pd.read_csv(full/'daily.csv',index_col='Date',parse_dates=['Date'])
    prior=daily.equity.shift(1,fill_value=10000.)
    yearly=[]
    for year,part in daily.groupby(daily.index.year):
        start=float(prior.loc[part.index[0]])
        yearly.append(dict(year=int(year),net_return=float(part.equity.iloc[-1]/start-1),
                           start_equity_usd=start,end_equity_usd=float(part.equity.iloc[-1]),
                           fees_usd=float(part.fees.sum())))
    pd.DataFrame(yearly).to_csv(full/'yearly_close_equity.csv',index=False)
    trades=pd.read_csv(full/'trades.csv')
    trades.groupby('reason').agg(orders=('symbol','size'),fees_usd=('fee','sum'),
                                net_notional_usd=('signed_notional','sum')).to_csv(full/'trade_reasons.csv')
    numeric={c['check']:c['max_abs_error'] for c in parity['checks'] if 'max_abs_error' in c}
    native=json.loads((OUT/'runtime/h60_full_01.run.json').read_text(encoding='utf-8'))
    source_names=['47_prepare_lean_migration.py','48_compare_lean_migration.py','49_summarize_lean_migration.py',
        'lean_migration/main.py','lean_migration/decision.py','tests/test_lean_migration_contract.py',
        'tools/lean_runtime/run_lean.py','tools/lean_runtime/make_config.py']
    save(OUT/'DELIVERY.json',dict(status='PASS_FIXED_RESEARCH_PROXY_MIGRATION',
        full_run='engine_runs/h60_full_01',synthetic_run='engine_runs/synthetic_risk_01',
        full_native_exit_code=native['process_exit_code'],full_parity_checks=len(parity['checks']),
        metrics=m,max_numeric_errors=numeric,source_sha256={n:sha(ROOT/n) for n in source_names},
        original_strategy_unchanged=True,new_fits=0,reused_annual_model_prediction_sets=10,
        independent_2026_validation_used=False,ibkr_paper_orders=0,real_orders=0,
        profitability_decision='REJECT_NO_2026',
        known_optional_report_error='Full run caught in-run PortfolioMarginUsageAnalysis collection-modified exception; canonical exported daily ledger is intact and checked.',
        native_engine_commit=native['source_commit'],native_patch_sha256=native['source_patch_sha256']))
    docs=['README.md','REVIEW_INDEX.md','lean_migration/README.md','tools/lean_runtime/README.md']
    paths={ROOT/n for n in source_names+docs}
    paths.update((ROOT/'tools/lean_runtime/patches').glob('*'))
    paths.update(p for p in OUT.rglob('*') if p.is_file() and '__pycache__' not in p.parts
                 and p.name!='ARTIFACTS.csv')
    with (OUT/'ARTIFACTS.csv').open('w',encoding='utf-8',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=['relative_path','size_bytes','sha256'])
        writer.writeheader()
        for path in sorted(paths):
            writer.writerow(dict(relative_path=path.relative_to(ROOT).as_posix(),
                                 size_bytes=path.stat().st_size,sha256=sha(path)))
    print(json.dumps(dict(status='PASS_FIXED_RESEARCH_PROXY_MIGRATION',
                         full_checks=len(parity['checks']),equity_error_usd=numeric['daily.equity'],
                         quantity_error=numeric['positions.units'],native_exit_code=0,
                         synthetic_engine_passed=True,new_fits=0),indent=2))


if __name__=='__main__':
    main()
