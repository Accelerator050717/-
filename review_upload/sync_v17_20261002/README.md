# v17 review materials

Baseline `de51b46adf082a7708701cd2a209d44ade83fa8d`. Start at [the v17 report](../../data/experiments/adaptive_strategy_research_v17/REPORT.md), [cloud comparison](../../data/experiments/adaptive_strategy_research_v17/cloud/REPORT.md), and [REVIEW_INDEX](../../REVIEW_INDEX.md). Current target is net CAGR20–30%, preferred continuous drawdown below20%, budget30%; older30/50 targets are historical context.

## Actual completed work

All18 distinct cost/strategy configurations are complete:8 local fixed-survivor prototypes and10 historical dynamic QC configurations in project37249270 (7 at10bp,3 at20bp). There are20 actual completed backtest replays:8 local plus12 cloud. The cloud total includes one same-configuration output-only Ridge replay and one duplicate equal20bp launch caused by the parameter interface; neither is an additional distinct strategy. Two failed early cloud warm-up attempts are retained separately, not counted as completed results. All five cloud stock-selection candidates lose money and exceed30% drawdown; no strategy is upgraded.

SPY is the best budget-compliant main control at+1.39% CAGR/22.16% drawdown, far below the return target. Completed20bp checks: equal final$96,525.29,CAGR−1.75%,DD26.87%; SPY final$102,534.50,CAGR+1.26%,DD22.27%; failed trend-risk diagnostic final$92,123.76,CAGR−4.02%,DD33.49%. The latter remains rejected. All preregistered cost checks are complete; no further parameter search follows.

Actual fitting count is16: local10 plus cloud6. There are12 distinct annual models: local10 and cloud2. The cloud6 fits repeat the same two hash-identical annual models for the initial Ridge run, output-only replay, and paired risk-budget strategy; they are not six distinct candidate models. Failed cloud attempts contain0 fits/0 orders. Account verification has been resolved and the project runs on Free; the earlier access-block record is historical only.

See [cloud runs and failures](../../data/experiments/adaptive_strategy_research_v17/cloud/attempt_ledger.csv), [full cloud model parameters](../../data/experiments/adaptive_strategy_research_v17/cloud/cases/ridge_cost10/FITS.json), [common-condition results](../../data/experiments/adaptive_strategy_research_v17/cloud/comparison/results.csv), and [local generation identities](../../data/experiments/adaptive_strategy_research_v17/local_prototype/COMPLETE.json).

## Inventory and restore

`files.json` inventories exact reviewable paths/bytes/SHA256 and35 excluded local artifacts. Refresh this inventory after the final result/report writes, then `tools/prepare_v17_review.py --verify` checks it without replacing generation identities. Rebuildable environments, caches and credentials are excluded; the entire data directory is not ignored.

Local restore archive: `M:\ml项目\review_bundles\v17_local_20261002.zip`,6,566,945bytes (6.26MiB). SHA256 `14e3ff52220b33c4becf13449f501e57de6f0d631e8b4dccd17204cfef09c489`. Contains10 joblib models, complete local predictions, and8 configurations' trades/positions/targets:35 files,total22,157,504bytes. Each archive payload hash matches the original local COMPLETE manifest; CRC passed. No raw supplier data. See [LARGE_ARTIFACTS.csv](../../data/experiments/adaptive_strategy_research_v17/local_prototype/LARGE_ARTIFACTS.csv) and [ZIP_MANIFEST.json](../../data/experiments/adaptive_strategy_research_v17/local_prototype/ZIP_MANIFEST.json). Extract preserving checkout-root-relative paths; existing original inputs remain required under their frozen identities.

```powershell
.\.venv\Scripts\python.exe -B tools/research_v17_local.py --verify
.\.venv\Scripts\python.exe -B tools/prepare_v17_local_bundle.py --verify
.\.venv\Scripts\python.exe -B tools/prepare_v17_review.py --verify
```

The local ZIP is not a cloud backup. Full cloud prediction vectors and complete security-PnL records have not been archived locally; hashes cannot replace these artifacts. Complete daily cloud equity has not been independently downloaded/recomputed, so cloud maximum drawdown remains the reviewed code's engine-reported501-close statistic. Six unresolved terminal-label endpoints, conditional observed-endpoint ranks, and incomplete cash/share corporate-action rights remain explicit. Original supplier records stay in the permitted cloud environment. Allowed model parameters, aggregate monthly/annual results, run identities, code and reports are retained locally and in Git.

Old v5–v16 reports/results/material manifests remain unchanged.2026 stays sealed; no Live/paper/broker orders, funds operations, or purchases. The next priority is continuous dynamic-universe coverage and acceptance across2016–2025 with sufficient earlier warm-up/mature training history, preserving these failed rules and simple controls; no further tuning on the two-year development window.
