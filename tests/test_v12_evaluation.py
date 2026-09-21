"""Small fictitious fixtures for v12 reporting and paired acceptance logic."""
import importlib
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

evaluation = importlib.import_module('54_evaluate_training_cutoff')


def gate_fixture(b_cagr=.25, b_dd=-.22):
    rows = []
    for config in evaluation.CONFIGURATIONS:
        for protocol in ('A', 'B'):
            for scenario in evaluation.SCENARIOS:
                rows.append(dict(configuration=config, protocol=protocol, scenario=scenario,
                                 cagr=.15 if protocol == 'A' else b_cagr,
                                 max_drawdown=-.20 if protocol == 'A' else b_dd,
                                 total_return=1.))
    rows.append(dict(configuration='simple_spy', protocol='control', scenario='cost10',
                     cagr=.10, max_drawdown=-.18, total_return=1.))
    return pd.DataFrame(rows)


class EvaluationTests(unittest.TestCase):
    def test_improvement_does_not_lower_thirty_percent_goal(self):
        result = evaluation.gates(gate_fixture())
        self.assertTrue(result['research_improvement'])
        self.assertFalse(result['protected_numerical_objectives_met'])
        self.assertFalse(result['development_gate_passed'])
        self.assertFalse(result['prices_2026_accessed'])

    def test_stress_drawdown_rejects_higher_profit(self):
        table = gate_fixture(b_cagr=.35)
        mask = table.protocol.eq('B') & table.configuration.eq('protected') & table.scenario.eq('phase4')
        table.loc[mask, 'max_drawdown'] = -.31
        result = evaluation.gates(table)
        self.assertTrue(result['protected_numerical_objectives_met'])
        self.assertFalse(result['research_improvement'])
        self.assertFalse(result['development_gate_passed'])

    def test_both_costs_must_improve(self):
        table = gate_fixture(b_cagr=.35)
        mask = table.protocol.eq('B') & table.configuration.eq('protected') & table.scenario.eq('cost20')
        table.loc[mask, 'cagr'] = .14
        self.assertFalse(evaluation.gates(table)['research_improvement'])

    def test_development_gate_requires_beating_admissible_simple_controls(self):
        table = gate_fixture(b_cagr=.35)
        result = evaluation.gates(table)
        self.assertTrue(result['protected_numerical_objectives_met'])
        self.assertFalse(result['beats_admissible_same_budget_simple_cagr'])
        self.assertFalse(result['development_gate_passed'])
        mask = table.configuration.eq('simple_h60') & table.protocol.eq('B')
        table.loc[mask, 'cagr'] = .32
        self.assertTrue(evaluation.gates(table)['development_gate_passed'])

    def test_global_drawdown_is_not_reset_by_episode_peak(self):
        # Entirely fictitious: two 20% losses around a recovery reset => 36% account loss.
        daily = pd.DataFrame(dict(equity=[1., .8, .8, .64], episode_peak=[1., 1., .8, .8],
                                  drawdown=[0., -.2, -.2, -.36]))
        result = evaluation.full_history_check(dict(daily=daily, metrics=dict(max_drawdown=-.36)))
        self.assertTrue(result['full_history_budget_exceeded'])
        self.assertAlmostEqual(result['minimum_recorded_episode_drawdown'], -.2)
        daily['drawdown'] = daily.equity / daily.episode_peak - 1
        with self.assertRaises(AssertionError):
            evaluation.full_history_check(dict(daily=daily, metrics=dict(max_drawdown=-.2)))

    def test_rank_ic_uses_common_maturity_without_deleting_prediction_tail(self):
        dates = pd.to_datetime(['2024-01-02', '2025-12-22'])
        scores = pd.DataFrame(dict(Date=[dates[0]] * 3 + [dates[1]] * 3,
                                   symbol=['X', 'Y', 'Z'] * 2,
                                   A=[0., 1., 2., 0., 1., 2.], B=[2., 1., 0., 2., 1., 0.]))
        labels = scores[['Date', 'symbol']].copy()
        labels['rank_60'] = [0., .5, 1., np.nan, np.nan, np.nan]
        labels['exit_60'] = pd.to_datetime(['2024-04-01'] * 3 + [None] * 3)
        with patch.object(evaluation, 'SYMBOLS', ['X', 'Y', 'Z']):
            daily, summary, annual = evaluation.signal_diagnostics(scores, labels)
        self.assertEqual(len(scores), 6)
        self.assertEqual(len(daily), 2)
        self.assertEqual(summary.unmatured_prediction_dates_retained.tolist(), [1, 1])
        self.assertAlmostEqual(summary.loc[summary.protocol.eq('A'), 'mean_rank_ic'].iloc[0], 1.)
        self.assertAlmostEqual(summary.loc[summary.protocol.eq('B'), 'mean_rank_ic'].iloc[0], -1.)
        self.assertEqual(set(annual.year), {2024})

    def test_annual_turnover_uses_previous_account_nav_and_fees_include_slippage(self):
        dates = pd.to_datetime(['2024-12-31', '2025-01-02'])
        daily = pd.DataFrame(dict(equity=[2., 1.8], episode_peak=[2., 2.],
                                  drawdown=[0., -.1], gross=[.5, .5], **{'return': [1., -.1]}), index=dates)
        trades = pd.DataFrame(dict(Date=dates, signed_notional=[1., -.9], signed_units=[1., -1.],
                                   proxy_fill=[1., .9], stop_extra_bps=[0, 100],
                                   fee=[.01, .02], reason=['scheduled', 'stop_gap']))
        rows = evaluation.annual_rows('fixture', dict(daily=daily, trades=trades, events=pd.DataFrame()))
        self.assertAlmostEqual(rows[1]['turnover_two_way'], .9 / 2.)
        self.assertAlmostEqual(rows[1]['return_net'], -.1)
        self.assertAlmostEqual(rows[1]['stop_slippage_per_initial_nav'], .9 * (1 / .99 - 1))
        self.assertAlmostEqual(rows[1]['explicit_cost_per_year_start_nav'], (.02 + .9 * (1 / .99 - 1)) / 2.)


if __name__ == '__main__':
    unittest.main()
