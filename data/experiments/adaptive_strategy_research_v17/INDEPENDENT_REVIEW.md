# v17 independent review

This review covers the local completed experiment and static cloud-code contracts. It is not a cloud execution, paper-trading, or independent-profitability certificate. The review itself performed **0 fits and 0 strategy backtests**; loading frozen models and re-predicting saved keys is a read-only check.

## Conclusion on the completed local experiment

No local configuration meets the combined net-CAGR >=20% and full drawdown <=30% criteria. Unscaled Ridge reaches20.1091% CAGR but draws down31.2381%. The selected trend-budget Ridge has18.3952% CAGR and21.3015% drawdown at10bp; at20bp,16.4029% CAGR and21.4077% drawdown. The20bp same-pool equal control earns17.2561%, so the candidate's return advantage does not survive the higher cost. These are2016–2025 fixed-survivor30-stock development prototypes, not historical-dynamic-universe validation.

Compared with unscaled Ridge, the overlay reduces the maximum drawdown by9.9367percentage points, at a1.7140point annualized-return cost. This isolates a portfolio-budget change on the same predictions; it does not demonstrate an improved model. Compared with equal weight, the10bp overlay gains1.0035points of CAGR but at20bp loses0.8532points. A lower drawdown can be useful while the strategy still fails the combined goals.

## Checks actually completed

- Rehashed all59 current original input files listed in local `INPUT_IDENTITY.json`, including the old H60 identity-verification inputs. Re-ran `load_inputs()` without fitting or downloading.
- Loaded all10 hash-identified new annual models, verified feature order/alpha100/SVD, and checked scaler means and sample counts against the actual training cohorts. Every observation and label endpoint precedes its deployment-year January1 boundary.
- Recomputed all75,240 saved predictions from those frozen models and actual features. Maximum absolute discrepancy is below1e-16, consistent with CSV float representation. See `INDEPENDENT_MODEL_CHECKS.json`.
- Independently reconstructed each of8 saved final account amounts from signed trade cash flows; verified fee=absolute notional×rate, annual compounding, security-PnL totals, decision-before-trade, nonnegative cash, and global drawdown including initial100,000. Worst cash-flow residual is approximately3.3e-9dollars. See `INDEPENDENT_NUMERIC_CHECKS.json`.
- `tests/test_v17_research.py` contains11 targeted, explicitly fictional checks. They cover exact return endpoints, invariance to historical prefix truncation, no change to matured training data after future-price perturbation, retained immature prediction rows, next-open execution, both round-trip fees, continuous high water across a calendar-year boundary, rejection of missing executable prices, exact rank ties, strict label maturity, and cloud rolling-liquidity/terminal-label contracts. Run with `.\.venv\Scripts\python.exe -m unittest tests.test_v17_research -v`.

The accounting checks establish consistency of the adjusted-price fractional-unit proxy. They do not establish real fills, payment dates, or survival-bias removal. Price adjustment already contains dividend effects; no separate dividend cash is added in the local adapter.

## Plan discrepancy found after the fast local run

Root PLAN says to choose the least-drawdown rejected diagnostic if all candidates exceed30% drawdown; the local generation code/PLAN says highest CAGR in that fallback. This was reported promptly after inspection. The completed experiment has exactly one eligible candidate (`ridge_trend_budget`), so the discrepant branch was not executed and did not affect selection, costs, fits, or any result. Original generation identity/source was preserved and the discrepancy was disclosed rather than retroactively rewriting the plan.

## Cloud static review and remaining evidence boundaries

The cloud subclass uses the original native-equity two-stage execution and continuous close-NAV accounting. Daily historical Fundamental observations populate20-session liquidity windows; a missing observed session prevents that window from silently becoming "the last20 available values." Current price eligibility is applied at selection. Monthly feature rows are built before their future outcomes exist; annual fitting uses only previously matured endpoints, and old H60 predictions are not applied to new securities.

Two review findings were addressed in cloud code before its run: derived output is split into bounded RuntimeStatistic chunks with count/hash metadata, and the training-label limitation is explicit. A missing/terminal endpoint remains unresolved, never becomes zero return or a fabricated liquidation. However, ranks among resolved labels are **conditional on observed endpoints**; a passed cash/format gate cannot be read as complete-lifecycle/survivorship-free training validation. Any material unresolved cases require interpretation of the actual run output.

