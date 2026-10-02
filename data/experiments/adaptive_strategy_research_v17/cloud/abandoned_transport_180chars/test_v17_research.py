"""Small, independent checks for v17 timing, ranking and accounting contracts.

Fixtures are deliberately synthetic; they are not market observations.
"""
from collections import Counter, deque
from datetime import datetime, timedelta
import ast
import copy
import json
from pathlib import Path
import statistics
from types import SimpleNamespace

import numpy as np
import pandas as pd
import unittest

from tools.qc_v17_features import (
    centered_ranks,
    continuous_drawdown,
    eligible_training_rows,
    feature_vector,
)
from tools import research_v17_local as local
from tools import qc_v17_features as features


def test_cloud_features_have_exact_return_endpoints_and_scale_invariance():
    closes = [100 * 1.01 ** i for i in range(127)]
    actual = feature_vector(closes, 1_000_000, 2_000_000)
    np.testing.assert_allclose(actual[:4], [
        1.01 ** 5 - 1, 1.01 ** 20 - 1,
        1.01 ** 43 - 1, 1.01 ** 106 - 1,
    ], rtol=1e-12, atol=1e-12)
    assert abs(actual[4]) < 1e-12
    assert actual[5] == 0
    np.testing.assert_allclose(feature_vector([p / 10 for p in closes], 1_000_000, 2_000_000), actual, atol=1e-12)
    with unittest.TestCase().assertRaisesRegex(ValueError, "127 finite positive"):
        feature_vector(closes[:-1] + [float("nan")], 1_000_000, 2_000_000)


def test_rank_ties_and_vendor_order_do_not_manufacture_label_differences():
    values = [0.02, -0.01, 0.02, 0.10]
    ranks = centered_ranks(values)
    assert ranks[0] == ranks[2] == 0
    assert ranks[1] == -0.5 and ranks[3] == 0.5
    permutation = [3, 0, 2, 1]
    assert centered_ranks([values[i] for i in permutation]) == [ranks[i] for i in permutation]


def test_annual_training_requires_observation_and_label_end_before_boundary():
    rows = [
        {"id": "mature", "observed": datetime(2021, 11, 1), "label_end": datetime(2021, 12, 1)},
        {"id": "ends_at_boundary", "observed": datetime(2021, 12, 1), "label_end": datetime(2022, 1, 1)},
        {"id": "future_label", "observed": datetime(2021, 12, 1), "label_end": datetime(2022, 1, 4)},
        {"id": "future_observation", "observed": datetime(2022, 1, 4), "label_end": datetime(2022, 2, 1)},
    ]
    assert [r["id"] for r in eligible_training_rows(rows, 2022)] == ["mature"]
    assert len(eligible_training_rows(rows, 2023)) == 4


def test_continuous_peak_survives_two_loss_and_recovery_cycles():
    # First 20% loss, partial recovery, second 20% loss from 90k = 28% total.
    equity = [100_000, 80_000, 90_000, 72_000, 85_000]
    assert abs(continuous_drawdown(equity) - 0.28) < 1e-12
    # Fees on the first observation must not remove the initial 100k peak.
    assert abs(continuous_drawdown([99_900]) - 0.001) < 1e-12
    with unittest.TestCase().assertRaises(ValueError):
        continuous_drawdown([100_000, np.nan])


def synthetic_bars():
    dates = pd.bdate_range("2012-05-18", "2015-03-01")
    t = np.arange(len(dates), dtype=float)
    close = pd.DataFrame({"A": 50 * np.exp(.0004*t + .025*np.sin(t/11)),
                          "B": 70 * np.exp(.0002*t + .015*np.cos(t/13))}, index=dates)
    opened = close * (1 + .003*np.sin(t/7)[:, None])
    spy_close = pd.DataFrame({"SPY": 100*np.exp(.0003*t + .01*np.cos(t/17))}, index=dates)
    spy_open = spy_close * (1 + .002*np.cos(t/9)[:, None])
    return {"Open": opened, "Close": close}, {"Open": spy_open, "Close": spy_close}


