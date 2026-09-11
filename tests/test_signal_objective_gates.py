"""Invented metrics/calendars only: no fitting, market-data read or backtest.

These tests protect the preregistered v11 acceptance boundary. Their numbers
are deliberately synthetic and are not research performance evidence.
"""
from dataclasses import asdict, replace
import importlib
import unittest

import pandas as pd

from profit_priority_strategy import Policy


evaluation = importlib.import_module("51_evaluate_signal_objectives")


def synthetic_metrics():
    """Three failed 25%-CAGR candidates plus two admissible simple controls."""
    rows = [dict(signal=signal, scenario=scenario, cagr=.25,
                 max_drawdown=-.20, total_return=.50)
            for signal in evaluation.NEW_SIGNALS for scenario in evaluation.SCENARIOS]
    rows.extend(dict(signal=signal, scenario="cost10", cagr=cagr,
                     max_drawdown=-.20, total_return=.40)
                for signal, cagr in (("simple_h60", .20), ("simple_spy", .10)))
    return pd.DataFrame(rows)


def set_metrics(table, signal, scenario="cost10", **values):
    selected = table.signal.eq(signal) & table.scenario.eq(scenario)
    assert selected.sum() == 1
    for name, value in values.items():
        table.loc[selected, name] = value


def synthetic_calendar():
    """Intentionally irregular session records, not an actual exchange calendar."""
    dates = pd.to_datetime([
        "2018-01-02", "2018-01-03", "2018-01-05", "2018-01-08",
        "2018-01-10", "2018-01-11", "2018-01-16", "2018-01-17",
        "2018-01-19", "2018-01-22", "2018-01-24", "2018-01-25",
    ])
    return dates, dates[[0, 4, 6, 7]], dates.delete(5), dates[10]