The algorithm starts in2018 to accumulate history and does not trade before2022. Consequently, the ordinary platform headline CAGR includes idle preparation time. Fair evaluation must use its custom2022–2023 result,501 regular-close observations, and24 monthly decisions, not the ordinary full-engine-span annualization. Native company-action/terminal cash and payment-date limitations from v15 remain.

Static source review is not proof that QuantConnect ran the code successfully. Cloud execution identities, actual model counts, chunk completeness, gates and numeric results must be read from the separately saved cloud run evidence. This document does not certify any cloud result absent those records.

## Reviewed implementation identity

- Local completed generation: `tools/research_v17_local.py`, SHA256 `a66a1453b252445ff13fbae7c3ff869e3fcd10f080d3fc02c5750d6eebcc79cf`.
- Cloud code at static review: `tools/qc_v17_research.py`, SHA256 `dff379e29f33d8811c42fd9851b27e847c7556a3053709da9654bf6fe656c086`.
- Pure cloud helpers: `tools/qc_v17_features.py`, SHA256 `ebe2fa043ba519e233d7253d61134efa1c4986bbc2922fc268c7df7bc5d36b08`.

Later cloud repairs must retain their own identities; these reviewed hashes must not be replaced to imply that this review certified an uninspected source version. Original inputs/results and2026 embargo remain intact.

## Appendix: revision02 duplicate-snapshot repair review

The first actual cloud attempt (`199d1175e796340f958a3e96c45bdf67`, project37249270, engine2.5.0.0.18149) stopped at2018-12-03 with `Duplicate Fundamental SID`, before any model fit or order. Its failed result remains recorded; it is not a strategy-return observation.

Revision02 changes input validation only: the required-field snapshot for a SID is copied on first observation, identical subsequent snapshots are counted and ignored, and any conflicting required field raises an explicit error. Dates, availability, security type, price, DollarVolume and ticker are compared. It does not keep an arbitrary "best" conflicting row or insert duplicate dates into the20-session window. The first snapshot cannot be mutated by the caller.

13 targeted checks now pass, including an exact duplicate on every fictional universe session, no window inflation, conflicting duplicate rejection without overwriting the first record, and an error containing field names/times rather than price/volume payloads. Local methods and the frozen revision02 cloud snapshots have matching ASTs; snapshot bytes match `cloud/revision02/PRE_RUN.json`:

- Cloud main SHA256 `4549f9b06504530ae32908fb65ee882044ba18ee42248bae5a42de61b5ee8b8d`.
- Cloud helper SHA256 `058d2c541fc47b1cdebfaae6b90bad759f8ea2b84388f13b15db2dd0ce74b70a`.
- Unchanged core recorded SHA256 `ab35fd31f6c7f30aa762bdfe4b82ac2675142c9b61fa1067a7e2781eac46e357`.

No additional blocking cash, annual-label cutoff or execution-timing issue was found in this revision's static inspection. The review does not imply that conflicting duplicates are safe to accept or that a subsequent cloud run has succeeded; actual retry evidence remains separate.

The next attempt (`279bf8437f4abd7a2d5b620bdccbefde`) also failed before fitting/trading: the running cloud helper lacked the new function. The saved attempt record attributes this to pasting before the editor tab finished loading, despite an initial clipboard readback. This is a deployment/source-selection failure, not evidence against or in favor of the research model. Reopening and reading the actual saved tab is needed in addition to an immediate clipboard echo.

## Appendix: derived-output verifier

`tools/summarize_v17_cloud.py` (review SHA256 `e3c1f126517a1e34ad825bbedfdb86cf9cd66236b2ee9f66a3c6559bd83c20b2`) validates chunk presence/count/hash, two-year monthly/annual arithmetic, model parameter hashes, strict deployment-label boundaries and per-security cash-PnL totals. Two additional synthetic checks establish that missing/corrupt chunks and a label maturing exactly on January1 fail verification. The targeted suite now has15 passing checks.

Capture RuntimeStatistic cell values as their original strings. Parsing/re-stringifying inner JSON through JavaScript can convert `1.0` to `1`, changing the Python digest without changing economic meaning. That is a transport mismatch to report, not a reason to disable hashes. The verifier correctly states that monthly closes provide only a drawdown lower bound; it does not pretend to independently reconstruct daily maximum drawdown.

## Appendix: actual200-character transport limit

