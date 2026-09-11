"""Export existing, hash-identified H60 inputs for LEAN; never train or download."""
import argparse
import csv
from dataclasses import asdict, replace
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess

import numpy as np
import pandas as pd

from h60_research_inputs import load_inputs, save, sha
from panel_config import ROOT
import profit_priority_strategy as strategy
import research_features as features

OUT = ROOT / 'data/experiments/lean_migration_v10'
GOLDEN = ROOT / 'data/experiments/h60_risk_execution_v8/backtests'
CASE = 'stop_on_soft_off_cost10'
SHARED = ('profit_priority_strategy.py', 'research_backtest.py')


def finite_rows(frame):
    """JSON null is allowed only for pre-trading rolling warmup values."""
    return [[float(x) if np.isfinite(x) else None for x in row]
            for row in frame.to_numpy()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', choices=('full', 'smoke'), default='full')
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    folder = OUT / ('input' if args.case == 'full' else 'smoke_input')
    registered = folder / 'EXPORT_IDENTITY.json'
    bars, _, spy, scores, observations, final, identity = load_inputs()
    calendar, names = bars['Open'].index, list(bars['Open'].columns)
    first_index = int(calendar.get_loc(observations[0])) + 1
    if args.case == 'smoke':
        final = calendar[first_index + 19]
        observations = observations[observations < final]
    first = calendar[first_index]
    assert final.year <= 2025 and calendar.max().year <= 2025
    policy = replace(strategy.Policy(), soft_enabled=False)
    source_hashes = {name: sha(ROOT / name) for name in SHARED}
    source_hashes['h60_research_inputs.py'] = sha(ROOT / 'h60_research_inputs.py')
    expected = dict(schema_version=1, case=args.case, first_date=str(first.date()),
                    final_date=str(final.date()), policy=asdict(policy),
                    source_hashes=source_hashes, input_identity=identity,
                    plan_sha256=sha(OUT / 'PLAN.md'),
                    exporter_sha256=sha(Path(__file__)))
    if registered.exists():
        previous = json.loads(registered.read_text(encoding='utf-8'))
        assert previous['stable_identity'] == expected, 'Export identity changed; preserve the old experiment.'
        for name, digest in previous['exported_sha256'].items():
            assert sha(folder / name) == digest, f'Export changed: {name}'
        print(json.dumps(dict(status='verified_existing', folder=str(folder),
                              files=len(previous['exported_sha256']), new_fits=0)))
        return
    if folder.exists() and any(folder.iterdir()):
        raise FileExistsError(f'Incomplete export already exists, inspect before reusing: {folder}')
    (folder / 'bars').mkdir(parents=True)
    (folder / 'shared').mkdir()
    for name in SHARED:
        shutil.copyfile(ROOT / name, folder / 'shared' / name)
    risk = strategy.risk_inputs(bars, spy, policy.target_vol)
    times = [('09:30:00', 'OPEN', 'Open'), ('12:00:00', 'RANGE', 'Low'),
             ('16:00:00', 'CLOSE', 'Close')]
    sessions = calendar[(calendar >= first) & (calendar <= final)]
    exported = {}
    for symbol in names:
        rel = f'bars/{symbol}.csv'
        with (folder / rel).open('w', encoding='utf-8', newline='') as handle:
            writer = csv.writer(handle)
            writer.writerow(['timestamp', 'phase', 'value'])
            for date in sessions:
                for clock, phase, field in times:
                    writer.writerow([f'{date.date()}T{clock}', phase,
                                     format(float(bars[field].loc[date, symbol]), '.17g')])
        exported[rel] = sha(folder / rel)
    package = dict(
        schema_version=1, research_only=True, live_mode_allowed=False,
        initial_cash=10000., names=names,
        groups={s: features.SECTOR_PROXY.get(s, 'market') for s in names},
        policy=asdict(policy), cost_bps=10, stop_extra_bps=10,
        first_date=str(first.date()), final_date=str(final.date()),
        calendar=[str(d.date()) for d in calendar],
        observations=[str(d.date()) for d in observations],
        scores={str(d.date()): [float(x) for x in scores.loc[d]] for d in observations},
        risk={**{key: finite_rows(risk[key]) for key in ('distance', 'vol', 'returns')},
              'trend': [bool(x) for x in risk['trend']],
              'spy_exposure': [float(x) if np.isfinite(x) else None for x in risk['spy_exposure']]},
        data_files={s: f'bars/{s}.csv' for s in names},
        data_sha256=exported,
        shared_directory='shared', shared_source_sha256={n: source_hashes[n] for n in SHARED},
        prediction_source=identity['prediction_source'], models=identity['models'], new_fits=0,
        price_basis='Original adjusted daily OHLC / fractional research return proxy; not executable broker prices',
        phase_clock='Artificial daily-bar sequence OPEN 09:30, RANGE 12:00, CLOSE 16:00 America/New_York; not observed intraday times',
        reference_case=CASE, experiment_plan_sha256=expected['plan_sha256'])
    save(folder / 'package.json', package)
    for name in SHARED:
        exported[f'shared/{name}'] = sha(folder / 'shared' / name)
    exported['package.json'] = sha(folder / 'package.json')
    save(registered, dict(stable_identity=expected, exported_sha256=exported,
                         generated_at_utc=datetime.now(timezone.utc).isoformat()))
    if args.case == 'full':
        reference = {f'{CASE}_{key}.{ext}': sha(GOLDEN / f'{CASE}_{key}.{ext}')
                     for key, ext in [('daily','csv'), ('trades','csv'), ('positions','csv'),
                                      ('targets','csv'), ('events','csv'), ('metrics','json')]}
        save(OUT / 'REFERENCE_IDENTITY.json', dict(directory=str(GOLDEN), files=reference,
              base_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()))
        save(OUT / 'INPUT_IDENTITY.json', identity)
    print(json.dumps(dict(status='exported', folder=str(folder), sessions=len(sessions),
                          symbols=len(names), observations=len(observations),
                          bytes=sum(p.stat().st_size for p in folder.rglob('*') if p.is_file()),
                          new_fits=0, prices_2026_accessed=False)))


if __name__ == '__main__':
    main()
