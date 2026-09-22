# Norgate route: current evidence and access boundary

Checked 2026-09-22 15:04 UTC. This is a vendor-access assessment, **not a Norgate sample acceptance**. No account was created, software installed, subscription purchased, vendor database queried, or 2026 market data read.

## Actual local access

Targeted read-only inspection found no Norgate/Premium Data directory immediately under Program Files, Program Files (x86), ProgramData, LocalAppData or AppData; no Norgate uninstall entry in the usual HKLM/HKCU registries; no matching updater process; no `norgatedata` package in the project `.venv`; no user `.norgatedata` folder or `NORGATEDATA_ROOT` variable. No credential values were inspected or printed. These checks do not prove that the user lacks an account or a nonstandard installation; they establish that this project has no verified usable local NDU route today.

## Product and minimum access

The minimum suitable US package is **Platinum**: daily history from 1990, delisted securities, historical index membership, and OTC continuation for securities formerly listed on a major exchange. Published prices are **USD 346.50 for six months / USD 630 for twelve months**. Diamond adds older history and is unnecessary for the project's 2016–2025 period. The extra current-OTC package is not needed merely to obtain formerly major-exchange-listed securities. Prices are listed USD, before any location-specific checkout treatment. [Official package comparison](https://norgatedata.com/stockmarketpackages.php)

The free Platinum trial lasts **three weeks** but restricts daily history to **two years**. It includes the relevant features, so recent 2024–2025 cases could test access after activation, subject to the actual returned date range. It cannot supply the 2023 ATVI event or the complete 2016–2025 research interval at today's date. No trial has been activated. [Trial form](https://norgatedata.com/subscribe/freetrial.php), [subscription page](https://norgatedata.com/subscribe/)

## Documented fields, not yet run against licensed data

The official Python package needs a running Windows NDU installation and an active subscription. Its documented interface permits the following mapping; actual raw schemas must still be inspected before implementation. [Official Python package documentation, linked by Norgate](https://pypi.org/project/norgatedata/)

| Vendor interface | Proposed v9 use / boundary |
|---|---|
| `database('US Equities')`, `database('US Equities Delisted')` | Enumerate current and terminated instruments together; retain `assetid`, symbol, name. |
| `assetid(symbol)`, `symbol(assetid)` | Namespace `NORGATE:ASSETID`; identity is separate from current display ticker. |
| `index_constituent_timeseries(assetid, indexname, ...)` | Daily membership indicator; not an announcement timestamp. |
| `major_exchange_listed_timeseries(assetid, ...)` | Major-exchange versus OTC status; not ultimate cancellation. |
| `price_timeseries(assetid, start_date=..., end_date='2025-12-31', ...)` | Date/OHLC, volume, turnover, unadjusted close, dividend where applicable. |
| `StockPriceAdjustmentType.NONE/CAPITAL/CAPITALSPECIAL/TOTALRETURN` | Record exact adjustment setting, not an assumed default. |
| `PaddingType.NONE` | Preserve missing observations; never manufacture tradable prices. |
| `last_database_update_time('us')` | Local update time, not historical information availability. |

Dividend-column content depends on adjustment choice and is associated with entitlement before the ex-date, not cash payment. Total-return prices must not receive the same distribution again. [Python dividend notes](https://pypi.org/project/norgatedata/)

## Material data gaps

Norgate documents stable lifetime AssetIDs, but supplies only current ticker/name, not dated former tickers. Index membership describes effective dates; announcement dates are absent. Historical corrections are applied without version history. Delisting means no longer tradable in that country's market, distinct from moving to OTC. Delisting reasons, delisting returns and events after termination are not supplied. Exact historical exchange names are absent; major-exchange status is available. Historical sector classification is absent. The FAQ and Python documentation disagree on the start of major-exchange status coverage (1990 versus 2000); actual returned coverage needs checking. [Data FAQ](https://norgatedata.com/data-package-faq.php), [Python documentation](https://pypi.org/project/norgatedata/)

Project consequence: downloading this database today would create a revision-bearing reconstruction, not prove what was received historically. `available_at` must remain unknown unless a separate dated announcement establishes it. Membership transitions alone cannot establish strict pre-announcement availability. Ending OHLC cannot establish liquidation proceeds or cash-reuse date. A prior-ticker side table and independently sourced termination rights/settlement evidence remain necessary. This is our mapping assessment, not a claim that those additional facts have been obtained from Norgate. The vendor's suggested final-bar exit is **not adopted**: it would not prove an executable historical exit.

## License and reproducibility

The current EULA identifies version **20260825**, licenses an individual for personal use, allows two personal installations and backups during the subscription, and prohibits redistributing content without specific permission for limited extracts. Its content definition includes metadata and transformations. Private GitHub status does not supply that permission. The EULA distinguishes non-reconstructable derived outputs and requires removal of underlying content when access ends. Thus this project would keep vendor rows and snapshots outside Git; code and non-reconstructable check summaries could be candidates for sharing, with source-specific restrictions still checked. [Current EULA](https://norgatedata.com/subscribe/eula.php)

The subscription FAQ explicitly includes personal/academic research, permits personal processing outside the NDU installation, and requires deleting exported/normalized data, snapshots, event data and backups after expiry when not imminently renewing. It states no retention exception is available. These are substantial constraints for durable reproduction. No institutional or UCI account has been verified; permission for academic **use** is not evidence of free academic **access**. [Licensing FAQ](https://norgatedata.com/faq.php)

## Minimal next access action, if this route is selected

For a zero-price capability check, the user would personally activate the **US Stocks Platinum three-week trial**, install/log in to NDU, and let it create the licensed local database. No password needs to be sent to this project. Query results would be capped at 2025-12-31, with only the available portion of 2024–2025 inspected. An updater may synchronize newer vendor data automatically, so activation/setup must be kept distinct from this round's prohibition on reading 2026 observations; no updater has been started here.

For **the complete 2016–2025 history and ATVI 2023**, the minimum listed paid access is **US Stocks Platinum, six months, USD 346.50**, obtained by the user only after a separate purchase decision. It provides local daily membership, stable vendor IDs and price/status data; it still does **not** fill announcement-time, historical ticker, terminal-return or actual-payment gaps. Do not purchase merely to declare those gaps solved. Do not request raw database uploads to GitHub or ChatGPT. An active subscription must be maintained for retention/reproduction of extracted underlying data.

No Norgate data-dependent v9 checks have run. This route is currently **access blocked**, with capabilities and limitations verified from official documentation only.
