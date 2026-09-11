"""H60 decisions shared with research; raw execution prices stay outside model features.

The runtime state is serializable. Its next-open transition is persisted together
with the execution batch. No calls in this module download, fit, or submit orders.
"""
from copy import deepcopy
from dataclasses import asdict
from datetime import date
import json

import joblib
import numpy as np
import pandas as pd

from panel_config import ROOT
from h60_research_inputs import sha
from h60_execution import digest, ExecutionBlocked
from profit_priority_strategy import (Policy, DrawdownState, scheduled_weights,
    reduction_weights, clip_weights, protection_floor)


def validate_manifest(manifest):
    if manifest['strategy_role'] not in ('engineering_only','frozen_candidate') or manifest['model']['scoring_year']>=2026:
        raise ExecutionBlocked('No approved 2026 model/holdout freeze exists in this version')
    model=manifest['model']
    path=ROOT/model['path']
    if sha(path)!=model['sha256']:
        raise ExecutionBlocked('Frozen H60 model hash differs')
    for file,digest_value in manifest['source_sha256'].items():
        if sha(ROOT/file)!=digest_value:
            raise ExecutionBlocked('Strategy source changed since engineering manifest was sealed: '+file)
    if not model['train_last_label_exit']<f"{model['scoring_year']-1}-01-01" or not model['validation_last_label_exit']<f"{model['scoring_year']}-01-01":
        raise ExecutionBlocked('Annual training/label maturity protocol violated')
    calendar=manifest['calendar']
    if calendar!=sorted(set(calendar)) or not set(manifest['observations']).issubset(calendar):
        raise ExecutionBlocked('Frozen trading calendar invalid')
    return True


def score_feature_snapshot(frame,asof,manifest):
    """Reusable forward signal entry: known X only, frozen annual H60 model only.

    A 2025 engineering model refuses 2026 observations. Providing fresh X does
    not authorize fitting, validation or broker submission.
    """
    validate_manifest(manifest)
    model=manifest['model']; features=model['features']; symbols=manifest['symbols']
    if pd.Timestamp(asof).year!=model['scoring_year'] or asof not in manifest['calendar']:
        raise ExecutionBlocked('Observation is outside the frozen scoring year/calendar')
    if list(frame.columns)!=['Date','symbol',*features] or not frame.Date.eq(asof).all():
        raise ExecutionBlocked('Feature order/date differs or forbidden extra columns were supplied')
    if len(frame)!=len(symbols) or frame.symbol.duplicated().any() or set(frame.symbol)!=set(symbols):
        raise ExecutionBlocked('Incomplete/duplicate cross section')
    x=frame.set_index('symbol').reindex(symbols)[features]
    if not np.isfinite(x.to_numpy()).all():
        raise ExecutionBlocked('Missing or non-finite features')
    bundle=joblib.load(ROOT/model['path'])
    if bundle['features']!=features:
        raise ExecutionBlocked('Feature order inside model differs')
    return pd.Series(bundle['model'].predict(x),index=symbols)


