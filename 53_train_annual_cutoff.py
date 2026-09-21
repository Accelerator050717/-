"""v12 single-factor annual H60 update: exactly ten fits, frozen local data only."""
import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys
import time
import warnings

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

OUT = ROOT / 'data/experiments/h60_training_cutoff_v12'
YEARS = tuple(range(2016, 2026))
DEADLINE = datetime.fromisoformat('2026-09-21T20:50:37+00:00')
BASE = '8b70778217cc2e0405cd20b68e4a3ba9f51b6cd9'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def stable_save(path, payload):
    if path.exists():
        if read(path) != payload:
            raise ValueError(f'Frozen identity changed: {path}')
    else:
        save(path, payload)


def training_rows(panel, year, feature_order):
    """Reselect from the full panel; labels ending on deployment date are unavailable."""
    complete = panel[['rank_60', *feature_order]].notna().all(axis=1)
    rows = panel.loc[complete & panel.Date.lt(f'{year}-01-01')
                     & panel.exit_60.lt(f'{year}-01-01')].copy()
    if rows.empty or not np.isfinite(rows[['rank_60', *feature_order]].to_numpy()).all():
        raise ValueError('Empty or nonfinite training cohort')
    return rows


def scoring_rows(panel, year, baseline_keys, feature_order):
    """Keep A's exact key order, including features whose future label is still absent."""
    keys = baseline_keys.loc[baseline_keys.Date.dt.year.eq(year), ['Date', 'symbol']]
    rows = keys.merge(panel, on=['Date', 'symbol'], how='left', validate='one_to_one', indicator=True)
    if rows.empty or not rows._merge.eq('both').all():
        raise ValueError('A prediction key missing from full panel')
    rows = rows.drop(columns='_merge')
    if not np.isfinite(rows[feature_order].to_numpy()).all():
        raise ValueError('Prediction features missing; do not silently remove keys')
    return rows


def register(identity):
    plan = dict(experiment='h60_training_cutoff_v12', base_commit=BASE,
                design_sha256=sha(OUT/'PLAN.md'), years=list(YEARS), target='rank_60',
                feature_order=rf.EXTENDED_FEATURES,
                model=dict(kind='Ridge', alpha=100, solver='svd', fit_intercept=True),
                protocol_A='original v5 models and saved scores; exit_60 < Y-1 January 1',
                protocol_B='full original panel: Date < Y January 1 and exit_60 < Y January 1; complete X/rank_60',
                policy=asdict(replace(Policy(), soft_enabled=False)),
                configurations=['protected', 'simple_h60'],
                scenarios=['cost10','cost20','cost30_stop50','delayed_next_open','phase1','phase4','exclude_NVDA'],
                improvement_rule='protected B CAGR > A at cost10 AND cost20; B all 7 full-history DD >= -0.30',
                cagr_floor=.30, cagr_aspiration=.50, drawdown_ceiling=.30, preferred_drawdown=.20,
                initial_equity=1., usd_scale=10000, cash_interest=0.,
                maximum_new_fits=10, maximum_new_replays=14, reused_models=10, reused_controls=21,
                deadline_utc=DEADLINE.isoformat(), input_identity=identity,
                prices_2026_accessed=False, broker_orders=0)
    path = OUT/'plan.json'
    if path.exists():
        existing = read(path)
        existing.pop('registered_at_utc')
        if existing != plan:
            raise ValueError('Registered plan differs; preserve existing experiment')
    else:
        save(path, dict(registered_at_utc=datetime.now(timezone.utc).isoformat(), **plan))
    stable_save(OUT/'INPUT_IDENTITY.json', identity)
    return sha(path)


