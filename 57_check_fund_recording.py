"""Record-only historical identity check before freezing the v13 risk experiment."""
from dataclasses import replace
from datetime import datetime,timezone
import importlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

from panel_config import ROOT
from h60_research_inputs import load_inputs,save,sha
import research_features as features
from profit_priority_strategy import Policy
from h60_global_research import simulate
from strategy_fund_journal import FundJournal

previous=importlib.import_module('51_evaluate_signal_objectives')
audit=importlib.import_module('42_evaluate_h60_risk_fixes').audit
OUT=ROOT/'data/experiments/continuous_fund_risk_v13'


def main():
    proof=OUT/'RECORD_ONLY_CHECK.json'
    sources={name:sha(ROOT/name) for name in ('57_check_fund_recording.py','h60_global_research.py',
              'h60_global_control.py','strategy_fund_journal.py','profit_priority_strategy.py','research_backtest.py')}
    if proof.exists():
        saved=json.loads(proof.read_text(encoding='utf-8'))
        if saved['source_sha256']!=sources:
            raise ValueError('Record-only source identity changed; retain previous evidence and review')
        for row in saved['files']:
            if sha(ROOT/row['path'])!=row['sha256']:
                raise ValueError('Record-only artifact changed: '+row['path'])
        print('Existing record-only proof verified, no repeat replay.')
        return
    old=previous.verify_old_manifest()
    bars,_,spy,scores,obs,final,identity=load_inputs()
    save(OUT/'INPUT_IDENTITY.json',identity)
    checks=[];files=[]
    for configuration in ('protected','simple_h60'):
        folder=OUT/'record_only_final'/configuration;folder.mkdir(parents=True,exist_ok=True)
        path=folder/'fund.sqlite'
        scope_id='v13-record-only-'+configuration
        kwargs=dict(mode='risk' if configuration=='protected' else 'simple_h60',stops=configuration=='protected',
                    policy=replace(Policy(),soft_enabled=False),global_control=False)
        new=simulate(scores,bars,spy,features.SECTOR_PROXY,obs,final,**kwargs,journal_path=path,
             scope_id=scope_id,create_journal=not path.exists() and not Path(str(path)+'.scope.json').exists(),
             model_versions={m['year']:m['sha256'] for m in identity['models']})
        old_case='stop_on_soft_off_cost10' if configuration=='protected' else 'simple_h60_cost10'
        original=previous.read_old(old_case)
        comparison={}
        for key in previous.TABLE_KEYS:
            actual=new[key][original[key].columns].copy()
            # Frozen CSVs encode empty text as an empty field, read back as NA.
            # Normalize this representation only; never round numerical values.
            for column in actual:
                if pd.api.types.is_string_dtype(actual[column].dtype) or actual[column].dtype==object:
                    actual[column]=actual[column].replace('',pd.NA)
            pd.testing.assert_frame_equal(actual,original[key],check_exact=True,check_dtype=False)
            comparison[key]=dict(rows=len(original[key]),exact_values=True,empty_csv_text_normalized=True)
        check=audit(new,bars)
        np.testing.assert_allclose(new['daily'].cumulative_fund_drawdown,original['daily'].drawdown,rtol=0,atol=1e-14)
        journal=FundJournal(path,dict(scope_id=scope_id,currency='USD',owner='isolated_h60_research_capital',universe=list(scores.columns)))
        chain=journal.verify();state=journal.read();journal.close()
        save(folder/'final_state.json',state)
        checks.append(dict(configuration=configuration,original_case=old_case,**check,comparison=comparison,
                           original_cagr=original['metrics']['cagr'],original_max_drawdown=original['metrics']['max_drawdown'],
                           journal_chain=chain,scope_id=scope_id,model_versions=len(state['model_history']),
                           current_equity=state['equity'],unit_nav=state['unit_nav'],high_water_nav=state['high_water_nav'],
                           max_drawdown=state['max_drawdown']))
        for p in folder.iterdir():
            if p.is_file():
                files.append(dict(path=p.relative_to(ROOT).as_posix(),size_bytes=p.stat().st_size,sha256=sha(p)))
        print(configuration+': original targets/trades/positions/cash/NAV exactly unchanged; persisted event chain verified.',flush=True)
    save(proof,dict(completed_at_utc=datetime.now(timezone.utc).isoformat(),source_sha256=sources,
                    original_manifest=old,checks=checks,files=files,record_only_historical_replays=2,
                    controlled_historical_replays=0,new_fits=0,prices_2026_accessed=False,orders_sent=0))


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
