"""人工构造 IBKR 响应；这些测试不代表真实连接或真实账户验证。"""

import asyncio
from datetime import datetime, timezone
import json
from types import SimpleNamespace as NS
import unittest

from ibkr_readonly import ReadonlyConfig, account_identity, check_readiness


class FakeIB:
    """只实现白名单只读方法；任何意外的其他方法调用都会让测试失败。"""
    def __init__(self, ready=True, timeout_orders=False, unknown_position=False):
        self.client = NS(isReady=lambda: ready, serverVersion=lambda: 178)
        self.ready = ready
        self.timeout_orders = timeout_orders
        self.unknown_position = unknown_position
        self.disconnected = False
        self.calls = []

    async def connectAsync(self, host, port, **kwargs):
        self.calls.append(("connect", kwargs))
        assert kwargs["readonly"] is True
        assert kwargs["clientId"] > 0
        assert kwargs["fetchFields"].value == 0
        assert kwargs["raiseSyncErrors"] is True

    def isConnected(self):
        return self.ready

    def managedAccounts(self):
        return ["DU1234567"]

    async def reqCurrentTimeAsync(self):
        self.calls.append(("server_time", {}))
        return datetime(2025, 1, 2, 15, tzinfo=timezone.utc)

    async def reqPositionsAsync(self):
        self.calls.append(("positions", {}))
        return [NS(account="U9999999" if self.unknown_position else "DU1234567",
                   contract=NS(symbol="FICTITIOUS", secType="STK", currency="USD"),
                   position=9876.54321, avgCost=54321.12345)]

    async def reqAllOpenOrdersAsync(self):
        self.calls.append(("open_orders", {}))
        if self.timeout_orders:
            raise asyncio.TimeoutError("DU1234567 private account text must not leak")
        return [NS(order=NS(account="DU1234567", action="BUY", totalQuantity=78910),
                   contract=NS(symbol="FICTITIOUS"), orderStatus=NS(status="Submitted"))]

    def disconnect(self):
        self.disconnected = True


class ReadonlyReadinessTests(unittest.TestCase):
    def run_probe(self, fake=None, **changes):
        fake = fake or FakeIB()
        kwargs = dict(client_factory=lambda: fake,
                      port_probe=lambda host, port: {"port": port, "tcp_open": True},
                      process_probe=lambda: {"status": "synthetic", "names": []},
                      availability_probe=lambda: {"available": True, "selected": "synthetic_test_client"})
        kwargs.update(changes)
        report = check_readiness(ReadonlyConfig(ports=(7497,)), **kwargs)
        return report, fake

    def test_no_listener_does_not_attempt_handshake(self):
        report, fake = self.run_probe(port_probe=lambda host, port: {"port": port, "tcp_open": False})
        self.assertEqual(report["status"], "not_connected")
        self.assertEqual(report["blocker"], "no_local_candidate_tcp_listener")
        self.assertEqual(fake.calls, [])

    def test_missing_client_keeps_connection_unavailable(self):
        report, fake = self.run_probe(availability_probe=lambda: {"available": False})
        self.assertEqual(report["blocker"], "selected_python_client_not_installed")
        self.assertEqual(fake.calls, [])

    def test_tcp_open_without_handshake_is_not_connected(self):
        report, fake = self.run_probe(FakeIB(ready=False))
        self.assertEqual(report["status"], "not_connected")
        self.assertFalse(report["paper_account_confirmed"])
        self.assertTrue(fake.disconnected)

    def test_only_readonly_calls_and_default_redaction(self):
        report, fake = self.run_probe()
        self.assertEqual(report["status"], "connected_readonly_snapshot")
        self.assertFalse(report["paper_account_confirmed"])
        text = json.dumps(report)
        for secret in ("DU1234567", "9876.54321", "54321.12345", "78910"):
            self.assertNotIn(secret, text)
        self.assertEqual([call[0] for call in fake.calls], ["connect", "server_time", "positions", "open_orders"])
        self.assertTrue(fake.disconnected)

    def test_paper_identity_requires_all_evidence(self):
        account = "DU1234567"
        good = ReadonlyConfig(expected_account=account, expected_environment="paper")
        self.assertTrue(account_identity([account], good, True)["paper_confirmed"])
        self.assertFalse(account_identity([account], good, False)["paper_confirmed"])
        self.assertFalse(account_identity(["DU0000"], good, True)["paper_confirmed"])
        self.assertFalse(account_identity([account], ReadonlyConfig(ports=(7497,)), True)["paper_confirmed"])
        wrong = ReadonlyConfig(expected_account="U1234567", expected_environment="paper")
        self.assertFalse(account_identity(["U1234567"], wrong, True)["paper_confirmed"])

    def test_timeout_or_unknown_account_does_not_become_empty_snapshot(self):
        for fake in (FakeIB(timeout_orders=True), FakeIB(unknown_position=True)):
            report, fake = self.run_probe(fake)
            self.assertEqual(report["status"], "connected_partial_snapshot")
            self.assertTrue(report["connection_attempts"][0]["errors"])
            self.assertNotIn("DU1234567", json.dumps(report))

    def test_zero_client_remote_host_and_other_operations_rejected(self):
        for config in (ReadonlyConfig(client_id=0), ReadonlyConfig(host="example.com"),
                       ReadonlyConfig(operation="trade")):
            with self.assertRaises(ValueError):
                check_readiness(config, port_probe=lambda *_: self.fail("must reject before probe"))


if __name__ == "__main__":
    unittest.main()