def verify_complete(implementation):
    stable_save(OUT/'TRAINING_IDENTITY.json', implementation)
    marker = OUT/'TRAINING_COMPLETE.json'
    if not marker.exists():
        return False
    complete = read(marker)
    for name, digest in complete['outputs_sha256'].items():
        if sha(OUT/name) != digest:
            raise ValueError(f'Completed training output changed: {name}')
    print('Completed v12 training verified; zero additional fits.', flush=True)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--register-only', action='store_true')
    args = parser.parse_args()
    _, _, _, baseline, _, _, identity = load_inputs()
    plan_sha = register(identity)
    if args.register_only:
        print('Plan and frozen input identities registered before fits/replays.', flush=True)
        return
    names = ('53_train_annual_cutoff.py','research_features.py','research_horizons.py',
             'h60_research_inputs.py','profit_priority_strategy.py','research_backtest.py')
    implementation = dict(plan_sha256=plan_sha, source_sha256={p:sha(ROOT/p) for p in names},
                          packages={p:importlib.metadata.version(p) for p in ('numpy','pandas','scikit-learn','scipy','joblib')})
    if verify_complete(implementation):
        return
    generation_path = OUT/'GENERATION_CONTEXT.json'
    if not generation_path.exists():
        save(generation_path, dict(git_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
             started_at_utc=datetime.now(timezone.utc).isoformat(), training_source_sha256=implementation['source_sha256'],
             note='Generation HEAD is provenance, not immutable equality. New uncommitted source snapshots are authoritative.'))
    for name in names:
        path = OUT/'source_snapshot'/name
        path.parent.mkdir(exist_ok=True)
        if path.exists():
            if path.read_bytes() != (ROOT/name).read_bytes():
                raise ValueError('Generation source snapshot differs')
        else:
            path.write_bytes((ROOT/name).read_bytes())
    panel = pd.read_csv(PRIOR/'panel.csv', usecols=['Date','symbol','exit_60','rank_60',*rf.EXTENDED_FEATURES],
                        parse_dates=['Date','exit_60'], float_precision='round_trip')
    panel = panel.sort_values(['Date','symbol']).reset_index(drop=True)
    assert len(panel) == 95010 and len(rf.EXTENDED_FEATURES) == 81
    assert not panel.duplicated(['Date','symbol']).any() and panel.Date.max().year == 2025
    assert panel.Date.min() == pd.Timestamp('2013-05-22')
    # Same row order as A's original saved long-format predictions.
    keys = pd.read_csv(PRIOR/'all_scores.csv', usecols=['Date','symbol','ridge_h60_price'],
                       parse_dates=['Date'], float_precision='round_trip').rename(columns={'ridge_h60_price':'A'})
    original_training = pd.read_csv(PRIOR/'training_summary.csv').query("id == 'ridge_h60_price'").set_index('year')
    training, blocks, coefficients, checks = [], [], [], []
    for year in YEARS:
        train = training_rows(panel, year, rf.EXTENDED_FEATURES)
        old_train = training_rows(panel, year-1, rf.EXTENDED_FEATURES)
        develop = scoring_rows(panel, year, keys, rf.EXTENDED_FEATURES)
        old = next(m for m in identity['models'] if m['year'] == year)
        assert len(old_train) == int(original_training.loc[year,'train_rows'])
        assert train.Date.min() == old_train.Date.min() == pd.Timestamp('2013-05-22')
        old_valid = train.loc[train.Date.ge(f'{year-1}-01-01')]
        newly_mature_boundary = train.loc[train.Date.lt(f'{year-1}-01-01') & train.exit_60.ge(f'{year-1}-01-01')]
        assert len(train) == len(old_train)+len(old_valid)+len(newly_mature_boundary)
        assert len(old_valid) == int(original_training.loc[year,'validation_rows'])
        assert train.groupby('Date').symbol.nunique().eq(len(SYMBOLS)).all()
        original = joblib.load(ROOT/old['path'])
        with threadpool_limits(limits=2):
            check_A = original['model'].predict(develop[rf.EXTENDED_FEATURES])
        year_scores = keys.loc[keys.Date.dt.year.eq(year)].copy()
        np.testing.assert_allclose(check_A, year_scores.A, rtol=0, atol=1e-12)
        contract = dict(year=year, target='rank_60', feature_order=rf.EXTENDED_FEATURES,
                        training_identity_sha256=sha(OUT/'TRAINING_IDENTITY.json'),
                        train_rows=len(train), A_train_rows=len(old_train), added_rows=len(train)-len(old_train),
                        former_validation_rows=len(old_valid), newly_mature_boundary_rows=len(newly_mature_boundary),
                        train_first=str(train.Date.min().date()), train_last_observation=str(train.Date.max().date()),
                        train_last_exit=str(train.exit_60.max().date()), cutoff_exclusive=f'{year}-01-01',
                        scoring_rows=len(develop), A_model_sha256=old['sha256'],
                        training_key_sha256=__import__('hashlib').sha256(train[['Date','symbol']].to_csv(index=False,date_format='%Y-%m-%d').encode()).hexdigest())
        path = OUT/'models'/f'{year}_mature_rank60.joblib'
        record_path = path.with_suffix('.json')
        if path.exists() or record_path.exists():
            if not path.exists() or not record_path.exists():
                raise ValueError('Incomplete saved fit; do not silently refit')
            record = read(record_path)
            assert record['contract'] == contract and sha(path) == record['model_sha256']
            model = joblib.load(path)['model']
        else:
            if datetime.now(timezone.utc) >= DEADLINE:
                save(OUT/'PROGRESS.json', dict(status='deadline', completed_fits=len(training), next_year=year))
                raise TimeoutError('Budget reached; artifacts preserved')
            model = make_pipeline(StandardScaler(), Ridge(alpha=100, solver='svd'))
            begin = time.perf_counter()
            with warnings.catch_warnings(record=True) as caught, threadpool_limits(limits=2):
                warnings.simplefilter('always')
                model.fit(train[rf.EXTENDED_FEATURES], train.rank_60)
            duration = time.perf_counter()-begin
            path.parent.mkdir(exist_ok=True)
            joblib.dump(dict(model=model, features=rf.EXTENDED_FEATURES, contract=contract, mode='development_only'),path)
            record = dict(contract=contract, model_sha256=sha(path), fit_seconds=duration,
                          warnings=[f'{w.category.__name__}: {w.message}' for w in caught],
                          fitted_at_utc=datetime.now(timezone.utc).isoformat())
            save(record_path, record)
        with threadpool_limits(limits=2):
            prediction = model.predict(develop[rf.EXTENDED_FEATURES])
        assert np.isfinite(prediction).all()
        np.testing.assert_allclose(model[0].mean_, train[rf.EXTENDED_FEATURES].mean().to_numpy(), rtol=1e-12,atol=1e-12)
        assert model[0].n_samples_seen_ == len(train)
        year_scores['B'] = prediction
        blocks.append(year_scores)
        training.append(dict(**{k:v for k,v in contract.items() if k!='feature_order'},
                            model_sha256=record['model_sha256'], model_path=path.relative_to(ROOT).as_posix(),
                            fit_seconds=record['fit_seconds'], warnings=json.dumps(record['warnings']),
                            fitted_at_utc=record['fitted_at_utc']))
        checks.append(dict(year=year, A_model_sha256=old['sha256'], A_max_abs_prediction_error=float(np.max(np.abs(check_A-year_scores.A))),
                           scaler_only_B_training=True, unmatured_scoring_rows=int(develop.rank_60.isna().sum())))
        coefficients.extend(dict(year=year, feature=f, standardized_coefficient=float(c)) for f,c in zip(rf.EXTENDED_FEATURES,model[-1].coef_))
        pd.DataFrame(training).to_csv(OUT/'training_summary.csv',index=False)
        print(f'{year}: A rows={len(old_train)}, B={len(train)}, +{len(train)-len(old_train)}; last label={contract["train_last_exit"]}; fit={record["fit_seconds"]:.3f}s',flush=True)
    scores = pd.concat(blocks, ignore_index=True)
    pd.testing.assert_frame_equal(scores[['Date','symbol','A']],keys,check_exact=True)
    assert len(scores) == 75240 and scores.groupby('Date').symbol.nunique().eq(30).all()
    scores.to_csv(OUT/'scores.csv',index=False,date_format='%Y-%m-%d')
    restored = pd.read_csv(OUT/'scores.csv',parse_dates=['Date'],float_precision='round_trip')
    pd.testing.assert_frame_equal(scores,restored,check_exact=True)
    pd.DataFrame(coefficients).to_csv(OUT/'coefficients.csv',index=False)
    save(OUT/'TRAINING_CHECKS.json',dict(years=checks, feature_count=81, score_rows=len(scores),
          target='original panel rank_60, unchanged', A_saved_scores_exact=True, no_validation_claim_for_refitted_prior_year=True,
          training_history_start='2013-05-22', new_fits=10, reused_models=10, prices_2026_accessed=False))
    files = ['scores.csv','training_summary.csv','coefficients.csv','TRAINING_CHECKS.json','TRAINING_IDENTITY.json','GENERATION_CONTEXT.json']
    files += [p.relative_to(OUT).as_posix() for p in sorted((OUT/'models').glob('*'))]
    files += [p.relative_to(OUT).as_posix() for p in sorted((OUT/'source_snapshot').glob('*'))]
    save(OUT/'TRAINING_COMPLETE.json',dict(completed_at_utc=datetime.now(timezone.utc).isoformat(), new_fits=10,reused_models=10,
          prices_2026_accessed=False, broker_orders=0, outputs_sha256={f:sha(OUT/f) for f in files}))
    print('Ten annual fits complete. No other fits, no 2026 data, no broker access.',flush=True)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