class H60Runtime:
    def __init__(self,manifest,state=None):
        self.manifest=manifest
        self.policy=Policy(**manifest['risk_policy'])
        self.calendar=manifest['calendar']; self.symbols=manifest['symbols']
        self.schedule={self.calendar[self.calendar.index(d)+1]:d for d in manifest['observations']
                       if self.calendar.index(d)+1<len(self.calendar)}
        self.state=deepcopy(state) if state is not None else dict(
            drawdown=asdict(DrawdownState()),pending_cap=None,previous_close={},
            blocked_until={},floors={},seen_fills=[],last_open=None,last_close=None,close_hash=None)

    def apply_fills(self,ledger,day):
        """Use actual broker-filled quantities/prices, never target quantities."""
        for row in ledger['orders'].values():
            order=row['state']; s=order['symbol']
            for eid,fill in order['executions'].items():
                if eid in self.state['seen_fills']:
                    continue
                moment=row.get('fill_times',{}).get(eid)
                if moment is None:
                    raise ExecutionBlocked('Actual execution timestamp required for stock cooldown')
                filled_day=str(pd.Timestamp(moment).tz_convert('America/New_York').date())
                if filled_day>day or filled_day not in self.calendar:
                    raise ExecutionBlocked('Execution is outside the verified calendar/as-of boundary')
                index=self.calendar.index(filled_day)
                if order['side']=='BUY':
                    old=self.state['floors'].get(s)
                    # A planned addition cannot lower an existing protection floor.
                    floor=protection_floor(float('nan') if old is None else old,float(fill['price']),
                                             new_position=old is None,scheduled=True)
                    self.state['floors'][s]=float(floor)
                elif row['reason']=='stock_protection':
                    self.state['blocked_until'][s]=index+self.policy.stock_cooldown
                self.state['seen_fills'].append(eid)

    def next_open(self,day,scores,risk,positions,cash,quotes):
        index=self.calendar.index(day)
        if index<1:
            raise ExecutionBlocked('Need previous completed session')
        observation=self.calendar[index-1]
        if risk['returns'].index[-1]!=pd.Timestamp(observation):
            raise ExecutionBlocked('Risk inputs must physically stop at previous close')
        if self.state['last_open'] and day<=self.state['last_open']:
            raise ExecutionBlocked('Open already committed; replay stored execution batch instead')
        dd=DrawdownState(**self.state['drawdown'])
        scheduled=day in self.schedule
        equity=float(cash)+sum(float(positions[s])*float(quotes[s]['bid']) for s in self.symbols)
        dd.resume(index,equity/float(self.manifest['budget']),bool(risk['trend'].iloc[-1]),scheduled,self.policy)
        w=None; reason=None; reduction=False
        if dd.pending_flat:
            w=pd.Series(0.,index=self.symbols);reason='portfolio_flat';reduction=True
            dd.pending_flat=False;self.state['pending_cap']=None
        elif scheduled and not dd.paused:
            if self.schedule[day]!=observation:
                raise ExecutionBlocked('Schedule does not map to previous completed session')
            eligible=[s for s in self.symbols if index>=self.state['blocked_until'].get(s,-1)]
            w=scheduled_weights(scores,{s for s in self.symbols if float(positions[s])>0},risk,len(risk['returns'])-1,
                self.manifest['groups'],multiplier=dd.multiplier(index),eligible=eligible,policy=self.policy)
            reason='scheduled';dd.pending_half=False;self.state['pending_cap']=None
            for s in self.symbols:
                if float(positions[s])>0 and s in self.state['floors']:
                    self.state['floors'][s]=protection_floor(self.state['floors'][s],float(quotes[s]['bid']),scheduled=True)
        elif (dd.pending_half or self.state['pending_cap'] is not None) and not dd.paused:
            if set(self.state['previous_close'])!=set(self.symbols):
                raise ExecutionBlocked('Previous raw closes missing for risk reduction')
            previous=pd.Series({s:float(positions[s])*self.state['previous_close'][s] for s in self.symbols})
            cap=pd.Series(self.state['pending_cap']) if self.state['pending_cap'] is not None else None
            w=reduction_weights(previous,float(cash),cap,dd.pending_half)
            reason='daily_risk_reduce';reduction=True;dd.pending_half=False;self.state['pending_cap']=None
        self.state['drawdown']=asdict(dd);self.state['last_open']=day
        if w is None:
            return None
        return dict(decision_id=digest([self.manifest['strategy_id'],day,reason]),
                    weights={s:float(w[s]) for s in self.symbols},reduction=reduction,reason=reason,
                    observation=observation,execution_day=day,runtime_after=deepcopy(self.state))

    def close(self,day,positions,cash,raw_closes):
        signature=digest([day,{s:str(v) for s,v in positions.items()},str(cash),raw_closes])
        if self.state['last_close']==day:
            if self.state['close_hash']!=signature:
                raise ExecutionBlocked('Same close date has conflicting account/quote facts')
            return None
        if self.state['last_close'] and day<self.state['last_close']:
            raise ExecutionBlocked('Close clock cannot go backwards')
        if set(raw_closes)!=set(self.symbols) or not all(np.isfinite(v) and v>0 for v in raw_closes.values()):
            raise ExecutionBlocked('Raw close snapshot incomplete')
        index=self.calendar.index(day)
        equity=float(cash)+sum(float(positions[s])*raw_closes[s] for s in self.symbols)
        dd=DrawdownState(**self.state['drawdown'])
        event=dd.observe(index,equity/float(self.manifest['budget']),self.policy)
        if not dd.paused:
            weights=pd.Series({s:float(positions[s])*raw_closes[s]/equity for s in self.symbols})
            clipped=clip_weights(weights,self.manifest['groups'],self.policy)
            if (clipped<weights-1e-8).any():
                self.state['pending_cap']={s:float(clipped[s]) for s in self.symbols}
        for s in self.symbols:
            if float(positions[s])==0:
                self.state['floors'].pop(s,None)
        self.state.update(drawdown=asdict(dd),previous_close=raw_closes,last_close=day,close_hash=signature)
        return event
