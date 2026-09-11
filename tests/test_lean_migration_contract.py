"""Invented phase/ledger fixtures; these tests are NOT a LEAN engine run."""
from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import shutil
import sys
import unittest

import numpy as np
import pandas as pd

from lean_migration.decision import H60Decision
from profit_priority_strategy import Policy


def synthetic_package():
    """Eight fictional securities, synthetic risk inputs, and no vendor data."""
    dates = pd.bdate_range("2019-01-02", periods=125)
    names = [f"SIM_{j}" for j in range(8)]
    observations = dates[[60, 65, 85, 100, 110]]
    return dict(
        schema_version=1, research_only=True, live_mode_allowed=False,
        names=names, calendar=[d.date().isoformat() for d in dates],
        groups={name: name for name in names},
        policy=asdict(replace(Policy(), soft_enabled=False)),
        initial_cash=10000., cost_bps=10, stop_extra_bps=10,
        first_date=dates[61].date().isoformat(), final_date=dates[120].date().isoformat(),
        observations=[d.date().isoformat() for d in observations],
        scores={d.date().isoformat(): list(range(8)) for d in observations},
        risk={"distance": [[.15] * 8 for _ in dates],
              "vol": [[.02] * 8 for _ in dates],
              "returns": [[(-1) ** i * .01 + j * .0001 for j in range(8)]
                          for i in range(len(dates))],
              "trend": [True] * len(dates), "spy_exposure": [1.] * len(dates)},
    )


class SyntheticBroker:
    """Only for controller unit tests; intentionally not a broker adapter."""
    def __init__(self, package):
        self.names = package["names"]
        self.q = np.zeros(len(self.names))
        self.money = float(package["initial_cash"])
        self.rate = package["cost_bps"] / 10000
        self.fees = 0.
        self.marks = np.ones(len(self.names)) * 100
        self.trades = []
        self.current_date = None
        self.current_phase = None

    def quantities(self, names):
        return [self.q[self.names.index(name)] for name in names]

    def cash(self):
        return self.money

    def equity(self):
        return self.money + float(self.q @ self.marks)

    def cumulative_fees(self):
        return self.fees

    def execute(self, name, quantity, price, reason, observation, threshold, risk_action):
        fee = abs(quantity * price) * self.rate
        self.money -= quantity * price + fee
        position = self.names.index(name)
        self.q[position] += quantity
        # Double-precision fixture dust cleanup, analogous to the legacy replay.
        # Actual LEAN decimal quantities must be verified in the engine run.
        if abs(self.q[position]) < 1e-10:
            self.q[position] = 0.
        self.fees += fee
        self.trades.append(dict(name=name, quantity=quantity, price=price, reason=reason,
                                observation=observation, threshold=threshold,
                                risk_action=risk_action, fee=fee,
                                Date=self.current_date, phase=self.current_phase))


def phase(controller, broker, name, day, values=None):
    values = np.full(len(broker.names), 100.) if values is None else np.asarray(values)
    broker.marks = values
    broker.current_date = controller.calendar[day].date().isoformat()
    broker.current_phase = name
    controller.process(name, controller.calendar[day], values, broker)


