"""H60 decisions over sequential daily proxy phases and a broker-owned ledger.

This is a historical parity adapter, not a live strategy. OPEN, RANGE and CLOSE
are explicitly artificial ordering of the original daily observations. The
broker supplies all cash, quantities and fills; this module never assigns them.
"""
from dataclasses import asdict

import numpy as np
import pandas as pd

from profit_priority_strategy import (
    Policy, DrawdownState, scheduled_weights, reduction_weights, clip_weights,
    protection_floor, stop_fill,
)
from research_backtest import _rebalance, reduce_only, _check_dates


def validate_package(package):
    """Validate ordering and observed-input boundaries before any engine order."""
    names = package["names"]
    if not names or len(set(names)) != len(names) or not all(isinstance(s, str) and s for s in names):
        raise ValueError("Security names must be unique nonempty strings")
    if set(package["groups"]) != set(names):
        raise ValueError("Every security requires exactly one risk group")
    calendar = pd.DatetimeIndex(package["calendar"])
    observations = pd.DatetimeIndex(package["observations"])
    _check_dates(calendar, "package calendar")
    _check_dates(observations, "package observations")
    if calendar.empty or observations.empty or calendar.max() >= pd.Timestamp("2026-01-01"):
        raise ValueError("Historical package requires nonempty pre-2026 dates")
    positions = calendar.get_indexer(observations)
    if (positions < 59).any():
        raise ValueError("Missing observation or historical risk window")
    first, final = pd.Timestamp(package["first_date"]), pd.Timestamp(package["final_date"])
    if (positions[0] + 1 >= len(calendar) or first != calendar[positions[0] + 1]
            or final not in calendar or final <= observations[-1]):
        raise ValueError("First/final dates do not match the frozen observation schedule")
    if set(package["scores"]) != {day.date().isoformat() for day in observations}:
        raise ValueError("Scores must match frozen observation dates exactly")
    for row in package["scores"].values():
        array = np.asarray(row, dtype=float)
        if array.shape != (len(names),) or not np.isfinite(array).all():
            raise ValueError("Missing or invalid frozen score row")
    for key in ("distance", "vol", "returns"):
        array = np.asarray(package["risk"][key], dtype=float)
        if array.shape != (len(calendar), len(names)):
            raise ValueError(f"Risk {key} shape differs from calendar and securities")
    for key in ("trend", "spy_exposure"):
        if len(package["risk"][key]) != len(calendar):
            raise ValueError(f"Risk {key} length differs from calendar")
    if not np.isfinite(package["initial_cash"]) or package["initial_cash"] <= 0:
        raise ValueError("Initial cash must be finite and positive")
    for key in ("cost_bps", "stop_extra_bps"):
        if not np.isfinite(package[key]) or not 0 <= package[key] < 10000:
            raise ValueError("Invalid cost rate")