def test_local_label_is_twenty_open_intervals_and_no_future_feature_dependence():
    bars, spy = synthetic_bars()
    panel = local.build_panel(bars, spy)
    pos = 400
    date = bars["Open"].index[pos]
    row = panel.loc[panel.Date.eq(date) & panel.symbol.eq("A")].iloc[0]
    expected_excess = (bars["Open"].A.iloc[pos+21] / bars["Open"].A.iloc[pos+1]
                       - spy["Open"].SPY.iloc[pos+21] / spy["Open"].SPY.iloc[pos+1])
    assert abs(row.excess20 - expected_excess) < 1e-12
    assert row.exit20 == bars["Open"].index[pos+21]
    assert abs(row.target - expected_excess/(row.vol20*np.sqrt(20))) < 1e-12
    prefix = local.build_panel({k:v.iloc[:pos+1] for k,v in bars.items()},
                               {k:v.iloc[:pos+1] for k,v in spy.items()})
    pd.testing.assert_frame_equal(prefix[["Date", "symbol", *local.FEATURES]],
        panel.loc[panel.Date.le(date), ["Date", "symbol", *local.FEATURES]].reset_index(drop=True))
    # A current feature-ready row survives without a completed forward label.
    assert prefix.iloc[-1][local.FEATURES].notna().all()
    assert pd.isna(prefix.iloc[-1].target)


def test_local_training_boundary_and_future_price_changes_leave_train_unchanged():
    bars, spy = synthetic_bars()
    panel = local.build_panel(bars, spy)
    train = local.train_rows(panel, 2014)
    assert train.Date.max() < pd.Timestamp("2014-01-01")
    assert train.exit20.max() < pd.Timestamp("2014-01-01")
    altered = {k:v.copy() for k,v in bars.items()}
    for frame in altered.values():
        frame.loc["2014-01-01":] *= 3
    altered_spy = {k:v.copy() for k,v in spy.items()}
    for frame in altered_spy.values():
        frame.loc["2014-01-01":] *= 2
    pd.testing.assert_frame_equal(train, local.train_rows(local.build_panel(altered, altered_spy), 2014))


def test_local_next_open_execution_roundtrip_fees_and_cash_reconciliation():
    dates = pd.bdate_range("2020-01-02", periods=4)
    frame = pd.DataFrame({"A": [10., 20., 20., 20.]}, index=dates)
    bars = {"Open": frame, "Close": frame.copy()}
    weights = pd.DataFrame({"A": [.9]}, index=dates[:1])
    result = local.simulate_weights(weights, bars, dates[-1], 10)
    first = result["trades"].iloc[0]
    assert first.Date == dates[1] and first.proxy_fill == 20
    # No return capture from signal close $10 to next open $20.
    bought_dollars = 100_000*.9/(1+.9*.001)
    expected = 100_000 - 2*.001*bought_dollars
    assert abs(result["daily"].equity.iloc[-1] - expected) < 1e-8
    assert abs(result["trades"].fee.sum() - (100_000-expected)) < 1e-8
    assert result["daily"].cash.ge(0).all()
    assert local.audit_result(result, bars)["decision_precedes_fill"]


def test_local_full_drawdown_is_not_reset_when_calendar_year_changes():
    dates = pd.to_datetime(["2019-12-30", "2019-12-31", "2020-01-02", "2020-01-03", "2020-01-06"])
    frame = pd.DataFrame({"A": [100., 80., 90., 72., 72.]}, index=dates)
    # Enter at100, then marks80/90/72; final liquidation preserves72.
    opened = pd.DataFrame({"A": [100., 100., 90., 72., 72.]}, index=dates)
    result = local.simulate_weights(pd.DataFrame({"A": [1.]}, index=dates[:1]),
                                    {"Open": opened, "Close": frame}, dates[-1], 0)
    assert abs(result["daily"].drawdown.min() + .28) < 1e-12


