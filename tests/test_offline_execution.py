"""所有输入均为虚构数据；测试执行会计和拒绝逻辑，不代表市场结果。"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from offline_execution import ReplayBlocked, ReplayExecutor, digest


class OfflineExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.model = self.root / "fictitious_model.bin"
        self.model.write_bytes(b"FICTITIOUS MODEL: never used for market predictions")
        self.sha = hashlib.sha256(self.model.read_bytes()).hexdigest()
        self.days = ["2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07"]
        self.symbols = ["A", "B", "C", "D", "E", "F"]
        self.features = ["past_return", "past_volatility"]
        self.weights = {symbol: .2 for symbol in self.symbols[:5]}
        self.prices = {symbol: 100. for symbol in self.symbols}
        self.path = self.root / "state.json"
        self.engine = self.create()

    def create(self, **changes):
        kwargs = dict(state_path=self.path, calendar=self.days, symbols=self.symbols,
                      feature_names=self.features, model_path=self.model,
                      expected_model_sha256=self.sha, initial_cash=10000, cost_bps=10)
        kwargs.update(changes)
        return ReplayExecutor(**kwargs)

    def submit(self, engine=None, **changes):
        kwargs = dict(batch_key="batch1", observed_date=self.days[0], asof=self.days[0],
                      weights=self.weights, feature_order=self.features)
        kwargs.update(changes)
        return (engine or self.engine).submit_target(**kwargs)

    def fill(self, engine=None, **changes):
        kwargs = dict(batch_key="batch1", execution_date=self.days[1], asof=self.days[1], prices=self.prices)
        kwargs.update(changes)
        return (engine or self.engine).fill_next_open(**kwargs)

    def unchanged_when_blocked(self, callback):
        before = self.path.read_bytes()
        with self.assertRaises((ReplayBlocked, ValueError)):
            callback()
        self.assertEqual(before, self.path.read_bytes())

    def test_restart_and_two_instances_are_idempotent(self):
        second = self.create()  # 在第一次成交前创建第二实例，检测旧缓存覆盖风险。
        self.submit()
        self.assertEqual(self.fill()["new_fills"], 5)
        before = self.path.read_bytes()
        self.assertEqual(self.fill(second)["status"], "already_filled")
        self.assertEqual(self.submit(second)["status"], "already_recorded")
        self.assertEqual(before, self.path.read_bytes())
        restored = self.create()
        self.assertEqual(self.fill(restored)["new_fills"], 0)
        state = restored.read_state()
        self.assertEqual(len(state["fills"]), 5)
        self.assertAlmostEqual(sum(fill["fee"] for fill in state["fills"]), 10000 - 10000 / 1.001, places=8)

    def test_reused_key_different_intent_is_blocked(self):
        self.submit()
        changed = {symbol: .2 for symbol in self.symbols[1:]}
        self.unchanged_when_blocked(lambda: self.submit(weights=changed))
        self.fill()
        self.unchanged_when_blocked(lambda: self.fill(prices={symbol: 101. for symbol in self.symbols}))

    def test_missing_nan_infinite_zero_negative_prices_blocked(self):
        self.submit()
        bad_values = [float("nan"), float("inf"), 0., -1.]
        for value in bad_values:
            with self.subTest(price=value):
                bad = {**self.prices, "A": value}
                self.unchanged_when_blocked(lambda: self.fill(prices=bad))
        self.unchanged_when_blocked(lambda: self.fill(prices={k: v for k, v in self.prices.items() if k != "A"}))

    def test_weights_feature_order_and_asof_blocked(self):
        for weights in ({"A": -.1}, {"A": .3}, {symbol: .2 for symbol in self.symbols}):
            self.unchanged_when_blocked(lambda: self.submit(weights=weights))
        self.unchanged_when_blocked(lambda: self.submit(feature_order=list(reversed(self.features))))
        self.unchanged_when_blocked(lambda: self.submit(asof="2025-01-01"))

    def test_next_session_is_exact_and_needs_target(self):
        self.unchanged_when_blocked(lambda: self.fill())
        self.submit()
        self.unchanged_when_blocked(lambda: self.fill(execution_date=self.days[0], asof=self.days[0]))
        self.unchanged_when_blocked(lambda: self.fill(execution_date=self.days[2], asof=self.days[2]))
        self.unchanged_when_blocked(lambda: self.fill(asof=self.days[0]))

    def test_pending_fill_must_precede_snapshot(self):
        self.submit()
        self.unchanged_when_blocked(lambda: self.engine.reconcile_snapshot(self.days[1], self.days[1], self.prices))
        self.fill()
        snapshot = self.engine.reconcile_snapshot(self.days[1], self.days[1], self.prices)
        self.assertLess(snapshot["nav"], 10000)
        self.assertEqual(self.engine.reconcile_snapshot(self.days[1], self.days[1], self.prices), snapshot)

    def test_cash_and_positions_tampering_detected_even_with_new_checksum(self):
        self.submit()
        self.fill()
        original = json.loads(self.path.read_text(encoding="utf-8"))
        for field in ("cash", "positions"):
            damaged = deepcopy(original)
            if field == "cash":
                damaged["cash"] += 1
            else:
                damaged["positions"]["A"] += 1
            damaged.pop("state_hash")
            damaged["state_hash"] = digest(damaged)
            self.path.write_text(json.dumps(damaged), encoding="utf-8")
            self.unchanged_when_blocked(lambda: self.engine.read_state())
        self.path.write_text(json.dumps(original), encoding="utf-8")

    def test_unknown_mode_model_hash_and_lock_fail_closed(self):
        self.unchanged_when_blocked(lambda: self.create(mode="live"))
        self.unchanged_when_blocked(lambda: self.create(expected_model_sha256="0" * 64))
        self.engine.lock_path.write_text("fictitious stale lock")
        self.unchanged_when_blocked(lambda: self.submit())
        self.engine.lock_path.unlink()
        self.model.write_bytes(b"TAMPERED fictitious model")
        self.unchanged_when_blocked(lambda: self.submit())

    def test_missing_previously_initialized_state_does_not_reset_cash(self):
        self.submit()
        self.fill()
        self.path.unlink()
        with self.assertRaises(ReplayBlocked):
            self.create()
        self.assertFalse(self.path.exists())

    def test_drift_rebalance_snapshots_and_final_cash_reconcile(self):
        self.submit()
        self.fill()
        self.engine.reconcile_snapshot(self.days[1], self.days[1], self.prices)
        second_key = "batch2"
        self.submit(batch_key=second_key, observed_date=self.days[1], asof=self.days[1])
        changed = {**self.prices, "A": 200.}
        self.fill(batch_key=second_key, execution_date=self.days[2], asof=self.days[2], prices=changed)
        snapshot = self.engine.reconcile_snapshot(self.days[2], self.days[2], changed)
        nonzero = [value for value in snapshot["position_values"].values() if value > 0]
        self.assertAlmostEqual(max(nonzero), min(nonzero), places=7)
        self.assertGreaterEqual(snapshot["cash"], 0)
        state = self.engine.read_state()
        independent_cash = 10000 - sum(fill["signed_notional"] + fill["fee"] for fill in state["fills"])
        self.assertAlmostEqual(independent_cash, snapshot["cash"], places=7)


if __name__ == "__main__":
    unittest.main()
