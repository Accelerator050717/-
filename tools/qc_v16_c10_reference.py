"""Value original C10 executions using the observer's existing SPY close marks.

This is a cash/quantity reference ledger, not an algorithm: no orders, History,
optimization or additional market-data subscription. Executions are the original
QC C10 user-generated records. Provider dividend distributions and close prices
are consumed in cloud; only reference account results are returned.
"""
from decimal import Decimal
import hashlib
import json


ORIGINAL_BACKTEST = "0d921feb058a7e18dac120f1d27097b8"
EXECUTION_FIELDS = ("fill_date", "ui_row", "quantity", "fill_price")
# Populated only from the original C10 UI evidence before the one allowed replay.
ORIGINAL_EXECUTIONS = [
    [
        "2022-01-05",
        1,
        188,
        "477.25"
    ],
    [
        "2022-02-03",
        2,
        1,
        "450.93"
    ],
    [
        "2022-03-03",
        3,
        1,
        "440.59"
    ],
    [
        "2022-04-04",
        4,
        -1,
        "453.20"
    ],
    [
        "2022-05-04",
        5,
        2,
        "417.13"
    ],
    [
        "2022-07-06",
        6,
        3,
        "382.07"
    ],
    [
        "2022-08-02",
        7,
        -2,
        "409.03"
    ],
    [
        "2022-09-06",
        8,
        1,
        "393.13"
    ],
    [
        "2022-10-05",
        9,
        2,
        "373.32"
    ],
    [
        "2022-11-02",
        10,
        -1,
        "383.96"
    ],
    [
        "2022-12-02",
        11,
        -1,
        "402.14"
    ],
    [
        "2023-01-05",
        12,
        2,
        "381.76"
    ],
    [
        "2023-02-02",
        13,
        -1,
        "414.83"
    ],
    [
        "2023-03-03",
        14,
        1,
        "399.56"
    ],
    [
        "2023-05-02",
        15,
        -1,
        "414.78"
    ],
    [
        "2023-08-02",
        16,
        -1,
        "453.30"
    ],
    [
        "2023-10-04",
        17,
        2,
        "422.06"
    ],
    [
        "2023-12-04",
        18,
        -1,
        "455.60"
    ],
    [
        "2023-12-29",
        19,
        -194,
        "476.47"
    ]
]
EXECUTION_EVIDENCE_SHA256 = '78beab4ef11c41adf38ccfc02f31f319bd6d468f96b5a4418e8683f4aa20e18b'


def dec(value):
    return Decimal(str(value))


def verify_original_executions(executions):
    if len(executions) != 19:
        raise ValueError("C10 requires all 19 original filled orders")
    if len({row[1] for row in executions}) != 19:
        raise ValueError("Duplicate original C10 UI row")
    if executions != sorted(executions, key=lambda row: (row[0], row[1])):
        raise ValueError("Original C10 fill dates are not ordered")
    quantity = 0
    notional = signed = Decimal(0)
    buys = 0
    for date, ui_row, shares, price in executions:
        if not ("2022-01-01" <= date <= "2023-12-29"):
            raise ValueError("C10 execution outside fixed evaluation years")
        if not isinstance(shares, int) or shares == 0 or dec(price) <= 0:
            raise ValueError("Invalid C10 original execution")
        quantity += shares
        if quantity < 0:
            raise ValueError("Original C10 reference would be short")
        notional += abs(dec(shares) * dec(price))
        signed += dec(shares) * dec(price)
        buys += shares > 0
    if quantity != 0 or buys != 10:
        raise ValueError("C10 final quantity or buy/sell counts differ")
    if notional != dec("191973.01") or -signed != dec("489.09"):
        raise ValueError("Original C10 displayed executions do not reproduce exact notional/trade cash")
    return {"fills": len(executions), "buy_fills": buys, "sell_fills": 19 - buys,
            "notional": float(notional), "fees": float(notional / 1000),
            "net_trade_cash_before_fees": float(-signed), "final_quantity": quantity}