def test_local_rejects_missing_prices_instead_of_forward_filling():
    dates = pd.bdate_range("2020-01-02", periods=4)
    frame = pd.DataFrame({"A": [10., 10., np.nan, 10.]}, index=dates)
    with unittest.TestCase().assertRaisesRegex(ValueError, "Price missing/invalid"):
        local.simulate_weights(pd.DataFrame({"A": [.9]}, index=dates[:1]),
                               {"Open": frame, "Close": frame.copy()}, dates[-1], 10)


def cloud_method(name):
    """Run one method with explicit fake observations, never a LEAN engine."""
    path = Path(__file__).resolve().parents[1]/"tools/qc_v17_research.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    klass = next(node for node in tree.body if isinstance(node, ast.ClassDef))
    method = next(node for node in klass.body if isinstance(node, ast.FunctionDef) and node.name == name)
    space = dict(Counter=Counter, deque=deque, statistics=statistics, datetime=datetime,
                 math=__import__("math"), features=features,
                 Universe=SimpleNamespace(UNCHANGED="unchanged"),
                 core=SimpleNamespace(stable_top=lambda rows, n: sorted(rows, key=lambda r: (-r[0], r[1]))[:n]))
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), "exec"), space)
    return space[name]


def test_cloud_liquidity_uses_exact_prior_observation_dates_not_last_twenty_available_rows():
    select = cloud_method("select_universe")
    hours = SimpleNamespace(is_date_open=lambda t, extended: True,
                            get_previous_trading_day=lambda t: t-timedelta(days=1))
    obj = SimpleNamespace(time=None, spy="SPY", securities={"SPY": SimpleNamespace(exchange=SimpleNamespace(hours=hours))},
        last_universe_observation=None, observation_days=deque(maxlen=20), dv_history={}, universe_month=None,
        previous_pool=set(), pool=[], seen=set(), months=[], stats=Counter())
    symbols = [SimpleNamespace(id=f"S{i:03d}", value=f"T{i:03d}") for i in range(101)]
    # Fictional daily sessions intentionally include weekends; this checks the
    # observation-calendar contract, not a real exchange holiday calendar.
    for day in range(21):
        obj.time = datetime(2018, 12, 12)+timedelta(days=day)
        observed = obj.time-timedelta(days=1)
        records = []
        for i, symbol in enumerate(symbols):
            if i == 0 and day == 10:  # Otherwise high-liquidity name has a gap.
                continue
            records.append(SimpleNamespace(symbol=symbol, time=observed, end_time=obj.time,
                has_fundamental_data=True, security_reference=SimpleNamespace(security_type="ST00000001"),
                price=10, dollar_volume=1000 if i == 0 else 100))
        # An identical vendor duplicate must neither lengthen the window nor
        # change its per-session date sequence or selected stock count.
        records.append(records[-1])
        selected = select(obj, records)
    assert len(selected) == 100
    assert "S000" not in {str(s.id) for s in selected}
    assert obj.current_month["liquidity_history_incomplete"] == 1
    assert datetime.fromisoformat(obj.current_month["engine_available_time"]) <= obj.time
    assert obj.stats["fundamental_duplicate_identical"] == 21


def test_cloud_exact_duplicate_is_idempotent_and_first_snapshot_is_independent():
    fingerprint = dict(time="2018-11-30", end_time="2018-12-01", has_fundamental=True,
                       security_type="ST00000001", price="10.0", dollar_volume="100.0", ticker="ABC")
    seen = {}
    assert features.accept_unique_observation(seen, "SID", fingerprint)
    assert not features.accept_unique_observation(seen, "SID", dict(fingerprint))
    assert len(seen) == 1
    fingerprint["price"] = "999.0"
    assert seen["SID"]["price"] == "10.0"  # caller mutation cannot alter first facts


def test_cloud_conflicting_duplicate_fails_without_overwriting_or_exposing_prices():
    first = dict(time="2018-11-30", end_time="2018-12-01", price="10.0", ticker="ABC")
    seen = {"SID": dict(first)}
    conflict = dict(first, price="999.0", ticker="XYZ")
    with unittest.TestCase().assertRaises(ValueError) as caught:
        features.accept_unique_observation(seen, "SID", conflict)
    text = str(caught.exception)
    assert "SID=SID" in text and "fields=price,ticker" in text
    assert "999.0" not in text and "10.0" not in text
    assert seen == {"SID": first}


