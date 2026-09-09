# 24组模型的完整对照

price=81价格/ETF列；fund=97列；full=125列；base=22列。所有主交易每5个交易日调仓，费用为单边10bp；cost20单独注明。native IC按各自预测周期、共同成熟日期比较，IC5则全部用同一1502日的5日标签。

| model | kind | horizon | input | features | native_IC_common_dates | IC5_full_dates | top5_CAGR | top10_CAGR | top5_max_drawdown | top5_IR | top5_cost20_CAGR | top5_gate | top10_gate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| v3_elastic_h5_base | elastic | 5 | base | 22 | 0.0242 | 0.0245 | 32.97% | 23.54% | -30.77% | 0.8215 | 25.63% | False | False |
| v3_elastic_h5_full | elastic | 5 | full | 125 | 0.0182 | 0.0184 | 26.24% | 17.58% | -38.39% | 0.5753 | 21.48% | False | False |
| v3_elastic_h5_fund | elastic | 5 | fund | 97 | 0.0134 | 0.0144 | 29.84% | 19.83% | -35.54% | 0.7145 | 24.23% | False | False |
| v3_elastic_h5_price | elastic | 5 | price | 81 | 0.0249 | 0.0258 | 34.25% | 21.26% | -37.63% | 0.8884 | 27.97% | False | False |
| v3_ranker_h5_full | ranker | 5 | full | 125 | 0.0169 | 0.0157 | 14.24% | 14.40% | -35.61% | -0.1363 | 9.92% | False | False |
| v3_ranker_h5_price | ranker | 5 | price | 81 | 0.0331 | 0.0343 | 23.76% | 20.18% | -35.84% | 0.4118 | 18.18% | False | False |
| v3_ridge_h5_full | ridge | 5 | full | 125 | 0.0172 | 0.0177 | 23.58% | 17.88% | -37.99% | 0.4328 | 18.86% | False | False |
| v3_ridge_h5_price | ridge | 5 | price | 81 | 0.0223 | 0.0236 | 29.68% | 22.82% | -38.89% | 0.6866 | 23.58% | False | False |
| v3_elastic_h20_base | elastic | 20 | base | 22 | 0.0565 | 0.0318 | 33.26% | 25.35% | -36.75% | 0.8138 | 29.54% | False | False |
| v3_elastic_h20_full | elastic | 20 | full | 125 | 0.0186 | 0.0065 | 18.59% | 18.60% | -38.68% | 0.1579 | 16.06% | False | False |
| v3_elastic_h20_fund | elastic | 20 | fund | 97 | 0.0161 | 0.0081 | 28.13% | 24.26% | -39.58% | 0.6053 | 24.81% | False | False |
| v3_elastic_h20_price | elastic | 20 | price | 81 | 0.0400 | 0.0244 | 28.07% | 24.75% | -40.87% | 0.5867 | 24.43% | False | False |
| v3_ranker_h20_full | ranker | 20 | full | 125 | 0.0297 | 0.0224 | 20.22% | 22.45% | -34.14% | 0.2343 | 17.45% | False | False |
| v3_ranker_h20_price | ranker | 20 | price | 81 | 0.0518 | 0.0343 | 21.75% | 22.40% | -45.86% | 0.3242 | 16.81% | False | False |
| v3_ridge_h20_full | ridge | 20 | full | 125 | 0.0183 | 0.0055 | 19.77% | 20.36% | -35.85% | 0.2135 | 17.12% | False | False |
| v3_ridge_h20_price | ridge | 20 | price | 81 | 0.0401 | 0.0242 | 29.27% | 24.67% | -38.86% | 0.6406 | 25.55% | False | False |
| v3_elastic_h60_base | elastic | 60 | base | 22 | 0.1121 | 0.0380 | 33.40% | 28.23% | -38.05% | 0.8008 | 30.04% | False | False |
| v3_elastic_h60_full | elastic | 60 | full | 125 | 0.0456 | 0.0106 | 22.51% | 20.45% | -40.65% | 0.3716 | 20.33% | False | False |
| v3_elastic_h60_fund | elastic | 60 | fund | 97 | 0.0605 | 0.0152 | 33.42% | 23.79% | -39.10% | 0.8560 | 30.85% | False | False |
| v3_elastic_h60_price | elastic | 60 | price | 81 | 0.1413 | 0.0367 | 36.84% | 22.76% | -39.77% | 0.9469 | 33.83% | False | False |
| v3_ranker_h60_full | ranker | 60 | full | 125 | -0.0170 | 0.0048 | 17.46% | 18.72% | -36.62% | 0.0412 | 15.66% | False | False |
| v3_ranker_h60_price | ranker | 60 | price | 81 | 0.0854 | 0.0281 | 23.59% | 20.30% | -42.66% | 0.4385 | 19.26% | False | False |
| v3_ridge_h60_full | ridge | 60 | full | 125 | 0.0452 | 0.0103 | 22.41% | 21.97% | -40.65% | 0.3660 | 20.07% | False | False |
| v3_ridge_h60_price | ridge | 60 | price | 81 | 0.1407 | 0.0362 | 39.13% | 23.51% | -39.60% | 1.0378 | 36.07% | False | False |
