"""Independent boundary checks using explicitly fictitious prices and model IDs."""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from h60_global_research import simulate
from profit_priority_strategy import Policy


def fixture():
    dates = pd.bdate_range("2019-03-01", periods=210)
    close = pd.DataFrame({"AAA": np.full(len(dates), 100.)}, index=dates)
    bars = {key: close.copy() for key in ("Open", "High", "Low", "Close")}
    spy = pd.Series(100. + np.arange(len(dates)) * .1, index=dates)
    scores = pd.DataFrame({"AAA": np.ones(len(dates))}, index=dates)
    return dates, bars, spy, scores, {"AAA": "fictional-group"}


def repair_range(bars):
    bars["Low"] = np.minimum(bars["Open"], bars["Close"])
    bars["High"] = np.maximum(bars["Open"], bars["Close"])


class GlobalBoundaryTests(unittest.TestCase):
    def options(self):
        # A one-asset fictional full-allocation diagnostic makes arithmetic visible.
        return dict(mode="equal", stops=False, breaker=False, global_control=True,
                    cost_bps=10, policy=replace(Policy(), soft_enabled=False))

    def test_upward_opening_gap_reduction_caps_actual_open_exposure(self):
        dates, bars, spy, scores, groups = fixture()
        bars["Close"].iloc[202, 0] = 88.
        bars["Open"].iloc[203:, 0] = 132.
        bars["Close"].iloc[203:, 0] = 132.
        repair_range(bars)
        result = simulate(scores, bars, spy, groups, dates[[200]], dates[206], **self.options())
        self.assertEqual(result["daily"].loc[dates[202], "global_mode"], "REDUCED")
        actual = result["daily"].loc[dates[203]]
        self.assertLessEqual(actual.invested / actual.open_equity, .4 + 1e-12)
        change = result["trades"].loc[result["trades"].Date.eq(dates[203])]
        self.assertTrue(change.reason.eq("global_risk_reduce").all())
        self.assertTrue(change.signed_units.lt(0).all())
        self.assertEqual(len(change), 1)
        self.assertLess(result["positions"].loc[dates[203], "AAA"],
                        result["positions"].loc[dates[202], "AAA"])

    def test_final_liquidation_fee_is_observed_and_can_enter_review_lock(self):
        dates, bars, spy, scores, groups = fixture()
        # Entry spends 1/(1+.001). Exit value before costs=.7505; after=.7497495.
        bars["Open"].iloc[203, 0] = 100 * 1.001 * .7505
        repair_range(bars)
        with tempfile.TemporaryDirectory() as directory:
            result = simulate(scores, bars, spy, groups, dates[[200]], dates[203],
                journal_path=Path(directory) / "fund.sqlite", scope_id="fictional-final-fee",
                create_journal=True, **self.options())
        final = result["daily"].iloc[-1]
        self.assertAlmostEqual(final.equity, .7505 * .999, places=12)
        self.assertEqual(final.global_mode, "REVIEW_LOCKED")
        self.assertFalse(result["fund_state"]["risk_state"]["pending_flat"])
        self.assertTrue(result["positions"].iloc[-1].eq(0).all())
        lock = result["events"].loc[result["events"].event.eq("global_review_lock")]
        self.assertEqual(len(lock), 1)
        self.assertEqual(lock.iloc[0].Date, dates[203])
        self.assertAlmostEqual(result["fund_state"]["max_drawdown"], final.equity - 1)

    def test_model_metadata_handoff_keeps_risk_scope_and_loss_after_restart(self):
        dates, bars, spy, scores, groups = fixture()
        bars["Open"].iloc[203:, 0] = 88.
        bars["Close"].iloc[202:, 0] = 88.
        repair_range(bars)
        args = (scores, bars, spy, groups, dates[[200]], dates[206])
        years = set(dates.year)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fund.sqlite"
            partial = simulate(*args, journal_path=path, scope_id="same-fictional-capital",
                create_journal=True, stop_after_session=2,
                model_versions={y: "fictional-model-A" for y in years}, run_id="process-1",
                **self.options())
            before = partial["fund_state"]
            result = simulate(*args, journal_path=path, scope_id="same-fictional-capital",
                model_versions={y: "fictional-model-B" for y in years}, run_id="process-2",
                **self.options())
            after = result["fund_state"]
        self.assertEqual(before["scope"], after["scope"])
        self.assertEqual(after["fund_shares"], before["fund_shares"])
        self.assertEqual(after["high_water_nav"], before["high_water_nav"])
        self.assertLessEqual(after["max_drawdown"], before["max_drawdown"])
        self.assertEqual([row["version"] for row in after["model_history"]],
                         ["fictional-model-A", "fictional-model-B"])
        self.assertEqual(after["valuation_cursor"], len(result["daily"]))
        self.assertEqual(result["daily"].iloc[2].global_mode, "REDUCED")


if __name__ == "__main__":
    unittest.main()
