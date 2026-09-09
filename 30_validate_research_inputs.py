"""从原始事实/保存来源复核事件值；从模型文件复核实际训练边界和变换。"""
import hashlib
import importlib
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pandas_market_calendars as mcal
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler

import fundamental_features as ff
import research_event_features as ef
import research_horizons as rh
from panel_config import ROOT, SYMBOLS

runner = importlib.import_module("28_train_multihorizon")
OUTPUT = runner.OUTPUT


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def ratio(a, b):
    return a["val"] / b["val"] if a is not None and b is not None and b["val"] > 0 else np.nan


def audit_events():
    panel = pd.read_csv(ef.EVENT_PANEL_PATH, parse_dates=["Date"], float_precision="round_trip")
    provenance = read_jsonl(ef.EVENT_AUDIT_DIR / "provenance.jsonl")
    events = read_jsonl(ef.EVENT_AUDIT_DIR / "period_events.jsonl")
    earliest = min(event["filed"] for event in events)
    calendar = mcal.get_calendar("NYSE").schedule(start_date=earliest, end_date="2025-12-31").index
    facts_verified, formula_cells, event_cells = 0, 0, 0
    for symbol in SYMBOLS:
        payload = json.loads((ff.SEC_DIR / f"{symbol}.json").read_text(encoding="utf-8"))
        data = panel.loc[panel.symbol.eq(symbol)].reset_index(drop=True)
        raw_keys = set()
        for tag, concept in payload["facts"]["us-gaap"].items():
            for unit, values in concept.get("units", {}).items():
                for item in values:
                    raw_keys.add((tag, unit, item.get("start"), item.get("end"), item.get("filed"),
                                  item.get("accn"), item.get("form"), float(item["val"])))
        snapshots = []
        for row in [r for r in provenance if r["symbol"] == symbol]:
            f = row["facts"]
            for fact in f.values():
                if fact is None:
                    continue
                key = tuple(fact[field] for field in ("tag", "unit", "start", "end", "filed", "accn", "form", "val"))
                assert key in raw_keys and fact["filed"] <= row["event_filed"]
                assert fact["end"] <= fact["filed"]
                facts_verified += 1
            for prefix in ("balance", "prior_balance", "annual", "prior_annual"):
                anchor = f[f"{prefix}_{'profit' if 'annual' in prefix else 'assets'}"]
                if anchor is None:
                    continue
                fields = ("revenue", "cfo", "assets") if "annual" in prefix else ("liabilities", "equity")
                for field in fields:
                    fact = f[f"{prefix}_{field}"]
                    if fact is not None:
                        assert fact["end"] == anchor["end"] and fact["accn"] == anchor["accn"]
                        if "annual" in prefix and field != "assets":
                            assert fact["start"] == anchor["start"]
            for field in ("balance_assets", "annual_profit"):
                current, prior = f[field], f[f"prior_{field}"]
                if current and prior:
                    assert 330 <= (pd.Timestamp(current["end"])-pd.Timestamp(prior["end"])).days <= 400
            profit_delta = None
            if f["annual_profit"] and f["prior_annual_profit"]:
                profit_delta = {"val": f["annual_profit"]["val"] - f["prior_annual_profit"]["val"]}
            values = [ratio(f["annual_revenue"], f["prior_annual_revenue"])-1,
                      ratio(f["annual_profit"], f["annual_revenue"])-ratio(f["prior_annual_profit"], f["prior_annual_revenue"]),
                      ratio(f["annual_cfo"], f["annual_revenue"])-ratio(f["prior_annual_cfo"], f["prior_annual_revenue"]),
                      ratio(profit_delta, f["annual_assets"]),
                      ratio(f["annual_cfo"], f["annual_assets"])-ratio(f["prior_annual_cfo"], f["prior_annual_assets"]),
                      ratio(f["balance_liabilities"], f["balance_assets"])-ratio(f["prior_balance_liabilities"], f["prior_balance_assets"]),
                      ratio(f["balance_equity"], f["balance_assets"])-ratio(f["prior_balance_equity"], f["prior_balance_assets"])]
            snapshots.append({"filed": pd.Timestamp(row["event_filed"]), **dict(zip(ef.CHANGE_FEATURES, values))})
        recomputed = pd.merge_asof(data[["Date"]], pd.DataFrame(snapshots).sort_values("filed"),
                                   left_on="Date", right_on="filed", allow_exact_matches=False, direction="backward")
        np.testing.assert_allclose(data[ef.CHANGE_FEATURES], recomputed[ef.CHANGE_FEATURES], rtol=0, atol=1e-14, equal_nan=True)
        assert (recomputed.filed < recomputed.Date).all()
        formula_cells += len(data)*7
        for kind in ("balance", "annual", "financial_amendment"):
            selected = sorted([r for r in events if r["symbol"] == symbol and r["kind"] == kind], key=lambda r:r["filed"])
            if kind != "financial_amendment":
                ends = [r["period_end"] for r in selected]
                assert all(b > a for a,b in zip(ends, ends[1:]))
                assert all("/A" not in r["form"] for r in selected)
            for event in selected:
                fact = event["source_fact"]
                assert tuple(fact[k] for k in ("tag", "unit", "start", "end", "filed", "accn", "form", "val")) in raw_keys
            filed = pd.to_datetime([r["filed"] for r in selected])
            first_sessions = calendar.searchsorted(filed, side="right")
            observed_positions = calendar.get_indexer(data.Date)
            expected = []
            for position in observed_positions:
                usable = first_sessions[first_sessions <= position]
                expected.append(position-usable[-1] if len(usable) else np.nan)
            expected = np.asarray(expected)
            if kind != "financial_amendment":
                np.testing.assert_array_equal(data[f"event_sessions_since_new_{kind}"], expected)
                for h in (5,20):
                    flags = np.where(np.isfinite(expected), (expected < h).astype(float), np.nan)
                    np.testing.assert_array_equal(data[f"event_new_{kind}_filed_{h}d"], flags)
                event_cells += len(data)*3
            else:
                np.testing.assert_array_equal(data.event_financial_amendment_filed_20d, (expected < 20).astype(float))
                event_cells += len(data)
        for column in ef.EVENT_VALUE_FEATURES:
            np.testing.assert_array_equal(data[f"{column}_missing"], data[column].isna().astype(int))
    return {"status": "passed", "rows": len(panel), "source_fact_references_matched_raw": facts_verified,
            "financial_change_cells_recomputed": formula_cells, "event_clock_and_flag_cells_recomputed": event_cells,
            "missing_indicator_cells_checked": len(panel)*14,
            "scope": "Raw fact membership, filed availability, within-period matching, arithmetic, event period advance and clock; not a complete historical-vintage database guarantee."}


