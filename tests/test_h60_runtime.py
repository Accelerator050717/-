"""Synthetic parity checks for shared research/execution decisions."""
from dataclasses import asdict, replace
import unittest

import numpy as np
import pandas as pd

import profit_priority_strategy as research
from h60_strategy_runtime import H60Runtime
from h60_execution import ExecutionBlocked
from test_robust_strategy import fixture


class RuntimeTests(unittest.TestCase):
    def test_scheduled_targets_equal_research_engine_and_prefix_only(self):
        dates,bars,spy,scores,groups=fixture()
        policy=replace(research.Policy(),soft_enabled=False)
        manifest=dict(calendar=[str(d.date()) for d in dates],observations=[str(dates[250].date())],
                      risk_policy=asdict(policy),symbols=list(scores.columns),groups=groups,
                      budget='10000',strategy_id='synthetic')
        runtime=H60Runtime(manifest)
        obs=str(dates[250].date()); day=str(dates[251].date())
        risk=research.risk_inputs({k:v.loc[:obs] for k,v in bars.items()},spy.loc[:obs])
        positions={s:0 for s in scores.columns};quotes={s:dict(bid='100',ask='100') for s in scores.columns}
        decision=runtime.next_open(day,scores.loc[obs],risk,positions,10000,quotes)
        actual=research.simulate(scores,bars,spy,groups,dates[[250]],dates[256],policy=policy)['targets'].iloc[0]
        np.testing.assert_array_equal(list(decision['weights'].values()),actual[scores.columns].astype(float))
        with self.assertRaises(ExecutionBlocked):
            runtime.next_open(day,scores.loc[obs],risk,positions,10000,quotes)
        other=H60Runtime(manifest)
        future=research.risk_inputs(bars,spy)
        with self.assertRaises(ExecutionBlocked):
            other.next_open(day,scores.loc[obs],future,positions,10000,quotes)

    def test_same_close_is_idempotent_but_conflicting_fact_is_rejected(self):
        dates,bars,spy,scores,groups=fixture()
        manifest=dict(calendar=[str(d.date()) for d in dates],observations=[str(dates[250].date())],
                      risk_policy=asdict(replace(research.Policy(),soft_enabled=False)),symbols=list(scores.columns),
                      groups=groups,budget='10000',strategy_id='synthetic')
        runtime=H60Runtime(manifest)
        positions={s:'0' for s in scores.columns};closes={s:100. for s in scores.columns}
        day=str(dates[251].date())
        self.assertIsNone(runtime.close(day,positions,'10000',closes))
        self.assertIsNone(runtime.close(day,positions,'10000',closes))
        with self.assertRaises(ExecutionBlocked):
            runtime.close(day,positions,'9000',closes)


if __name__=='__main__':
    unittest.main()