def test_cloud_unresolved_terminal_label_is_visible_and_never_zero_filled():
    resolve = cloud_method("resolve_labels")
    start, end = datetime(2022, 1, 3, 16, 5), datetime(2022, 2, 1, 16, 5)
    pending = [{"symbol": s, "sid": s, "observed": start, "prediction": None, "x": [1.]} for s in ("A", "B", "DELISTED")]
    histories = {"A": [(start, 10.), (end, 11.)], "B": [(start, 10.), (end, 9.)], "DELISTED": [(start, 10.)]}
    obj = SimpleNamespace(time=end, pending_features=pending, history_closes=lambda symbol: histories[symbol],
        terminal={"DELISTED": str(end)}, unresolved_labels=[], training_rows=[], label_checks=[], prediction_checks=[])
    resolve(obj)
    assert {row["sid"] for row in obj.training_rows} == {"A", "B"}
    assert obj.unresolved_labels == [{"sid": "DELISTED", "start": "2022-01-03", "end": "2022-02-01", "reason": "terminal_endpoint_unresolved"}]
    assert obj.label_checks[-1]["unresolved"] == {"terminal_endpoint_unresolved": 1}
    assert obj.label_checks[-1]["resolved"] == 2


def cloud_parser():
    path = Path(__file__).resolve().parents[1]/"tools/summarize_v17_cloud.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    methods = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ("decoded", "verify_runtime")]
    namespace = dict(json=json, math=__import__("math"), datetime=datetime,
                     FEATURE_NAMES=features.FEATURE_NAMES, stable_digest=features.stable_digest,
                     decode_runtime_payload=features.decode_runtime_payload,
                     continuous_drawdown=features.continuous_drawdown, statistics=statistics)
    exec(compile(ast.Module(body=methods, type_ignores=[]), str(path), "exec"), namespace)
    return namespace["verify_runtime"]


def synthetic_cloud_capture():
    months = {f"{y}-{m:02d}": [f"{y}-{m:02d}-28", 100000., 0., 100000., 0.]
              for y in (2022, 2023) for m in range(1, 13)}
    runtime = {"v17_summary": dict(mode="eq", training_count=0, model_hashes=[], gate_pass=True,
        evaluation="2022-2023 development", **{"2026_market_data_used": False},
        final_equity=100000., net_cumulative=0., net_cagr=0., max_drawdown=0., fees_paid=0.,
        final_gross_holdings=0., open_orders_at_end=0, annual_returns={"2022": 0., "2023": 0.}, stats={}),
        "v17_months": months}
    for month in months:
        runtime[f"v17_predictions_{month}_index"] = dict(rows=0, chunks=0, sha256=features.stable_digest([]))
    runtime["v17_security_pnl_0"] = [["SID", 0.]]
    runtime["v17_security_pnl_index"] = dict(rows=1, chunks=1, sha256=features.stable_digest([["SID", 0.]]))
    return runtime


def test_cloud_summary_rejects_missing_or_corrupt_derived_chunks():
    parse = cloud_parser()
    runtime = synthetic_cloud_capture()
    assert parse(runtime)[-1]["passed"]
    corrupted = copy.deepcopy(runtime)
    corrupted["v17_security_pnl_0"][0][1] = 1.
    checked = parse(corrupted)[-1]
    assert not checked["passed"]
    assert any(r["check"] == "v17_security_pnl_sha256" and not r["passed"] for r in checked["checks"])
    del corrupted["v17_security_pnl_0"]
    checked = parse(corrupted)[-1]
    assert any(r["check"] == "v17_security_pnl_chunks_present" and not r["passed"] for r in checked["checks"])