class H60Decision:
    def __init__(self, package):
        validate_package(package)
        self.names = list(package["names"])
        self.calendar = pd.DatetimeIndex(package["calendar"])
        if (not self.calendar.is_unique or not self.calendar.is_monotonic_increasing
                or self.calendar.max() >= pd.Timestamp("2026-01-01")):
            raise ValueError("Historical package must have a unique ordered pre-2026 calendar")
        self.groups = package["groups"]
        self.policy = Policy(**package["policy"])
        if self.policy.soft_enabled or not self.policy.hard_enabled:
            raise ValueError("This migration fixes the v8 stop-on/soft-off/hard-on cell")
        self.initial_cash = float(package["initial_cash"])
        self.cost_rate = float(package["cost_bps"]) / 10000
        self.stop_extra_bps = float(package["stop_extra_bps"])
        self.scores = package["scores"]
        observations = pd.DatetimeIndex(package["observations"])
        positions = self.calendar.get_indexer(observations)
        if (positions < 59).any() or not observations.is_unique:
            raise ValueError("Missing observation or historical risk window")
        self.schedule = {int(pos + 1): int(pos) for pos in positions}
        self.first = int(positions[0] + 1)
        self.finish = int(self.calendar.get_loc(package["final_date"]))
        self.risk = {}
        for key in ("distance", "vol", "returns"):
            self.risk[key] = pd.DataFrame(package["risk"][key], index=self.calendar,
                                          columns=self.names, dtype=float)
        for key in ("trend", "spy_exposure"):
            self.risk[key] = pd.Series(package["risk"][key], index=self.calendar)
        self.drawdown = DrawdownState(episode_peak=self.initial_cash)
        self.threshold = np.full(len(self.names), np.nan)
        self.blocked_until = np.full(len(self.names), -1)
        self.pending_cap = None
        self.previous_close = None
        self.expected_day, self.expected_phase = self.first, "OPEN"
        self.daily, self.positions, self.targets, self.events = [], [], [], []
        self.observation_audit = []
        self.completed = False

    def _positions(self, broker):
        values = np.asarray(broker.quantities(self.names), dtype=float).copy()
        if values.shape != (len(self.names),) or (values < -1e-8).any():
            raise AssertionError("Broker holdings violate long-only shape or quantity")
        return values

    def _rebalance(self, broker, weights, reason, observation, reduction=False,
                   risk_action=""):
        quantities = self._positions(broker)
        sizing = reduce_only if reduction else _rebalance
        target, expected_cash, changes, _ = sizing(
            quantities * self.opened, broker.cash(), weights.to_numpy(), self.cost_rate)
        # LEAN owns order admission, fills, commission debits and position changes.
        for j in np.argsort(changes, kind="stable"):
            delta = changes[j] / self.opened[j]
            if changes[j] < 0 and target[j] == 0:
                # Closing a position uses the broker's actual quantity; do not
                # divide multiplied floats and accidentally oversell by dust.
                delta = -quantities[j]
            if abs(delta) >= self.initial_cash * 1e-14:
                broker.execute(self.names[j], float(delta), float(self.opened[j]),
                               reason, observation, float(self.threshold[j]), risk_action)
        after = self._positions(broker)
        if reduction and (after > quantities + 1e-8).any():
            raise AssertionError("Unscheduled risk reduction bought shares")
        if not np.isclose(broker.cash(), expected_cash, rtol=1e-9, atol=1e-5):
            raise AssertionError(f"Engine cash {broker.cash()} != sizing cash {expected_cash}")
        for j in range(len(self.names)):
            if after[j] <= 1e-8:
                self.threshold[j] = np.nan
            elif quantities[j] <= 1e-8:
                self.threshold[j] = protection_floor(np.nan, self.opened[j], new_position=True)
            elif reason == "scheduled" or after[j] > quantities[j] + 1e-8:
                self.threshold[j] = protection_floor(self.threshold[j], self.opened[j], scheduled=True)
        self.targets.append(dict(Date=self.date, observation_date=observation,
            reason=reason, reduce_only=reduction, risk_action=risk_action,
            **{s: float(weights[s]) for s in self.names}))

    def _stop(self, broker, j, price, reason):
        quantity = self._positions(broker)[j]
        broker.execute(self.names[j], -float(quantity), float(price), reason,
                       self.calendar[self.day - 1].date().isoformat(),
                       float(self.threshold[j]), "")
        self.blocked_until[j] = self.day + self.policy.stock_cooldown
        self.threshold[j] = np.nan

    def process(self, phase, date, values, broker):
        """Process one complete cross-section, rejecting skipped/repeated phases."""
        day = int(self.calendar.get_loc(date))
        if self.completed or day != self.expected_day or phase != self.expected_phase:
            raise ValueError(f"Unexpected phase {date}/{phase}; expected "
                             f"{self.calendar[self.expected_day]}/{self.expected_phase}")
        values = np.asarray(values, dtype=float)
        if values.shape != (len(self.names),) or not np.isfinite(values).all() or (values <= 0).any():
            raise ValueError("Incomplete or invalid phase values; no price filling")
        self.day, self.date = day, self.calendar[day].date().isoformat()
        if phase == "OPEN":
            self._open(values, broker)
            self.expected_phase = "RANGE"
        elif phase == "RANGE":
            self._range(values, broker)
            self.expected_phase = "CLOSE"
        else:
            self._close(values, broker)
            self.expected_day += 1
            self.expected_phase = "OPEN"
            self.completed = day == self.finish

    def _open(self, opened, broker):
        self.opened = opened
        self.cost_before = broker.cumulative_fees()
        scheduled = self.day in self.schedule
        prior_date = self.calendar[self.day - 1].date().isoformat()
        for j in np.flatnonzero(self._positions(broker) > 1e-8):
            if opened[j] <= self.threshold[j]:
                self._stop(broker, j, opened[j] * (1 - self.stop_extra_bps / 10000), "stop_gap")
        zero = pd.Series(0., index=self.names)
        if self.day == self.finish:
            self._rebalance(broker, zero, "final_liquidation", prior_date)
        else:
            if self.drawdown.pending_flat:
                self._rebalance(broker, zero, "portfolio_flat", prior_date)
                self.drawdown.pending_flat = False
                self.pending_cap = None
            equity = broker.cash() + float(self._positions(broker) @ opened)
            if self.drawdown.resume(self.day, equity, bool(self.risk["trend"].iloc[self.day - 1]),
                                    scheduled, self.policy):
                self.events.append(dict(Date=self.date, event="portfolio_resume", equity=equity))
            if scheduled and not self.drawdown.paused:
                observation = self.schedule[self.day]
                if observation >= self.day:
                    raise AssertionError("Decision observes a current/future close")
                observation_date = self.calendar[observation].date().isoformat()
                scores = pd.Series(self.scores[observation_date], index=self.names, dtype=float)
                quantities = self._positions(broker)
                weights = scheduled_weights(scores,
                    {s for j, s in enumerate(self.names) if quantities[j] > 1e-8},
                    self.risk, observation, self.groups,
                    multiplier=self.drawdown.multiplier(self.day),
                    eligible=[s for j, s in enumerate(self.names) if self.day >= self.blocked_until[j]],
                    policy=self.policy)
                if not np.isfinite(weights).all() or weights.sum() > 1 + 1e-10:
                    raise ValueError("Invalid or leveraged target")
                self.observation_audit.append(dict(execution_date=self.date,
                    observation_date=observation_date, risk_window_end=observation_date))
                self._rebalance(broker, weights, "scheduled", observation_date)
                self.drawdown.pending_half = False
                self.pending_cap = None
            elif (self.drawdown.pending_half or self.pending_cap is not None) and not self.drawdown.paused:
                if self.previous_close is None:
                    raise AssertionError("No completed prior close for reduction")
                previous = pd.Series(self._positions(broker) * self.previous_close, index=self.names)
                weights = reduction_weights(previous, broker.cash(), self.pending_cap,
                                            self.drawdown.pending_half)
                action = ("cap_and_soft" if self.pending_cap is not None and self.drawdown.pending_half
                          else "soft" if self.drawdown.pending_half else "cap")
                self._rebalance(broker, weights, "daily_risk_reduce", prior_date, True, action)
                self.drawdown.pending_half = False
                self.pending_cap = None
        self.open_nav = broker.cash() + float(self._positions(broker) @ opened)

    def _range(self, lows, broker):
        if (lows > self.opened + 1e-8).any():
            raise ValueError("Daily low exceeds opening price")
        self.low_mark = broker.cash() + float(self._positions(broker) @ lows)
        if self.day != self.finish:
            for j in np.flatnonzero(self._positions(broker) > 1e-8):
                price, reason = stop_fill(self.opened[j], lows[j], self.threshold[j], self.stop_extra_bps)
                if reason:
                    self._stop(broker, j, price, reason)

    def _close(self, closed, broker):
        quantity = self._positions(broker)
        cash = broker.cash()
        invested = float(quantity @ closed)
        equity = cash + invested
        if cash < -1e-5 or equity <= 0:
            raise AssertionError("Cash borrowing or non-positive portfolio equity")
        engine_equity = broker.equity()
        if not np.isclose(engine_equity, equity, atol=1e-5, rtol=1e-9):
            raise AssertionError(f"LEAN valuation {engine_equity} differs from current marks {equity}")
        if self.day != self.finish:
            event = self.drawdown.observe(self.day, equity, self.policy)
            if event:
                self.events.append(dict(Date=self.date, event=event, equity=equity,
                                        episode_drawdown=equity / self.drawdown.episode_peak - 1))
            if not self.drawdown.paused:
                weights = pd.Series(quantity * closed / equity, index=self.names)
                clipped = clip_weights(weights, self.groups, self.policy)
                if (clipped < weights - 1e-8).any():
                    self.pending_cap = clipped
        self.daily.append(dict(Date=self.date, open_equity=self.open_nav,
            equity=engine_equity, low_stress_equity=min(self.low_mark, equity),
            cash=cash, invested=invested, gross=invested / equity,
            fees=broker.cumulative_fees() - self.cost_before,
            cumulative_fees=broker.cumulative_fees(), paused=self.drawdown.paused,
            soft=self.drawdown.soft, episode_peak=self.drawdown.episode_peak))
        self.positions.append(dict(Date=self.date, **dict(zip(self.names, map(float, quantity)))))
        self.previous_close = closed.copy()

    def status(self):
        return dict(completed=self.completed, sessions=len(self.daily),
                    scheduled_decisions=len(self.observation_audit),
                    policy=asdict(self.policy), price_basis="original adjusted daily return proxy",
                    phase_clock="artificial OPEN/RANGE/CLOSE, not observed intraday sequence",
                    new_fits=0, prices_2026_accessed=False, live_enabled=False)