class LeanMigrationContractTests(unittest.TestCase):
    def setUp(self):
        self.package = synthetic_package()

    def test_rejects_2026_or_duplicate_calendar_before_any_order(self):
        for value in ("2026-01-02", self.package["calendar"][-2]):
            package = deepcopy(self.package)
            package["calendar"][-1] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                H60Decision(package)

    def test_rejects_observation_disorder_and_missing_history(self):
        for replacement in (
            list(reversed(self.package["observations"])),
            [self.package["calendar"][20]],
            [self.package["observations"][0]] * 2,
        ):
            package = deepcopy(self.package)
            package["observations"] = replacement
            with self.subTest(observations=replacement), self.assertRaises(ValueError):
                H60Decision(package)

    def test_rejects_ambiguous_names_or_wrong_execution_boundaries(self):
        for field, value in (
            ("names", [self.package["names"][0]] * 8),
            ("first_date", self.package["calendar"][60]),
            ("final_date", self.package["calendar"][60]),
        ):
            package = deepcopy(self.package)
            package[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                H60Decision(package)

    def test_rejects_policy_drift_from_registered_cell(self):
        for field, value in (("soft_enabled", True), ("hard_enabled", False)):
            package = deepcopy(self.package)
            package["policy"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                H60Decision(package)

    def test_missing_or_nonfinite_cross_section_places_no_order(self):
        for prices in ([100.] * 7, [100.] * 7 + [np.nan], [100.] * 7 + [0.]):
            controller, broker = H60Decision(self.package), SyntheticBroker(self.package)
            with self.subTest(prices=prices), self.assertRaises(ValueError):
                phase(controller, broker, "OPEN", controller.first, prices)
            self.assertEqual(broker.trades, [])
            self.assertEqual(controller.expected_phase, "OPEN")

    def test_duplicate_or_skipped_phase_cannot_duplicate_orders(self):
        controller, broker = H60Decision(self.package), SyntheticBroker(self.package)
        with self.assertRaises(ValueError):
            phase(controller, broker, "RANGE", controller.first)
        phase(controller, broker, "OPEN", controller.first)
        count = len(broker.trades)
        for name, day in (("OPEN", controller.first), ("CLOSE", controller.first),
                          ("OPEN", controller.first + 1)):
            with self.subTest(phase=name, day=day), self.assertRaises(ValueError):
                phase(controller, broker, name, day)
            self.assertEqual(len(broker.trades), count)

    def test_future_risk_and_scores_do_not_change_current_order(self):
        changed = deepcopy(self.package)
        # These values exist in a historical archive but are not yet observable.
        first = 61
        changed["risk"]["spy_exposure"][first:] = [0.] * (len(changed["calendar"]) - first)
        for key in ("distance", "vol", "returns"):
            changed["risk"][key][first:] = [[9.] * 8 for _ in changed["calendar"][first:]]
        for observation in changed["observations"][1:]:
            changed["scores"][observation] = list(reversed(range(8)))
        brokers = []
        for package in (self.package, changed):
            controller, broker = H60Decision(package), SyntheticBroker(package)
            phase(controller, broker, "OPEN", controller.first)
            brokers.append(broker)
            self.assertLess(controller.observation_audit[0]["observation_date"],
                            controller.observation_audit[0]["execution_date"])
        np.testing.assert_array_equal(brokers[0].q, brokers[1].q)
        self.assertEqual(brokers[0].cash(), brokers[1].cash())

    def test_gap_stop_blocks_reentry_on_same_scheduled_open(self):
        package = deepcopy(self.package)
        package["observations"] = [package["calendar"][60], package["calendar"][61]]
        package["scores"] = {date: list(range(8)) for date in package["observations"]}
        controller, broker = H60Decision(package), SyntheticBroker(package)
        for name in ("OPEN", "RANGE", "CLOSE"):
            phase(controller, broker, name, 61)
        before_count = len(broker.trades)
        prices = [100.] * 7 + [70.]
        phase(controller, broker, "OPEN", 62, prices)
        trades = broker.trades[before_count:]
        stops = [trade for trade in trades if trade["name"] == "SIM_7"]
        self.assertEqual([trade["reason"] for trade in stops], ["stop_gap"])
        self.assertAlmostEqual(stops[0]["price"], 69.93)
        self.assertAlmostEqual(broker.q[-1], 0.)
        self.assertEqual(controller.blocked_until[-1], 67)

    def test_gap_during_daily_cap_reduction_never_buys_or_reopens(self):
        controller, broker = H60Decision(self.package), SyntheticBroker(self.package)
        phase(controller, broker, "OPEN", 61)
        phase(controller, broker, "RANGE", 61)
        # Different appreciation creates a genuine cap reduction on the next day.
        phase(controller, broker, "CLOSE", 61, [140.] + [100.] * 7)
        self.assertIsNotNone(controller.pending_cap)
        previous = broker.q.copy()
        count = len(broker.trades)
        phase(controller, broker, "OPEN", 62, [100.] * 7 + [70.])
        trades = broker.trades[count:]
        self.assertTrue(any(trade["reason"] == "daily_risk_reduce" for trade in trades))
        self.assertTrue(all(trade["quantity"] <= 0 for trade in trades))
        self.assertTrue((broker.q <= previous + 1e-8).all())
        self.assertAlmostEqual(broker.q[-1], 0.)

    def test_hard_pause_waits_for_cooldown_trend_and_schedule_then_recovers(self):
        controller, broker = H60Decision(self.package), SyntheticBroker(self.package)
        for day in range(controller.first, controller.finish + 1):
            prices = [100.] * 8 if day == controller.first else [50.] * 8
            for name in ("OPEN", "RANGE", "CLOSE"):
                phase(controller, broker, name, day, prices)
        events = {event["event"]: event for event in controller.events}
        self.assertEqual(events["portfolio_halt"]["Date"], self.package["calendar"][62])
        self.assertEqual(events["portfolio_resume"]["Date"], self.package["calendar"][86])
        targets = {target["Date"]: target for target in controller.targets
                   if target["reason"] == "scheduled"}
        half = sum(targets[self.package["calendar"][86]][name] for name in broker.names)
        full = sum(targets[self.package["calendar"][101]][name] for name in broker.names)
        self.assertAlmostEqual(half, .4)
        self.assertAlmostEqual(full, .8)
        self.assertFalse(any(day["soft"] for day in controller.daily))
        self.assertTrue(controller.status()["completed"])
        np.testing.assert_allclose(broker.q, np.zeros(8), atol=1e-8)
        self.assertGreater(broker.fees, 0.)
        self.assertAlmostEqual(controller.daily[-1]["equity"], broker.money)


def fixed_export_regression():
    """Full saved-input controller regression, expressly NOT a LEAN engine run."""
    root = Path(__file__).resolve().parents[1]
    experiment = root / "data/experiments/lean_migration_v10"
    folder = experiment / "input"
    output = experiment / "synthetic_controller_regression"
    output.mkdir(exist_ok=True)
    package = json.loads((folder / "package.json").read_text(encoding="utf-8"))
    identity = json.loads((folder / "EXPORT_IDENTITY.json").read_text(encoding="utf-8"))
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    for name, expected in identity["exported_sha256"].items():
        if digest(folder / name) != expected:
            raise ValueError(f"Export changed: {name}")
    for name, expected in package["shared_source_sha256"].items():
        if digest(root / name) != expected:
            raise ValueError(f"Current imported strategy differs from export: {name}")
    # Read archived adjusted phase prices, with no data API or model fit.
    frames = {name: pd.read_csv(folder / relative, float_precision="round_trip")
              for name, relative in package["data_files"].items()}
    controller, broker = H60Decision(package), SyntheticBroker(package)
    first_frame = frames[controller.names[0]]
    expected_rows = (controller.finish - controller.first + 1) * 3
    for name, frame in frames.items():
        if len(frame) != expected_rows or not frame[["timestamp", "phase"]].equals(
                first_frame[["timestamp", "phase"]]):
            raise ValueError(f"Missing, duplicate or misaligned saved phase rows: {name}")
    for row in range(expected_rows):
        date = pd.Timestamp(first_frame.timestamp.iloc[row]).normalize()
        day = controller.calendar.get_loc(date)
        values = [frames[name].value.iloc[row] for name in controller.names]
        try:
            phase(controller, broker, first_frame.phase.iloc[row], day, values)
        except Exception:
            print(json.dumps(dict(failed_phase=str(first_frame.timestamp.iloc[row]),
                                  cash=broker.cash(), quantities=broker.q.tolist())))
            raise
    if not controller.completed:
        raise AssertionError("Synthetic full-package replay did not finish")
    actual = {"daily": pd.DataFrame(controller.daily),
              "positions": pd.DataFrame(controller.positions),
              "targets": pd.DataFrame(controller.targets)}
    actual["trades"] = pd.DataFrame(broker.trades).rename(columns={
        "name": "symbol", "quantity": "signed_units", "price": "proxy_fill",
        "observation": "observation_date", "threshold": "stop_threshold"})
    reference = root / "data/experiments/h60_risk_execution_v8/backtests"
    case = "stop_on_soft_off_cost10"
    checks = {}
    for kind, frame in actual.items():
        frame.to_csv(output / f"{kind}.csv", index=False)
        original = pd.read_csv(reference / f"{case}_{kind}.csv", float_precision="round_trip")
        if kind in ("daily", "positions"):
            keys = ["Date"]
        elif kind == "targets":
            keys = ["Date", "reason"]
        else:
            keys = ["Date", "reason", "symbol"]
        original, frame = [value.sort_values(keys, kind="stable").reset_index(drop=True)
                           for value in (original, frame)]
        if not original[keys].equals(frame[keys]):
            raise AssertionError(f"{kind} key/row mismatch")
        if kind == "daily":
            columns = ["open_equity", "equity", "low_stress_equity", "cash", "invested",
                       "fees", "cumulative_fees", "episode_peak"]
            scales = {column: package["initial_cash"] for column in columns}
            scales["gross"] = 1.
            tolerance = {column: .01 for column in columns}
            tolerance["gross"] = 1e-9
            for field in ("paused", "soft"):
                if not original[field].equals(frame[field]):
                    raise AssertionError(f"Daily state differs: {field}")
        elif kind == "positions":
            scales = {name: package["initial_cash"] for name in controller.names}
            tolerance = dict.fromkeys(scales, 1e-6)
        elif kind == "targets":
            scales = dict.fromkeys(controller.names, 1.)
            tolerance = dict.fromkeys(scales, 1e-9)
        else:
            scales = {"signed_units": package["initial_cash"], "proxy_fill": 1.,
                      "fee": package["initial_cash"]}
            tolerance = {"signed_units": 1e-6, "proxy_fill": 1e-8, "fee": .01}
            if not original.observation_date.equals(frame.observation_date):
                raise AssertionError("Trade observation dates differ")
        errors = {}
        for column, scale in scales.items():
            maximum = float(np.max(np.abs(frame[column].to_numpy() - original[column].to_numpy() * scale)))
            errors[column] = maximum
            if maximum > tolerance[column]:
                raise AssertionError(f"{kind}/{column}: {maximum} > {tolerance[column]}")
        checks[kind] = dict(rows=len(frame), max_absolute_error=errors, tolerance=tolerance)
    report = dict(status="PASS_SYNTHETIC_CONTROLLER_REGRESSION", actual_lean_engine=False,
                  description="Python decision unit regression with a fictional fill/ledger fixture",
                  new_fits=0, prices_2026_accessed=False, paper_or_live_orders=0,
                  package_sha256=digest(folder / "package.json"),
                  decision_sha256=digest(root / "lean_migration/decision.py"),
                  checks=checks, controller=controller.status())
    (output / "RESULT.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


def export_synthetic_engine_fixture():
    """Export explicitly fictional prices to exercise LEAN pause/resume mechanics."""
    root = Path(__file__).resolve().parents[1]
    experiment = root / "data/experiments/lean_migration_v10"
    folder = experiment / "synthetic_input"
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    identity_path = folder / "EXPORT_IDENTITY.json"
    if identity_path.exists():
        identity = json.loads(identity_path.read_text(encoding="utf-8"))
        for name, expected in identity["exported_sha256"].items():
            if digest(folder / name) != expected:
                raise ValueError(f"Previously exported synthetic fixture changed: {name}")
        print(json.dumps(dict(status="verified_existing_synthetic_fixture", folder=str(folder))))
        return
    if folder.exists() and any(folder.iterdir()):
        raise FileExistsError("Preserve incomplete synthetic export before retry")
    (folder / "bars").mkdir(parents=True)
    (folder / "shared").mkdir()
    package = synthetic_package()
    shared = ("profit_priority_strategy.py", "research_backtest.py")
    for name in shared:
        shutil.copyfile(root / name, folder / "shared" / name)
    controller, broker = H60Decision(package), SyntheticBroker(package)
    records = []
    for day in range(controller.first, controller.finish + 1):
        value = 100. if day == controller.first else 50.
        for phase_name, clock in (("OPEN", "09:30:00"), ("RANGE", "12:00:00"),
                                  ("CLOSE", "16:00:00")):
            records.append(dict(timestamp=f"{package['calendar'][day]}T{clock}",
                                phase=phase_name, value=value))
            phase(controller, broker, phase_name, day, [value] * 8)
    files = {}
    for name in package["names"]:
        relative = f"bars/{name}.csv"
        pd.DataFrame(records).to_csv(folder / relative, index=False)
        files[relative] = digest(folder / relative)
    package.update(
        fictional_test_data=True,
        data_files={name: f"bars/{name}.csv" for name in package["names"]},
        data_sha256=files.copy(), shared_directory="shared",
        shared_source_sha256={name: digest(root / name) for name in shared},
        prediction_source="INVENTED fixture scores, no trained model or market observation",
        models=[], new_fits=0,
        price_basis="INVENTED prices and risk values for engineering tests only; not market data",
        phase_clock="Artificial OPEN 09:30 / RANGE 12:00 / CLOSE 16:00 in New York",
        reference_case="SYNTHETIC_HARD_PAUSE_RECOVERY_ONLY",
        experiment_plan_sha256=digest(experiment / "PLAN.md"),
    )
    (folder / "package.json").write_text(json.dumps(package, indent=2), encoding="utf-8")
    expected = dict(
        fictional_test_data=True, actual_lean_engine=False,
        phase_records_per_symbol=len(records), securities=8,
        source="Python unit-test fixture ledger; compare engine output independently",
        events=controller.events,
        expected_halt_date=package["calendar"][62],
        expected_resume_date=package["calendar"][86],
        expected_recovery_gross=.4, expected_restored_gross=.8,
        expected_final_quantities=dict(zip(package["names"], broker.q.tolist())),
        expected_final_cash=broker.cash(), expected_fees=broker.fees,
        real_market_data=False, new_fits=0, models_reused=0,
    )
    (folder / "EXPECTED_SYNTHETIC.json").write_text(json.dumps(expected, indent=2), encoding="utf-8")
    for path in folder.rglob("*"):
        if path.is_file():
            files[path.relative_to(folder).as_posix()] = digest(path)
    identity = dict(stable_identity=dict(
        schema_version=1, case="fictional_hard_pause_recovery",
        new_fits=0, real_market_data=False,
        fixture_source_sha256=digest(Path(__file__)),
        shared_source_sha256=package["shared_source_sha256"]),
        exported_sha256=files)
    identity_path.write_text(json.dumps(identity, indent=2), encoding="utf-8")
    print(json.dumps(dict(status="exported_synthetic_fixture", folder=str(folder), **expected), indent=2))


if __name__ == "__main__":
    if "--fixed-export-regression" in sys.argv:
        fixed_export_regression()
    elif "--export-synthetic-engine-fixture" in sys.argv:
        export_synthetic_engine_fixture()
    else:
        unittest.main()
