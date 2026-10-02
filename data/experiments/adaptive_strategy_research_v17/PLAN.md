# v17 bounded adaptive research — registered before new results

Registered 2026-10-02 07:04 UTC; task began 06:58:44 UTC. Deadline 09:58:44 UTC, stop new experiments by 09:28 UTC. Baseline de51b46adf082a7708701cd2a209d44ade83fa8d; clean local main, remote same SHA verified. No prior local v17 found.

## Question and targets

Can persistent liquidity, medium-term signals, and a small annually trained model improve net return/risk versus simple common-condition controls? Research target net CAGR 20–30%, advanced >30%; full continuous drawdown preferably <=20%, budget <=30%. This supersedes the old sole minimum30/aspiration50 target. Development results cannot establish future profitability.

Maximum **18 new complete strategy/cost configurations**, annual fits counted separately. No leverage, shorting, options, Live/paper/broker actions, purchases, or 2026 market data. All failed and interrupted runs are retained. Implementation-error repairs are logged and are not disguised as parameter search. Original data/results are immutable.

## Route D: historical dynamic universe, cloud only (maximum10 configurations)

Use QC historical Morningstar-covered common stocks with stable SID, contemporaneous RAW price >$5. Daily observations for ALL then-eligible common stocks maintain exactly20 prior-session DollarVolume values. At each month-first decision, top100 by median, fixed SID ties. No current-day volume at current open, no today's-survivor list, no future-completeness universe filter. Warm-up2019–2021, evaluate complete2022–2023; these years remain development.

Seven10bp configurations: same-pool equal100, original20-day momentum top10,63-day momentum excluding latest20 top10, annual Ridge top10, medium-trend with one risk overlay, Ridge with same overlay, SPY. One strongest eligible research candidate plus equal and SPY at20bp adds3. Original v15 runs are historical context only; differing pool/source conditions cannot be labeled pure model improvement.

Ridge: StandardScaler fit on training only, alpha100; small fixed past-price/liquidity features, next-month split-adjusted price-return cross-sectional rank target, annual fits2022/2023. Only labels whose endpoint is strictly before deployment-yearJan1 may train. Feature/label endpoints and unresolved terminal/missing endpoints recorded; no zero-filled terminal return. Scoring universe is determined at scoring time, not by later label availability. Training months reconstructed as they were observed, not by querying current selected symbols backward.

Common cash100000,90%budget, whole shares, zero cash interest, raw native Equity orders/fills, v15 next-open reductions and following-open buys, identical last liquidation and fees. Split-adjusted price signals; dividends are LEAN cash-on-event proxy, not actual payment-date reconstruction. Reuse v15 cash/quantity checks and continuous close-equity peak. Risk overlay alone changes budget to45% below contemporaneous SPY200SMA, otherwise90%; no optimized thresholds/stops. It does not ensure a drawdown cap. Cases outside supported economic rights remain explicit.

Cloud generated code and hashes, parameters, fits, monthly outputs, model identity and derived checks saved; restricted records remain in cloud. No large encoded log-line transport (v16 truncation known). Missing authoritative evidence is not synthesized.

## Route L: local availability fallback, survivorship-biased prototype (maximum8 configurations)

At registration Chrome connection failed twice with request-header-policy errors. IAB opened QC but is logged out; user-only login requested. Local original2012–2025 snapshot identity checks passed59files/10oldmodels. Dynamic raw panel is not local. Continue useful local model research while cloud access is blocked, labeled separately throughout.

Use existing fixed30 surviving stocks, adjusted OHLC proxy, common original502 five-trading-day observations,2016-01-05 through2025-12-29. No old H60 predictions applied to new symbols. Five10bp configurations:30-stock equal,SPY90%,126-day momentum excluding last20 top10,new Ridge top10,same Ridge plus fixed45%/90% SPY200SMA budget. No extra stop/pause; diagnostic research only. Same initial100000, zero interest, next-open fractional-share adjustment proxy, close-equity continuous drawdown, final open liquidation fees for all. Reuse existing cash/fee rebalance solver, minimal readable adapter; not a native brokerage simulation.

Eight fixed features: r5,r20,r63skip20,r126skip20,vol20,dd63,relative20,SPYgap200. Target next20-session open-to-open return minus matching SPY return, divided by contemporaneous vol20*sqrt20. Annual StandardScaler+Ridge(alpha100),2016–2025, **10 fits**, date<Jan1 and label exit<Jan1, preserve all feature-ready prediction dates even if target not yet mature. Missing/imputation not fit across boundaries. Same-day cross sections never split randomly.

After five10bp results, choose at most1 non-control candidate by full DD<=30% then highest CAGR; if none meets budget choose least-DD only as rejected diagnostic. Re-run that candidate,equal,SPY at20bp (3more). This is a documented adaptive choice, not an unseen-test claim. No further fit/threshold/window/model sweep. Signal comparison trend/Ridge uses same exposure; risk contribution Ridge vs RidgeRisk is separate. The local universe cannot establish survival-bias removal or deployment readiness even if numerical targets pass.

## Evaluation and stopping

Report cumulative/net CAGR, full continuous DD, annual performance, volatility, turnover, costs, actual exposure/concentration, dominant stocks/months/years, matured-date prediction metrics as diagnostic. Global high water never resets at annual refit/recovery. Final candidate(s) require cost20 confirmation; numerical target and superiority vs same-condition controls judged separately. Independent validation and forward performance remain absent;2026 sealed.

Reject routes with inadequate evidence or no useful common-condition improvement; do not keep searching to meet a number. Cloud failures/login/API limits are recorded with exact completed counts; local success is never substituted for cloud validation. Reserve final30min for targeted tests, results, REVIEW_INDEX, material hashes/bundles, ordinary commit/push and remote SHA verification. No forced push.
