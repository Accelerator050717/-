# Independent local engineering review

Scope: `strategy_fund_journal.py`, `h60_fund_risk_bridge.py`, their direct tests, and the existing execution coordinator's stop/entry race behavior. No market data, training, real orders or paper orders were used.

Two concrete integration gaps were found and corrected before historical policy comparison:

1. Checking only currency, symbols and initial budget did not bind a fund to its execution strategy. The bridge now additionally requires the scope's immutable `execution_strategy_id` to match the executor. A different strategy with the same budget/symbols is rejected. A fresh fund also cannot adopt an executor that already has order or runtime history and thereby erase prior drawdown.
2. The new direct virtual submission wrapper initially bypassed the old coordinator's stop-fill cancellation of an outstanding entry remainder. Synchronization now invokes the existing cancellation path for those exact orders. Tests check `PendingCancel`, the remaining actual position, and preservation of cash/sell reservations until terminal broker facts are confirmed. The cancellation path cannot submit a new order.

Independent rerun after these fixes:

```powershell
.venv\Scripts\python.exe -m unittest tests.test_v13_fund_journal tests.test_v13_execution_continuity -v
```

Observed: **22 tests passed**, including real subprocess exits before/after the fund checkpoint, an exit after SQLite writes but before transaction commit, duplicate replay, record-only target/order parity, unknown submissions, scope isolation, changed quotes, partial gap exits and unitized external cash flows. This is local fictitious engineering evidence.

The fund's event deduplication cursor, event payloads, checkpoint and high-water state share one SQLite transaction. Source execution facts are checked against the last saved source specification, version, order IDs and fill/commission payloads. A gap between the two ledgers prevents additional risk until reconciliation and fact replay finish. This is recoverable coordination, not an atomic transaction across both databases.

Unitization correctly leaves NAV/drawdown unchanged by an external deposit or withdrawal; fees, dividends and interest remain returns. Model/process changes do not reset the fund ledger. The old executor still refuses an in-place manifest change, so an execution-level model handoff is **not** claimed merely because the fund journal supports a different model association.

Remaining explicit boundaries: scope covers allocated strategy funds, not an entire broker account; the bridge accepts exact `VirtualBroker` only; it receives an explicitly calculated risk state and is not a standalone unattended broker driver. Full historical recovery of late commissions, native equity/corporate actions, continuous protection and long-disconnection recovery remain incomplete. Malformed/missing state and late/out-of-order financial facts fail closed rather than silently recreating initial funding.

## Independent controller/replay boundary checks

`tests/test_v13_boundaries.py` adds three fictitious checks. Observed: all three passed.

- An upward opening gap after a recorded reduction trigger uses actual opening values when enforcing the cap and creates only sales.
- Fees paid by the final liquidation are included in the final cumulative-risk observation; a deliberately constructed final fee can cross the 25% review boundary, while the state correctly records that no liquidation remains pending.
- A model-metadata handoff in the same research-fund scope, including process restart, retains fund units, the cumulative high-water mark and prior losses. This checks accounting continuity; it does not claim execution support for replacing the frozen live-manifest contract.

Review also identified a pre-trade/post-fee distinction in the recovery exposure formula: a cap estimated from pre-trade NAV can be slightly larger than a recomputation using post-fee NAV. The plan had already been frozen when this diagnostic was considered, so the implementation and plan were preserved. `ENGINEERING_LIMITATIONS.md` records the concrete fictitious arithmetic and its interpretation. It is separate from gap risk and must not be described as an exact guaranteed loss bound.
