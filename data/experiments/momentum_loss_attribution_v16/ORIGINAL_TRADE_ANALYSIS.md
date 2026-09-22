# Original B10 native matched-trade evidence

Original run, UI display precision. These are FIFO FillToFill rows; annual grouping uses exit year, not calendar-year mark-to-market.

## Money bridge (USD)

| Component | USD |
|---|---:|
| initial_equity | 100000 |
| final_equity | 45921.277233917004 |
| net_account_pnl | -54078.722766082996 |
| native_matched_price_pnl_display | -53783.17 |
| dividend_cash_engine_proxy | 2009.72 |
| split_fraction_cash_engine_proxy | 0.000884917 |
| actual_fees | 2305.2826509999973 |
| explained_with_display_price_pnl | -54078.7317660829973 |
| unexplained_residual_account_minus_bridge | 0.0090000000013 |
| displayed_allocated_fees | 2305.3126750000000026 |
| display_allocated_fee_difference | 0.0300240000027026 |

## 2022: native exit-year scope

| UI ticker | Gross price P&L | Allocated displayed fee | Matched rows |
|---|---:|---:|---:|
| NTRB | -3825.54 | 12.62 | 1 |
| TSLA | -3514.01 | 37.59 | 3 |
| AMC | -2787.48 | 13.35 | 1 |
| UBER | -2596.20 | 31.88 | 2 |
| XYZ | -2450.40 | 14.9496 | 1 |
| GME | -2426.48 | 14.03752 | 1 |
| UPST | -2304.18 | 14.28 | 1 |
| EQT | -2007.58 | 10.830425 | 1 |
| MRO | -1970.87 | 11.13761 | 1 |
| DVN | -1767.78 | 36.61 | 3 |

Winners:

| UI ticker | Gross price P&L | Matched rows |
|---|---:|---:|
| FSLR | 1847.46 | 2 |
| ENPH | 1842.50 | 2 |
| ATVI | 1812.76 | 2 |
| NFLX | 1331.66 | 2 |
| CVX | 1049.86 | 2 |
| ISRG | 737.94 | 1 |
| XOM | 707.50 | 3 |
| T | 680.94 | 1 |
| GILD | 605.15 | 1 |
| OXY | 596.36 | 3 |

## 2023: native exit-year scope

| UI ticker | Gross price P&L | Allocated displayed fee | Matched rows |
|---|---:|---:|---:|
| KALA | -4671.24 | 10.53436 | 1 |
| TOP | -4240.34 | 5.80074 | 1 |
| SHOP | -2830.85 | 26.80634 | 3 |
| CVNA | -2583.00 | 15.62 | 2 |
| UPST | -2412.90 | 6.97 | 1 |
| MSGM | -1652.52 | 4.12848 | 1 |
| AMC | -1538.16 | 7.72 | 1 |
| XYZ | -1089.75 | 18.93 | 2 |
| AMD | -949.55 | 27.66 | 3 |
| AI | -908.41 | 24.314769999999999 | 4 |

Winners:

| UI ticker | Gross price P&L | Matched rows |
|---|---:|---:|
| META | 5114.34 | 6 |
| NVDA | 1345.89 | 5 |
| SOFI | 1126.37 | 3 |
| NKE | 934.77 | 2 |
| RIVN | 913.59 | 2 |
| HZNP | 694.44 | 1 |
| TSLA | 686.05 | 8 |
| COIN | 672.30 | 5 |
| MSFT | 573.78 | 2 |
| EL | 537.74 | 1 |

## full: native exit-year scope

| UI ticker | Gross price P&L | Allocated displayed fee | Matched rows |
|---|---:|---:|---:|
| UPST | -4717.08 | 21.25 | 2 |
| KALA | -4671.24 | 10.53436 | 1 |
| AMC | -4325.64 | 21.07 | 2 |
| TOP | -4240.34 | 5.80074 | 1 |
| NTRB | -3825.54 | 12.62 | 1 |
| XYZ | -3540.15 | 33.8796 | 3 |
| SHOP | -2830.85 | 26.80634 | 3 |
| TSLA | -2827.96 | 65.18 | 11 |
| CVNA | -2583.00 | 15.62 | 2 |
| GME | -2426.48 | 14.03752 | 1 |

Winners:

| UI ticker | Gross price P&L | Matched rows |
|---|---:|---:|
| META | 5114.34 | 6 |
| FSLR | 1847.46 | 2 |
| ENPH | 1842.50 | 2 |
| ATVI | 1812.76 | 2 |
| NFLX | 1342.49 | 4 |
| SOFI | 1126.37 | 3 |
| CVX | 1049.86 | 2 |
| NKE | 934.77 | 2 |
| RIVN | 913.59 | 2 |
| ISRG | 737.94 | 1 |
