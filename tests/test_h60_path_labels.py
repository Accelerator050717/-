"""全部虚构 OHLC；检验路径标签的时点、现金期、费用和成熟边界。"""
import unittest

import numpy as np
import pandas as pd

from h60_path_labels import build_path_labels


def fixture(count=8, symbols=("AAA", "BBB")):
    dates = pd.bdate_range("2020-01-02", periods=count)
    close = pd.DataFrame(100., index=dates, columns=list(symbols))
    bars = {"Open": close.copy(), "High": close * 1.01,
            "Low": close * .99, "Close": close.copy()}
    spy_close = pd.DataFrame(200., index=dates, columns=["SPY"])
    spy = {"Open": spy_close.copy(), "High": spy_close * 1.01,
           "Low": spy_close * .99, "Close": spy_close.copy()}
    return bars, spy


def set_session(bars, day, symbol, opened, low=None):
    bars["Open"].iloc[day, bars["Open"].columns.get_loc(symbol)] = opened
    bars["Close"].iloc[day, bars["Close"].columns.get_loc(symbol)] = opened
    bars["High"].iloc[day, bars["High"].columns.get_loc(symbol)] = opened * 1.01
    bars["Low"].iloc[day, bars["Low"].columns.get_loc(symbol)] = opened * .99 if low is None else low


class PathLabelTests(unittest.TestCase):
    def test_no_stop_identity_and_maturity(self):
        bars, spy = fixture()
        set_session(bars, 4, "AAA", 110)
        labels = build_path_labels(bars, spy, horizon=3)
        ready = labels.exit_60.notna()
        np.testing.assert_array_equal(labels.loc[ready, "plain_net_excess"],
                                      labels.loc[ready, "stopped_net_excess"])
        self.assertTrue(labels.loc[ready, "stop_reason"].eq("horizon").all())
        self.assertTrue(labels.loc[~ready, ["plain_net_excess", "stopped_net_excess",
                                          "plain_net_rank", "stopped_net_rank"]].isna().all().all())
        self.assertEqual(len(labels), 16)
        self.assertEqual(labels.iloc[0].entry_date, bars["Open"].index[1])
        self.assertEqual(labels.iloc[0].exit_60, bars["Open"].index[4])

    def test_entry_day_stop_and_fixed_horizon_spy(self):
        bars, spy = fixture()
        bars["Low"].iloc[1, 0] = 80
        set_session(spy, 4, "SPY", 220)
        row = build_path_labels(bars, spy, horizon=3).iloc[0]
        self.assertEqual(row.stop_reason, "stop_intraday")
        self.assertEqual(row.stopped_exit_date, bars["Open"].index[1])
        self.assertEqual(row.exit_60, bars["Open"].index[4])
        self.assertAlmostEqual(row.stopped_gross_excess, .85 * .999 - 1.10)

    def test_gap_uses_worse_open_and_does_not_reinvest(self):
        bars, spy = fixture()
        set_session(bars, 2, "AAA", 70)
        set_session(bars, 4, "AAA", 150)
        row = build_path_labels(bars, spy, horizon=3).iloc[0]
        self.assertEqual(row.stop_reason, "stop_gap")
        self.assertEqual(row.stopped_exit_date, bars["Open"].index[2])
        self.assertAlmostEqual(row.stopped_gross_excess, .70 * .999 - 1)
        self.assertAlmostEqual(row.plain_gross_excess, .50)

    def test_terminal_gap_precedes_liquidation_but_terminal_low_ignored(self):
        bars, spy = fixture()
        set_session(bars, 4, "AAA", 80)
        set_session(bars, 4, "BBB", 100, low=60)
        labels = build_path_labels(bars, spy, horizon=3)
        a, b = labels.iloc[0], labels.iloc[1]
        self.assertEqual(a.stop_reason, "stop_gap")
        self.assertAlmostEqual(a.stopped_gross_excess, .80 * .999 - 1)
        self.assertEqual(b.stop_reason, "horizon")
        self.assertEqual(b.stopped_gross_excess, 0.)

    def test_exact_two_sided_fee_formula(self):
        bars, spy = fixture()
        set_session(bars, 4, "AAA", 120)
        row = build_path_labels(bars, spy, horizon=3, cost_bps=25).iloc[0]
        self.assertAlmostEqual(row.plain_net_excess, 1.2 * (1 - .0025) / (1 + .0025) - 1)
        zero = build_path_labels(bars, spy, horizon=3, cost_bps=0, stop_extra_bps=0).iloc[0]
        self.assertEqual(zero.plain_net_excess, zero.plain_gross_excess)

    def test_prefix_mature_identity_and_early_stop_still_immature(self):
        bars, spy = fixture(12)
        bars["Low"].iloc[5, 0] = 70
        full = build_path_labels(bars, spy, horizon=3)
        short = build_path_labels({k: v.iloc[:7] for k, v in bars.items()},
                                  {k: v.iloc[:7] for k, v in spy.items()}, horizon=3)
        mature = short.exit_60.notna()
        pd.testing.assert_frame_equal(short.loc[mature].reset_index(drop=True),
                                      full.loc[full.Date.isin(short.loc[mature, "Date"])].reset_index(drop=True))
        immature = short.loc[short.Date.eq(bars["Open"].index[4])]
        self.assertTrue(immature.stopped_net_excess.isna().all())
        self.assertTrue(immature.stopped_exit_date.isna().all())

    def test_fixed_floor_ties_have_exact_same_rank_at_different_prices(self):
        bars, spy = fixture(symbols=("AAA", "BBB", "CCC"))
        for symbol, price in (("AAA", 123.4567), ("BBB", 0.37123)):
            for day in range(1, 5):
                set_session(bars, day, symbol, price, low=price * .80 if day == 1 else None)
        first = build_path_labels(bars, spy, horizon=3).iloc[:3].set_index("symbol")
        self.assertEqual(first.loc["AAA", "stopped_net_excess"], first.loc["BBB", "stopped_net_excess"])
        self.assertEqual(first.loc["AAA", "stopped_net_rank"], -.25)
        self.assertEqual(first.loc["BBB", "stopped_net_rank"], -.25)
        self.assertEqual(first.loc["CCC", "stopped_net_rank"], .5)

    def test_bad_prices_calendars_parameters_are_rejected(self):
        for kwargs in ({"horizon": 0}, {"horizon": 1.5}, {"horizon": True},
                       {"stop_fraction": 0}, {"stop_fraction": 1},
                       {"cost_bps": -1}, {"cost_bps": 10000},
                       {"stop_extra_bps": float("nan")}, {"stop_extra_bps": 10000}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                build_path_labels(*fixture(), **kwargs)
        for field, value in (("Open", np.nan), ("Close", 0), ("Low", 101), ("High", 99)):
            bars, spy = fixture()
            bars[field].iloc[1, 0] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                build_path_labels(bars, spy, horizon=3)
        bars, spy = fixture()
        with self.assertRaises(ValueError):
            build_path_labels(bars, {k: v.iloc[1:] for k, v in spy.items()}, horizon=3)
        with self.assertRaises(ValueError):
            build_path_labels({k: v.iloc[::-1] for k, v in bars.items()}, spy, horizon=3)


if __name__ == "__main__":
    unittest.main()
