"""Shared recoverable H60 open-cycle coordinator for virtual and paper adapters.

No broker fills are assumed. On cancellation/submission ambiguity it returns a
waiting state. A caller may invoke it again after receiving actual broker facts.
"""
from h60_execution import utc
from h60_strategy_runtime import H60Runtime


def plan_open_cycle(client,broker,manifest,day,scores,risk,quotes,now):
    if not client.reconcile(broker,now):
        return dict(status='blocked',reason=client.journal.read()['blocked'],intents=[])
    state=client.journal.read()
    runtime=H60Runtime(manifest,state.get('runtime'))
    runtime.apply_fills(state,day)
    if runtime.state['last_open']==day:
        # A crash after plan commit resumes the already persisted intents, with
        # no second target computation and no new decision/order identifiers.
        batches=[b for b in state['batches'].values() if b.get('execution_day')==day]
        client.save_runtime(runtime.state)
        return dict(status='resume_persisted_batch' if batches else 'no_action',
                    intents=[key for b in batches for key in b['intents']])
    cash,positions=client.balances(state)
    decision=runtime.next_open(day,scores,risk,positions,cash,quotes)
    if decision is None:
        client.save_runtime(runtime.state)
        return dict(status='no_action',intents=[])
    active=[(key,row) for key,row in state['orders'].items() if not row.get('terminal_reconciled')]
    if active:
        for key,row in active:
            client.cancel(key,broker,now)
        # Do NOT persist the previewed runtime/weights. A stop can fill while a
        # cancel is pending. Next call merges that fill then recomputes holdings,
        # stock cooldown and target weights before creating any new risk.
        return dict(status='await_cancel_reconciliation',intents=[])
    keys=client.plan_targets(decision['decision_id'],decision['weights'],quotes,now,
        reduction=decision['reduction'],reason=decision['reason'],runtime_after=decision['runtime_after'])
    return dict(status='intents_persisted',intents=keys,decision=decision)


def submit_next(client,broker,keys,quotes,now):
    """At most one new network submission; never spend unfilled sale proceeds."""
    if not client.reconcile(broker,now):
        return dict(status='blocked',reason=client.journal.read()['blocked'])
    state=client.journal.read()
    pending=[(key,state['orders'][key]) for key in keys if not state['orders'][key].get('terminal_reconciled')]
    if not pending:
        return dict(status='batch_terminal')
    # A partial entry can already have protective sells. If protection executes
    # while its entry remainder is open, cancel that remainder; a persisted old
    # target must not buy the stopped stock back. Keep reserves until confirmed.
    cancelled=[]
    for key,row in pending:
        if row['state']['side']!='BUY':
            continue
        stopped=any(other['reason']=='stock_protection'
            and other['state']['symbol']==row['state']['symbol']
            and any(utc(moment)>=utc(row['created_at']) for moment in other.get('fill_times',{}).values())
            for other in state['orders'].values())
        if stopped:
            client.cancel(key,broker,now)
            cancelled.append(key)
    if cancelled:
        return dict(status='protection_triggered_cancel_buy_remainder',intents=cancelled)
    pending.sort(key=lambda item:(item[1]['state']['side']!='SELL',item[0]))
    key,row=pending[0]
    if row['state']['attempted']:
        return dict(status='await_broker_fill_or_terminal_fact',intent=key)
    result=client.submit(key,broker,quotes,now)
    return dict(status='submitted_reconcile_before_next' if result else 'submission_uncertain',intent=key)
