"""IBKR 本地 TWS/IB Gateway 只读就绪探测；不含下单或设置修改接口。

只读客户端参数不是服务端权限证明，也不代表连接的是模拟账户。
账户身份、握手和数据请求分别记录；端口号只用来寻找本地服务。
"""

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
import json
import logging
import math
import os
import re
import socket
import subprocess


@dataclass(frozen=True)
class ReadonlyConfig:
    host: str = "127.0.0.1"
    ports: tuple = (7497, 4002, 7496, 4001)
    client_id: int = 9031  # 禁用 0，避免自动绑定手动订单。
    timeout: float = 4.0
    operation: str = "readonly_probe"
    expected_account: str | None = field(default=None, repr=False)
    expected_environment: str | None = None

    def validate(self):
        if self.operation != "readonly_probe" or self.host not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError("仅支持本机只读探测。")
        if not isinstance(self.client_id, int) or isinstance(self.client_id, bool) or self.client_id <= 0:
            raise ValueError("client_id 必须为非零正整数，不能绑定手动订单。")
        if not math.isfinite(self.timeout) or not 0 < self.timeout <= 20:
            raise ValueError("timeout 必须在 0 到 20 秒之间。")
        if not self.ports or len(set(self.ports)) != len(self.ports) or any(not isinstance(port, int) or not 1 <= port <= 65535 for port in self.ports):
            raise ValueError("端口列表非法。")
        if self.expected_environment not in (None, "paper", "live"):
            raise ValueError("未知账户环境配置。")


def client_availability():
    packages = {}
    for name in ("ib_async", "ibapi", "ib_insync", "aeventkit", "nest_asyncio", "tzdata"):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = None
    return dict(selected="ib_async", available=packages["ib_async"] is not None,
                official_sdk=False, versions=packages)


def probe_port(host, port, timeout=.35):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return dict(port=port, tcp_open=True)
    except OSError as exc:
        return dict(port=port, tcp_open=False, error_type=type(exc).__name__)


