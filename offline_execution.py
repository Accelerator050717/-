"""仅供历史工程回放的执行闭环；没有券商连接或真实下单接口。

prices 是供应商调整开盘收益代理，units 不是当年的真实股数。
asof/日期使用纽约交易日；方法分别固定在收盘评分或下一交易日开盘。
原子提交只保证本地账本一致性，不模拟券商网络请求的外部双写问题。
"""

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import uuid

import numpy as np

from research_backtest import _rebalance


class ReplayBlocked(ValueError):
    """输入、持久化状态或时序不可信，拒绝继续执行。"""


def digest(value):
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ReplayExecutor:
    def __init__(self, state_path, calendar, symbols, feature_names, model_path,
                 expected_model_sha256, initial_cash=10000.0, cost_bps=10.0,
                 mode="historical_replay"):
        self.path = Path(state_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_path = self.path.with_suffix(".lock")
        self.initialized_path = self.path.with_suffix(".initialized")
        self.blocked_path = self.path.parent / "blocked_requests.jsonl"
        self.blocked_path.touch(exist_ok=True)
        self.calendar = list(calendar)
        self.symbols = list(symbols)
        self.features = list(feature_names)
        self.model_path = Path(model_path)
        self.spec = dict(mode=mode, calendar_sha256=digest(self.calendar), symbols=self.symbols,
                         feature_names=self.features, model_sha256=expected_model_sha256,
                         initial_cash=float(initial_cash), cost_bps=float(cost_bps),
                         position_limit=0.2, price_basis="supplier_adjusted_open_proxy")
        try:
            if mode != "historical_replay":
                raise ReplayBlocked("仅接受 historical_replay；没有真实下单接口。")
            if (not self.calendar or self.calendar != sorted(set(self.calendar))
                    or any(datetime.strptime(day, "%Y-%m-%d").strftime("%Y-%m-%d") != day for day in self.calendar)):
                raise ReplayBlocked("需要完整、唯一、升序的纽约交易日历。")
            if (not self.symbols or len(set(self.symbols)) != len(self.symbols)
                    or not self.features or len(set(self.features)) != len(self.features)):
                raise ReplayBlocked("股票和特征必须非空且唯一。")
            if not np.isfinite(initial_cash) or initial_cash <= 0 or not np.isfinite(cost_bps) or not 0 <= cost_bps < 10000:
                raise ReplayBlocked("初始资金或费用非法。")
            self._verify_model()
            with self._locked():
                if self.initialized_path.exists():
                    if self.initialized_path.read_text(encoding="utf-8") != digest(self.spec):
                        raise ReplayBlocked("初始化标记与冻结配置不符。")
                    if not self.path.exists():
                        raise ReplayBlocked("曾初始化的账本文件缺失，禁止重置资金或自动重下。")
                if self.path.exists():
                    self._read()
                else:
                    state = dict(version=1, spec=self.spec, cash=float(initial_cash),
                                 positions={symbol: 0.0 for symbol in self.symbols},
                                 targets={}, processed_keys={}, fills=[], events=[], snapshots={}, clock=None)
                    # 标记先落盘：中断后的未知初始化状态也应拒绝自动重建资金。
                    with self.initialized_path.open("x", encoding="utf-8") as handle:
                        handle.write(digest(self.spec))
                        handle.flush()
                        os.fsync(handle.fileno())
                    self._commit(state)
                if not self.initialized_path.exists():
                    # 兼容本次开发中已核对的现有账本；不修改金融状态。
                    self.initialized_path.write_text(digest(self.spec), encoding="utf-8")
        except Exception as exc:
            self._log_blocked("initialize", str(exc))
            raise

    @contextmanager
    def _locked(self):
        try:
            fd = os.open(self.lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        except FileExistsError as exc:
            raise ReplayBlocked("账本锁已存在；并发或崩溃状态未知，禁止自动重试交易。") from exc
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(str(os.getpid()))
            yield
        finally:
            self.lock_path.unlink()

    def _verify_model(self):
        actual = hashlib.sha256(self.model_path.read_bytes()).hexdigest()
        if actual != self.spec["model_sha256"]:
            raise ReplayBlocked("冻结模型 SHA256 不符。")

    def _log_blocked(self, action, reason):
        entry = dict(utc=datetime.now(timezone.utc).isoformat(), action=action, reason=reason)
        with self.blocked_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _validate_account(self, state):
        if state["spec"] != self.spec or set(state["positions"]) != set(self.symbols):
            raise ReplayBlocked("状态配置与冻结回放定义不符。")
        cash = self.spec["initial_cash"]
        positions = {symbol: 0.0 for symbol in self.symbols}
        ids = set()
        for fill in state["fills"]:
            symbol = fill["symbol"]
            if symbol not in positions or fill["order_id"] in ids:
                raise ReplayBlocked("成交股票未知或订单 ID 重复。")
            ids.add(fill["order_id"])
            price, units, notional, fee = (fill[name] for name in ("price", "signed_units", "signed_notional", "fee"))
            if (not np.isfinite([price, units, notional, fee]).all() or price <= 0
                    or not np.isclose(notional, price * units, rtol=1e-12, atol=1e-9)
                    or not np.isclose(fee, abs(notional) * self.spec["cost_bps"] / 10000, rtol=1e-12, atol=1e-9)):
                raise ReplayBlocked("成交价格、金额或费用账本不一致。")
            positions[symbol] += units
            cash -= notional + fee
        if (not np.isfinite(state["cash"]) or state["cash"] < -1e-10
                or not np.isclose(cash, state["cash"], rtol=0, atol=1e-8)):
            raise ReplayBlocked("现金与成交账本不一致或现金为负。")
        for symbol, units in state["positions"].items():
            if not np.isfinite(units) or units < -1e-10 or not np.isclose(units, positions[symbol], rtol=1e-11, atol=1e-9):
                raise ReplayBlocked("持仓与成交账本不一致或存在卖空。")
        for key, processed in state["processed_keys"].items():
            if key not in state["targets"] or processed["intent_hash"] != state["targets"][key]["intent_hash"]:
                raise ReplayBlocked("已处理键与目标意图不一致。")
            actual_ids = [fill["order_id"] for fill in state["fills"] if fill["batch_key"] == key]
            if actual_ids != processed["order_ids"]:
                raise ReplayBlocked("已处理键与成交订单集合不一致。")
        if any(fill["batch_key"] not in state["processed_keys"] for fill in state["fills"]):
            raise ReplayBlocked("存在未登记处理键的成交。")

    def _read(self):
        state = json.loads(self.path.read_text(encoding="utf-8"))
        recorded_hash = state.pop("state_hash", None)
        if recorded_hash != digest(state):
            raise ReplayBlocked("状态文件完整性校验失败。")
        self._validate_account(state)
        return state

    def _commit(self, state):
        self._validate_account(state)
        sealed = {**state, "state_hash": digest(state)}
        temporary = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("x", encoding="utf-8") as handle:
                json.dump(sealed, handle, ensure_ascii=False, indent=2, allow_nan=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _operate(self, action, callback):
        try:
            with self._locked():
                self._verify_model()
                # 每次在锁内重新读磁盘，两个实例不能用缓存旧状态互相覆盖。
                state = self._read()
                changed, result = callback(state)
                if changed:
                    state["version"] += 1
                    self._commit(state)
                return result
        except Exception as exc:
            self._log_blocked(action, str(exc))
            raise

    def read_state(self):
        return self._operate("read_state", lambda state: (False, deepcopy(state)))

    def _day(self, date, asof):
        if date not in self.calendar or asof != date:
            raise ReplayBlocked("未知交易日或 asof 过期；不填价、不移动日期。")
        return self.calendar.index(date)

    def _prices(self, prices):
        if set(prices) != set(self.symbols):
            raise ReplayBlocked("需要固定全股票池的完整调整开盘价。")
        values = np.array([prices[symbol] for symbol in self.symbols], dtype=float)
        if not np.isfinite(values).all() or (values <= 0).any():
            raise ReplayBlocked("价格缺失、非有限或非正，拒绝成交。")
        return values

    def _advance(self, state, date, phase):
        now = [self.calendar.index(date), 0 if phase == "open" else 1]
        if state["clock"] is not None and now < state["clock"]:
            raise ReplayBlocked("不能在已有状态之后倒退执行新的历史事件。")
        state["clock"] = now

    @staticmethod
    def _event(state, kind, **values):
        event = dict(event_id=len(state["events"]) + 1, kind=kind, **values)
        state["events"].append(event)
        return event

    def submit_target(self, batch_key, observed_date, asof, weights, feature_order):
        """只记录收盘后可知的目标；此方法不接收任何未来成交价格。"""
        def submit(state):
            position = self._day(observed_date, asof)
            if not isinstance(batch_key, str) or not batch_key or position + 1 >= len(self.calendar):
                raise ReplayBlocked("批次键为空或没有下一交易日。")
            if list(feature_order) != self.features:
                raise ReplayBlocked("特征列顺序与冻结模型不符。")
            if not set(weights).issubset(self.symbols):
                raise ReplayBlocked("目标包含未知股票。")
            full = {symbol: float(weights.get(symbol, 0.0)) for symbol in self.symbols}
            values = np.array(list(full.values()))
            if (not np.isfinite(values).all() or (values < 0).any()
                    or (values > 0.2 + 1e-12).any() or values.sum() > 1 + 1e-12):
                raise ReplayBlocked("禁止负权重、单股超过20%或目标总权重超过100%。")
            intent = dict(batch_key=batch_key, observed_date=observed_date, asof=asof,
                          execution_date=self.calendar[position + 1], weights=full,
                          model_sha256=self.spec["model_sha256"], feature_order=list(feature_order))
            intent["intent_hash"] = digest(intent)
            if batch_key in state["targets"]:
                if state["targets"][batch_key] != intent:
                    raise ReplayBlocked("同批次键对应不同目标，禁止覆盖或重下。")
                return False, dict(status="already_recorded", intent_hash=intent["intent_hash"])
            self._advance(state, observed_date, "close")
            state["targets"][batch_key] = intent
            self._event(state, "target", **intent, phase="close")
            return True, dict(status="recorded", intent_hash=intent["intent_hash"])
        return self._operate("submit_target", submit)

    def fill_next_open(self, batch_key, execution_date, asof, prices):
        """仅在目标观察日的下一 session 开盘进行本地虚拟成交。"""
        def execute(state):
            self._day(execution_date, asof)
            price = self._prices(prices)
            if batch_key not in state["targets"]:
                raise ReplayBlocked("没有已观察并持久化的目标，禁止成交。")
            intent = state["targets"][batch_key]
            if execution_date != intent["execution_date"]:
                raise ReplayBlocked("成交必须发生在目标观察日的确切下一交易日开盘。")
            request_hash = digest(dict(batch_key=batch_key, date=execution_date, prices=price.tolist(), asof=asof))
            if batch_key in state["processed_keys"]:
                if state["processed_keys"][batch_key]["request_hash"] != request_hash:
                    raise ReplayBlocked("同成交键对应不同成交请求，禁止重下。")
                return False, dict(status="already_filled", new_fills=0, batch_key=batch_key)
            if execution_date in state["snapshots"]:
                raise ReplayBlocked("该开盘账户快照已封存，不能在其后插入新成交。")
            self._advance(state, execution_date, "open")
            old = np.array([state["positions"][symbol] for symbol in self.symbols]) * price
            weights = np.array([intent["weights"][symbol] for symbol in self.symbols])
            target, cash, changes, total_fee = _rebalance(old, state["cash"], weights, self.spec["cost_bps"] / 10000)
            if cash < -1e-10 or (target < 0).any() or (target > (target.sum() + cash) * (0.2 + 1e-11)).any():
                raise ReplayBlocked("模拟成交后持仓或现金违反限制。")
            order_ids = []
            for j in np.flatnonzero(changes != 0):
                symbol = self.symbols[j]
                order_id = digest(dict(intent_hash=intent["intent_hash"], symbol=symbol))
                order = dict(order_id=order_id, batch_key=batch_key, intent_hash=intent["intent_hash"],
                             date=execution_date, phase="open", symbol=symbol,
                             signed_units=float(changes[j] / price[j]), signed_notional=float(changes[j]),
                             price=float(price[j]), fee=float(abs(changes[j]) * self.spec["cost_bps"] / 10000))
                self._event(state, "simulated_order", **order)
                self._event(state, "fill", **order)
                state["fills"].append(order)
                order_ids.append(order_id)
            state["cash"] = float(cash)
            state["positions"] = {symbol: float(target[j] / price[j]) for j, symbol in enumerate(self.symbols)}
            state["processed_keys"][batch_key] = dict(intent_hash=intent["intent_hash"], request_hash=request_hash, order_ids=order_ids)
            self._event(state, "reconcile_after_fill", batch_key=batch_key, date=execution_date,
                        cash=cash, nav=float(target.sum() + cash), batch_fee=total_fee)
            # 整批 orders/fills/processed_keys/现金/持仓经核对后一次提交。
            return True, dict(status="filled", new_fills=len(order_ids), batch_key=batch_key)
        return self._operate("fill_next_open", execute)

    def reconcile_snapshot(self, date, asof, prices):
        def snapshot(state):
            self._day(date, asof)
            price = self._prices(prices)
            price_hash = digest(price.tolist())
            if any(target["execution_date"] <= date and key not in state["processed_keys"]
                   for key, target in state["targets"].items()):
                raise ReplayBlocked("存在到期但尚未成交的目标，不能先封存账户快照。")
            if date in state["snapshots"]:
                if state["snapshots"][date]["price_hash"] != price_hash:
                    raise ReplayBlocked("同日快照的价格改变，拒绝覆盖。")
                return False, deepcopy(state["snapshots"][date])
            self._advance(state, date, "open")
            values = {symbol: state["positions"][symbol] * float(price[j]) for j, symbol in enumerate(self.symbols)}
            result = dict(date=date, phase="open", asof=asof, price_hash=price_hash,
                          cash=state["cash"], positions=deepcopy(state["positions"]), position_values=values,
                          nav=float(state["cash"] + sum(values.values())),
                          cumulative_fees=float(sum(fill["fee"] for fill in state["fills"])),
                          reconciliation="cash_and_units_match_fill_ledger")
            state["snapshots"][date] = result
            self._event(state, "daily_reconcile", **result)
            return True, deepcopy(result)
        return self._operate("reconcile_snapshot", snapshot)