def test_cloud_summary_rejects_label_maturing_on_deployment_boundary():
    runtime = synthetic_cloud_capture()
    runtime["v17_summary"].update(mode="ridge", training_count=2)
    for year in (2022, 2023):
        params = dict(mean=[0.]*8, scale=[1.]*8, coefficient=[0.]*8, intercept=0.)
        model_hash = features.stable_digest(dict(parameters=params, features=list(features.FEATURE_NAMES), input_sha256="fictional"))
        runtime[f"v17_fit_{year}"] = dict(parameters=params, input_sha256="fictional", model_sha256=model_hash,
            feature_order=list(features.FEATURE_NAMES), observed_last=f"{year-1}-11-01T16:05:00",
            label_end_last=f"{year-1}-12-01T16:05:00")
        runtime["v17_summary"]["model_hashes"].append(model_hash)
    assert cloud_parser()(runtime)[-1]["passed"]
    runtime["v17_fit_2022"]["label_end_last"] = "2022-01-01T00:00:00"
    checked = cloud_parser()(runtime)[-1]
    assert not checked["passed"]
    assert any(r["check"] == "v17_fit_2022_labels_matured_before_boundary" and not r["passed"] for r in checked["checks"])


def test_runtime_text_transport_preserves_unicode_floats_and_significant_spaces():
    value = {"unicode": "风险与收益🚀"*40, "sid": " leading and trailing ",
             "float": 1.0, "integer": 1, "negative_zero": -0.0,
             "tiny": 1e-300, "bool": True, "none": None}
    for size in (1, 7, 180):
        meta, parts = features.runtime_payload_parts(value, size)
        assert max(map(len, parts)) <= size
        assert all(part.isascii() and len(part.encode("utf-8")) == len(part) for part in parts)
        assert len(json.dumps(meta, separators=(",", ":"))) <= 180
        # Browser outer-JSON persistence is safe if inner text stays untouched.
        saved = json.loads(json.dumps(dict(meta=meta, parts=parts)))
        decoded = features.decode_runtime_payload(saved["meta"], saved["parts"])
        assert decoded == value and decoded["sid"] == " leading and trailing "
        assert type(decoded["float"]) is float and type(decoded["integer"]) is int
        assert type(decoded["bool"]) is bool and np.signbit(decoded["negative_zero"])
    with unittest.TestCase().assertRaises(ValueError):
        features.runtime_payload_parts({"invalid": float("nan")})


def test_runtime_text_transport_rejects_missing_truncated_reordered_or_mutated_chunks():
    meta, parts = features.runtime_payload_parts({"text": "ABC DEF "*100, "number": 1.0})
    variants = [parts[:-1], [parts[0][:-1], *parts[1:]], list(reversed(parts)),
                ["X"+parts[0][1:], *parts[1:]], ["中文", *parts[1:]],
                ["x"*181, *parts[1:]]]
    for damaged in variants:
        with unittest.TestCase().assertRaises(ValueError):
            features.decode_runtime_payload(meta, damaged)


def test_cloud_parser_reads_exact_small_text_cells_and_rejects_damaged_cell():
    old = synthetic_cloud_capture()
    values = {"v17_summary": old["v17_summary"], "v17_months": old["v17_months"],
              "v17_security_pnl": [["SID", 0.]]}
    values.update({f"v17_predictions_{month}": [] for month in old["v17_months"]})
    cells = {}
    for key, value in values.items():
        meta, parts = features.runtime_payload_parts(value)
        prefix = "v17_payload_"+key.removeprefix("v17_")
        cells[prefix+"_meta"] = json.dumps(meta, separators=(",", ":"))
        cells.update({prefix+"_"+str(i): part for i, part in enumerate(parts)})
    assert all(len(value) <= 180 for value in cells.values())
    checked = cloud_parser()({"runtime_statistics": cells})[-1]
    assert checked["passed"]
    assert any(r["check"] == "v17_summary_text_transport" for r in checked["checks"])
    cells["v17_payload_summary_0"] = cells["v17_payload_summary_0"][:-1]
    with unittest.TestCase().assertRaisesRegex(ValueError, "character count"):
        cloud_parser()({"runtime_statistics": cells})


def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    for name, function in sorted(globals().items()):
        if name.startswith("test_") and callable(function):
            suite.addTest(unittest.FunctionTestCase(function))
    return suite


if __name__ == "__main__":
    unittest.main()