class SignalObjectiveGateTests(unittest.TestCase):
    def test_net_cagr_and_drawdown_budget_boundaries_are_inclusive(self):
        table = synthetic_metrics()
        set_metrics(table, "plain_magnitude", cagr=.30, max_drawdown=-.30)
        result = evaluation.gate_rows(table)
        self.assertTrue(result["candidates"]["plain_magnitude"]["development_passed"])
        self.assertEqual(result["selected_for_development_review"], "plain_magnitude")
        self.assertFalse(result["candidates"]["plain_magnitude"]["preferred_drawdown_within_20"])
        set_metrics(table, "plain_magnitude", cagr=.30 - 1e-12)
        self.assertFalse(evaluation.gate_rows(table)["candidates"]["plain_magnitude"]["development_passed"])

    def test_higher_cagr_cannot_override_excess_drawdown(self):
        table = synthetic_metrics()
        set_metrics(table, "plain_magnitude", cagr=.75, max_drawdown=-.30 - 1e-12)
        set_metrics(table, "stopped_magnitude", cagr=.31)
        result = evaluation.gate_rows(table)
        self.assertFalse(result["candidates"]["plain_magnitude"]["drawdown_within_30"])
        self.assertFalse(result["candidates"]["plain_magnitude"]["development_passed"])
        self.assertEqual(result["selected_for_development_review"], "stopped_magnitude")

    def test_each_cost_or_fixed_stress_must_have_strictly_positive_cumulative_return(self):
        for scenario in evaluation.SCENARIOS[1:]:
            for total_return in (0., -.001):
                with self.subTest(scenario=scenario, total_return=total_return):
                    table = synthetic_metrics()
                    set_metrics(table, "plain_magnitude", cagr=.50)
                    set_metrics(table, "plain_magnitude", scenario, total_return=total_return)
                    result = evaluation.gate_rows(table)
                    gate = result["candidates"]["plain_magnitude"]
                    self.assertFalse(gate["all_fixed_stress_positive_and_drawdown_within_30"])
                    self.assertFalse(gate["development_passed"])
                    self.assertIsNone(result["selected_for_development_review"])

    def test_each_stress_drawdown_uses_the_same_inclusive_budget(self):
        for scenario in evaluation.SCENARIOS[1:]:
            with self.subTest(scenario=scenario):
                table = synthetic_metrics()
                set_metrics(table, "plain_magnitude", cagr=.40)
                set_metrics(table, "plain_magnitude", scenario, max_drawdown=-.30)
                self.assertTrue(evaluation.gate_rows(table)["candidates"]["plain_magnitude"]["development_passed"])
                set_metrics(table, "plain_magnitude", scenario, max_drawdown=-.300001)
                self.assertFalse(evaluation.gate_rows(table)["candidates"]["plain_magnitude"]["development_passed"])

    def test_must_strictly_beat_every_risk_admissible_simple_control(self):
        table = synthetic_metrics()
        set_metrics(table, "plain_magnitude", cagr=.40)
        set_metrics(table, "simple_h60", cagr=.40, max_drawdown=-.30)
        self.assertFalse(evaluation.gate_rows(table)["candidates"]["plain_magnitude"]["development_passed"])
        # A higher-return control beyond the preregistered risk ceiling is not
        # an admissible winner; the remaining simple control still must be beat.
        set_metrics(table, "simple_h60", cagr=.80, max_drawdown=-.31)
        self.assertTrue(evaluation.gate_rows(table)["candidates"]["plain_magnitude"]["development_passed"])
        set_metrics(table, "simple_spy", cagr=.41)
        self.assertFalse(evaluation.gate_rows(table)["candidates"]["plain_magnitude"]["development_passed"])

    def test_selection_uses_passing_cagr_then_exact_id_tiebreak_only(self):
        table = synthetic_metrics()
        set_metrics(table, "plain_magnitude", cagr=.80, max_drawdown=-.31)
        set_metrics(table, "stopped_magnitude", cagr=.35)
        set_metrics(table, "stopped_rank", cagr=.40)
        self.assertEqual(evaluation.gate_rows(table)["selected_for_development_review"], "stopped_rank")
        set_metrics(table, "stopped_magnitude", cagr=.40)
        self.assertEqual(evaluation.gate_rows(table)["selected_for_development_review"], "stopped_magnitude")
        # A genuine numerical difference is not rounded into a display tie.
        set_metrics(table, "stopped_rank", cagr=.40 + 1e-12)
        self.assertEqual(evaluation.gate_rows(table)["selected_for_development_review"], "stopped_rank")

    def test_development_pass_never_unlocks_2026_or_independent_validation(self):
        for passing in (False, True):
            with self.subTest(passing=passing):
                table = synthetic_metrics()
                if passing:
                    set_metrics(table, "plain_magnitude", cagr=.50)
                result = evaluation.gate_rows(table)
                for name in ("independent_validation_passed", "candidate_frozen_for_2026", "prices_2026_accessed"):
                    self.assertFalse(result[name])
                self.assertTrue(result["old_0_of_98_unchanged"])
                self.assertEqual(result["decision"], "DEVELOPMENT_ONLY_REVIEW_REQUIRED" if passing else "REJECT_NO_2026")
                if not passing:
                    self.assertIsNone(result["selected_for_development_review"])

    def test_all_scenarios_preserve_protection_hard_pause_and_policy(self):
        calendar, observations, scores, final = synthetic_calendar()
        expected_policy = asdict(replace(Policy(), soft_enabled=False))
        expected_costs = {"cost10": (10, 10), "cost20": (20, 10),
                          "cost30_stop50": (30, 50), "delayed_next_open": (20, 50),
                          "phase1": (10, 10), "phase4": (10, 10), "exclude_NVDA": (10, 10)}
        for scenario in evaluation.SCENARIOS:
            with self.subTest(scenario=scenario):
                _, kwargs = evaluation.scenario_options(scenario, calendar, observations, scores, final)
                self.assertEqual(kwargs["mode"], "risk")
                self.assertIs(kwargs["stops"], True)
                self.assertIs(kwargs["breaker"], True)
                self.assertIs(kwargs["policy"].soft_enabled, False)
                self.assertIs(kwargs["policy"].hard_enabled, True)
                self.assertEqual(asdict(kwargs["policy"]), expected_policy)
                self.assertEqual((kwargs["cost_bps"], kwargs["stop_extra_bps"]), expected_costs[scenario])
                self.assertEqual(kwargs.get("delayed_stops", False), scenario == "delayed_next_open")
                self.assertEqual(kwargs.get("excluded", ()), ("NVDA",) if scenario == "exclude_NVDA" else ())

    def test_phase_uses_session_offsets_and_drops_missing_or_terminal_scores(self):
        calendar, observations, scores, final = synthetic_calendar()
        phase1, _ = evaluation.scenario_options("phase1", calendar, observations, scores, final)
        phase4, _ = evaluation.scenario_options("phase4", calendar, observations, scores, final)
        # Matches 42's calendar-record shift followed by score availability and
        # strict observation < final filtering, not a shift by calendar days.
        pd.testing.assert_index_equal(phase1, pd.to_datetime(["2018-01-03", "2018-01-17", "2018-01-19"]))
        pd.testing.assert_index_equal(phase4, pd.to_datetime(["2018-01-10", "2018-01-19"]))
        unchanged, _ = evaluation.scenario_options("cost10", calendar, observations, scores, final)
        pd.testing.assert_index_equal(unchanged, observations)

    def test_unregistered_scenario_is_rejected(self):
        with self.assertRaises(ValueError):
            evaluation.scenario_options("phase2", *synthetic_calendar())


if __name__ == "__main__":
    unittest.main()
