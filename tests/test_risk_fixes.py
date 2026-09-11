"""Synthetic gap/regime fixtures: implementation invariants, not historical P&L."""
import unittest
from dataclasses import replace

import numpy as np
import pandas as pd

import profit_priority_strategy as v7
import robust_strategy as v6
from research_backtest import _rebalance, reduce_only
from test_robust_strategy import fixture


class RiskFixTests(unittest.TestCase):
    def test_gap_target_cannot_buy_or_reopen(self):
        old = np.array([12.5, 8., 0.])
        weights = np.array([.125, .12, .05])
        legacy = _rebalance(old, 75., weights, .001)
        self.assertTrue((legacy[2] > 0).any())
        target, cash, change, fee = reduce_only(old, 75., weights, .001)
        self.assertTrue((change <= 0).all())
        self.assertEqual(target[2], 0.)
        self.assertAlmostEqual(cash + target.sum() + fee, 95.5)
        self.assertAlmostEqual(fee, abs(change).sum() * .001)

    def test_both_real_engine_paths_are_sell_only(self):
        for engine in (v6, v7):
            with self.subTest(engine=engine.__name__):
                dates, bars, spy, scores, groups = fixture()
                bars['Close'].iloc[251, 0] *= 1.35
                bars['High'].iloc[251, 0] = bars['Close'].iloc[251, 0] * 1.01
                bars['Open'].iloc[252, 1] *= .6
                bars['Low'].iloc[252, 1] = bars['Open'].iloc[252, 1] * .99
                result = engine.simulate(scores, bars, spy, groups, dates[[250]], dates[256],
                                         stops=False, breaker=False,
                                         policy=replace(engine.Policy(), risk_per_stock=1., risk_total=1., target_vol=1.))
                reduce = result['trades'].query("reason == 'daily_risk_reduce'")
                self.assertGreater(len(reduce), 0)
                self.assertTrue(reduce.signed_units.le(0).all())
                self.assertTrue(result['positions'].loc[dates[252]].le(result['positions'].loc[dates[251]]).all())

    def test_default_spy_formula_and_parameter_are_connected(self):
        dates, bars, _, scores, groups = fixture()
        spy = pd.Series(100 + np.sin(np.arange(len(dates))) * 3, index=dates)
        expected = (.15 / (spy.pct_change(fill_method=None).rolling(20).std(ddof=1) * np.sqrt(252))).clip(upper=1)
        for engine in (v6, v7):
            pd.testing.assert_series_equal(engine.risk_inputs(bars, spy)['spy_exposure'], expected)
            outputs = [engine.simulate(scores, bars, spy, groups, dates[[250]], dates[256],
                        mode='incumbent', stops=False, breaker=False,
                        policy=replace(engine.Policy(), target_vol=value)) for value in (.05, .10)]
            first, second = [r['targets'].iloc[0][['AAPL','MSFT']].astype(float) for r in outputs]
            np.testing.assert_allclose(second, first * 2)

    def test_soft_off_does_not_disable_hard_pause_or_recovery(self):
        p = replace(v7.Policy(), soft_enabled=False)
        state = v7.DrawdownState()
        self.assertIsNone(state.observe(1, .85, p))
        self.assertEqual(state.observe(2, .79, p), 'portfolio_halt')
        self.assertTrue(state.pending_flat)
        state.pending_flat = False
        self.assertFalse(state.resume(23, .79, False, True, p))
        self.assertTrue(state.resume(23, .79, True, True, p))
        self.assertEqual(state.multiplier(24), .5)
        self.assertEqual(state.multiplier(33), 1.)


if __name__ == '__main__':
    unittest.main()
