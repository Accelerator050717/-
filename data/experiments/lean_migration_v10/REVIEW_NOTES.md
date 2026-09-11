# Independent migration contract review

Scope: inspect the fixed-input exporter and sequential H60 controller, add isolated failure tests, and run a Python-controller regression. This document does **not** certify an actual LEAN run, IBKR connectivity, or performance beyond the archived development interval.

## Findings and resolutions

- The initial adapter checked copied strategy code but did not check phase-price files or `package.json` against `EXPORT_IDENTITY.json`. The adapter now verifies the export manifest, shared source hashes, phase hashes, and contained local paths before initialization.
- The initial controller accepted unsorted observations, mismatched first/final boundaries, and duplicate security names. `validate_package` now rejects ambiguous schedules and cross-section shapes before orders.
- A full-sale round trip through `(quantity * price) / price` could leave approximately `-1.4e-14` shares in a float test ledger. The controller now uses the broker's exact held quantity when the sizing target is zero. The explicitly fictional double-precision broker also removes dust below `1e-10`; this fixture cleanup is not evidence about LEAN decimal holdings. Actual engine parity has its own unchanged `1e-6` share tolerance.
- Confirmed against pinned native source `Brokerages/Backtesting/BacktestingBrokerage.cs`: a completely filled event with zero attached commission invokes the security fee model. The custom fill event's initial zero fee therefore does not intentionally suppress commissions.

## Targeted tests

`tests/test_lean_migration_contract.py` has 10 test methods covering:

- Pre-2026 ordered calendars, unique identities, correct observation/execution dates, frozen soft/hard switches.
- Missing, nonfinite, duplicate, or skipped phase inputs; rejected repeat phases cannot create more orders.
- Changes to future scores and future risk rows cannot change the current opening decision.
- Gap-stop exits cannot reopen on the same scheduled open; cap reductions cannot buy after gaps.
- An invented 50% overnight gap triggers the hard pause even with the soft reduction disabled; trading resumes only on the later eligible scheduled day, at reduced exposure, then returns to full permitted exposure.
- Final liquidation leaves the fictional ledger flat after fees.

Command from the repository root:

```powershell
.venv/Scripts/python.exe -m unittest discover -s tests -p test_lean_migration_contract.py -v
```

## Full saved-input Python regression

Run:

```powershell
$env:PYTHONPATH='.'
.venv/Scripts/python.exe tests/test_lean_migration_contract.py --fixed-export-regression
```

This reads the already exported 2016–2025 adjusted-price phase files, verifies their hashes, and compares the controller with the saved v8 `stop_on_soft_off_cost10` reference. The fictional broker supplies all fills and cash; LEAN is not imported. See `synthetic_controller_regression/RESULT.json` for actual counts, source identity, tolerances and numerical errors. No model is trained, no market data is downloaded, and no 2026 price is read.

## Explicitly fictional package for an additional engine check

`synthetic_input/` contains eight `SIM_*` instruments with invented prices/risk values, 60 sessions and 180 artificial phases per instrument. `EXPECTED_SYNTHETIC.json` is the separate Python-fixture expectation, not engine output. It expects a March 29, 2019 hard pause, May 2 scheduled resumption, target gross exposure `0.4` during recovery and `0.8` afterward, followed by final liquidation. The 50% gap deliberately demonstrates that a 20% pause threshold does not guarantee a 20% realized-loss cap.

Recheck/create only the same fixture:

```powershell
$env:PYTHONPATH='.'
.venv/Scripts/python.exe tests/test_lean_migration_contract.py --export-synthetic-engine-fixture
```

The real-engine run and its independent comparison must be reported separately. Original adjusted-price proxy equivalence does not establish raw-share precision, corporate-action settlement, real stop execution, broker restart recovery, or out-of-sample profitability.
