"""Pure sizing/ranking regressions. Does not import LEAN or query market data."""
import ast
import hashlib
from pathlib import Path


def load_functions():
    path = Path(__file__).resolve().parents[1] / "tools" / "qc_v15_dynamic_pilot.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    namespace = {"ast": ast, "hashlib": hashlib}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


def test_ties_do_not_depend_on_incoming_vendor_order():
    top = load_functions()["stable_top"]
    rows = [(100, "SID_B", "old_ticker"), (100, "SID_A", "new_ticker"), (90, "SID_C", "third")]
    assert top(rows, 2) == top(list(reversed(rows)), 2)
    assert [row[1] for row in top(rows, 2)] == ["SID_A", "SID_B"]


def test_whole_shares_keep_budget_and_expensive_security_cash():
    targets = load_functions()["whole_share_targets"]
    prices = {"A": 137, "B": 50101, "C": 19}
    actual = targets(list(prices), prices, 100000)
    assert actual == {"A": 218, "B": 0, "C": 1578}
    assert sum(prices[s] * q for s, q in actual.items()) <= 90000
    assert all(isinstance(q, int) and q >= 0 for q in actual.values())
    assert targets([], {}, 100000) == {}
    assert targets(["A"], prices, -1) == {"A": 0}


def test_missing_mark_keeps_its_cash_allocation():
    targets = load_functions()["whole_share_targets"]
    assert targets(["known", "unknown"], {"known": 10}, 100) == {"known": 4}


def test_executable_identity_ignores_docs_but_detects_logic():
    digest = load_functions()["executable_ast_sha256"]
    documented = '"""module prose"""\n# comment\ndef f():\n    """function prose"""\n    return 5\n'
    compact = 'def f():\n    return 5\n'
    assert digest(documented) == digest(compact)
    assert digest(compact) != digest(compact.replace("return 5", "return 6"))
