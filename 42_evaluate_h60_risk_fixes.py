"""Fixed v8 experiment. Existing H60 scores only; no fitting, downloading or broker orders."""
import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
import importlib.util
import json
import subprocess
import sys
import time

import numpy as np
import pandas as pd

import profit_priority_strategy as v7
import robust_strategy as v6
import research_features as rf
from panel_config import ROOT, SYMBOLS
from h60_research_inputs import load_inputs, save, sha

BASE = '9d98008d72f096c2c1fa33a998f000fe62c48bb5'
OUT = ROOT / 'data/experiments/h60_risk_execution_v8'
DEADLINE = datetime.fromisoformat('2026-09-09T10:07:43+00:00')


def legacy(filename, name):
    path = OUT / 'legacy' / filename
    path.parent.mkdir(exist_ok=True)
    content = subprocess.check_output(['git', 'show', f'{BASE}:{filename}'], cwd=ROOT)
    if path.exists():
        assert path.read_bytes() == content
    else:
        path.write_bytes(content)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def audit(result, bars):
    daily, trades, positions = (result[k] for k in ('daily','trades','positions'))
    changes = trades.groupby('Date').cash_change.sum().reindex(daily.index, fill_value=0)
    np.testing.assert_allclose(1 + changes.cumsum(), daily.cash, rtol=1e-9, atol=1e-10)
    units = trades.pivot_table(index='Date', columns='symbol', values='signed_units', aggfunc='sum', fill_value=0)
    units = units.reindex(index=daily.index, columns=positions.columns, fill_value=0).cumsum()
    np.testing.assert_allclose(units, positions, rtol=1e-9, atol=1e-10)
    np.testing.assert_allclose(daily.cash + (positions * bars['Close'].loc[daily.index]).sum(axis=1), daily.equity, rtol=1e-10)
    np.testing.assert_allclose(trades.fee.sum(), daily.fees.sum(), rtol=1e-10)
    assert positions.iloc[-1].eq(0).all() and daily.cash.ge(-1e-10).all()
    assert result['targets'].observation_date.lt(result['targets'].Date).all()
    return dict(ledger_passed=True, final_flat=True, days=len(daily), trades=len(trades))