def probe_processes():
    if os.name != "nt":
        return dict(status="unavailable_on_this_platform", names=[])
    command = "@(Get-Process -Name tws,ibgateway,java,javaw -ErrorAction SilentlyContinue | Select-Object -ExpandProperty ProcessName) | ConvertTo-Json -Compress"
    try:
        completed = subprocess.run(["powershell", "-NoProfile", "-Command", command],
                                   capture_output=True, text=True, timeout=8,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        if completed.returncode != 0:
            return dict(status="probe_failed", names=[])
        value = json.loads(completed.stdout) if completed.stdout.strip() else []
        return dict(status="checked", names=[value] if isinstance(value, str) else value)
    except Exception as exc:
        return dict(status="probe_failed", error_type=type(exc).__name__, names=[])


def account_identity(accounts, config, handshake_complete):
    """只在明确配置、DU 响应和成功握手同时成立时确认纸面账户身份。"""
    if not handshake_complete:
        status = "no_handshake"
    elif not config.expected_account or not config.expected_environment:
        status = "unconfigured"
    elif config.expected_account not in accounts:
        status = "configured_account_not_in_response"
    elif config.expected_environment == "paper" and not re.fullmatch(r"DU\d+", config.expected_account):
        status = "paper_prefix_mismatch"
    elif config.expected_environment == "live" and config.expected_account.startswith("DU"):
        status = "live_configuration_conflicts_with_paper_prefix"
    else:
        status = "configured_identity_matches_response"
    paper = (status == "configured_identity_matches_response" and config.expected_environment == "paper")
    return dict(status=status, paper_confirmed=paper, configured_account_present=bool(config.expected_account and config.expected_account in accounts),
                port_used_as_account_evidence=False, trading_authorized=False)


@contextmanager
def quiet_client_logs():
    # ib_async 的连接/仓位日志可能含账户、数量和价格；本模块只返回白名单字段。
    previous = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        yield
    finally:
        logging.disable(previous)


def redacted_positions(positions, aliases):
    items = []
    for position in positions:
        if position.account not in aliases:
            raise ValueError("仓位响应包含未知账户。")
        contract = position.contract
        items.append(dict(account_alias=aliases[position.account], symbol=contract.symbol,
                          security_type=contract.secType, currency=contract.currency,
                          quantity="redacted", average_cost="omitted"))
    return dict(status="received", count=len(items), items=items)


def redacted_orders(orders, aliases):
    items = []
    for number, trade in enumerate(orders, 1):
        account = trade.order.account
        if account not in aliases:
            raise ValueError("开放订单响应包含未知账户。")
        items.append(dict(order_alias=f"order_{number}", account_alias=aliases[account],
                          symbol=trade.contract.symbol, action=trade.order.action,
                          status=trade.orderStatus.status, quantity="redacted", prices="omitted"))
    return dict(status="received", count=len(items), items=items,
                scope="one_time_all_open_orders_snapshot_not_a_subscription")


async def collect_connection(config, port, client_factory=None):
    from ib_async import StartupFetchNONE
    if client_factory is None:
        from ib_async import IB
        client_factory = IB
    ib = client_factory()
    result = dict(port=port, status="not_connected", handshake_complete=False,
                  client_readonly_requested=True, server_readonly_setting="not_verified",
                  account_identity=account_identity([], config, False), accounts=None,
                  positions=None, open_orders=None, server_time_utc=None, errors=[])
    with quiet_client_logs():
        try:
            # 非零 client ID；关闭资金、子账户及成交记录的自动拉取。
            # 当前 ib_async 2.1.0 仍自动同步 positions，故同步错误必须抛出。
            await ib.connectAsync(config.host, port, clientId=config.client_id,
                                  timeout=config.timeout, readonly=True, raiseSyncErrors=True, fetchFields=StartupFetchNONE)
            if not ib.isConnected() or not ib.client.isReady():
                raise ConnectionError("握手没有完成。")
            result["handshake_complete"] = True
            result["server_version"] = ib.client.serverVersion()
            accounts = list(ib.managedAccounts())
            if not accounts or len(set(accounts)) != len(accounts) or any(not isinstance(account, str) or not account for account in accounts):
                raise ValueError("账户响应为空或不可信。")
            aliases = {account: f"account_{j + 1}" for j, account in enumerate(sorted(accounts))}
            result["accounts"] = [dict(alias=aliases[account], has_DU_prefix=bool(re.fullmatch(r"DU\d+", account))) for account in sorted(accounts)]
            result["account_identity"] = account_identity(accounts, config, True)
            if config.expected_account and result["account_identity"]["status"] != "configured_identity_matches_response":
                result["status"] = "connected_identity_mismatch"
                return result
            for stage, request, serialize in (
                ("server_time_utc", ib.reqCurrentTimeAsync, lambda value: value.astimezone(timezone.utc).isoformat()),
                ("positions", ib.reqPositionsAsync, lambda value: redacted_positions(value, aliases)),
                ("open_orders", ib.reqAllOpenOrdersAsync, lambda value: redacted_orders(value, aliases)),
            ):
                try:
                    result[stage] = serialize(await asyncio.wait_for(request(), timeout=config.timeout))
                except Exception as exc:
                    # 不记录原始错误文本，避免泄露账号或资金；未知响应不伪装为空仓。
                    result["errors"].append(dict(stage=stage, error_type=type(exc).__name__))
            result["status"] = "connected_readonly_snapshot" if not result["errors"] else "connected_partial_snapshot"
        except Exception as exc:
            result["errors"].append(dict(stage="handshake_or_account_sync", error_type=type(exc).__name__))
            result["status"] = "connected_partial_snapshot" if result["handshake_complete"] else "not_connected"
        finally:
            ib.disconnect()
    return result


def check_readiness(config=None, *, port_probe=probe_port, process_probe=probe_processes,
                    client_factory=None, availability_probe=client_availability):
    config = config or ReadonlyConfig()
    config.validate()
    availability = availability_probe()
    ports = [port_probe(config.host, port) for port in config.ports]
    report = dict(checked_at_utc=datetime.now(timezone.utc).isoformat(), operation="readonly_probe",
                  client=availability, processes=process_probe(), host=config.host, ports=ports,
                  connection_attempts=[], status="not_connected", orders_sent=0,
                  account_identifiers="masked_by_ephemeral_alias", sensitive_values="not_collected_or_redacted",
                  server_readonly_setting="not_verified", paper_account_confirmed=False,
                  market_data_permissions="not_tested_no_market_data_requested",
                  limitations=["TCP open alone is not an API handshake.",
                               "readonly=True does not establish TWS server permissions or paper/live account type.",
                               "Free delayed quotes do not establish live or historical data entitlements.",
                               "No authentication, settings changes, order submission, or cancellation methods are provided."])
    open_ports = [item["port"] for item in ports if item["tcp_open"]]
    if not open_ports:
        report["blocker"] = "no_local_candidate_tcp_listener"
        return report
    if not availability["available"]:
        report["blocker"] = "selected_python_client_not_installed"
        return report
    for port in open_ports:
        attempt = asyncio.run(collect_connection(config, port, client_factory))
        report["connection_attempts"].append(attempt)
        if attempt["handshake_complete"]:
            report["status"] = attempt["status"]
            report["paper_account_confirmed"] = attempt["account_identity"]["paper_confirmed"]
            break
    if report["status"] == "not_connected":
        report["blocker"] = "tcp_service_found_but_no_verified_api_handshake"
    return report
