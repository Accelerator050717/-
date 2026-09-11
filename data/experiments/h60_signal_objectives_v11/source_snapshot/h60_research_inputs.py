"""Read and identify existing H60 artifacts; never fit or download data."""
import csv
import hashlib
import json
from pathlib import Path

import joblib
import pandas as pd

from panel_config import ROOT, SYMBOLS
import research_features as rf

PRIOR = ROOT / "data/experiments/extended_history_v5"
RAW = ROOT / "data/raw/extended_2012_2025"


def sha(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def save(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def load_inputs():
    with (ROOT / 'review_upload/inventory.csv').open(encoding='utf-8', newline='') as f:
        original = {r['relative_path']: r['sha256'] for r in csv.DictReader(f)}
    identities = {}

    def check(path):
        rel = path.relative_to(ROOT).as_posix()
        digest = sha(path)
        if digest != original[rel]:
            raise ValueError(f'Original upload input identity changed: {rel}')
        identities[rel] = dict(sha256=digest, size_bytes=path.stat().st_size)
        return digest

    frames = {}
    # All 44 original input hashes are checked, though the replay only needs OHLC/SPY.
    for symbol in dict.fromkeys((*SYMBOLS, 'SPY', *rf.CONTEXT_SYMBOLS)):
        path = RAW / f'{symbol}.csv'
        meta = json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
        assert check(path) == meta['sha256'] and meta['parameters']['end'] == '2026-01-01'
        if symbol in (*SYMBOLS, 'SPY'):
            frame = pd.read_csv(path, index_col='Date', parse_dates=['Date'], float_precision='round_trip').loc['2012-05-18':]
            assert frame.index.max() <= pd.Timestamp('2025-12-31')
            frames[symbol] = frame
    spy = frames['SPY']['Adj Close']
    for frame in frames.values():
        assert frame.index.equals(spy.index)
    bars = {field: pd.DataFrame({s: frames[s][field] * frames[s]['Adj Close'] / frames[s].Close for s in SYMBOLS})
            for field in ('Open', 'High', 'Low')}
    bars['Close'] = pd.DataFrame({s: frames[s]['Adj Close'] for s in SYMBOLS})
    spy_bars = {field: (frames['SPY'][field] * frames['SPY']['Adj Close'] / frames['SPY'].Close).to_frame('SPY')
                for field in ('Open', 'High', 'Low')}
    spy_bars['Close'] = spy.to_frame('SPY')
    check(PRIOR / 'adjusted_opens.csv')
    pd.testing.assert_frame_equal(bars['Open'], pd.read_csv(PRIOR / 'adjusted_opens.csv', index_col='Date', parse_dates=['Date'], float_precision='round_trip'), check_exact=True)
    check(PRIOR / 'all_scores.csv')
    scores = pd.read_csv(PRIOR / 'all_scores.csv', usecols=['Date','symbol','ridge_h60_price'], parse_dates=['Date'], float_precision='round_trip')
    scores = scores.pivot(index='Date', columns='symbol', values='ridge_h60_price').reindex(columns=SYMBOLS)
    schedule_path = PRIOR / 'backtests/ridge_h60_price_vol15_cost10_periods.csv'
    check(schedule_path)
    periods = pd.read_csv(schedule_path, parse_dates=['observation_date', 'exit_date'])
    observations, final = pd.DatetimeIndex(periods.observation_date), periods.exit_date.iloc[-1]
    check(PRIOR / 'training_summary.csv')
    training = pd.read_csv(PRIOR / 'training_summary.csv').query("id == 'ridge_h60_price'")
    check(PRIOR / 'panel.csv')
    panel = pd.read_csv(PRIOR / 'panel.csv', usecols=['Date','exit_60','y_60'], parse_dates=['Date','exit_60'])
    models = []
    for row in training.itertuples():
        path = PRIOR / f'{row.year}_ridge_h60_price.joblib'
        digest = check(path)
        assert digest == row.model_sha256
        bundle = joblib.load(path)  # Owned, hash-identified local artifacts only.
        assert bundle['features'] == rf.EXTENDED_FEATURES
        assert bundle['candidate'] == {'id':'ridge_h60_price','kind':'ridge','horizon':60}
        assert bundle['model'][-1].alpha == 100 and bundle['model'][-1].solver == 'svd'
        train = panel.loc[panel.Date.lt(f'{row.year-1}-01-01') & panel.exit_60.lt(f'{row.year-1}-01-01') & panel.y_60.notna()]
        assert len(train) == row.train_rows
        assert str(train.exit_60.max().date()) == row.train_last_exit
        assert row.validation_last_exit < f'{row.year}-01-01'
        models.append(dict(year=row.year, path=path.relative_to(ROOT).as_posix(), sha256=digest,
                           train_last_observation=str(train.Date.max().date()),
                           train_last_label_exit=row.train_last_exit,
                           validation_last_label_exit=row.validation_last_exit,
                           scoring_year=row.year, features=bundle['features'], alpha=100, solver='svd'))
    return bars, spy_bars, spy, scores, observations, final, dict(
        input_files=identities, models=models, new_fits=0, reused_annual_models=len(models),
        prediction_source='v5 original saved ridge_h60_price column, no refit or re-ranking ensemble',
        market_price_last=str(spy.index.max().date()), prices_2026_accessed=False,
        observations=[str(d.date()) for d in observations], final_exit=str(final.date()),
        common_calendar=[str(d.date()) for d in spy.index],
        raw_price_basis='Yahoo snapshot: split-normalized history plus adjustment factors, not executable quotes')
