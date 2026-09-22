"""Small fictitious accounting examples, not market data or strategy tests."""
import ast
from pathlib import Path

import math
import base64
import hashlib
import json
import lzma
import runpy


def pnl():
    path = Path(__file__).resolve().parents[1] / "tools" / "qc_v16_attribution_observer.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "mark_to_market_pnl")
    namespace = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
    return namespace["mark_to_market_pnl"]


def test_partial_exit_and_cross_month_marks_reconcile_complete_cash_profit():
    calculate = pnl()
    # Buy ten at100, close90; sell four95, close remaining six92; exit six110.
    stages = [(0, 900, 1000, 1), (900, 552, -380, .38), (552, 0, -660, .66)]
    prices, nets = zip(*(calculate(before, after, fill, 0, 0, fee) for before, after, fill, fee in stages))
    assert all(math.isclose(a, b, abs_tol=1e-10) for a, b in zip(prices, (-100, 32, 108)))
    assert math.isclose(sum(prices), 380 + 660 - 1000, abs_tol=1e-10)
    assert math.isclose(sum(nets), 40 - 2.04, abs_tol=1e-10)


def test_split_and_fraction_cash_are_not_investment_profit():
    calculate = pnl()
    assert calculate(100, 100, 0, 0, 0, 0) == (0, 0)  # two-for-one shares double, price halves
    # Reverse split converts10*10 into3*30 plus10 fraction cash.
    assert calculate(100, 90, 0, 0, 10, 0) == (-10, 0)


def test_dividend_enters_once_and_terminal_proceeds_are_signed_fill_cash():
    calculate = pnl()
    assert calculate(100, 98, 0, 2, 0, 0) == (-2, 0)
    # Terminal sale at same cached value is not a second dividend/cash credit.
    assert calculate(537.8, 0, -537.8, 0, 0, 0) == (0, 0)


def test_observer_calls_no_history_or_object_store_and_base_is_imported():
    source = (Path(__file__).resolve().parents[1] / "tools" / "qc_v16_attribution_observer.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert any(isinstance(n, ast.Import) and any(a.name == "v15_core" for a in n.names) for n in tree.body)
    assert not any(isinstance(n, ast.Attribute) and n.attr in {"history", "object_store"} for n in ast.walk(tree))


def test_financial_transport_and_readable_runtime_reject_tampering():
    module = runpy.run_path(str(Path(__file__).resolve().parents[1] / "tools" / "summarize_qc_v16_attribution.py"))
    # Explicitly fictitious flat account; this is a transport test, not a run.
    runtime = {f"v16 M{y}-{m:02d}": "B=100000.0 C=100000.0 F=0.0 D=0.0 S=0.0 R=0.0"
               for y in (2022, 2023) for m in range(1, 13)}
    digest = hashlib.sha256(json.dumps(runtime, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    payload = {"schema": "v16-compact-1", "monthly_runtime_sha256": digest, "spy_reference": {}}
    raw = json.dumps(payload, separators=(",", ":")).encode()
    envelope = {"encoding": "lzma-base64-derived-financial-records", "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw), "data": base64.b64encode(lzma.compress(raw)).decode()}
    decoded, receipt = module["decode"]("V16_ATTRIBUTION " + json.dumps(envelope))
    assert decoded == payload and receipt["transport_verified"]
    checked = module["restore_monthly_runtime"](decoded, runtime)
    assert checked["rows"] == 24 and all(r[3] == 0 for r in decoded["months"])
    modified = dict(runtime)
    modified["v16 M2022-01"] = modified["v16 M2022-01"].replace("B=100000.0", "B=100001.0")
    try:
        module["restore_monthly_runtime"](payload, modified)
    except ValueError:
        pass
    else:
        raise AssertionError("Changed monthly money must fail its source hash")


def test_partial_json_does_not_accept_an_unfinished_numeric_value():
    module = runpy.run_path(str(Path(__file__).resolve().parents[1] / "tools" / "recover_qc_v16_partial_log.py"))
    actual, _ = module["complete_fields"]('{"complete":[1,2],"unfinished":123')
    assert actual == {"complete": [1, 2]}
    actual, _ = module["complete_fields"]('{"complete":1,"unfinished":[2,3')
    assert actual == {"complete": 1}
