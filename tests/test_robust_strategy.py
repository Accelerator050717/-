"""全部为虚构行情/故障场景，不是实际成交或收益证据。"""
import unittest
from dataclasses import replace

import numpy as np
import pandas as pd

from robust_strategy import (Policy, DrawdownState, allocate, clip_weights,
                             stop_fill, simulate, risk_inputs)
from research_backtest import run_backtest


def fixture():
    dates = pd.bdate_range("2020-01-01", periods=290)
    base = 100 + np.arange(290)*.01 + np.sin(np.arange(290)*.3)
    close = pd.DataFrame({"AAPL":base, "MSFT":base*1.5}, index=dates)
    bars = {"Open":close*.999, "High":close*1.015, "Low":close*.985, "Close":close}
    spy = pd.Series(100+np.arange(290)*.1+np.sin(np.arange(290))*.1,index=dates)
    scores = pd.DataFrame({"AAPL":1.,"MSFT":0.},index=dates[250:281])
    groups = {"AAPL":"tech","MSFT":"tech"}
    return dates,bars,spy,scores,groups


class RobustStrategyTests(unittest.TestCase):
    def test_gap_does_not_fill_at_stop(self):
        price,reason = stop_fill(70.,65.,90.,10)
        self.assertEqual(reason,"stop_gap")
        self.assertAlmostEqual(price,69.93)
        self.assertLess(price,90.)

    def test_intraday_trigger_and_no_touch(self):
        self.assertEqual(stop_fill(100.,91.,90.,10),(None,None))
        price,reason = stop_fill(100.,85.,90.,10)
        self.assertEqual(reason,"stop_intraday")
        self.assertAlmostEqual(price,89.91)

    def test_caps_and_risk_budget(self):
        names = ["AAPL","MSFT","NVDA","AMZN","GOOGL","META","XOM","CVX","COP","PG"]
        groups = dict(zip(names,["tech"]*3+["retail"]+["comm"]*2+["energy"]*3+["staple"]))
        scores = pd.Series(np.arange(10),index=names)
        distances = pd.Series(.12,index=names)
        rng = np.random.default_rng(7)
        history = pd.DataFrame(rng.normal(0,.025,(60,10)),columns=names)
        w,_ = allocate(scores,set(),distances,history.std(),history,groups,True)
        self.assertLessEqual(w.max(),.10+1e-12)
        self.assertLessEqual(w[names[:6]].sum(),.35+1e-12)
        self.assertLessEqual((w*distances).sum(),.05+1e-12)
        self.assertTrue((w*distances <= .0075+1e-12).all())
        for group in set(groups.values()):
            self.assertLessEqual(w[[s for s in names if groups[s]==group]].sum(),.25+1e-12)

    def test_retain_buffer_does_not_exceed_ten(self):
        names = [f"S{i:02}" for i in range(20)]
        score = pd.Series(np.arange(20,0,-1),index=names)
        rng = np.random.default_rng(8)
        history = pd.DataFrame(rng.normal(0,.01,(60,20)),columns=names)
        w,_ = allocate(score,set(names[10:15]),pd.Series(.05,index=names),history.std(),
                       history,{s:s for s in names},True)
        self.assertEqual(int(w.gt(0).sum()),10)
        self.assertTrue(w.loc[names[10:15]].gt(0).all())

    def test_circuit_breaker_and_conditional_recovery(self):
        state = DrawdownState()
        self.assertEqual(state.observe(2,.91,Policy()),"portfolio_half")
        self.assertEqual(state.multiplier(3),.5)
        self.assertEqual(state.observe(4,.85,Policy()),"portfolio_halt")
        self.assertEqual(state.multiplier(5),0.)
        self.assertFalse(state.resume(24,.84,True,True,Policy()))
        self.assertFalse(state.resume(25,.84,False,True,Policy()))
        self.assertFalse(state.resume(25,.84,True,False,Policy()))
        self.assertTrue(state.resume(25,.84,True,True,Policy()))
        self.assertEqual(state.episode_peak,.84)
        self.assertEqual(state.multiplier(26),.5)
        self.assertEqual(state.multiplier(35),1.)

    def test_old_equal_open_equity_reproduces(self):
        dates,bars,spy,scores,groups = fixture()
        old = run_backtest(scores,bars["Open"],spy,start=dates[250],end=dates[277],top_k=None)
        result = simulate(scores,bars,spy,groups,old["periods"].observation_date,
                          old["daily_equity"].index[-1],mode="equal",stops=False,breaker=False)
        np.testing.assert_allclose(result["daily"].open_equity,old["daily_equity"].equity,rtol=1e-12,atol=1e-12)

    def test_missing_price_rejected(self):
        dates,bars,spy,scores,groups = fixture()
        bars["Low"].iloc[251,0] = np.nan
        with self.assertRaises(ValueError):
            simulate(scores,bars,spy,groups,dates[[250]],dates[256])

    def test_same_day_high_cannot_raise_same_day_stop(self):
        dates,bars,spy,scores,groups = fixture()
        bars["High"].iloc[251] *= 2
        result = simulate(scores,bars,spy,groups,dates[[250]],dates[254],breaker=False)
        self.assertFalse(result["trades"].reason.str.startswith("stop_").any())

    def test_future_rows_do_not_change_past_trades(self):
        dates,bars,spy,scores,groups = fixture()
        full = simulate(scores,bars,spy,groups,dates[[250,255,260,265,270]],dates[276])
        prefix = simulate(scores.loc[:dates[266]],{k:v.loc[:dates[266]] for k,v in bars.items()},
                          spy.loc[:dates[266]],groups,dates[[250,255,260]],dates[266])
        pd.testing.assert_frame_equal(full["daily"].loc[:dates[265]],prefix["daily"].loc[:dates[265]],check_exact=True)

    def test_ledger_and_no_borrowing(self):
        dates,bars,spy,scores,groups = fixture()
        bars["Open"].iloc[253] *= .7
        bars["Close"].iloc[253] *= .7
        bars["Low"].iloc[253] *= .69
        result = simulate(scores,bars,spy,groups,dates[[250,255,260]],dates[266])
        cash = 1 + result["trades"].cash_change.sum()
        self.assertAlmostEqual(cash,result["daily"].cash.iloc[-1])
        self.assertTrue(result["daily"].cash.ge(-1e-12).all())
        self.assertTrue(result["positions"].ge(-1e-12).all().all())
        self.assertEqual(result["positions"].iloc[-1].sum(),0.)
        self.assertGreater(result["metrics"]["gap_stops"],0)

    def test_delayed_stop_uses_next_open(self):
        dates,bars,spy,scores,groups = fixture()
        bars["Low"].iloc[252] *= .7
        bars["Open"].iloc[253] *= .8
        bars["Close"].iloc[253] *= .8
        bars["Low"].iloc[253] *= .79
        result = simulate(scores,bars,spy,groups,dates[[250]],dates[256],delayed_stops=True)
        rows = result["trades"].query("reason == 'stop_delayed'")
        self.assertGreater(len(rows),0)
        self.assertTrue(rows.Date.eq(dates[253]).all())
        np.testing.assert_allclose(rows.proxy_fill,rows.session_open*.999)

    def test_risk_inputs_prefix(self):
        dates,bars,spy,_,_ = fixture()
        full = risk_inputs(bars,spy)
        prefix = risk_inputs({k:v.loc[:dates[265]] for k,v in bars.items()},spy.loc[:dates[265]])
        for key in full:
            if isinstance(full[key],pd.Series):
                pd.testing.assert_series_equal(full[key].loc[:dates[265]],prefix[key],check_exact=True)
            else:
                pd.testing.assert_frame_equal(full[key].loc[:dates[265]],prefix[key],check_exact=True)


if __name__ == "__main__":
    unittest.main()
