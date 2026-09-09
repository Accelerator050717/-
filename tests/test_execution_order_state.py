"""全部为虚构订单和价格；不连接账户，不代表券商集成已验证。"""

from decimal import Decimal
import unittest
from execution_order_state import OrderState


class OrderLifecycleTests(unittest.TestCase):
    def order(self):
        item = OrderState("fictitious-intent", "FICTITIOUS", "BUY", "10")
        item.begin_attempt()
        item.acknowledge("fake-order-7")
        item.reconcile(snapshot_complete=True, open_references=["fake-order-7"], total_executed=0)
        return item

    def test_submit_timeout_never_automatically_resends(self):
        item = OrderState("fake-timeout", "FICTITIOUS", "BUY", "10")
        item.begin_attempt()
        item.mark_disconnected()
        restored = OrderState.from_json(item.to_json())
        self.assertEqual(restored.status, "UNKNOWN_REQUIRES_RECONCILIATION")
        with self.assertRaises(ValueError):
            restored.begin_attempt()
        self.assertFalse(restored.reconcile(snapshot_complete=True, open_references=[], total_executed=0))

    def test_partial_fill_duplicate_and_restart(self):
        item = self.order()
        self.assertTrue(item.record_execution("fake-fill-1", "fake-order-7", 4, "100.25"))
        restored = OrderState.from_json(item.to_json())
        self.assertFalse(restored.record_execution("fake-fill-1", "fake-order-7", "4.0", "100.250"))
        self.assertEqual(restored.filled, Decimal(4))
        self.assertEqual(restored.cash_delta_before_fees, Decimal("-401.00"))
        self.assertEqual(restored.status, "PARTIALLY_FILLED")

    def test_status_cannot_invent_fill_or_cash(self):
        item = self.order()
        item.observe_status("fake-order-7", "Filled", 10)
        self.assertEqual(item.status, "AWAITING_EXECUTION_DETAILS")
        self.assertEqual(item.cash_delta_before_fees, 0)
        item.record_execution("fake-fill-1", "fake-order-7", 10, 100)
        self.assertEqual(item.status, "FILLED")

    def test_cancel_race_preserves_late_fill(self):
        item = self.order()
        item.record_execution("fake-fill-1", "fake-order-7", 4, 100)
        item.request_cancel_locally()
        item.observe_status("fake-order-7", "Cancelled", 7)
        self.assertEqual(item.status, "AWAITING_EXECUTION_DETAILS")
        item.record_execution("fake-fill-2", "fake-order-7", 3, 101)
        self.assertEqual(item.status, "CANCELLED")
        self.assertEqual(item.filled, 7)
        self.assertEqual(item.cash_delta_before_fees, -703)

    def test_full_fill_wins_over_late_cancel_status(self):
        item = self.order()
        item.record_execution("fake-fill-1", "fake-order-7", 10, 100)
        item.observe_status("fake-order-7", "Cancelled", 0)
        self.assertEqual(item.status, "FILLED")

    def test_missing_open_order_is_ambiguous(self):
        item = self.order()
        item.mark_disconnected()
        self.assertFalse(item.reconcile(snapshot_complete=True, open_references=[], total_executed=0))
        self.assertEqual(item.status, "UNKNOWN_REQUIRES_RECONCILIATION")
        self.assertTrue(item.reconcile(snapshot_complete=True, open_references=[], terminal_reference="fake-order-7",
                                       terminal_status="Cancelled", total_executed=0))
        self.assertEqual(item.status, "CANCELLED")

    def test_incomplete_or_mismatched_snapshot_stays_unknown(self):
        item = self.order()
        for complete, count in ((False, 0), (True, 1)):
            self.assertFalse(item.reconcile(snapshot_complete=complete, open_references=["fake-order-7"], total_executed=count))
            self.assertEqual(item.status, "UNKNOWN_REQUIRES_RECONCILIATION")

    def test_conflicting_fill_or_overfill_halts(self):
        for conflict in (True, False):
            item = self.order()
            item.record_execution("fake-fill-1", "fake-order-7", 4, 100)
            with self.assertRaises(ValueError):
                item.record_execution("fake-fill-1" if conflict else "fake-fill-2", "fake-order-7", 7, 101)
            self.assertEqual(item.status, "HALTED")
            self.assertEqual(item.filled, 4)

    def test_execution_revision_not_counted_twice(self):
        item = self.order()
        item.record_execution("fictional.0001.01.01", "fake-order-7", 4, 100)
        with self.assertRaises(ValueError):
            item.record_execution("fictional.0001.01.02", "fake-order-7", 4, 100)
        self.assertEqual(item.status, "HALTED")
        self.assertEqual(item.filled, 4)

    def test_wrong_order_invalid_price_and_inactive_do_not_trade(self):
        item = self.order()
        for reference, price in (("another-order", 100), ("fake-order-7", "NaN"), ("fake-order-7", -1)):
            with self.assertRaises(ValueError):
                item.record_execution("fake-fill-1", reference, 4, price)
        self.assertEqual(item.filled, 0)
        item.observe_status("fake-order-7", "Inactive", 0)
        self.assertEqual(item.status, "HALTED")


if __name__ == "__main__":
    unittest.main()
