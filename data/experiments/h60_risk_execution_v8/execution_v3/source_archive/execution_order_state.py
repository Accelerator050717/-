"""单个订单的离线状态归并原型；没有网络、下单、撤单或账户接口。

输入必须是外部适配器已核验身份的事件。这里检验不确定性、回报去重
与成交账本规则，不声称实现券商端 exactly-once、事务持久化或资金风控。
"""

from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
import json


def positive_decimal(value):
    try:
        value = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("数值格式非法。") from exc
    if not value.is_finite() or value <= 0:
        raise ValueError("数值必须为有限正数。")
    return value


@dataclass
class OrderState:
    intent_key: str
    symbol: str
    side: str
    quantity: str
    attempted: bool = False
    broker_reference: str | None = None
    uncertain: bool = False
    cancel_requested: bool = False
    terminal_status: str | None = None
    reported_filled: str = "0"
    executions: dict = field(default_factory=dict)
    halted_reason: str | None = None

    def __post_init__(self):
        if not self.intent_key or not self.symbol or self.side not in ("BUY", "SELL"):
            raise ValueError("本地意图缺少身份字段。")
        self.quantity = str(positive_decimal(self.quantity))

    @property
    def filled(self):
        return sum((Decimal(row["quantity"]) for row in self.executions.values()), Decimal(0))

    @property
    def cash_delta_before_fees(self):
        value = sum((Decimal(row["quantity"]) * Decimal(row["price"]) for row in self.executions.values()), Decimal(0))
        return -value if self.side == "BUY" else value

    @property
    def status(self):
        if self.halted_reason:
            return "HALTED"
        if self.filled == Decimal(self.quantity):
            return "FILLED"
        if self.uncertain:
            return "UNKNOWN_REQUIRES_RECONCILIATION"
        if Decimal(self.reported_filled) > self.filled:
            return "AWAITING_EXECUTION_DETAILS"
        if self.terminal_status:
            return self.terminal_status
        if self.cancel_requested:
            return "CANCEL_PENDING"
        if self.filled:
            return "PARTIALLY_FILLED"
        return "ACKNOWLEDGED" if self.broker_reference else "SUBMIT_PENDING" if self.attempted else "INTENT"

    def begin_attempt(self):
        # 未来网络适配器必须先持久化 attempted，再发送；本原型只变更内存状态。
        if self.attempted or self.halted_reason or self.terminal_status:
            raise ValueError("此意图已尝试或终止；禁止自动重新发送。")
        self.attempted = True
        self.uncertain = True

    def mark_disconnected(self):
        if not self.attempted:
            raise ValueError("尚未尝试提交。")
        self.uncertain = True

    def acknowledge(self, reference):
        if not self.attempted or not isinstance(reference, str) or not reference:
            raise ValueError("确认缺少有效意图或订单引用。")
        if self.broker_reference and self.broker_reference != reference:
            self.halted_reason = "conflicting_broker_reference"
            raise ValueError("同一意图对应了冲突的券商订单。")
        self.broker_reference = reference
        # 首次确认可结束提交不确定状态；重连仍须完整快照核对。

    def record_execution(self, execution_id, reference, quantity, price, *, correction=False):
        if self.halted_reason or not self.attempted or not self.broker_reference or reference != self.broker_reference:
            raise ValueError("成交身份未匹配或订单已隔离。")
        if not isinstance(execution_id, str) or not execution_id:
            raise ValueError("缺少成交ID。")
        # 仅作为单股票回报原型：IBKR 更正可只改变最后一个点后的数字。
        # 不把更正记为另一笔成交，也不在这里自动改写旧账；组合订单未支持。
        base, separator, revision = execution_id.rpartition(".")
        revised_known_id = separator and revision.isdigit() and any(
            old.rpartition(".")[0] == base and old != execution_id for old in self.executions)
        if correction or revised_known_id:
            self.halted_reason = "execution_correction_requires_reconciliation"
            raise ValueError("成交更正需要核对原账，不能累计为新的成交。")
        quantity, price = positive_decimal(quantity), positive_decimal(price)
        record = {"reference": reference, "quantity": format(quantity.normalize(), "f"),
                  "price": format(price.normalize(), "f")}
        if execution_id in self.executions:
            if self.executions[execution_id] != record:
                self.halted_reason = "conflicting_execution_id"
                raise ValueError("同一成交ID出现冲突；不得重复记账或静默更正。")
            return False
        if self.filled + quantity > Decimal(self.quantity):
            self.halted_reason = "overfill_or_unhandled_execution_correction"
            raise ValueError("累计成交超过意图数量；需核对更正回报。")
        self.executions[execution_id] = record
        return True

    def observe_status(self, reference, status, cumulative_filled):
        if self.halted_reason or not self.broker_reference or reference != self.broker_reference:
            raise ValueError("状态回报身份未匹配。")
        if status not in {"Submitted", "PreSubmitted", "PendingCancel", "Cancelled", "ApiCancelled", "Filled", "Inactive"}:
            raise ValueError("未实现的状态不能自行解释。")
        count = Decimal(str(cumulative_filled))
        if not count.is_finite() or count < 0 or count > Decimal(self.quantity):
            raise ValueError("累计成交数量非法。")
        # 迟到状态不能让已知成交倒退；状态回报本身不改现金/股数。
        self.reported_filled = str(max(Decimal(self.reported_filled), count))
        if status in ("Cancelled", "ApiCancelled"):
            self.terminal_status = "CANCELLED"
        elif status == "Inactive":
            self.halted_reason = "inactive_requires_reason_and_reconciliation"
        elif status == "Filled" and count != Decimal(self.quantity):
            self.halted_reason = "filled_status_quantity_mismatch"
        if status == "PendingCancel":
            self.cancel_requested = True

    def request_cancel_locally(self):
        if not self.attempted or self.halted_reason or self.terminal_status or self.filled == Decimal(self.quantity):
            raise ValueError("不能对未提交、已成交或已终止意图记录撤单请求。")
        self.cancel_requested = True

    def reconcile(self, *, snapshot_complete, open_references, terminal_reference=None,
                  terminal_status=None, total_executed=None):
        # “不在开放订单里”不证明从未提交：它也可能已成交、已撤销或快照不全。
        if self.halted_reason or not snapshot_complete or not self.broker_reference:
            self.uncertain = True
            return False
        if total_executed is None or Decimal(str(total_executed)) != self.filled:
            self.uncertain = True
            return False
        if self.broker_reference in open_references:
            if self.terminal_status or self.filled == Decimal(self.quantity):
                self.halted_reason = "open_and_terminal_snapshot_conflict"
                return False
            self.uncertain = False
            return True
        if terminal_reference != self.broker_reference or terminal_status not in ("Filled", "Cancelled", "ApiCancelled"):
            self.uncertain = True
            return False
        self.observe_status(terminal_reference, terminal_status, total_executed)
        if terminal_status == "Filled" and self.filled != Decimal(self.quantity):
            self.uncertain = True
            return False
        self.uncertain = False
        return True

    def to_json(self):
        return json.dumps(asdict(self), sort_keys=True, allow_nan=False)

    @classmethod
    def from_json(cls, text):
        result = cls(**json.loads(text))
        if result.filled > Decimal(result.quantity) or (result.executions and not result.attempted):
            raise ValueError("保存的成交记录与意图冲突。")
        for item in result.executions.values():
            positive_decimal(item["quantity"])
            positive_decimal(item["price"])
            if item["reference"] != result.broker_reference:
                raise ValueError("保存的成交引用不一致。")
        return result
