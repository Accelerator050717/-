"""Freeze v13 once, after completed foundation checks, before any risk replay."""
from dataclasses import asdict, replace
from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from h60_research_inputs import sha,save
from h60_global_control import GlobalPolicy
from profit_priority_strategy import Policy

OUT=ROOT/'data/experiments/continuous_fund_risk_v13'


def main():
    if (OUT/'plan.json').exists():
        plan=json.loads((OUT/'plan.json').read_text(encoding='utf-8'))
        if plan['design_sha256']!=sha(OUT/'PLAN.md'):
            raise ValueError('Frozen PLAN changed; do not overwrite original registration')
        print('Plan already frozen; preserved.')
        return
    if (OUT/'EVALUATION_IDENTITY.json').exists() or (OUT/'backtests').exists():
        raise ValueError('Cannot preregister after starting the controlled experiment')
    proof=OUT/'RECORD_ONLY_CHECK.json'
    recording=json.loads(proof.read_text(encoding='utf-8'))
    engineering=OUT/'engineering/final_verification/CONTINUITY_REPORT.json'
    assert recording['record_only_historical_replays']==2
    assert json.loads(engineering.read_text(encoding='utf-8'))['equality'] is True
    save(OUT/'plan.json',dict(registered_at_utc=datetime.now(timezone.utc).isoformat(),
        design_sha256=sha(OUT/'PLAN.md'),record_only_check_sha256=sha(proof),
        engineering_check_sha256=sha(engineering),
        input_identity=json.loads((OUT/'INPUT_IDENTITY.json').read_text(encoding='utf-8')),
        policy=asdict(replace(Policy(),soft_enabled=False)),risk_policy=asdict(GlobalPolicy()),
        scenarios=list(importlib.import_module('51_evaluate_signal_objectives').SCENARIOS),
        cagr_floor=.30,cagr_aspiration=.50,drawdown_ceiling=.30,preferred_drawdown=.20,
        new_fits=0,new_runs=14,deadline_utc='2026-09-22T15:56:34+00:00'))
    print('Single v13 design frozen after completed foundation evidence.')


if __name__=='__main__':
    main()