The captured running output from `be47f9b57e7e311484b1a1f8bd13af55` proves that3500-character chunks were insufficient. `attempt03_partial_runtime.json` contains41 visible cells:31 are exactly200characters and incomplete JSON;10 index manifests remain complete at98–99characters. The visible2022 fit prefix reports3450 training rows, but complete model parameters/hash cannot be recovered from that truncated prefix. This is partial fit/run evidence, not a verified full artifact set.

The original partial capture is retained. A planned repeat of the same research configuration changes transport observability only; it must retain its own run identity and actual repeated fit count. Neither completing a transport repair nor a successful static test retroactively makes the original clipped output complete.

## Appendix: first completed cloud result and source identity

The final logs of attempt03 were subsequently recovered through the rendered log DOM's text, despite blank-looking cells. They contain a full identity, two fit summaries and full strategy summary. All three actual runtime source hashes match the frozen revision02 upload bytes with exactly CRLF→LF normalization plus one terminal LF; executable ASTs also match. No broader semantic normalization was needed. See `INDEPENDENT_CLOUD_SOURCE_CHECK.json`.

The completed Ridge10 run reports final86,297.525113903dollars, net cumulative−13.7024748861%, CAGR−7.1082270238%, and daily maximum drawdown42.2349682561%. Annual returns−40.6781082561% and+45.4733195065% compound to the reported final amount. Two annual fits used3450 and4645 rows; recorded observation/label endpoints precede each January1 boundary, and fit model hashes match the final summary. These facts were independently recalculated from saved log records; daily drawdown and full parameter hashes cannot yet be independently verified from the clipped artifacts. `INDEPENDENT_FIRST_CLOUD_NUMERIC_CHECK.json` records that distinction.

Economic/data limits remain:9 missing observations include3 held observations;18,807.25dollars is the sum of marked exposure over those observations, **not** a loss contribution or distinct capital at risk. Native terminal liquidation5,715.30dollars is an engine cash proxy, not verified final payment. Six unresolved training-label endpoints remain recorded. The run fails both the research return target and30% drawdown budget; those limitations do not justify silently changing or deleting its securities.

The same actual logs also prove a50-custom-statistic limit. The180-character-chunk prototype was therefore stopped before cloud deployment, despite its18 passing synthetic tests. Its source/tests are archived in `cloud/abandoned_transport_180chars/` as an unsuccessful implementation path. No new cloud fit/backtest was run with that prototype. The replacement must remain within the key and per-value limits and state which full artifacts cannot be retained on Free.

## Appendix: bounded Free observability replacement

The replacement uses at most45 custom statistic keys, each at most200 serialized ASCII characters. It retains24 month-end account summaries plus a fixed set of scalar results/model summaries. Full fit parameters, source identity and the final aggregate result use ordinary log records under a9000-byte self-imposed budget including64bytes of framing per record, leaving headroom within the observed Free10KB allowance. An omitted record sets a sticky `log_complete=False`; it is not silently treated as saved. Full predictions and full per-security PnL are explicitly not archived. Ordinary derived Equity/Gross/Cash charts are added for the official results-download path; their actual row count/completeness must still be verified.

The active targeted suite has17 passing checks, including the45th key/update boundary, rejection of a46th unique key, the exact200-character serialized boundary, Unicode expansion, and truthful log-budget failure. These are fictional format/budget checks, not proof of cloud storage availability.

`INDEPENDENT_OBSERVER_ONLY_CHECK.json` compares the replacement (main sourceSHA256 `934c0956fdc94ccb740f7cdf74b85284727afcd3bd7e2b88f602ddf6a5c215ee`) with the actually executed revision02 snapshot. Universe selection, history reads, label resolution, fitting, decisions, event processing and daily accounting are AST-identical after removing **only** explicit log/runtime-statistic/plot calls. Initialization is likewise identical after excluding those calls and the three new output-budget state variables. No feature, label, fit, order, cash or holding-update nodes were removed from this comparison. The evidence supports an observation-only repeat; comparison of the actual repeated results remains a separate check.

## Appendix: completed observation-only repeat

Run `8853629b1527c771f1e1b44cf99bbfc3` completed and its saved capture contains45 custom RuntimeStatistic values (maximum104characters) and7423bytes of V17 JSON logs including64bytes of framing per record. All56 numerical fields from the original full summary match **exactly**, with no missing/changed original summary fields. Both model hashes are identical; the newly retained full scaler/coefficient/intercept parameters independently reconstruct those hashes. The three runtime source hashes again match their respective reviewed files after LF normalization plus one terminal LF.

