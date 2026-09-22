"""One cumulative-unit-NAV research controller, independent of episode peaks.

These are preregistered research rules, not broker limits or fill guarantees.
The fund journal owns the continuous high water and never resets it here.
"""
from dataclasses import asdict, dataclass
import math


@dataclass(frozen=True)
class GlobalPolicy:
    reduce_drawdown: float = .10
    reduce_gross_cap: float = .40
    pause_drawdown: float = .20
    review_drawdown: float = .25
    budget_drawdown: float = .30
    normal_restore_drawdown: float = .05
    cooldown_sessions: int = 20
    recovery_gross_cap: float = .25
    recovery_loss: float = .05
    assumed_asset_shock: float = .30


@dataclass
class GlobalRisk:
    mode: str = 'NORMAL'
    reason: str = 'initialized_strategy_scope'
    paused_until: int = -1
    pending_flat: bool = False
    resume_unit_nav: float | None = None
    recovery_floor: float | None = None
    last_resume_session: int | None = None
    budget_breached: bool = False
    pause_count: int = 0
    resume_count: int = 0

    def _check(self, unit_nav, high_water):
        if (not math.isfinite(unit_nav) or not math.isfinite(high_water)
                or unit_nav <= 0 or high_water <= 0):
            raise ValueError('Trusted positive actual unit NAV/high water required')
        if self.mode not in ('NORMAL','REDUCED','HALTED','RECOVERY','REVIEW_LOCKED'):
            raise ValueError('Unknown global risk mode; do not initialize over it')

    def cap(self, unit_nav, high_water, policy=GlobalPolicy()):
        self._check(unit_nav, high_water)
        if self.mode in ('HALTED','REVIEW_LOCKED'):
            return 0.
        if self.mode == 'REDUCED':
            return policy.reduce_gross_cap
        if self.mode == 'RECOVERY':
            remaining = max(0., unit_nav-(1-policy.budget_drawdown)*high_water)
            return min(policy.recovery_gross_cap, remaining/unit_nav/policy.assumed_asset_shock)
        return 1.

    def _pause(self, day, reason, policy):
        self.mode, self.reason = 'HALTED', reason
        self.pending_flat = True
        self.paused_until = day + 1 + policy.cooldown_sessions
        self.pause_count += 1
        return dict(event='global_pause', reason=reason)

    def observe(self, day, unit_nav, high_water, policy=GlobalPolicy()):
        """At actual close only; resulting exits/reductions execute next open."""
        self._check(unit_nav, high_water)
        dd = unit_nav/high_water-1
        events=[]
        if unit_nav <= (1-policy.budget_drawdown)*high_water and not self.budget_breached:
            self.budget_breached=True
            events.append(dict(event='global_budget_breach',reason='actual_unit_nav_beyond_30_percent_budget'))
        if unit_nav <= (1-policy.review_drawdown)*high_water:
            if self.mode != 'REVIEW_LOCKED':
                self.mode='REVIEW_LOCKED';self.reason='remaining_budget_not_more_than_5_high_water_percentage_points'
                self.pending_flat=True;self.pause_count+=1
                events.append(dict(event='global_review_lock',reason=self.reason))
            return events
        if self.mode == 'REVIEW_LOCKED':
            return events  # No automatic unlock, including after cashflows/model changes.
        if self.mode == 'HALTED':
            return events
        if self.mode == 'RECOVERY':
            if self.resume_unit_nav is None or self.recovery_floor is None:
                raise ValueError('Recovery anchor missing; cannot silently resume')
            if unit_nav <= max(self.recovery_floor,(1-policy.budget_drawdown)*high_water):
                events.append(self._pause(day,'new_loss_since_actual_recovery',policy))
            elif unit_nav >= (1-policy.normal_restore_drawdown)*high_water:
                self.mode='NORMAL';self.reason='actual_unit_nav_recovers_within_5_percent_of_preserved_high_water'
                events.append(dict(event='global_normal',reason=self.reason))
            # The old >=20% loss is deliberately not a fresh recovery trigger.
            return events
        if unit_nav <= (1-policy.pause_drawdown)*high_water:
            events.append(self._pause(day,'cumulative_drawdown_20_percent',policy))
        elif self.mode == 'NORMAL' and unit_nav <= (1-policy.reduce_drawdown)*high_water:
            self.mode='REDUCED';self.reason='cumulative_drawdown_10_percent'
            events.append(dict(event='global_reduce',reason=self.reason))
        elif self.mode == 'REDUCED' and unit_nav >= (1-policy.normal_restore_drawdown)*high_water:
            self.mode='NORMAL';self.reason='actual_unit_nav_recovers_within_5_percent_of_preserved_high_water'
            events.append(dict(event='global_normal',reason=self.reason))
        return events

    def try_resume(self, day, unit_nav, high_water, *, trend, scheduled,
                   confirmed_flat, no_pending_orders, episode_ready, policy=GlobalPolicy()):
        self._check(unit_nav,high_water)
        dd=unit_nav/high_water-1
        if (self.mode!='HALTED' or day<self.paused_until or not trend or not scheduled
                or not confirmed_flat or not no_pending_orders or not episode_ready
                or unit_nav <= (1-policy.review_drawdown)*high_water or self.budget_breached):
            return False
        self.mode='RECOVERY';self.reason='cooldown_trend_schedule_and_remaining_budget_allow_limited_reentry'
        self.pending_flat=False
        self.resume_unit_nav=float(unit_nav)
        self.recovery_floor=max((1-policy.budget_drawdown)*high_water,(1-policy.recovery_loss)*unit_nav)
        self.last_resume_session=int(day);self.resume_count+=1
        return True

    def as_dict(self):
        return asdict(self)
