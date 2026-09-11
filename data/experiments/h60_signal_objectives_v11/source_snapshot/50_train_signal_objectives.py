"""v11: three fixed H60 target hypotheses; existing inputs only, never broker/data APIs."""
import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys
import time

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from h60_research_inputs import PRIOR, load_inputs, save, sha
from panel_config import ROOT, SYMBOLS
import research_features as rf
from profit_priority_strategy import Policy

OUT = ROOT / 'data/experiments/h60_signal_objectives_v11'
CONFIGS = {'plain_magnitude': 'plain_net_excess', 'stopped_magnitude': 'stopped_net_excess',
           'stopped_rank': 'stopped_net_rank'}
YEARS = tuple(range(2016, 2026))
DEADLINE = datetime.fromisoformat('2026-09-11T04:54:13+00:00')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def stable_save(path, payload):
    if path.exists():
        if read(path) != payload:
            raise ValueError(f'Immutable experiment identity changed: {path}')
    else:
        save(path, payload)


def split_fold(panel, year):
    """All targets mature at the common terminal date, never the earlier stop date."""
    mature = panel.exit_60.notna() & panel[list(CONFIGS.values())].notna().all(axis=1)
    train = panel.loc[mature & panel.Date.lt(f'{year-1}-01-01') & panel.exit_60.lt(f'{year-1}-01-01')]
    valid = panel.loc[mature & panel.Date.ge(f'{year-1}-01-01') & panel.Date.lt(f'{year}-01-01')
                      & panel.exit_60.lt(f'{year}-01-01')]
    develop = panel.loc[panel.Date.ge(f'{year}-01-01') & panel.Date.lt(f'{year+1}-01-01')]
    for part in (train, valid, develop):
        if part.empty or not part.groupby('Date').symbol.nunique().eq(len(SYMBOLS)).all():
            raise ValueError('Incomplete annual cross section')
    assert train.exit_60.max() < valid.Date.min() and valid.exit_60.max() < develop.Date.min()
    return train.copy(), valid.copy(), develop.copy()