The repeat's24 monthly account records reconcile internally; compounding residual is approximately7.3e-11dollars. Original run24-month records were not retained, so month-by-month equivalence between the two runs is **not verified**. The independent comparison is `INDEPENDENT_CLOUD_REPEAT_CHECK.json`. Actual repeat training count is2, even though the models match; this review itself fitted0 models.

The daily drawdown remains an engine-reported42.23497%; no downloaded501-day account series was available at this checkpoint. Verified month-end records imply at least40.67811% drawdown. Full predictions and full per-security PnL remain unarchived; checksums identify them but do not replace their contents.

The top-PnL table uses full stable SID strings. A prefix such as `FB`, `CCIV`, `NB`, `YHOO` or `WPI` is not by itself proof of the trading ticker on a particular date. Native terminal cash5715.30dollars incurs zero engine fee; the difference between gross turnover×10bp and the reported fee is5.71530dollars, consistent with that disclosed proxy rather than an unexplained fee residual.

## Appendix: comparison guards

The read-only comparison requires all seven registered10bp modes, including equal and SPY controls, before selecting a finalist. Review added a guard against incomplete/mismatched source identities and stopped absent signal hashes from comparing equal as `None==None`. Candidate selection first applies the30% full-drawdown budget; meeting the20% return floor is reported separately. If every candidate exceeds the budget, only the least-drawdown rejected diagnostic is selected, not the highest-return over-budget candidate. Synthetic regressions cover each boundary and missing/false complete-log declarations; the current targeted suite has22 passing checks. No cloud strategy was changed by these verifier repairs.

## Focused execution, adjustment and label review

No additional confirmed implementation defect was found that requires stopping the remaining fixed comparisons. This is a limited code/evidence judgment, not a claim of perfect market-data or execution fidelity.

- **Two-stage execution:** the monthly completed-close decision freezes whole-share targets. Reductions are MOO orders for the next opening; buys are funded only after actual sell receipts/open orders have resolved, then use a later MOO. Initial entry also waits for that second opening, even when there is nothing to sell. This deliberate delay applies to every new mode. Stock daily-bar fill notifications and SPY minute-bar notifications have different receipt times; the native modeled opening price must not be presented as a real observed auction fill. Pending sells are not spent as cash. Immediate settlement is still a research assumption.
- **RAW holdings versus adjusted signals:** holdings and fills use RAW data; only signal/label History requests use SplitAdjusted prices. Both endpoints of a forward label come from the same request/adjustment anchor, so a split between endpoints is not accidentally treated as a gain/loss. Native split events adjust held quantities and frozen targets, with separate cash-in-lieu accounting. Price-return labels exclude dividends; the native account includes dividend cash once. Actual payment dates and full spinoff/exchange rights remain unverified. A split combined with a missing fresh held mark would require checking the actual event path; aggregate missing counts do not independently rule out every stale-mark issue.
- **Missing-label scope:** six unresolved endpoints are recorded across all2019–2023 transitions. Only the first four have endpoints before either annual deployment cutoff: APC(2019-09-03), YHOO(2019-11-01), CELG(2019-12-02), WPI(2020-06-01), where strings are stable SID prefixes, not independently verified trading tickers. Both2022 and2023 fitted cohorts therefore have four otherwise generated terminal rows unavailable for ranking, against3450 and4645 resolved training rows. The ABMD endpoint2023-01-03 and ATVI endpoint2023-11-01 enter neither annual fitted cohort. They do affect later completed-label/IC coverage. No missing terminal value is set to zero and scoring does not depend on a future label, but the remaining training ranks are conditional on available endpoints; their small row count does not prove a small economic bias.
- **Prediction target versus held return:** the cloud model predicts the rank of next-month decision-close price return. Executed holdings start/end at delayed openings, pay costs and receive proxy dividends. The model target is consequently not identical to realized net holding return. This mismatch is a stated research design limitation; positive rank IC alone cannot establish profitable execution.
- **Fair comparison scope:** the five concentrated stock-signal modes share the same contemporaneous127-price-point eligibility and SID ordering. Equal100 retains the full selected pool where current prices exist, including names with shorter signal history, and whole-share rounding can leave more cash than in a10-stock book. SPY has one instrument and its own rounding. Therefore model-versus-equal differences combine ranking, eligibility, concentration and actual exposure; only the paired same-signal risk overlay isolates the chosen budget rule. Target90%/45% is calculated at decision prices, not guaranteed actual fill/close weight after gaps. Ridge10's observed maximum aggregate exposure91.0262% and maximum single close weight12.5256% illustrate that distinction without indicating borrowing; the original cash/leverage gate still applies.

