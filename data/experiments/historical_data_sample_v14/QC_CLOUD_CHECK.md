# Minimal QuantConnect cloud inspection — prepared, not run

`tools/qc_v14_cloud_check.py` is a fixed **data-access inspection**, not a strategy. The current local-browser QuantConnect terminal showed Sign In in the parent task's check. No authenticated cloud run or supplier-data acceptance is claimed.

## Minimal user action

1. Sign in to your existing QuantConnect account in the local browser. No payment, paid subscription or academic-license entitlement is assumed. A new account is not created by this task.
2. Open a Python project and its cloud Research notebook (`research.ipynb`). Check that the organization offers the free Research node and relevant historical datasets. If the UI requires payment or grants different rights, stop there.
3. Paste the contents of `tools/qc_v14_cloud_check.py` into a notebook cell; execute it, then run `check_cloud_sample()` in another cell. This is the **Research notebook**, not a Backtest or Live deployment.

The script only requests fixed windows ending in 2020, 2022 or 2023 for AAPL, TSLA, META/FB, TWTR, SIVB and ATVI. Every history call supplies both dates. It disables price seeding and fill forward and requests raw daily bars, so the inspection does not silently create tradable prices during gaps. The SID lookup is dated; META's pre-change lookup explicitly uses FB.

The output is non-reconstructive diagnostics: row/error counts and identity-equality booleans. It contains no OHLCV values, raw SID/map records, event dates/amounts or full membership tables. The script has no disk, Object Store, HTTP export or order operation. Provider data stays inside the permitted Research environment. Do not append `display(history)`, `to_csv`, Object Store persistence or raw logs to circumvent the data license.

## What is and is not tested

- Checks whether raw bars, typed symbol-change/delisting history, and a filtered historical trading-stock universe are queryable for the selected cases.
- Checks duplicate timestamps, finite/ordered OHLCV, and FB/META SID continuity without outputting raw records.
- Query failure is `unavailable` with the exception class only. Empty results remain unknown and cannot prove that no event occurred. A generated SID alone is not proof that the vendor covers that security.
- Lifecycle typed history is documented on the algorithm API inherited by QuantBook; this cloud account/version has **not** executed it. If unsupported or unentitled, retain the error summary instead of inventing another event endpoint.
- Universe selection is a trading-stock research universe, **not** S&P 500 membership. TSLA coverage in it cannot validate the S&P addition date.
- Delisting events are engine metadata; this script does not assert original announcement receipt, exchange-specific halts, OTC continuation, terminal recovery, or usable cash. No count is a return or complete-universe certification.

Validation in this task is limited to Python parsing/compilation and inspection of official API documentation and matching local LEAN method signatures. `AlgorithmImports`/cloud entitlements were not executed locally; no fictional output accompanies the script.

Official API references checked 2026-09-22:

- [Research key concepts and explicit date ranges](https://www.quantconnect.com/docs/v2/research-environment/datasets/key-concepts)
- [US equity research: raw normalization and subscriptions](https://www.quantconnect.com/docs/v2/research-environment/datasets/us-equity)
- [Research `universe_history`](https://www.quantconnect.com/docs/v2/research-environment/universes)
- [Historical symbol resolution](https://www.quantconnect.com/docs/v2/writing-algorithms/key-concepts/security-identifiers)
- [Typed SymbolChangedEvent and Delisting history](https://www.quantconnect.com/docs/v2/writing-algorithms/historical-data/asset-classes/us-equities)
- [`add_security(Symbol, ...)` API](https://www.lean.io/docs/v2/lean-engine/class-reference/py/QuantConnect/Algorithm/QCAlgorithm/)
- [QuantBook inheritance](https://github.com/QuantConnect/Lean/blob/8ee075a39918f2df6fe9e0a5944e366fb60d10dc/Research/QuantBook.cs)
- [Typed history explicit-date overload](https://github.com/QuantConnect/Lean/blob/8ee075a39918f2df6fe9e0a5944e366fb60d10dc/Algorithm/QCAlgorithm.History.cs)

Restart: rerun the same notebook cells with the same fixed constants; no persistent state, orders or imported project model is involved. Preserve an allowed summary and its retrieval date when it actually runs. Do not convert this prepared script into a claimed data result.
