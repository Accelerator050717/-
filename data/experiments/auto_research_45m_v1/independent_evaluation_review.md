# Independent evaluation review

This review uses actual saved 2020–2025 results. It did not train a model, change a parameter, or read 2026 prices.

## Conclusion

The final 32-candidate evaluation reproduces independently. No candidate passes every predeclared gate; no candidate is eligible to open the sealed 2026 evaluation. `m16_elastic_rank` is the highest-IR development candidate, not a confirmed improvement.

## Best development candidate: m16_elastic_rank

| Gate | Actual | Required | Result |
|---|---:|---:|---|
| Net CAGR | 34.253188% | > 21.087408% | PASS |
| Information ratio vs same-pool equal weight | 0.888440 | >= 0.5 | PASS |
| Positive calendar-year excess returns | 5/6 | >= 4/6 | PASS |
| Maximum drawdown | -37.631990% | >= -37.048962% | FAIL |
| Mean cross-sectional Rank IC | 0.025841703 | >= 0.03 and >= 4 positive IC years | FAIL (6 positive IC years) |
| 20 bp net CAGR | 27.969739% | > equal-weight 17.906421% | PASS |
| Simultaneous lower bound, daily active return | -0.0000916008 | > 0 | FAIL |

The drawdown fails by 0.583028 percentage points. The simultaneous bound is for the arithmetic mean of daily active returns, not CAGR, portfolio alpha, or a probability of profitability.

## Annual return definition

Annual candidate return = last NAV in that calendar year / last NAV in the previous calendar year - 1. The first year starts from implicit cash NAV 1. Annual excess = candidate annual return minus equal-pool annual return. It is not the sum of overlapping five-day labels, and not the geometric return of a long-short portfolio. Daily returns similarly include the first entry fee through first NAV - 1.

| Year | Candidate return | Equal-pool return | Difference (percentage points) |
|---|---:|---:|---:|
| 2020 | 24.893618% | 18.715230% | 6.178387 |
| 2021 | 63.556347% | 35.477265% | 28.079082 |
| 2022 | -14.967971% | -3.179758% | -11.788213 |
| 2023 | 72.896900% | 20.014522% | 52.882377 |
| 2024 | 46.991551% | 24.097915% | 22.893636 |
| 2025 | 32.267161% | 16.732648% | 15.534513 |

## Joint bootstrap verification

An independent implementation sampled one repetition at a time and used date-frequency weights and matrix multiplication. It reproduced the saved implementation, which samples indexed arrays in batches. Each repetition shares the same circular 20-trading-day block indices across all 32 candidates. Candidate active series are centered; the standard deviation of 2,000 resampled means is the fixed bootstrap studentizer. The 95th percentile of the maximum standardized deviation gives the shared critical value. Lower = observed mean - critical value × bootstrap standard error.

Critical max-t: 2.861875436967. Maximum lower-bound discrepancy: 1.518e-17. All 32 gate decisions independently reproduced.

This is an approximate simultaneous interval conditional on the historical series and this declared family. Circular blocks cannot guarantee regime stability and impose an artificial wrap from the end of the sample to its beginning. A 20-day block is a fixed modeling choice. The procedure does not erase earlier adaptive experiments, the adaptive reason for adding Huber follow-ups, selection of surviving stocks, adjusted-price revisions, or data-source limitations. Positive point estimates are not a proof of future profitability.

## CSV precision issue: diagnosed and corrected

The superseded `huber_scale_followup` evaluation used default CSV float parsing. Score changes around 1e-16 altered ties or near ties in discrete rank combinations, changing four original candidate portfolios. Reading original score files with `float_precision="round_trip"` restored all four original CAGRs and independently computed Rank ICs with zero difference. The final evaluation preserves all original thirty score arrays exactly and reproduces both 10 bp and 20 bp original metrics within 1e-12. The superseded directory is evidence of the issue, not the authoritative final result.

| Candidate | Original CAGR | Superseded CAGR | Final CAGR |
|---|---:|---:|---:|
| r10_momentum_lowvol | 10.652072% | 11.194375% | 10.652072% |
| e28_model_ensemble | 31.063119% | 31.442238% | 31.063119% |
| e29_rule_model_ensemble | 15.588839% | 15.721679% | 15.588839% |
| e30_ranker_ensemble | 30.271962% | 29.287125% | 30.271962% |

The correction preserves the model definitions; it is not retraining or selecting a better-performing tie convention. Near-tie handling remains something to specify explicitly in future experiments.

## Scope of independent checks

Checked every saved daily NAV against CAGR, total return and maximum drawdown; recomputed all 32 information ratios, calendar-year active returns, within-date Spearman ICs and positive IC year counts; independently reconstructed bootstrap numerical results; checked every gate and the empty holdout selection; compared original and final score arrays and baseline/candidate metrics. The separate backtest reviewer owns independent trade/unit/cash reconstruction. The 20 bp gate here was checked against saved 20 bp metrics, not a second independent execution engine.

## Machine-readable audit

```json
{
  "status": "PASS",
  "reviewed_at_utc": "2026-09-07T09:03:18.461598+00:00",
  "author_role": "independent evaluation reviewer; no training or parameter changes",
  "final_directory": "final_evaluation",
  "candidate_count": 32,
  "dates": 1506,
  "first_date": "2020-01-03",
  "last_date": "2025-12-30",
  "rank_observation_dates": 1502,
  "bootstrap_repetitions": 2000,
  "block_length": 20,
  "seed": 20260907,
  "critical_max_t": 2.8618754369673423,
  "max_abs_cagr_return_drawdown_error": 0.0,
  "max_abs_rank_ic_error": 0.0,
  "max_abs_ir_error": 0.0,
  "max_abs_bootstrap_lower_error": 1.5178830414797062e-17,
  "max_original_metric_drift_after_round_trip_fix": 0.0,
  "all_original_score_arrays_exactly_preserved": true,
  "passed_all_gates": 0,
  "selected_candidate": null,
  "best_development_candidate": "m16_elastic_rank",
  "best_failed_gates": [
    "gate_drawdown",
    "gate_rank_ic",
    "gate_simultaneous_ci"
  ],
  "source_sha256": {
    "comparison.csv": "b3158142209a69fe9b164f634613add1af1fbe7efaba3e33ec8c138dc0f74cfe",
    "bootstrap_and_selection.json": "9cec4dfd42f8981eddc072c9eff4151ad91b5ace29ed3c1cb7cf0cd13bbb474e",
    "all_equity.csv": "5efcce363215149cea6bb5b188e12182b01d8151c8e2c3ae05a2c4e210d41d8c",
    "ranking_metrics.csv": "49564b865efbde67187f218de90b12d226e5a9db22e1135e0da9d1d26bdea5ca",
    "cost_metrics.json": "38b33930fe70fff5b29a36a0fa4394dabc0a3073ca920b77f0a0d51912fa51cc",
    "stress_metrics.json": "30a4814a6b5005fc71eb277853e49047e0b55a6270fbb65e572977761858bab1",
    "all_development_scores.csv": "9c6f761eeac4b8c017871bd55838c3875cfac8ec9f495277f6f590ca402051df"
  }
}
```