No supplier RAW panel was downloaded. Complete per-month membership lists, complete prediction vectors and full per-security daily paths are not locally retained under this Free output protocol. Common frozen source and parameter/model/prediction fingerprints support the comparison but do not substitute for an immutable raw-data snapshot or prove exact monthly membership equality across every run. A candidate near a decision threshold must retain these limitations; an engine gate pass cannot establish complete real-world terminal settlement, independent validation or deployment readiness.

## Descriptive annual coefficient check (no fitting)

`cloud/standardized_coefficients_2022_2023.csv` compares the eight saved coefficient values from `cloud/cases/ridge_cost10/FITS.json` (source SHA256 `efe69c37ee0f970d0aef980e5068f420a1c73122a95a58c2af423fb99f598b97`). Only one of eight signs changes: `return_20` moves from -0.006959 to +0.001192 and remains seventh by absolute coefficient size. The largest absolute coefficient changes from `return_126_skip_20` (-0.021385 in2022) to `volatility_20` (-0.033015 in2023, versus -0.018835 previously). `return_63_skip_20` remains positive (+0.016297 to +0.017675), moving from fourth to second by absolute size; the positive median-dollar-volume coefficient falls from +0.017893 to +0.009419. This is a change in fitted sensitivities, not proof that a feature caused gains/losses or that annual fitting is unstable. Each coefficient is measured in that year's training-standard-deviation units, with a different fitted scaler and correlated inputs.

The model's label remains a monthly decision-close to next decision-close price-return rank; the implemented portfolio reduces at the next opening and buys at a later opening, then incurs costs and receives native dividend cash. Thus the label and executable holding return have different intervals and economic contents. Aligning these while holding features, universe, fitting schedule and portfolio construction fixed is a legitimate future single-factor question. No alignment experiment, additional fit, model selection or strategy modification was performed for this descriptive check.

## Actual Ridge same-signal risk pair

The Ridge10 run and RidgeRisk10 (`34c60a7570c87925873ca04af7dcafe7`) have identical2022/2023 training-input hashes, full scaler/coefficients/intercept, model hashes, row counts, observation/label boundaries and feature order. Their prediction-panel checksum is also identical (`f31094d72727e08bad852ce71d9c52a8cc4b20b62806b4f8ff90b58d267ba556`); all eight common source/configuration identity fields match. `INDEPENDENT_RIDGE_RISK_PAIR_CHECK.json` retains the complete read-only comparison and input-file digests. This supports a same-signal budget comparison, while full prediction contents remain unarchived.

The SPY-trend45% budget reduces reported daily drawdown from42.23497% to38.91544%, an improvement of3.31953percentage points, but lowers net CAGR from-7.10823% to-9.76533% (-2.65711points). Final equity falls by4863.123156516dollars to81,434.401957387. Average invested exposure falls from81.46524% to62.86093%, and volatility from28.98221% to20.82886%.2022 return improves by3.34205points while2023 gives back15.51915points relative to the same Ridge signal. Neither result reaches the20% return floor or30% drawdown budget. The fixed overlay has not rescued this signal in the two-year development sample; lower volatility alone is not an acceptable profitability result. Daily drawdown is still engine-reported, with monthly arithmetic independently checked.

## Complete seven-case10bp review

`INDEPENDENT_CLOUD_SEVEN_CASE_CHECK.json` independently checks all seven saved cases, common source/configuration identity,24-month cash-plus-marked-holdings accounting, monthly dollar PnL, annual compounding and final cumulative/CAGR calculations. Maximum monthly dollar discrepancy is approximately1.46e-11. Annualization uses the explicitly implemented730calendar days divided by365.25, not an exact two-year exponent. All seven source identities match; their daily full-history drawdowns remain engine-reported.

