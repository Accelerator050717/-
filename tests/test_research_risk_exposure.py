"""虚构价格检验现金和股票目标权重，不代表真实收益。"""
import unittest
import numpy as np
import pandas as pd
from research_backtest import run_backtest


class ExposureBacktestTests(unittest.TestCase):
    def setUp(self):
        self.dates = pd.bdate_range("2020-01-01",periods=13)
        self.prices = pd.DataFrame({"FICTITIOUS":np.arange(100.0,113.0)},index=self.dates)
        self.scores = self.prices*0
        self.spy = self.prices.FICTITIOUS

    def run_case(self,exposure=None,cost=0):
        return run_backtest(self.scores,self.prices,self.spy,end="2020-02-01",top_k=1,cost_bps=cost,
                            gross_exposure=None if exposure is None else pd.Series(exposure,index=self.dates))

    def test_default_and_explicit_full_exposure_identical(self):
        a,b = self.run_case(None,10),self.run_case(1.0,10)
        for key in ("daily_equity","periods","trades"):
            pd.testing.assert_frame_equal(a[key],b[key],check_exact=True)
        self.assertEqual(a["metrics"],b["metrics"])

    def test_all_cash_never_trades_and_nav_stays_one(self):
        result = self.run_case(0.0,10)
        self.assertTrue(result["trades"].empty)
        np.testing.assert_array_equal(result["daily_equity"].equity,1.0)
        self.assertEqual(result["metrics"]["total_cost"],0)
        self.assertTrue(result["periods"].n_holdings.eq(0).all())

    def test_half_exposure_manual_returns(self):
        result = self.run_case(0.5)
        expected = (0.5+0.5*106/101)*(0.5+0.5*111/106)
        self.assertAlmostEqual(result["metrics"]["final_equity"],expected)
        self.assertTrue(result["daily_equity"].cash.ge(0).all())

    def test_exposure_uses_observation_not_entry_value(self):
        exposure = pd.Series(0.0,index=self.dates)
        exposure.iloc[0] = 1.0
        result = run_backtest(self.scores,self.prices,self.spy,end="2020-02-01",top_k=1,cost_bps=0,gross_exposure=exposure)
        self.assertAlmostEqual(result["metrics"]["final_equity"],106/101)

    def test_bad_or_misaligned_exposure_rejected(self):
        for value in (-0.1,1.1,np.nan,np.inf):
            with self.assertRaises(ValueError):
                self.run_case(value)
        with self.assertRaises(ValueError):
            run_backtest(self.scores,self.prices,self.spy,gross_exposure=pd.Series(1.0,index=self.dates[:-1]))


if __name__ == "__main__":
    unittest.main()
