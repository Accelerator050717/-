"""v7虚构场景：保护阈值更新频率、软降仓恢复、日期与现金账本。"""
import unittest

import numpy as np
import pandas as pd

from test_robust_strategy import fixture
import profit_priority_strategy as v7


class ProfitPriorityTests(unittest.TestCase):
    def test_soft_risk_restores_after_recovery(self):
        state = v7.DrawdownState()
        self.assertEqual(state.observe(2,.89,v7.Policy()),"portfolio_half")
        self.assertEqual(state.multiplier(3),.5)
        self.assertEqual(state.observe(4,.96,v7.Policy()),"portfolio_restore")
        self.assertEqual(state.multiplier(5),1.)
        self.assertFalse(state.pending_half)

    def test_fixed_stop_ignores_daily_peak_and_atr(self):
        dates,bars,spy,scores,groups = fixture()
        entry = bars["Open"].iloc[251,0]
        bars["High"].iloc[251,0] = entry*1.25
        bars["Close"].iloc[251,0] = entry*1.20
        bars["High"].iloc[252,0] = entry*1.21
        bars["Low"].iloc[252,0] = entry*.90
        result = v7.simulate(scores,bars,spy,groups,dates[[250]],dates[254],breaker=False)
        stopped = result["trades"].query("symbol == 'AAPL' and reason.str.startswith('stop_')",engine="python")
        self.assertEqual(len(stopped),0)

    def test_fixed_stop_and_cash_reconcile(self):
        dates,bars,spy,scores,groups = fixture()
        entry = bars["Open"].iloc[251,0]
        bars["Low"].iloc[252,0] = entry*.80
        result = v7.simulate(scores,bars,spy,groups,dates[[250]],dates[256],breaker=False)
        stopped = result["trades"].query("reason == 'stop_intraday' and symbol == 'AAPL'")
        self.assertEqual(len(stopped),1)
        self.assertAlmostEqual(stopped.iloc[0].stop_threshold,entry*.85)
        self.assertAlmostEqual(stopped.iloc[0].proxy_fill,entry*.85*.999)
        self.assertAlmostEqual(1+result["trades"].cash_change.sum(),result["daily"].cash.iloc[-1])

    def test_no_same_day_reentry_after_gap(self):
        dates,bars,spy,scores,groups = fixture()
        bars["Open"].iloc[256] *= .7
        bars["Close"].iloc[256] *= .7
        bars["Low"].iloc[256] *= .69
        result = v7.simulate(scores,bars,spy,groups,dates[[250,255,260]],dates[266])
        trades = result["trades"]
        same = trades.loc[trades.Date.eq(dates[256])]
        self.assertTrue(same.signed_units.lt(0).all())
        self.assertTrue(result["positions"].loc[dates[256]].eq(0).all())

    def test_prefix_does_not_use_future(self):
        dates,bars,spy,scores,groups = fixture()
        full = v7.simulate(scores,bars,spy,groups,dates[[250,255,260,265,270]],dates[276])
        prior = v7.simulate(scores.loc[:dates[266]],{k:v.loc[:dates[266]] for k,v in bars.items()},
                            spy.loc[:dates[266]],groups,dates[[250,255,260]],dates[266])
        pd.testing.assert_frame_equal(full["daily"].loc[:dates[265]],prior["daily"].loc[:dates[265]],check_exact=True)


if __name__=="__main__":
    unittest.main()