Trend63 and Trend63Risk share exactly the same score-panel hash (`774dfee26f1f1d36bdf97fb6e62f4ba6e54591af5ea1852fc94f4670f139ed4c`) and no fitted models. The overlay improves drawdown by4.87544points (37.55838% to32.68295%) but reduces CAGR by1.89915points (-1.13009% to-3.02924%) and final equity by3716.87221dollars.2022 return improves3.38542points, while2023 return falls11.70030points. Thus both same-signal overlay pairs trade less exposure and shallower losses for lower two-year returns; neither meets the risk ceiling or return floor.

All five non-control candidates have daily maximum drawdown above30%. The comparator correctly rejects all five and chooses Trend63Risk only as the predeclared least-drawdown **failed diagnostic** for20bp sensitivity. It is not an accepted strategy or the highest-return candidate. SPY, the best budget-compliant control, has only1.39111% net CAGR and22.15843% drawdown; it also misses the research return target. The chart's seven source CSV hashes match the saved24 observed month-end values plus initial capital; the image is readable and explicitly states that connecting lines do not represent intramonth drawdown. No new fitting, trading or parameter search was part of this check.

## Operator annotation versus actual duplicate run

The attempted SPY20 run `b429500071dead38dd40a2f87e5a3142` actually reports Equal20 in both generated identity and final summary. Its operator annotation remains SPY20 in the original capture; it was not silently rewritten. A minimal parser guard now rejects a provided mode/cost annotation if it disagrees with the actual summary, while the existing generated-identity checks independently confirm actual mode/cost. The new regression covers wrong mode, matching annotation and wrong cost; the recorded targeted suite has23 passing tests. Frozen strategy/feature/execution source is unchanged.

`INDEPENDENT_DUPLICATE_RUN_CHECK.json` independently verifies that this original capture fails **only** the annotation guard, made zero fits, and is a duplicate of the canonical Equal20 run. All24 monthly CSV records match byte-for-byte. Every summary field matches except an approximately9.1e-13dollar attribution-residual difference. It counts as an extra completed replay, not a new configuration and not a successful SPY20 run. The later actual SPY20 run has a separate backtest identity (`e316c96dea9462fc38630c6c684bd128`). Browser editor settings and user-assigned run labels are not proof of what the completed engine executed.

## Final ten-case and cost review

All ten canonical cloud cases were re-read directly from their original completed captures using the final read-only parser, including the new annotation guard. Every case passes, and its raw summary, full model parameters and24 monthly rows match the saved derived case. Capture SHA256 values also match. Runtime source hashes agree with `cloud/revision03/main.py`, `cloud/revision03/qc_v17_features.py` and the frozen `cloud/qc_v15_dynamic_pilot.py` after the previously established LF-plus-one-terminal-LF transformation. Early root-level cloud main/helper snapshots and the uncompressed original tools core are different preserved artifacts, not the recovery source for these runs. Details are in `INDEPENDENT_CLOUD_TEN_CASE_CHECK.json`.

Increasing ordinary single-side cost from10bp to20bp reduces net CAGR by0.37813points for Equal100,0.13092points for SPY, and0.99233points for Trend63Risk. The failed diagnostic ends at92,123.76494dollars, net CAGR-4.02157%, cumulative-7.87624%, and engine-reported full drawdown33.48808%. Its unchanged score hash supports a same-signal cost comparison; it remains rejected. Higher costs also change integer shares and subsequent cash paths, so end-equity differences are not required to equal the difference in fee totals. Equal/SPY's empty score-vector hashes do not prove complete monthly-universe equality; that separate archive limitation remains explicit.

The final record contains18 unique strategy/cost configurations (8local,10cloud),20 completed replays (8local,12cloud including two repeats), and2 additional cloud warm-up errors. There were16 actual fits:10local plus6cloud, producing12 unique annual model identities (10local,2cloud). This independent review itself performed0 fits and0 backtests. All registered cost checks are complete; all five active dynamic-pool candidates are rejected, and none of the local prototypes simultaneously meets the research return/risk targets. The final root report no longer contains stale cloud-access-blocked or main-comparison-pending claims.

This final engineering/data check does not upgrade the evidence: evaluation years remain development history, complete daily cloud account curves were not independently downloaded, full prediction/membership vectors were not archived, and unresolved lifecycle/terminal cash assumptions remain. No2026 market data, forward performance, paper execution or live trading is established by this work. No additional model or risk-parameter search is justified by the current failed configurations.