class C10Reference:
    def __init__(self):
        self.identity_check = verify_original_executions(ORIGINAL_EXECUTIONS)
        self.executions = list(ORIGINAL_EXECUTIONS)
        self.cursor = 0
        self.quantity = 0
        self.cash = dec(100000)
        self.fees = Decimal(0)
        self.dividends = Decimal(0)
        self.last_date = None
        self.dividend_dates = set()
        self.months = {}
        self.last_equity = dec(100000)
        self.daily_rows = 0

    def observe_dividend(self, date, distribution):
        """Call before close() on the engine dividend date, using prior shares."""
        if not ("2022-01-01" <= date <= "2023-12-31"):
            return
        if date in self.dividend_dates:
            raise ValueError("Duplicate SPY dividend date in C10 reference")
        if self.last_date is not None and date <= self.last_date:
            raise ValueError("Late SPY dividend after reference close")
        self.dividend_dates.add(date)
        credit = self.quantity * dec(distribution)
        self.cash += credit
        self.dividends += credit

    def close(self, date, close_price, mark_date):
        """Consume unchanged original fills, then value at that regular close."""
        if not ("2022-01-01" <= date <= "2023-12-31"):
            return
        if self.last_date is not None and date <= self.last_date:
            raise ValueError("Duplicate/out-of-order reference close")
        if mark_date != date or dec(close_price) <= 0:
            raise ValueError("Missing current regular-close SPY mark")
        while self.cursor < len(self.executions) and self.executions[self.cursor][0] <= date:
            fill_date, _, shares, price = self.executions[self.cursor]
            if fill_date != date:
                raise ValueError("Missing original C10 fill-date close")
            signed = dec(shares) * dec(price)
            fee = abs(signed) / 1000
            self.cash -= signed + fee
            self.fees += fee
            self.quantity += shares
            self.cursor += 1
        if self.cash < 0 or self.quantity < 0:
            raise ValueError("Negative cash/quantity in fixed C10 reference")
        equity = self.cash + self.quantity * dec(close_price)
        month = date[:7]
        row = self.months.setdefault(month, {"month": month, "begin_equity": float(self.last_equity)})
        row.update(date=date, end_equity=float(equity), cash=float(self.cash), quantity=self.quantity,
                   cumulative_fees=float(self.fees), cumulative_dividends=float(self.dividends))
        self.last_equity = equity
        self.last_date = date
        self.daily_rows += 1

    def summary(self):
        end2022 = dec(self.months.get("2022-12", {}).get("end_equity", 0))
        checks = {"all_original_fills_consumed": self.cursor == 19,
                  "24_months": len(self.months) == 24,
                  "501_closes": self.daily_rows == 501,
                  "flat_at_end": self.quantity == 0,
                  "fees_match": abs(self.fees - dec("191.97301")) < dec("0.000001"),
                  "dividends_match": abs(self.dividends - dec("2502.51")) < dec("0.000001"),
                  "final_equity_match": abs(self.last_equity - dec("102799.62699")) < dec("0.000001"),
                  "2022_regular_close_equity_match": abs(end2022 - dec("83250.21788")) < dec("0.000001")}
        payload = json.dumps(self.executions, separators=(",", ":"))
        return {"source": "Original C10 filled orders, valued on existing B10 observer SPY regular closes; no new orders or History",
                "original_backtest": ORIGINAL_BACKTEST,
                "execution_evidence_sha256": EXECUTION_EVIDENCE_SHA256,
                "execution_rows_sha256": hashlib.sha256(payload.encode()).hexdigest(),
                "execution_fields": EXECUTION_FIELDS, "execution_static_check": self.identity_check,
                "checks": checks, "all_checks_pass": all(checks.values()),
                "fees": float(self.fees), "dividends": float(self.dividends),
                "final_equity": float(self.last_equity), "final_quantity": self.quantity,
                "months": [self.months[m] for m in sorted(self.months)],
                "limitations": "Original UI fill prices must match original exact aggregate totals; dividends use LEAN event-time cash; market data revisions remain possible"}


if __name__ == "__main__":
    print(json.dumps(verify_original_executions(ORIGINAL_EXECUTIONS), indent=2))
