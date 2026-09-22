"""Fictitious cash/price/fill fixtures only; no broker or market-data calls."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from strategy_fund_journal import FundJournal, FundJournalError


SCOPE = dict(scope_id="fictional-fund-one", owner="test-strategy", currency="USD", universe=["AAA"])
T0 = "2020-01-01T16:00:00+00:00"
T1 = "2020-01-02T16:00:00+00:00"
T2 = "2020-01-03T16:00:00+00:00"
T3 = "2020-01-04T16:00:00+00:00"


class FundJournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "fund.sqlite"
        self.journal = FundJournal.create(self.path, SCOPE, 1000, T0)

    def tearDown(self):
        if self.journal is not None:
            self.journal.close()
        self.temp.cleanup()

    def commit(self, batch, at, events=(), price=100, **kwargs):
        return self.journal.commit(batch, at, events, {"AAA": price},
            kwargs.pop("checkpoint", {"session": batch}),
            kwargs.pop("model_version", "original-A"), kwargs.pop("run_id", "process-1"), **kwargs)

    def test_two_loss_cycles_and_model_handoff_preserve_high_water(self):
        buy = dict(id="buy", at=T1, kind="fill", symbol="AAA", quantity=10, price=100)
        self.commit("buy", T1, [buy])
        first = self.commit("loss-one", T2, price=80,
                            risk_state={"mode": "paused", "episode_peak": 800})
        self.assertAlmostEqual(first["current_drawdown"], -.2)
        second = self.commit("restart-new-model", T3, price=64, model_version="legitimate-new-model",
                             run_id="process-2", risk_state={"mode": "recovery", "episode_peak": 640})
        self.assertAlmostEqual(second["equity"], 640)
        self.assertAlmostEqual(second["high_water_nav"], 1)
        self.assertAlmostEqual(second["max_drawdown"], -.36)
        self.assertEqual(second["fund_shares"], 1000)
        self.assertEqual(len(second["model_history"]), 2)

    def test_external_flows_preserve_nav_and_income_changes_it(self):
        self.commit("fee", T1, [dict(id="fee", at=T1, kind="income", amount=-100, reason="fee")])
        after = self.commit("deposit", T2, [dict(id="deposit", at=T2, kind="cashflow", amount=900)])
        self.assertAlmostEqual(after["fund_shares"], 2000)
        self.assertAlmostEqual(after["unit_nav"], .9)
        self.assertAlmostEqual(after["current_drawdown"], -.1)
        events = [dict(id="withdraw", at=T3, kind="cashflow", amount=-450),
                  dict(id="dividend", at=T3, kind="income", amount=15, reason="dividend"),
                  dict(id="interest", at=T3, kind="income", amount=15, reason="interest")]
        final = self.commit("withdraw-income", T3, events)
        self.assertAlmostEqual(final["fund_shares"], 1500)
        self.assertAlmostEqual(final["unit_nav"], .92)
        self.assertAlmostEqual(final["max_drawdown"], -.1)
        self.assertAlmostEqual(final["external_flows_total"], 450)
        self.assertAlmostEqual(final["income_total"], -70)

    def test_batch_and_event_duplicates_do_not_double_book(self):
        event = dict(id="fee", at=T1, kind="income", amount=-10, reason="fee")
        first = self.commit("first", T1, [event])
        repeated = self.commit("first", T1, [event], run_id="restarted-process")
        self.assertEqual(first, repeated)
        cumulative_retry = self.commit("second", T2, [event])
        self.assertEqual(cumulative_retry["cash"], 990)
        self.assertEqual(cumulative_retry["event_cursor"], 1)
        self.assertEqual(self.journal.verify()["events"], 1)

    def test_changed_event_conflict_quarantines_without_partial_commit(self):
        event = dict(id="fee", at=T1, kind="income", amount=-10, reason="fee")
        self.commit("first", T1, [event])
        with self.assertRaisesRegex(FundJournalError, "changed payload"):
            self.commit("conflict", T2, [dict(event, amount=-20)])
        state = self.journal.read()
        self.assertEqual(state["cash"], 990)
        self.assertEqual(state["event_cursor"], 1)
        self.assertIsNotNone(state["blocked"])
        self.assertEqual(state["risk_mode"], "review_required")
        self.assertEqual(self.journal.verify()["records"], 2)

    def test_partial_gap_fill_records_remaining_position_and_actual_loss(self):
        self.commit("buy", T1, [dict(id="buy", at=T1, kind="fill", symbol="AAA", quantity=10, price=100)])
        partial = self.commit("partial-stop", T2,
            [dict(id="partial", at=T2, kind="fill", symbol="AAA", quantity=-3, price=60, fee=1)], price=60,
            risk_state={"mode": "exit_pending", "unfilled_quantity": 7})
        self.assertEqual(partial["positions"]["AAA"], 7)
        self.assertEqual(partial["cash"], 179)
        self.assertEqual(partial["equity"], 599)
        self.assertAlmostEqual(partial["current_drawdown"], -.401)
        self.assertEqual(partial["risk_state"]["unfilled_quantity"], 7)

    def test_unknown_cash_never_becomes_deposit_and_block_survives_restart(self):
        first = self.commit("reconcile", T1, expected_cash=1100)
        self.assertEqual(first["cash"], 1000)
        self.assertEqual(first["fund_shares"], 1000)
        self.assertIn("Unexplained cash", first["blocked"])
        self.journal.close()
        self.journal = FundJournal(self.path, SCOPE)
        after = self.commit("later-agreement", T2, expected_cash=1000)
        self.assertEqual(after["blocked"], first["blocked"])

    def test_scope_isolation_and_missing_marker_or_database_fail_closed(self):
        other = dict(SCOPE, scope_id="another-fund")
        with self.assertRaisesRegex(FundJournalError, "identity mismatch"):
            FundJournal(self.path, other)
        other_journal = FundJournal.create(Path(self.temp.name) / "other.sqlite", other, 50, T0)
        self.commit("fee", T1, [dict(id="fee", at=T1, kind="income", amount=-30, reason="fee")])
        self.assertEqual(other_journal.read()["unit_nav"], 1)
        other_journal.close()
        self.journal.close()
        self.journal = None
        self.path.unlink()
        with self.assertRaisesRegex(FundJournalError, "missing"):
            FundJournal(self.path, SCOPE)
        with self.assertRaisesRegex(FundJournalError, "never reset"):
            FundJournal.create(self.path, SCOPE, 1000, T0)

    def test_corrupt_state_or_event_cursor_never_initializes(self):
        self.commit("first", T1, [dict(id="fee", at=T1, kind="income", amount=-10, reason="fee")])
        self.journal.close()
        self.journal = None
        with sqlite3.connect(self.path) as db:
            db.execute("DELETE FROM events")
        db.close()
        with self.assertRaisesRegex(FundJournalError, "deduplication index"):
            FundJournal(self.path, SCOPE)

    def test_reordered_fact_fails_without_losing_last_valid_state(self):
        self.commit("valuation", T2)
        with self.assertRaisesRegex(FundJournalError, "order conflict"):
            self.commit("late-fill", T3, [dict(id="late", at=T1, kind="income", amount=1, reason="interest")])
        self.assertEqual(self.journal.read()["last_valuation_at"], "2020-01-03T16:00:00.000000+00:00")
        self.assertEqual(self.journal.read()["cash"], 1000)

    def test_cashflow_before_batch_requires_its_own_contemporaneous_prices(self):
        self.commit("buy", T1, [dict(id="buy", at=T1, kind="fill", symbol="AAA", quantity=5, price=100)])
        state = self.commit("funding", T3, [dict(id="deposit", at=T2, kind="cashflow", amount=450,
                                                   prices={"AAA": 80}, valuation_at=T2)], price=90)
        self.assertAlmostEqual(state["fund_shares"], 1500)
        self.assertAlmostEqual(state["unit_nav"], 1400 / 1500)
        self.assertAlmostEqual(state["max_drawdown"], -.1)

    def test_real_process_crash_before_commit_rolls_back_then_retry_matches(self):
        self.journal.close()
        self.journal = None
        script = r'''
import json, os, sys
from strategy_fund_journal import FundJournal
j=FundJournal(sys.argv[1],json.loads(sys.argv[2]))
original=j._write_record
def crash(*args,**kwargs):
    original(*args,**kwargs)
    os._exit(23)
j._write_record=crash
j.commit('buy','2020-01-02T16:00:00+00:00',
 [dict(id='buy',at='2020-01-02T16:00:00+00:00',kind='fill',symbol='AAA',quantity=5,price=100,fee=1)],
 {'AAA':80},{'pending':'remaining5'},'original-A','process-1')
'''
        run = subprocess.run([sys.executable, "-c", script, str(self.path), json.dumps(SCOPE)],
                             cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
        self.assertEqual(run.returncode, 23, run.stderr)
        self.journal = FundJournal(self.path, SCOPE)
        self.assertEqual(self.journal.read()["cash"], 1000)
        self.assertEqual(self.journal.read()["event_cursor"], 0)
        event = dict(id="buy", at=T1, kind="fill", symbol="AAA", quantity=5, price=100, fee=1)
        after = self.commit("buy", T1, [event], price=80, checkpoint={"pending": "remaining5"})
        self.assertEqual(after["cash"], 499)
        self.assertEqual(after["equity"], 899)
        self.journal.close()
        self.journal = FundJournal(self.path, SCOPE)
        self.assertEqual(self.journal.read(), after)
        retry = self.commit("buy", T1, [event], price=80, checkpoint={"pending": "remaining5"}, run_id="process-2")
        self.assertEqual(retry, after)
        self.assertEqual(list(self.journal.history())[0]["checkpoint"], {"pending": "remaining5"})


if __name__ == "__main__":
    unittest.main()
