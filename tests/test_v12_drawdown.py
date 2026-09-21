"""Fictional risk-cycle recovery must not erase full-account drawdown."""
import unittest

import numpy as np

from v12_drawdown_check import continued_statistic, run_check


class FullHistoryDrawdownTests(unittest.TestCase):
    def test_actual_simulator_repeated_halt_resume_retains_global_drawdown(self):
        _, daily, summary = run_check()
        self.assertEqual(summary["halts"], 2)
        self.assertEqual(summary["resumes"], 2)
        self.assertLess(summary["full_history_max_drawdown"], -.30)
        for row in summary["resume_rows"]:
            self.assertGreater(row["account_high_water"], row["episode_peak"])
            self.assertLess(abs(row["episode_drawdown"]), .01)
            self.assertLess(row["full_history_drawdown"], -.20)
        self.assertAlmostEqual(daily.drawdown.min(), summary["full_history_max_drawdown"])
        self.assertTrue(summary["serialized_statistic_continuation_matches_whole_history"])

    def test_account_checkpoint_retains_earlier_high_and_worst_after_recovery(self):
        # A deliberately higher past account peak makes resetting it observable.
        prefix, checkpoint = continued_statistic([1., 1.2, .9])
        suffix, final = continued_statistic([1., .8, 1.3],
                                           checkpoint["account_high_water"],
                                           checkpoint["worst_account_drawdown"])
        expected, whole = continued_statistic([1., 1.2, .9, 1., .8, 1.3])
        np.testing.assert_allclose(prefix + suffix, expected, rtol=0, atol=0)
        self.assertEqual(final, whole)
        self.assertAlmostEqual(final["account_high_water"], 1.3)
        self.assertAlmostEqual(final["worst_account_drawdown"], -1 / 3)


if __name__ == "__main__":
    unittest.main()
