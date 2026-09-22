# Independent read-only review of the v14 sample

Reviewed the fixed public-fact mapper, `60_check_historical_sample.py`, the unchanged v9 implementation, normalized package, acceptance identity, information-time facts, price-coverage summary, and terminal-ledger checks. Selected TWTR/SIVB clauses were independently checked against the saved issuer-PDF text and saved SEC/official-document evidence. This review did not download more data, modify frozen inputs, run training, backtest returns, connect a broker, or execute the prepared QuantConnect cloud script.

## Commands actually run

| Command | Result |
|---|---|
| `.venv\Scripts\python.exe 60_check_historical_sample.py` | Exit 0; saved acceptance and source/input/output hashes verified |
| `.venv\Scripts\python.exe 60_check_historical_sample.py --verify-local` | Exit 0; additionally verified 35 local source/price-file hashes |
| `.venv\Scripts\python.exe 46_check_historical_universe.py --package data/reference/universe_events/v14_public_sample --universe SP500_PARTIAL_PUBLIC_V14 --asof 2023-03-15T09:30:00-04:00` | Exit 0; 6 membership rows, 3 core security-event rows, 1 known member, 0 eligible securities; full-universe/training-ready flags false |

The 35-file count includes preserved HTTP error bodies and metadata. It is **not** a count of 35 successfully retrieved evidentiary documents. Error responses are identified separately and are not used as the original text of an issuer or exchange publication. Web-tool extractions are distinguished from downloaded original document bytes.

## Mapping and evidence conclusions

- Six cases include five new project-local identities plus the unchanged ATVI reference. CIK is not misrepresented as a universal permanent security identifier. META/FB share-class continuity is supported by issuer evidence; the SIVB/SIVBQ mapping uses the explicit CUSIP/event evidence and does not join new reorganization shares to old common.
- The S&P membership stream is deliberately partial. The TSLA nonmember checkpoint is clearly derived from an announcement and is not counted as an actual index deletion. Missing AAPL/META membership and absent active-trading evidence remain unknown. The old SIVB inclusion remains queryable before its later removal.
- `effective_at` and `available_at` are separately sourced. The saved metadata distinguishes day-end/open-boundary conventions from true publication clocks. Fifteen of sixteen new fact records lack verified intraday publication timestamps, and all lack original vendor-receipt/revision vintages. The claim is limited dated-event querying, not fully archived point-in-time tradability.
- SIVB halt, index removal, listing suspension, ticker/venue transition, exchange delisting, and eventual cancellation remain different facts. OTC transition is not converted into v9 `unknown_terminal`. The issuer document explicitly distinguishes old common holders receiving no distribution from new equity issued for creditor claims.
- The known SIVB zero-distribution cancellation remains unsupported in the v9 ledger rather than being disguised as a zero-cash entitlement. The legacy ledger's retained quantity is visibly pending reconciliation and cannot be used as a tradable asset or valued position. This is an exposed limitation, not completed cancellation accounting.
- The TWTR document supports a $54.20 right for qualifying old common shares, subject to its exclusions. The hypothetical 10-share check creates $542 receivable and zero available cash. No payment receipt, sale price, terminal return or payout date is invented. ATVI remains a separate $950 hypothetical receivable regression with no cash released.
- AAPL and META each have 1,508 aligned 2020–2025 local snapshot rows. The checker rejects disallowed dates before reading price columns, checks OHLCV/date properties, and exports no prices. These are retrospectively downloaded Yahoo snapshots, not original contemporaneous quotes. Four case-price histories and all complete terminal-return linkages remain missing.

## Four separate verdicts retained

| Question | Review conclusion |
|---|---|
| Format and local identity | **PASS WITH LIMITS** for this selected package; no general vendor-ID/issuance-history certification |
| Information time | **LIMITED** to the cited facts and conservative boundaries; no complete historical receipt/revision record |
| Sufficient for return research | **FAIL**: missing case prices, terminal-return linkage, verified cash receipts and supported cancellation accounting |
| Complete historical universe | **FAIL**: selected partial index events cannot establish exhaustive membership or a historical trading-stock universe |

No blocking defect or overstated overall PASS was found in the reviewed acceptance. These results do not resolve the original 30-stock survivorship bias and are not evidence toward the 30% net CAGR goal.

## QuantConnect pre-2026 boundary check

The prepared cloud function creates a fresh QuantBook, sets both start/end to 2025-12-31, disables `seed_initial_prices`, and only then calls `add_security`. All price, lifecycle and universe-history queries use explicit 2020/2022/2023 start/end windows. The inspected local LEAN code gates automatic price seeding on `SeedInitialPrices` and initializes the default security initializer with `SecuritySeeder.Null`. No implicit 2026 price request was found in this static path. This is **not** cloud execution or a network-request audit; current cloud entitlements/runtime remain unverified and require user login.
