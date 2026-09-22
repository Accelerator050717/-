# Existing local historical price coverage

Read-only inputs; no downloads, training, return backtests, broker connections or 2026 observations. Checked window: 2020-01-01 through 2025-12-31; NYSE calendar: 1508 sessions.

| Snapshot | Whole-file dates / rows | Checked sample rows | Hash / format | Missing sessions / duplicates / invalid OHLC |
|---|---|---:|---|---|
| AAPL | 2012-01-03 to 2025-12-31 / 3520 | 1508 | PASS | 0 / 0 / 0 |
| META | 2012-05-18 to 2025-12-31 / 3425 | 1508 | PASS | 0 / 0 / 0 |

Only AAPL and META snapshots were opened. The five-name filename-only search (TSLA, SIVB, SIVBQ, TWTR, ATVI) prunes all 2026-named directories/files and reads no matching contents. Results are recorded explicitly in JSON; an absent local file does not mean the security lacked historical trading.

META boundary-record presence: {'2022-06-08': True, '2022-06-09': True}. The JSON date-alignment checks determine whether the period has a session gap. This is a current-META-labelled vendor series, not proof that the old FB ticker, share class and legal security identity were correctly mapped historically. Independent identity evidence is still required. AAPL/META are Nasdaq listings; the NYSE calendar is a US session-date alignment proxy here, not a claim about their listing venue or intraday tradeability.

Metadata records Yahoo/yfinance snapshots obtained in September 2026 with auto_adjust=False and back_adjust=False; the maximum observed date in each file is still 2025-12-31. The acquisition timestamp is not an information-availability timestamp for every historical observation. These settings do not guarantee untouched, original-vintage executable quotations: Yahoo historical OHLC can incorporate split conventions, and Adj Close incorporates vendor adjustment/revision history. Never mix adjusted prices with an independently applied identical dividend or terminal return.

Neither snapshot provides the missing sample securities' final market prices, delisting returns, takeover receivables or actual reusable cash receipt dates. Unknown terminal proceeds stay unknown; no terminal return is imputed and no final-bar liquidation is assumed. Passing schema and date alignment does not make this six-security lifecycle sample sufficient for return research or eliminate the original 30-stock survivorship bias.

Reproduce: `.venv\Scripts\python.exe tools/check_v14_price_coverage.py`. Only PRICE_COVERAGE.json and this summary are written. No price values are exported in either summary. SHA256, acquisition metadata, missing-date lists and check outcomes are in the JSON.