def enrich(result):
    daily, trades, m = result['daily'], result['trades'], result['metrics']
    duration = (daily.index[-1]-daily.index[0]).days / 365.25
    previous_nav = daily.equity.shift(1, fill_value=1.)
    notionals = trades.groupby('Date').signed_notional.apply(lambda x: x.abs().sum()).reindex(daily.index, fill_value=0)
    stopped = trades.loc[trades.reason.str.startswith('stop_')]
    stop_slip = float((stopped.signed_units.abs() * stopped.proxy_fill * (1/(1+0*stopped.stop_extra_bps-stopped.stop_extra_bps/10000)-1)).sum())
    reductions = trades.loc[trades.reason.eq('daily_risk_reduce')]
    m.update(total_return=m['final_equity']-1, turnover_two_way_per_year=float((notionals / previous_nav).sum()/duration),
             cumulative_notional_per_initial_nav=float(notionals.sum()), fee_per_initial_nav=float(trades.fee.sum()),
             stop_slippage_per_initial_nav=stop_slip, explicit_total_cost_per_initial_nav=float(trades.fee.sum()+stop_slip),
             risk_reduction_buy_orders=int(reductions.signed_units.gt(1e-12).sum()),
             risk_reduction_buy_notional=float(reductions.loc[reductions.signed_units.gt(1e-12),'signed_notional'].sum()))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--register-only', action='store_true')
    args = parser.parse_args()
    bars, spy_bars, spy, scores, observations, final, identity = load_inputs()
    source = {p:sha(ROOT/p) for p in ('research_backtest.py','profit_priority_strategy.py','robust_strategy.py','h60_research_inputs.py','42_evaluate_h60_risk_fixes.py')}
    plan = dict(base_commit=BASE, design_sha256=sha(OUT/'PLAN.md'), source_sha256=source,
                input_identity=identity, candidate=asdict(replace(v7.Policy(),soft_enabled=False)),
                costs=[10,20], fixed_stress=['cost30_stop50','delayed_next_open','phase1','phase4','exclude_NVDA'],
                cagr_floor=.30, cagr_aspiration=.50, preferred_drawdown=.20, drawdown_ceiling=.30,
                initial_equity=1., usd_scale=10000, cash_interest=0., new_fits=0)
    registered = OUT/'plan.json'
    if registered.exists():
        old = json.loads(registered.read_text(encoding='utf-8')); old.pop('registered_at_utc')
        assert old == plan, 'Registered identity differs; preserve results and investigate.'
    else:
        save(registered, dict(registered_at_utc=datetime.now(timezone.utc).isoformat(), **plan))
    save(OUT/'INPUT_IDENTITY.json', identity)
    if args.register_only:
        print('Fixed inputs, model hashes, time boundaries and plan registered. No fits or evaluations.')
        return
    if (OUT/'completion.json').exists():
        print('Complete results already exist; no experiments repeated.')
        return
    old7, old6 = legacy('profit_priority_strategy.py','v8_legacy7'), legacy('robust_strategy.py','v8_legacy6')
    rows, checks, results = [], {}, {}

    def run(name, engine=v7, use_bars=bars, use_scores=scores, obs=observations, **kwargs):
        path = OUT/'backtests'/f'{name}_metrics.json'
        if datetime.now(timezone.utc) >= DEADLINE:
            save(OUT/'PROGRESS.json', dict(status='deadline', completed=list(results), new_fits=0))
            raise TimeoutError('Fixed session deadline reached; artifacts retained.')
        if path.exists():
            result = dict(metrics=json.loads(path.read_text(encoding='utf-8')))
            for key in ('daily','trades','positions','targets','events'):
                p=path.with_name(f'{name}_{key}.csv')
                try:
                    result[key]=pd.read_csv(p,index_col='Date' if key in ('daily','positions') else None,
                                           parse_dates=['Date'],float_precision='round_trip')
                    if 'observation_date' in result[key]:
                        result[key]['observation_date']=pd.to_datetime(result[key]['observation_date'])
                except pd.errors.EmptyDataError:
                    result[key]=pd.DataFrame()
        else:
            begin=time.perf_counter()
            result=engine.simulate(use_scores,use_bars,spy,{s:rf.SECTOR_PROXY.get(s,'market') for s in use_bars['Open'].columns},
                                   obs,final,**kwargs)
            enrich(result)
            result['metrics']['runtime_seconds']=time.perf_counter()-begin
            path.parent.mkdir(exist_ok=True)
            for key in ('daily','trades','positions','targets','events'):
                result[key].to_csv(path.with_name(f'{name}_{key}.csv'),index=key in ('daily','positions'),date_format='%Y-%m-%d')
            save(path,result['metrics'])
        checks[name]=audit(result,use_bars)
        if engine in (v7,v6):
            assert result['metrics']['risk_reduction_buy_orders']==0
        results[name]=result
        rows.append(dict(case=name,**result['metrics']))
        pd.DataFrame(rows).to_csv(OUT/'all_results.csv',index=False)
        save(OUT/'PROGRESS.json',dict(status='running',completed=list(results),new_fits=0))
        print(f"{name}: CAGR {result['metrics']['cagr']:.3%}; DD {result['metrics']['max_drawdown']:.3%}; nonplanned buys {result['metrics']['risk_reduction_buy_orders']}",flush=True)
        return result

    # Exact same saved H60 predictions in each legacy/fixed bug pair, no ensemble recalculation.
    for family,old,new in (('v7',old7,v7),('v6',old6,v6)):
        for variant,stops,breaker in ([('allocation',False,False),('stops',True,False),('full',True,True)] if family=='v7' else [('allocation',False,False),('full',True,True)]):
            for label,engine in (('old',old),('fixed',new)):
                run(f'bug_{family}_{variant}_{label}',engine,stops=stops,breaker=breaker)
    for cost in (10,20):
        for stops in (True,False):
            for soft in (True,False):
                run(f'stop_{"on" if stops else "off"}_soft_{"on" if soft else "off"}_cost{cost}',
                    stops=stops,breaker=True,cost_bps=cost,policy=replace(v7.Policy(),soft_enabled=soft))
        run(f'simple_h60_cost{cost}',mode='simple_h60',stops=False,policy=replace(v7.Policy(),soft_enabled=False),cost_bps=cost)
        run(f'simple_spy_cost{cost}',use_bars=spy_bars,use_scores=pd.DataFrame(0.,index=scores.index,columns=['SPY']),
            mode='simple_spy',stops=False,policy=replace(v7.Policy(),soft_enabled=False),cost_bps=cost)
    run('background_h60_full_budget',mode='incumbent',stops=False,breaker=False)
    run('background_spy_full',use_bars=spy_bars,use_scores=pd.DataFrame(0.,index=scores.index,columns=['SPY']),mode='spy',stops=False,breaker=False)
    calendar=bars['Open'].index
    phases={phase:calendar[calendar.get_indexer(observations)+phase] for phase in (1,4)}
    stresses=[('cost30_stop50',dict(cost_bps=30,stop_extra_bps=50)),
              ('delayed_next_open',dict(cost_bps=20,stop_extra_bps=50,delayed_stops=True)),
              ('phase1',dict(obs=phases[1])),('phase4',dict(obs=phases[4])),('exclude_NVDA',dict(excluded=('NVDA',)))]
    for name,stress in stresses:
        for strategy in ('candidate','simple_h60','simple_spy'):
            kwargs=dict(stress)
            if 'obs' in kwargs:
                kwargs['obs']=kwargs['obs'][kwargs['obs'].isin(scores.index)&(kwargs['obs']<final)]
            if strategy=='simple_spy':
                kwargs.pop('excluded',None)
            run(f'stress_{name}_{strategy}',
                use_bars=spy_bars if strategy=='simple_spy' else bars,
                use_scores=pd.DataFrame(0.,index=scores.index,columns=['SPY']) if strategy=='simple_spy' else scores,
                mode='risk' if strategy=='candidate' else strategy,stops=strategy=='candidate',
                policy=replace(v7.Policy(),soft_enabled=False),**kwargs)
    table=pd.DataFrame(rows).set_index('case')
    main_names=[n for n in results if n.startswith(('stop_','simple_'))]
    table.loc[main_names].to_csv(OUT/'comparison.csv')
    table.loc[[n for n in results if n.startswith('stress_')]].to_csv(OUT/'stress_comparison.csv')
    bug_rows=[]
    for name in [n for n in results if n.startswith('bug_') and n.endswith('_old')]:
        fixed=name[:-3]+'fixed'
        a,b=table.loc[name],table.loc[fixed]
        bug_rows.append(dict(pair=name[:-4],old_buy_orders=int(a.risk_reduction_buy_orders),fixed_buy_orders=int(b.risk_reduction_buy_orders),
                             old_cagr=a.cagr,fixed_cagr=b.cagr,cagr_difference=b.cagr-a.cagr,
                             old_total_return=a.total_return,fixed_total_return=b.total_return,
                             old_drawdown=a.max_drawdown,fixed_drawdown=b.max_drawdown,
                             old_turnover=a.turnover_two_way_per_year,fixed_turnover=b.turnover_two_way_per_year,
                             old_buy_notional=a.risk_reduction_buy_notional,fixed_buy_notional=b.risk_reduction_buy_notional))
    pd.DataFrame(bug_rows).to_csv(OUT/'bug_impact.csv',index=False)
    equity=pd.DataFrame({n:r['daily'].equity for n,r in results.items()})
    equity.to_csv(OUT/'equity.csv')
    annual=[]
    for name,r in results.items():
        d=r['daily']
        for year,part in d.groupby(d.index.year):
            first_index=d.index.get_loc(part.index[0]); initial=1. if first_index==0 else d.equity.iloc[first_index-1]
            annual.append(dict(case=name,year=year,return_net=float(part.equity.iloc[-1]/initial-1),
                                volatility=float(part['return'].std(ddof=1)*np.sqrt(252)),
                                within_year_drawdown=float((part.equity/part.equity.cummax().clip(lower=initial)-1).min()),
                                full_history_drawdown_min=float(part.drawdown.min()),average_gross=float(part.gross.mean())))
    pd.DataFrame(annual).to_csv(OUT/'annual_results.csv',index=False)
    # Event records are descriptive; paired ablations measure aggregate rule effects.
    event_rows=[]; paths=[]
    for name in main_names:
        result=results[name]; trades=result['trades'].copy()
        trades['category']=trades.reason
        mask=trades.reason.eq('daily_risk_reduce')
        trades.loc[mask,'category']=trades.loc[mask,'risk_action'].map({'cap':'daily_cap','soft':'soft_reduce','cap_and_soft':'cap_and_soft'})
        for reason,part in trades.groupby('category'):
            event_rows.append(dict(case=name,category=reason,orders=len(part),buys=int(part.signed_units.gt(0).sum()),
                                   signed_notional=float(part.signed_notional.sum()),traded_notional=float(part.signed_notional.abs().sum()),fees=float(part.fee.sum())))
        if name=='stop_on_soft_off_cost10':
            for t in trades.loc[trades.reason.str.startswith('stop_')].itertuples():
                pos=calendar.get_loc(t.Date)
                row=dict(Date=t.Date,symbol=t.symbol,reason=t.reason,proxy_fill=t.proxy_fill,stop_threshold=t.stop_threshold)
                for horizon in (5,20,60):
                    row[f'after_{horizon}_sessions']=float(bars['Close'].iloc[pos+horizon][t.symbol]/t.proxy_fill-1) if pos+horizon<len(calendar) else None
                paths.append(row)
    pd.DataFrame(event_rows).to_csv(OUT/'trade_reason_summary.csv',index=False)
    pd.DataFrame(paths).to_csv(OUT/'stop_forward_paths.csv',index=False)
    principal=table.loc['stop_on_soft_off_cost10']
    stress=table.loc[[n for n in table.index if n.startswith('stress_') and n.endswith('_candidate')]+['stop_on_soft_off_cost20']]
    comparators=table.loc[['simple_h60_cost10','simple_spy_cost10']]
    admissible=comparators.loc[comparators.max_drawdown.ge(-.30)]
    gates=dict(cagr_at_least_30=bool(principal.cagr>=.30),drawdown_within_30=bool(principal.max_drawdown>=-.30),
               beats_admissible_simple_net_cagr=bool(len(admissible)>0 and principal.cagr>admissible.cagr.max()),
               all_fixed_stress_positive_and_drawdown_within_30=bool(stress.total_return.gt(0).all() and stress.max_drawdown.ge(-.30).all()))
    gates['development_passed']=all(gates.values())
    gates['preferred_drawdown_within_20']=bool(principal.max_drawdown>=-.20)
    gates['aspiration_cagr_50']=bool(principal.cagr>=.50)
    gates.update(candidate='stop_on_soft_off_cost10',independent_validation_passed=False,
                 candidate_frozen_for_2026=False,prices_2026_accessed=False,old_0_of_98_unchanged=True,
                 decision='REJECT_NO_2026' if not gates['development_passed'] else 'DEVELOPMENT_ONLY_FREEZE_REVIEW_REQUIRED')
    save(OUT/'GATES.json',gates)
    save(OUT/'RUN_CHECKS.json',checks)
    save(OUT/'TRAINING_RECORD.json',dict(new_fits=0,reused_models=identity['models'],saved_scores_reused=True,ensemble_recalculated=False))
    save(OUT/'completion.json',dict(completed_at_utc=datetime.now(timezone.utc).isoformat(),runs=len(results),
         new_fits=0,reused_models=10,source_sha256=source,all_ledgers_checked=True,prices_2026_accessed=False,
         orders_sent=0,gates=gates))
    print(json.dumps(gates,indent=2),flush=True)


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