def register(identity):
    plan = dict(experiment='h60_signal_objectives_v11', design_sha256=sha(OUT/'PLAN.md'),
                candidates=CONFIGS, baseline='v5 ridge_h60_price rank_60 reused', years=list(YEARS),
                feature_order=rf.EXTENDED_FEATURES, model=dict(kind='Ridge',alpha=100,solver='svd',fit_intercept=True),
                label=dict(horizon=60,stop_fraction=.15,cost_bps=10,stop_extra_bps=10),
                policy=asdict(replace(Policy(),soft_enabled=False)), costs=[10,20],
                fixed_stress=['cost30_stop50','delayed_next_open','phase1','phase4','exclude_NVDA'],
                cagr_floor=.30,cagr_aspiration=.50,drawdown_ceiling=.30,preferred_drawdown=.20,
                input_identity=identity, maximum_new_fits=30, reused_models=10,
                deadline_utc=DEADLINE.isoformat(),prices_2026_accessed=False,broker_orders=0)
    path=OUT/'plan.json'
    if path.exists():
        old=read(path); old.pop('registered_at_utc')
        if old != plan:
            raise ValueError('Plan identity mismatch; original results must be retained')
    else:
        save(path,dict(registered_at_utc=datetime.now(timezone.utc).isoformat(),**plan))
    stable_save(OUT/'INPUT_IDENTITY.json',identity)
    return sha(path)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--register-only',action='store_true')
    args=parser.parse_args()
    bars,spy_bars,spy,baseline,observations,final,identity=load_inputs()
    plan_sha=register(identity)
    if args.register_only:
        print('Plan registered against original hashes. New fits 0; evaluations 0.',flush=True)
        return
    from h60_path_labels import build_path_labels
    code_paths=['50_train_signal_objectives.py','h60_path_labels.py','research_features.py',
                'h60_research_inputs.py','profit_priority_strategy.py','research_backtest.py']
    sources={p:sha(ROOT/p) for p in code_paths}
    implementation=dict(plan_sha256=plan_sha,source_sha256=sources,
                        packages={n:importlib.metadata.version(n) for n in ('numpy','pandas','scikit-learn','scipy','joblib')},
                        git_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip())
    stable_save(OUT/'TRAINING_IDENTITY.json',implementation)
    if (OUT/'TRAINING_COMPLETE.json').exists():
        complete=read(OUT/'TRAINING_COMPLETE.json')
        for file,digest in complete['outputs_sha256'].items():
            assert sha(OUT/file)==digest, file
        print('Completed training identities verified; no fits repeated.',flush=True)
        return
    panel=pd.read_csv(PRIOR/'panel.csv',usecols=['Date','symbol','exit_60','y_60','rank_60',*rf.EXTENDED_FEATURES],
                      parse_dates=['Date','exit_60'],float_precision='round_trip').sort_values(['Date','symbol']).reset_index(drop=True)
    assert not panel.duplicated(['Date','symbol']).any() and len(panel)==95010
    labels=build_path_labels(bars,spy_bars,**read(OUT/'plan.json')['label'])
    # Join exact existing observations; keep feature-ready X even where future y is not yet mature.
    labels=panel[['Date','symbol']].merge(labels,on=['Date','symbol'],how='left',validate='one_to_one')
    assert len(labels)==len(panel)
    pd.testing.assert_series_equal(panel.exit_60,labels.exit_60,check_names=False)
    np.testing.assert_allclose(panel.y_60,labels.plain_gross_excess,rtol=0,atol=2e-14,equal_nan=True)
    np.testing.assert_allclose(panel.rank_60,labels.plain_net_rank,rtol=0,atol=1e-15,equal_nan=True)
    panel=panel.merge(labels.drop(columns='exit_60'),on=['Date','symbol'],validate='one_to_one')
    assert np.isfinite(panel[rf.EXTENDED_FEATURES].to_numpy()).all()
    labels.to_csv(OUT/'labels.csv',index=False,date_format='%Y-%m-%d')
    save(OUT/'LABEL_CHECKS.json',dict(original_gross_labels_equal=True,original_rank_labels_equal=True,
          original_terminal_dates_equal=True,panel_rows=len(panel),mature_rows=int(panel.exit_60.notna().sum()),
          stopped_rows=int(panel.stop_reason.str.startswith('stop',na=False).sum()),features=len(rf.EXTENDED_FEATURES),
          target_fields_excluded_from_features=not set(CONFIGS.values()).intersection(rf.EXTENDED_FEATURES),
          fixed_entry_stop_is_proxy_not_portfolio_return=True))
    training=[]; scores=[]; coefficients=[]; baseline_checks=[]; validation=[]
    for year in YEARS:
        train,valid,develop=split_fold(panel,year)
        old=next(m for m in identity['models'] if m['year']==year)
        assert str(train.exit_60.max().date())==old['train_last_label_exit']
        original=joblib.load(ROOT/old['path'])
        with threadpool_limits(limits=2):
            original_score=original['model'].predict(develop[rf.EXTENDED_FEATURES])
        saved=baseline.stack().rename('baseline_rank').reset_index()
        check=develop[['Date','symbol']].merge(saved,on=['Date','symbol'],validate='one_to_one')
        np.testing.assert_allclose(original_score,check.baseline_rank,rtol=0,atol=1e-12)
        baseline_checks.append(dict(year=year,max_abs_error=float(np.max(np.abs(original_score-check.baseline_rank))),sha256=old['sha256']))
        year_scores=check.copy()
        for candidate,target in CONFIGS.items():
            if datetime.now(timezone.utc)>=DEADLINE:
                save(OUT/'PROGRESS.json',dict(status='deadline',completed_fits=len(training),candidate=candidate,year=year))
                raise TimeoutError('Deadline reached, completed artifacts retained')
            stem=f'{year}_{candidate}'
            path=OUT/'models'/f'{stem}.joblib'; record_path=path.with_suffix('.json')
            contract=dict(candidate=candidate,target=target,year=year,plan_sha256=plan_sha,implementation=implementation,
                          train_rows=len(train),validation_rows=len(valid),development_rows=len(develop),
                          train_first=str(train.Date.min().date()),train_last_observation=str(train.Date.max().date()),
                          train_last_exit=str(train.exit_60.max().date()),validation_last_exit=str(valid.exit_60.max().date()))
            if path.exists() or record_path.exists():
                if not path.exists() or not record_path.exists():
                    raise ValueError(f'Incomplete saved fit; inspect without overwriting: {stem}')
                record=read(record_path)
                assert record['contract']==contract and sha(path)==record['model_sha256']
                bundle=joblib.load(path)
                model=bundle['model']
            else:
                model=make_pipeline(StandardScaler(),Ridge(alpha=100,solver='svd'))
                begin=time.perf_counter()
                with threadpool_limits(limits=2):
                    model.fit(train[rf.EXTENDED_FEATURES],train[target])
                duration=time.perf_counter()-begin
                path.parent.mkdir(exist_ok=True)
                joblib.dump(dict(model=model,features=rf.EXTENDED_FEATURES,contract=contract,mode='development_only'),path)
                record=dict(contract=contract,model_sha256=sha(path),fit_seconds=duration,
                            fitted_at_utc=datetime.now(timezone.utc).isoformat())
                save(record_path,record)
            with threadpool_limits(limits=2):
                pred=model.predict(develop[rf.EXTENDED_FEATURES]); vp=model.predict(valid[rf.EXTENDED_FEATURES])
                tp=model.predict(train[rf.EXTENDED_FEATURES])
            assert np.isfinite(pred).all()
            np.testing.assert_allclose(model[0].mean_,train[rf.EXTENDED_FEATURES].mean().to_numpy(),rtol=1e-12,atol=1e-12)
            year_scores[candidate]=pred
            row=dict(**{k:v for k,v in contract.items() if k!='implementation'},model_sha256=record['model_sha256'],
                     model_path=path.relative_to(ROOT).as_posix(),fit_seconds=record['fit_seconds'],
                     fitted_at_utc=record['fitted_at_utc'],train_mse=float(np.mean((tp-train[target])**2)),
                     validation_mse=float(np.mean((vp-valid[target])**2)))
            training.append(row)
            vr=valid[['Date','symbol']].copy();vr['candidate']=candidate;vr['prediction']=vp;vr['target']=valid[target].to_numpy()
            validation.append(vr)
            coefficients.extend(dict(candidate=candidate,year=year,feature=f,standardized_coefficient=float(c))
                                for f,c in zip(rf.EXTENDED_FEATURES,model[-1].coef_))
            pd.DataFrame(training).to_csv(OUT/'training_summary.csv',index=False)
            print(f'{stem}: train={len(train)}, validation={len(valid)}, scored={len(develop)}, fit={record["fit_seconds"]:.2f}s',flush=True)
        scores.append(year_scores)
    all_scores=pd.concat(scores,ignore_index=True).sort_values(['Date','symbol'])
    assert len(all_scores)==75240 and all_scores.groupby('Date').symbol.nunique().eq(len(SYMBOLS)).all()
    all_scores.to_csv(OUT/'scores.csv',index=False,date_format='%Y-%m-%d')
    restored=pd.read_csv(OUT/'scores.csv',parse_dates=['Date'],float_precision='round_trip')
    pd.testing.assert_frame_equal(all_scores.reset_index(drop=True),restored,check_exact=True)
    pd.DataFrame(coefficients).to_csv(OUT/'coefficients.csv',index=False)
    pd.concat(validation,ignore_index=True).to_csv(OUT/'validation_predictions.csv',index=False,date_format='%Y-%m-%d')
    save(OUT/'BASELINE_REUSE_CHECK.json',dict(annual_models=baseline_checks,new_baseline_fits=0,saved_prediction_rows=len(all_scores)))
    files=['labels.csv','scores.csv','training_summary.csv','coefficients.csv','validation_predictions.csv',
           'LABEL_CHECKS.json','BASELINE_REUSE_CHECK.json']
    files += [p.relative_to(OUT).as_posix() for p in sorted((OUT/'models').glob('*'))]
    save(OUT/'TRAINING_COMPLETE.json',dict(completed_at_utc=datetime.now(timezone.utc).isoformat(),new_fits=len(training),
         reused_models=10,prices_2026_accessed=False,broker_orders=0,outputs_sha256={f:sha(OUT/f) for f in files}))
    print('30 fits complete; 10 original models/predictions verified. No strategy evaluation yet.',flush=True)


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
