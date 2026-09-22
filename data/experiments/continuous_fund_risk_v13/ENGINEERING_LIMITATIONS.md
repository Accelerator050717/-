# Recovery cap: pre-trade NAV and transaction-cost boundary

The fixed controller estimates its recovery cap from the **currently known pre-trade unit NAV**, preserving the original trading-cost implementation. It is not an exact post-fill loss-budget solver. The following is an isolated **fictitious arithmetic diagnostic**, not a historical strategy result or an additional candidate.

Inputs: cumulative high-water NAV `1.0`; current unit NAV `0.751`; risk-asset value `0.300`; cash `0.451`; cost `10 bps`; 30% remaining-loss budget; assumed asset shock `30%`.

| Quantity | Value |
|---|---:|
| Pre-trade recovery cap | 0.22636484687083908 |
| Actual post-trade gross fraction after sizing to that cap | 0.22636484687083910 |
| Fee paid | 0.00013002943409294 |
| Post-fee unit NAV | 0.7508699705659071 |
| Cap recomputed from post-fee NAV | 0.22582680783628420 |
| Gross fraction above that recomputed cap | 0.00053803903455490 |

The final difference is **0.053804 percentage points of exposure**, approximately **5.38 basis points**. Fees reduce NAV and the remaining loss budget after sizing, so the post-fill fraction can slightly exceed a newly recomputed budget-derived cap. This does not mean an observed historical breach occurred, nor does it show that the assumed 30% shock bounds actual gaps.

Reproduce the arithmetic without any market data, training or execution:

```python
from h60_global_control import GlobalRisk
from research_backtest import reduce_only

state = GlobalRisk(mode="RECOVERY", resume_unit_nav=.758, recovery_floor=.7201)
before = state.cap(.751, 1.)
values, cash, change, fee = reduce_only([.300], .451, [before], .001)
after_nav = float(values.sum() + cash)
print(before, float(values.sum() / after_nav), float(fee), after_nav,
      state.cap(after_nav, 1.))
```

The preregistered plan and core implementation are unchanged. The comparison therefore measures one fixed pre-trade cap rule. A fee-aware sizing solver would be a separate engineering improvement, not a reason to reinterpret this experiment as an exact post-fee guarantee or to adjust its risk thresholds after observing results.

Other boundaries are documented in `ENGINEERING_CONTRACT.md`, `INDEPENDENT_ENGINEERING_REVIEW.md` and the execution continuity report: strategy funds are not the whole broker account; partial fills remain actual exposure; this is local virtual execution; late historical facts need reconciliation/reconstruction; and no paper or real order was sent.
