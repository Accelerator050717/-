"""Automatic continuous-risk transitions on reconciled VirtualBroker facts only.

No order or cancellation methods are called. Each close/open decision records
actual fill/fee IDs, the complete execution checkpoint, the continuous risk
transition and its idempotency cursor in ONE FundJournal transaction. The frozen
v13 historical policy and earlier record-only engineering evidence are unchanged.
FundJournal retains every trusted valuation high, whereas the frozen historical
comparison uses close highs. Consequently this engineering NAV adapter is not
claimed to reproduce the historical trading path. Open resume is accepted only
for a halted/locked fund; normal held-position opens are not a control entry.
"""
from copy import deepcopy
from datetime import date
import math
from zoneinfo import ZoneInfo

from h60_execution import ExecutionBlocked, digest, number, utc
from h60_global_control import GlobalRisk


class FundControlCycle:
    def __init__(self, bridge, *, runtime_manifest, calendar=None, observations=None):
        self.bridge = bridge
        source = bridge.client.journal.read()
        if (digest(runtime_manifest) != source['spec']['strategy_manifest_hash']
                or runtime_manifest['strategy_id'] != bridge.client.config.strategy_id
                or number(runtime_manifest['budget']) != number(bridge.client.config.budget)
                or runtime_manifest['symbols'] != bridge.client.symbols):
            raise ExecutionBlocked('Runtime manifest identity does not match the execution ledger')
        self.calendar = list(runtime_manifest['calendar'])
        self.observations = list(runtime_manifest['observations'])
        if ((calendar is not None and list(calendar) != self.calendar)
                or (observations is not None and list(observations) != self.observations)):
            raise ExecutionBlocked('Controller calendar differs from the frozen runtime day-index origin')
        if (not self.calendar or self.calendar != sorted(set(self.calendar))
                or self.observations != sorted(set(self.observations))
                or not set(self.observations).issubset(self.calendar)
                or any(date.fromisoformat(day).year >= 2026 for day in self.calendar)):
            raise ExecutionBlocked('Explicit ordered pre-2026 engineering calendar required')
        self.calendar_id = digest([self.calendar, self.observations])

    def initialize(self, now, prices):
        """Explicit initialization ONLY before this fund has any investment history."""
        state = self.bridge.fund.read()
        source = self.bridge.client.journal.read()
        if (state['event_cursor'] or float(state['high_water_nav']) != 1.
                or float(state['unit_nav']) != 1. or source['orders']):
            raise ExecutionBlocked('Cannot initialize controller over an existing investment history')
        if state['risk_state'].get('mode') not in ('observe', 'NORMAL'):
            raise ExecutionBlocked('Controller already has a different risk mode')
        return self.bridge.sync(now, prices, risk_state=GlobalRisk().as_dict())

    def close(self, day, now, prices):
        return self._transition('close', day, now, prices)

    def resume_open(self, day, now, prices, *, trend_observation, trend, episode_input):
        return self._transition('open', day, now, prices,
            trend_observation=trend_observation, trend=trend, episode_input=episode_input)

    def _transition(self, phase, day, now, prices, **context):
        if day not in self.calendar:
            raise ExecutionBlocked('Unknown decision session')
        session = self.calendar.index(day)
        local = utc(now).astimezone(ZoneInfo('America/New_York'))
        if local.date().isoformat() != day:
            raise ExecutionBlocked('Decision timestamp does not belong to its session')
        local_minutes = local.hour * 60 + local.minute
        if ((phase == 'close' and local_minutes < 16 * 60)
                or (phase == 'open' and not 9 * 60 + 30 <= local_minutes < 16 * 60)):
            raise ExecutionBlocked('Explicit regular-session open or completed close required')
        if set(prices) != set(self.bridge.client.symbols) or any(number(value) <= 0 for value in prices.values()):
            raise ExecutionBlocked('Actual valuation prices are incomplete')
        if phase == 'open':
            if (session == 0 or context['trend_observation'] != self.calendar[session - 1]
                    or not isinstance(context['trend'], bool)):
                raise ExecutionBlocked('Recovery trend must be from the previous completed session')
        fund = self.bridge.fund
        before = fund.read()
        if before.get('blocked'):
            raise ExecutionBlocked('Fund is quarantined; controller cannot clear its block')
        if utc(now) < utc(before['last_valuation_at']):
            raise ExecutionBlocked('Control decision predates the last actual valuation')
        if not self.bridge.client.reconcile(self.bridge.broker, now):
            raise ExecutionBlocked('Actual broker facts are not reconciled')
        source = self.bridge.client.journal.read()
        self.bridge._check_source_continuity(source)
        cash, positions = self.bridge.client.balances(source)
        actual_facts = dict(cash=str(cash), positions={s: str(q) for s, q in positions.items()},
                            events=self.bridge.facts(source))
        request = dict(phase=phase, day=day, at=utc(now).isoformat(),
                       prices={s: str(number(value)) for s, value in prices.items()}, context=context,
                       calendar_sha256=self.calendar_id)
        identity = digest([before['scope']['scope_id'], phase, day])
        clock = [session, 1 if phase == 'close' else 0]
        latest, prior = None, None
        for record in fund.history():
            saved = (record.get('checkpoint') or {}).get('continuous_control')
            if saved is None:
                continue
            if saved['calendar_sha256'] != self.calendar_id:
                raise ExecutionBlocked('Controller calendar identity changed; explicit review required')
            if saved['decision_id'] == identity:
                if saved['request'] != request or saved['actual_facts'] != actual_facts:
                    fund.quarantine('Repeated controller decision has conflicting facts', {'decision_id': identity})
                    raise ExecutionBlocked('Repeated controller decision has conflicting facts')
                prior = saved
            latest = saved
        if prior is not None:
            if latest['decision_id'] != identity or before['risk_state'] != prior['result']['risk_state']:
                raise ExecutionBlocked('Past controller decision cannot replace current risk state')
            if (not math.isclose(before['unit_nav'], prior['result']['unit_nav'], rel_tol=1e-12, abs_tol=1e-12)
                    or not math.isclose(before['high_water_nav'], prior['result']['high_water_nav'], rel_tol=1e-12, abs_tol=1e-12)):
                raise ExecutionBlocked('Actual valuation changed after the repeated controller decision')
            # Reconciliation appends source facts even when no economic event is
            # new. Save that checkpoint without observing/resuming a second time.
            checkpoint = dict(execution_document=deepcopy(source), execution_digest=digest(source),
                source_version=source['version'], run_id=self.bridge.run_id,
                scope_boundary='allocated strategy cash plus strategy-owned symbols only', continuous_control=prior)
            refreshed = fund.commit(batch_id='control-reconcile:' + digest([identity, source]),
                at=utc(now).isoformat(), events=actual_facts['events'], prices=prices,
                checkpoint=checkpoint, model_version=source['spec']['strategy_manifest_hash'],
                run_id=self.bridge.run_id, expected_cash=str(cash),
                expected_positions=actual_facts['positions'], risk_state=before['risk_state'])
            if refreshed.get('blocked'):
                raise ExecutionBlocked('Repeated control decision could not reconcile actual facts')
            return deepcopy(prior['result'])
        if latest is not None and clock <= latest['clock']:
            raise ExecutionBlocked('Controller decision clock moved backwards')
        if utc(now) < utc(before['last_valuation_at']):
            raise ExecutionBlocked('Control decision predates the last actual valuation')
        try:
            risk = GlobalRisk(**before['risk_state'])
            if before['risk_state'].get('mode') not in ('NORMAL', 'REDUCED', 'HALTED', 'RECOVERY', 'REVIEW_LOCKED'):
                raise ValueError('Continuous controller was not explicitly initialized')
        except (TypeError, ValueError) as exc:
            raise ExecutionBlocked('Persisted global risk state is invalid') from exc
        equity = float(cash + sum((positions[s] * number(prices[s]) for s in positions), number(0)))
        unit_nav = equity / float(before['fund_shares'])
        high_water = max(float(before['high_water_nav']), unit_nav)
        events, resumed = [], False
        if phase == 'close':
            events = risk.observe(session, unit_nav, high_water)
        else:
            if risk.mode not in ('HALTED', 'REVIEW_LOCKED'):
                raise ExecutionBlocked('Open recovery entry only applies to a halted or locked fund')
            persisted_episode = (source.get('runtime') or {}).get('drawdown')
            if persisted_episode is None or context['episode_input'] != persisted_episode:
                raise ExecutionBlocked('Recovery episode input differs from persisted strategy runtime')
            scheduled = context['trend_observation'] in self.observations
            episode_ready = (not persisted_episode['paused'] or session >= persisted_episode['paused_until'])
            flat = not any(number(q) != 0 for q in positions.values())
            no_pending = not any(not row.get('terminal_reconciled') for row in source['orders'].values())
            resumed = risk.try_resume(session, unit_nav, high_water,
                trend=context['trend'], scheduled=scheduled, confirmed_flat=flat,
                no_pending_orders=no_pending, episode_ready=episode_ready)
            if resumed:
                events = [dict(event='global_resume', reason=risk.reason)]
        result = dict(evidence='FICTIONAL VirtualBroker controller cycle; no orders or paper integration',
            scope_id=before['scope']['scope_id'], decision_id=identity, phase=phase, day=day,
            mode=risk.mode, risk_state=risk.as_dict(), events=events, resumed=resumed,
            unit_nav=unit_nav, high_water_nav=high_water,
            cumulative_drawdown=unit_nav / high_water - 1., gross_cap=risk.cap(unit_nav, high_water),
            cash=str(cash), positions=actual_facts['positions'])
        cursor = dict(decision_id=identity, calendar_sha256=self.calendar_id, clock=clock,
                      request=request, actual_facts=actual_facts, result=result)
        checkpoint = dict(execution_document=deepcopy(source), execution_digest=digest(source),
            source_version=source['version'], run_id=self.bridge.run_id,
            scope_boundary='allocated strategy cash plus strategy-owned symbols only', continuous_control=cursor)
        state = fund.commit(batch_id='control:' + identity, at=utc(now).isoformat(),
            events=actual_facts['events'], prices=prices, checkpoint=checkpoint,
            model_version=source['spec']['strategy_manifest_hash'], run_id=self.bridge.run_id,
            expected_cash=str(cash), expected_positions=actual_facts['positions'], risk_state=risk.as_dict())
        if state.get('blocked'):
            raise ExecutionBlocked('Actual financial facts require reconciliation')
        return result
