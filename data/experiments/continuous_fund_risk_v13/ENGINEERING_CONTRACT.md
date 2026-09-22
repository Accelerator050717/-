# v13 continuous strategy-fund accounting contract

This module controls the **funds continuously assigned to one automatic strategy**. It does not claim coverage of an entire IBKR account: unrelated holdings, cash, debt and activity are outside its scope.

## Identities and initialization

`scope_id`, owner, currency and the explicit instrument universe identify the funds. `model_version` identifies the prediction implementation and `run_id` identifies one process; neither changes the scope or resets its history. Model associations are appended to the existing state. The configured ledger path must remain stable across restarts and model handoffs.

`FundJournal.create(path, scope, initial_cash, at)` is an explicit, one-time initialization. `FundJournal(path, expected_scope)` opens an existing ledger only. Database/identity marker absence, partial initialization, corruption or scope mismatch fails closed. An existing ledger is never adopted with a different initial amount or silently recreated. Explicit creation of another ledger is an administrative act, not a supported recovery action; this local module is not a global registry of every copied database on disk.

## Accounting and durability

Each `commit(batch_id, at, events, prices, checkpoint, model_version, run_id, ...)` atomically persists:

- Stable event IDs, their original payload hashes and the processed-event cursor.
- Actual cash and signed filled quantities; unfilled orders do not become positions or proceeds.
- Current actual equity, fund units, unit NAV, cumulative high-water NAV, current and deepest cumulative drawdown.
- Valuation identity, model/run association, risk mode/reason/recovery state, and the strategy checkpoint.

SQLite `synchronous=FULL` transactions bind these records. The hash chain, event index and final state are checked when opening the journal. They detect corruption/inconsistency; they are not an authenticated defense against an attacker deliberately rewriting all hashes. A real subprocess killed after journal writes but before commit leaves the previous state intact; retry processes the same event once. A retry after committed state uses the existing ID and does not reapply fills or fees.

Amounts are float64 with explicit reconciliation tolerance (`1e-9` relative/absolute); this matches the current research arithmetic. Live multi-currency accounting, tax lots and broker corporate-action reconciliation remain outside this implementation.

## Event schema and unitization

All events have a unique `id`, timezone-aware `at`, and `kind`:

- `fill`: `symbol`, signed `quantity`, positive `price`, nonnegative `fee` (default zero).
- `cashflow`: signed external `amount`; units issued/redeemed at the actual pre-flow NAV.
- `income`: signed `amount`, `reason` equal to `fee`, `dividend` or `interest`; fees are negative and all these items affect performance.

For a cash flow at the batch valuation time, current batch prices can value its pre-flow holdings. Earlier flows require explicit contemporaneous `prices` and matching `valuation_at`. Deposits cannot erase drawdown, withdrawals cannot manufacture a return, and income is not treated as funding. Full liquidation of fund units/closing a fund requires separate administrative treatment and currently fails closed.

Event IDs repeated with identical normalized payloads are ignored. Changed payloads, reversed timestamps or newly discovered events before the last valuation quarantine the scope and require explicit reconstruction/review. A late commission is therefore an explicit current limitation, not silently re-dated income. Reconciliation compares supplied actual cash/positions with the event-derived ledger; differences persistently block new risk. Later agreement alone does not clear the block.

The journal records and exposes `blocked`; callers must honor it before new risk. It never submits, cancels or fills orders itself. The separate execution bridge reconciles broker facts before publishing a checkpoint; transactions across two independent SQLite ledgers are not claimed to be globally atomic.

## Verification and evidence boundary

Run from the repository root:

```powershell
.venv\Scripts\python.exe -m unittest tests.test_v13_fund_journal -v
```

The eleven tests use **fictitious** balances/prices only: two sequential loss/recovery cycles; model change; deposits, withdrawals and income; duplicate/reordered facts; scope isolation; missing/corrupt state; unexplained cash; partial gap fills; and a real process exit before transaction commit followed by restart/retry. These demonstrate local accounting and recovery behavior. They do not prove paper connectivity, forward performance, or guaranteed execution at a drawdown boundary.
