# QuantConnect route check — 2026-09-22

Status: **official documentation and local LEAN code inspected; no authenticated supplier query or licensed sample extraction completed by this check.** No account was created, subscription purchased, broker contacted, or order sent. No 2026 market observations were opened. This document describes access and gaps; it does not certify the full dataset.

## What the products mean

| Product | Useful documented capability | Boundary for this project |
|---|---|---|
| US Equity Coarse Universe | Daily historical trading-stock universe; price/volume and stable Symbols; history includes companies that later delist | A research universe filtered from tradable equities, **not an index membership history**. Daily end-of-day data must not be treated as available before that day's close. OTC is excluded. |
| US ETF Constituents | Historical holdings and weights for ETFs, including a possible SPY proxy universe | ETF holdings are **not an authoritative S&P index constituent announcement history**. Documentation says records can lag host ETF publications by up to one week; earlier history has monthly rather than daily coverage. |
| US Equity Security Master | Map/factor files and LEAN Split, Dividend, SymbolChangedEvent, Delisting objects | Corporate-action history, not an archival feed of original announcements, shareholder-specific receivables, or cash settlement confirmations. OTC is excluded. |

Sources: [Coarse Universe](https://www.quantconnect.com/docs/v2/writing-algorithms/datasets/quantconnect/us-equity-coarse-universe), [ETF Constituents](https://www.quantconnect.com/data/quantconnect-us-etf-constituents), [Security Master](https://www.quantconnect.com/docs/v2/writing-algorithms/datasets/quantconnect/us-equity-security-master).

## Identity, fields, and information time

LEAN's `Symbol.ID` is the provider namespace to preserve; `Symbol.Value` is the ticker and may change. Historical lookup must resolve the ticker **as of a specified date**. A current ticker string alone is not a stable security ID. The official API supports a mapping-resolution date. [Security identifiers](https://www.quantconnect.com/docs/v2/writing-algorithms/key-concepts/security-identifiers).

Local code inspection at LEAN commit `8ee075a39918f2df6fe9e0a5944e366fb60d10dc` confirms these raw layouts:

| Source | Fields actually confirmed from parser/code | Missing for strict v9 information-time use |
|---|---|---|
| `MapFileRow` | date, mapped ticker, optional primary exchange, optional mapping mode | original announcement timestamp, original vendor receipt timestamp, revision vintage |
| `CorporateFactorRow` | date, price factor, split factor, optional reference price | original corporate-action announcement and shareholder payment confirmation |
| `DelistingEventProvider` | Warning/Delisted events derived from map-file delisting date; price taken from last data point, or engine fallback 0 when absent | independently proven liquidation price, final recovery amount, OTC continuation, actual cash settlement |
| `CoarseFundamental` | Symbol, time/end time, price, volume, dollar volume, fundamental-data flag; adjustment-factor properties | original dated publication/receipt evidence for retrospective reconstructed rows |

Code sources: [MapFileRow](https://github.com/QuantConnect/Lean/blob/8ee075a39918f2df6fe9e0a5944e366fb60d10dc/Common/Data/Auxiliary/MapFileRow.cs), [CorporateFactorRow](https://github.com/QuantConnect/Lean/blob/8ee075a39918f2df6fe9e0a5944e366fb60d10dc/Common/Data/Auxiliary/CorporateFactorRow.cs), [DelistingEventProvider](https://github.com/QuantConnect/Lean/blob/8ee075a39918f2df6fe9e0a5944e366fb60d10dc/Engine/DataFeeds/Enumerators/DelistingEventProvider.cs), [CoarseFundamental](https://github.com/QuantConnect/Lean/blob/8ee075a39918f2df6fe9e0a5944e366fb60d10dc/Common/Data/UniverseSelection/CoarseFundamental.cs).

Interpretation: an engine-generated Warning date is not evidence of an issuer's announcement date. `Delisting.price` is not proof of a cash entitlement or payment. In particular, this project's normalizer must not inherit the engine's zero fallback as an unknown recovery estimate. A valid licensed in-environment check would retain separate event type, effective time, observed engine time and unknown announcement evidence; it would not set `available_at = effective_at` automatically.

Price files use raw exchange-oriented OHLCV scaled in the file format; daily/hour prices are converted from deci-cents by dividing by 10,000. Normalization and factor application need explicit selection, and factor-adjusted returns must not be combined with duplicate dividend/terminal cash additions. [Equity format](https://github.com/QuantConnect/Lean/blob/8ee075a39918f2df6fe9e0a5944e366fb60d10dc/Data/equity/readme.md).

## Access and redistribution

The Free tier documents a cloud research node and minute-or-coarser datasets. That is a possible **in-cloud check**, subject to the logged-in organization's actual entitlements. API/CLI local use requires a paid organization. No current account entitlement is inferred from an installed LEAN checkout. [Tier features](https://www.quantconnect.com/docs/v2/cloud-platform/organizations/tier-features).

The download license is limited to the licensed organization's internal LEAN use. It prohibits redistribution and format conversion; a private GitHub repository is not an exception. Security Master documentation additionally restricts consumption to LEAN. Thus a cloud license does not authorize exporting raw history through logs, Object Store or CSV to this project's external Python normalizer. Share check code and appropriately non-reconstructive conclusions; obtain explicit rights before any raw or reconstructive export. [Dataset licensing](https://www.quantconnect.com/docs/v2/cloud-platform/datasets/licensing).

Local inventory: `M:\quantconnect-lean-runtime\Lean\Data\equity\usa` physically contains only `daily/spy.zip`, `factor_files/spy.csv`, and `map_files/spy.csv`; it has no checked-out coarse universe or required lifecycle case sample. The Git tree lists more historical regression samples, but that is not a production-data entitlement or provenance audit. Crucially, the data-specific [USA readme](https://github.com/QuantConnect/Lean/blob/8ee075a39918f2df6fe9e0a5944e366fb60d10dc/Data/equity/usa/readme.md) names AlgoSeek and reserves all rights. LEAN's Apache software license must not be extended to those price samples. None of these data files was copied into this project's Git deliverable; the daily-price archive was not opened.

## Current published cost and minimum action

Official documentation checked on 2026-09-22 gives these **Quant Researcher data charges**, separate from organization/compute fees and taxes:

| Item | Published amount | Relevance |
|---|---:|---|
| Free cloud research tier | $0 tier | First route to inspect a small sample in the permitted cloud environment; account login and actual entitlement remain to be verified |
| US Equity Security Master local annual subscription | $600/year | Required before local US equity/coarse downloads |
| Coarse data by historical date | 5 QCC = $0.05 per daily file | Small date sample avoids the bulk coarse package, but not Security Master/organization prerequisites |
| Coarse bulk history / later annual updates | $600 / $240 | Not needed for a few dates |
| US equities daily bulk history | $2,136/year | Separate market-price dataset; selected-ticker purchases may cost less |

Sources: [Coarse local access/pricing](https://www.quantconnect.com/docs/v2/lean-cli/datasets/quantconnect/us-equity-coarse-fundamental), [US equities local access/pricing](https://www.quantconnect.com/docs/v2/lean-cli/datasets/quantconnect/us-equity), [current pricing page](https://www.quantconnect.com/pricing). The dynamic pricing page did not establish an authenticated final organization quote in this run; stale $8/$10 plan claims were not used. No academic license or grant was verified, and student status alone does not establish one.

Minimum user action for this route, if selected: **sign in to an existing QuantConnect Free account in the local browser and expose a cloud Research workspace with US equity/fundamental history access**. Then run a no-order, no-training, fixed pre-2026 inspection in that environment. Keep raw data there and export only permitted non-reconstructive summaries. This can check historical universe inclusion, Symbols, mapped tickers and supported corporate actions; it still cannot prove original announcement receipt, OTC prices, bankruptcy recoveries, or shareholder cash-settlement dates. No purchase is proposed or authorized here. If raw v9-compatible local data is essential, this standard license is not the right export permission by itself.
