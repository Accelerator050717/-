"""Synthetic metric fixtures; never replay prices or fit a model."""
import importlib
import unittest
import pandas as pd

evaluation = importlib.import_module('58_evaluate_continuous_risk')


def table():
    rows = []
    for variant in ('original','global'):
        for scenario in evaluation.SCENARIOS:
            rows.append(dict(variant=variant,configuration='protected',scenario=scenario,
                cagr=.32 if variant=='original' else .30,
                max_drawdown=-.24 if variant=='original' else -.21))
    return pd.DataFrame(rows)


class GatesTests(unittest.TestCase):
    def test_risk_value_and_profit_goal_are_separate(self):
        sample=table();sample.loc[sample.variant.eq('global'),'cagr']=.29
        sample.loc[sample.variant.eq('original'),'cagr']=.31
        result=evaluation.gates(sample)
        self.assertTrue(result['risk_value_gate_passed'])
        self.assertFalse(result['protected_numerical_objectives_met'])
        self.assertFalse(result['independent_validation_passed'])

    def test_drawdown_or_cost_failure_cannot_be_hidden(self):
        for column,value in (('cagr',.299),('max_drawdown',-.22)):
            sample=table()
            sample.loc[sample.variant.eq('global') & sample.scenario.eq('cost10'),column]=value
            self.assertFalse(evaluation.gates(sample)['risk_value_gate_passed'])

    def test_all_six_pressures_are_required_and_can_reject(self):
        sample=table()
        with self.assertRaises(ValueError):
            evaluation.gates(sample.iloc[:-1])
        sample.loc[sample.variant.eq('global') & sample.scenario.eq('phase4'),'max_drawdown']=-.265
        self.assertFalse(evaluation.gates(sample)['risk_value_gate_passed'])
        sample.loc[sample.variant.eq('global') & sample.scenario.eq('phase4'),'max_drawdown']=-.301
        self.assertFalse(evaluation.gates(sample)['risk_value_conditions']['all_six_stress_drawdowns_within_30'])

    def test_exact_registered_boundaries_are_accepted_but_never_independent(self):
        result=evaluation.gates(table())
        self.assertTrue(result['risk_value_gate_passed'])
        self.assertTrue(result['protected_numerical_objectives_met'])
        self.assertFalse(result['prices_2026_accessed'])
        self.assertFalse(result['model_promoted_to_lean_or_paper'])


if __name__=='__main__':
    unittest.main()