def audit_horizons():
    opens, spy = rh.adjusted_opens()
    targets = pd.read_csv(rh.TARGET_PATH, float_precision="round_trip", parse_dates=["Date", "exit_5", "exit_20", "exit_60"])
    checked = 0
    for h in rh.HORIZONS:
        positions = np.linspace(0, len(opens)-h-2, 100, dtype=int)
        for symbol in SYMBOLS:
            indexed = targets.loc[targets.symbol.eq(symbol)].set_index("Date")
            for i in positions:
                stock = opens[symbol].iloc[i+h+1]/opens[symbol].iloc[i+1]-1
                market = spy.iloc[i+h+1]/spy.iloc[i+1]-1
                assert abs(indexed.loc[opens.index[i],f"y_{h}"]-(stock-market)) < 2e-15
                assert indexed.loc[opens.index[i],f"exit_{h}"] == opens.index[i+h+1]
                checked += 1
    return {"status": "passed", "raw_endpoint_checks": checked, "horizons": list(rh.HORIZONS),
            "definition": "Indexed raw adjusted-open endpoints at t+1 and t+H+1; stock and SPY identical interval."}


def audit_fits():
    panel = rh.load_panel()
    checks = []
    configs = {m["id"]:m for m in runner.MODELS}
    for year in runner.YEARS:
        splits = {h:rh.split_fold(panel, year, h) for h in rh.HORIZONS}
        for path in sorted((OUTPUT/str(year)).glob("*_record.json")):
            record = json.loads(path.read_text(encoding="utf-8"))
            config = configs[record["model"]]
            train, valid, dev = splits[config["horizon"]]
            artifact = Path(record["artifact_path"])
            assert hashlib.sha256(artifact.read_bytes()).hexdigest() == record["model_sha256"]
            payload = joblib.load(artifact)
            features, model = payload["features"], payload["model"]
            assert features == runner.features_for(config)
            assert record["train_rows"] == len(train) and record["validation_rows"] == len(valid)
            assert record["train_last_exit"] == str(train[f"exit_{config['horizon']}"].max().date())
            assert record["validation_last_exit"] == str(valid[f"exit_{config['horizon']}"].max().date())
            if config["kind"] != "ranker":
                matrix = train[features]
                if config["feature_group"] in ("full", "fund"):
                    independently_fit = SimpleImputer(strategy="median", keep_empty_features=True)
                    matrix = independently_fit.fit_transform(matrix)
                    np.testing.assert_array_equal(model[0].statistics_, independently_fit.statistics_)
                scaler = next(step for _,step in model.steps if isinstance(step, StandardScaler))
                np.testing.assert_allclose(scaler.mean_, np.mean(matrix,axis=0), rtol=0, atol=1e-10)
                np.testing.assert_allclose(scaler.var_, np.var(matrix,axis=0), rtol=1e-12, atol=1e-10)
                assert np.asarray(scaler.n_samples_seen_).max() == len(train)
            else:
                curve = json.loads((artifact.parent/f"{record['model']}_curve.json").read_text(encoding="utf-8"))
                assert int(np.argmax(curve["validation"]["daily_ndcg5"]))+1 == record["best_iteration"]
            sample = dev.iloc[np.linspace(0,len(dev)-1,40,dtype=int)]
            saved = pd.read_csv(artifact.parent/f"{record['model']}_development.csv", float_precision="round_trip")
            np.testing.assert_allclose(model.predict(sample[features]), saved.score.iloc[sample.index], rtol=0, atol=1e-12)
            checks.append({"model":record["model"],"year":year,"status":"passed"})
    return {"status": "passed", "fits_checked":len(checks), "complete_144":len(checks)==144,
            "checks": checks, "scope":"Saved artifact hash/feature order, horizon-specific split, training-only preprocessing, predictions and ranker stopping iteration."}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if "--fits" in sys.argv:
        result = audit_fits()
        runner.save_json(OUTPUT/"FIT_CHECKS.json", result)
    else:
        result = {"events":audit_events(), "horizons":audit_horizons()}
        runner.save_json(OUTPUT/"INPUT_CHECKS.json", result)
    print(json.dumps({k:v for k,v in result.items() if k!="checks"},ensure_ascii=False,indent=2))
