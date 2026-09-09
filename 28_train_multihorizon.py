"""固定多周期研究：24配置×6年，48主策略与旧44共同筛选。"""

import hashlib
import importlib
import json
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import ElasticNet, Ridge
from sklearn.metrics import ndcg_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

import fundamental_features as ff
import research_event_features as ef
import research_features as rf
import research_horizons as rh
from panel_config import ROOT, SYMBOLS
from research_backtest import run_backtest
from research_evaluation import evaluate_candidates

old = importlib.import_module("15_run_research_batch")
OUTPUT = ROOT / "data/experiments/continuous_research_2h_v3"
PREVIOUS = ROOT / "data/experiments/automation_research_v2"
YEARS = tuple(range(2020, 2026))
TRAINING_DEADLINE = datetime.fromisoformat("2026-09-09T06:45:07+00:00")
MODELS = [dict(id=f"v3_{kind}_h{h}_{group}", kind=kind, horizon=h, feature_group=group)
          for kind in ("ridge", "elastic", "ranker") for h in rh.HORIZONS for group in ("price", "full")]
MODELS += [dict(id=f"v3_elastic_h{h}_{group}", kind="elastic", horizon=h, feature_group=group)
           for h in rh.HORIZONS for group in ("base", "fund")]
STRATEGIES = [dict(id=f"{m['id']}_top{k}", model=m["id"], top_k=k) for m in MODELS for k in (5, 10)]
ELASTIC_PARAMS = dict(alpha=0.001, l1_ratio=0.15, max_iter=2000, selection="random", random_state=42)
RIDGE_PARAMS = dict(alpha=100, solver="svd")
LGB_PARAMS = {**old.LGB_PARAMS, "objective": "lambdarank", "label_gain": [0,1,2,3,4],
              "lambdarank_truncation_level": 10}


def save_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def features_for(config):
    group = config["feature_group"]
    if group == "base":
        return list(rf.BASE_FEATURES)
    features = list(rf.EXTENDED_FEATURES)
    if group in ("fund", "full"):
        features += ff.FUND_FEATURES
    if group == "full":
        features += ef.EVENT_FEATURES
    return features


def register_plan():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    plan = {"models": MODELS, "strategies": STRATEGIES, "years": list(YEARS),
            "feature_order": {m["id"]: features_for(m) for m in MODELS},
            "data_sha256": {str(p.relative_to(ROOT)): sha(p) for p in (
                rf.RESEARCH_PANEL_PATH, rh.TARGET_PATH, ff.FUNDAMENTAL_PANEL_PATH, ef.EVENT_PANEL_PATH)},
            "ridge": RIDGE_PARAMS, "elastic": ELASTIC_PARAMS, "ranker": LGB_PARAMS,
            "early_stopping_rounds": 50,
            "imputation": "Linear fund/full: training median, keep_empty_features, no extra indicator; train-only standardization. Ranker: native NaN, source missing indicators retained.",
            "labels": "Each H uses next-open entry and H-session later open exit, relative SPY; own date rank and grades. Old y5 floats retained exactly for controls.",
            "split": "Annual expanding training, previous-year validation, horizon-specific exit purge; score same 45060 rows 2020-01-02 through 2025-12-22 without requiring future H labels.",
            "main_trading": {"rebalance_sessions": 5, "top_k": [5,10], "cost_bps": [10,20]},
            "diagnostics": "Elastic full H20/H60 top5/top10 also hold H with matched-schedule baselines, excluded from main selection.",
            "selection": "Unchanged gates, uniform y5 IC, old44 plus new48 joint max-t bootstrap 2000 x20-session blocks seed20260907; only all-gate unique winner may use sealed 2026.",
            "holdout": "See preregistered DESIGN.md. No 2026 market data before immutable unique candidate + final trained artifact manifest.",
            "training_deadline_utc": TRAINING_DEADLINE.isoformat()}
    path = OUTPUT / "plan.json"
    if path.exists():
        previous = json.loads(path.read_text(encoding="utf-8"))
        previous.pop("registered_at_utc")
        previous.pop("initial_code_sha256")
        if previous != plan:
            raise ValueError("固定计划或数据已改变；禁止覆盖原实验。")
    else:
        save_json(path, {**plan, "registered_at_utc": datetime.now(timezone.utc).isoformat(),
                        "initial_code_sha256": {p.name: sha(p) for p in (
                            Path(__file__), ROOT / "research_horizons.py", ROOT / "research_event_features.py")}})
    return sha(path)


def native_rows(rows, h):
    """只为排名指标构造本征标签视图；不改变主策略的 y5。"""
    result = rows[["Date", "symbol"]].copy()
    result[rf.TARGET] = rows[f"y_{h}"].to_numpy()
    result["relevance"] = rows[f"grade_{h}"].astype(int).to_numpy()
    return result


def control_name(config):
    if config["horizon"] != 5:
        return None
    if config["feature_group"] == "price":
        return {"ridge": "v2_ridge_extended_price", "elastic": "v2_elastic_extended_price",
                "ranker": "m22_ranker_extended"}[config["kind"]]
    if config["kind"] == "elastic" and config["feature_group"] == "fund":
        return "v2_elastic_extended_fund"
    return None


def train_one(config, year, train, valid, develop, plan_hash):
    name, h = config["id"], config["horizon"]
    folder = OUTPUT / str(year)
    folder.mkdir(exist_ok=True)
    checkpoint = folder / f"{name}_record.json"
    model_path = folder / f"{name}.joblib"
    dev_path, val_path = folder / f"{name}_development.csv", folder / f"{name}_validation.csv"
    if checkpoint.exists():
        record = json.loads(checkpoint.read_text(encoding="utf-8"))
        assert record["plan_sha256"] == plan_hash and record["model_sha256"] == sha(model_path)
        dev, val = [pd.read_csv(p, float_precision="round_trip", parse_dates=["Date"]) for p in (dev_path, val_path)]
        pd.testing.assert_frame_equal(dev[["Date", "symbol"]], develop[["Date", "symbol"]])
        pd.testing.assert_frame_equal(val[["Date", "symbol"]], valid[["Date", "symbol"]])
        print(f"{year} {name}: verified checkpoint", flush=True)
        return dev.score.to_numpy(), record
    if datetime.now(timezone.utc) >= TRAINING_DEADLINE:
        raise TimeoutError("已到固定拟合截止时间，保留已完成检查点。")
    features = features_for(config)
    if config["kind"] == "ranker":
        model = lgb.LGBMRanker(**LGB_PARAMS)
    else:
        estimator = Ridge(**RIDGE_PARAMS) if config["kind"] == "ridge" else ElasticNet(**ELASTIC_PARAMS)
        steps = [StandardScaler(), estimator]
        if config["feature_group"] in ("fund", "full"):
            steps.insert(0, SimpleImputer(strategy="median", keep_empty_features=True, add_indicator=False))
        model = make_pipeline(*steps)
    started = time.perf_counter()
    curve = None
    with warnings.catch_warnings(record=True) as caught, threadpool_limits(limits=4):
        warnings.simplefilter("always")
        if config["kind"] == "ranker":
            model.fit(train[features], train[f"grade_{h}"].astype(int),
                      group=old.ranking.check_groups(train), eval_group=[old.ranking.check_groups(valid)],
                      eval_X=valid[features], eval_y=valid[f"grade_{h}"].astype(int), eval_names=["validation"],
                      eval_at=[5], eval_metric=old.ranking.make_ranking_metric(native_rows(valid, h)),
                      callbacks=[lgb.early_stopping(50, first_metric_only=True, verbose=False)])
            curve = model.evals_result_["validation"]["daily_ndcg5"]
            assert int(np.argmax(curve)) + 1 == model.best_iteration_
            save_json(folder / f"{name}_curve.json", model.evals_result_)
        else:
            model.fit(train[features], train[f"rank_{h}"])
    seconds = time.perf_counter() - started
    val_score, dev_score = model.predict(valid[features]), model.predict(develop[features])
    assert np.isfinite(val_score).all() and np.isfinite(dev_score).all()
    control, difference = control_name(config), None
    if control:
        path = (ROOT / f"data/experiments/auto_research_45m_v1/{year}/development_scores.csv"
                if config["kind"] == "ranker" else PREVIOUS / f"{year}/development_scores.csv")
        expected = pd.read_csv(path, float_precision="round_trip", parse_dates=["Date"])
        pd.testing.assert_frame_equal(develop[["Date", "symbol"]], expected[["Date", "symbol"]])
        difference = float(np.max(np.abs(dev_score - expected[control].to_numpy())))
        np.testing.assert_allclose(dev_score, expected[control], rtol=0, atol=1e-12)
    payload = {"model": model, "features": features, "candidate": config, "mode": "research_only",
               "development_year": year, "train_last_exit": str(train[f"exit_{h}"].max().date()),
               "validation_last_exit": str(valid[f"exit_{h}"].max().date()), "plan_sha256": plan_hash}
    joblib.dump(payload, model_path)
    np.testing.assert_array_equal(joblib.load(model_path)["model"].predict(develop[features]), dev_score)
    ndcg = float(ndcg_score(valid[f"grade_{h}"].to_numpy().reshape(-1,30), val_score.reshape(-1,30), k=5, ignore_ties=False))
    n_iter = getattr(model.steps[-1][1], "n_iter_", None) if config["kind"] != "ranker" else None
    record = {**config, "model": name, "year": year, "status": "trained", "feature_count": len(features),
              "train_rows": len(train), "validation_rows": len(valid), "development_rows": len(develop),
              "train_first": str(train.Date.min().date()), "train_last": str(train.Date.max().date()),
              "train_last_exit": payload["train_last_exit"], "validation_first": str(valid.Date.min().date()),
              "validation_last": str(valid.Date.max().date()), "validation_last_exit": payload["validation_last_exit"],
              "validation_native_ndcg5": ndcg, "fit_seconds": seconds,
              "n_iter": int(n_iter) if n_iter is not None else None,
              "best_iteration": int(model.best_iteration_) if curve is not None else None,
              "attempted_iterations": len(curve) if curve is not None else None,
              "control": control, "max_control_score_difference": difference,
              "warnings": list(dict.fromkeys(str(w.message) for w in caught)),
              "model_sha256": sha(model_path), "artifact_path": model_path.as_posix(), "plan_sha256": plan_hash,
              "code_sha256": sha(Path(__file__)), "completed_at_utc": datetime.now(timezone.utc).isoformat()}
    for rows, values, path in ((develop, dev_score, dev_path), (valid, val_score, val_path)):
        frame = rows[["Date", "symbol", f"y_{h}", f"exit_{h}"]].copy()
        frame["score"] = values
        frame.to_csv(path, index=False, date_format="%Y-%m-%d")
        np.testing.assert_array_equal(pd.read_csv(path, float_precision="round_trip").score, values)
    # 完整文件全部落盘之后才标记可恢复的检查点。
    save_json(checkpoint, record)
    with (OUTPUT / "training_log.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
    print(f"{year} {name}: features={len(features)}, valH{h}NDCG={ndcg:.4f}, fit={seconds:.2f}s", flush=True)
    return dev_score, record


def fit_all(panel, plan_hash):
    blocks, records = [], []
    for year in YEARS:
        splits = {h: rh.split_fold(panel, year, h) for h in rh.HORIZONS}
        dev = splits[5][2]
        keep = ["Date", "symbol", "entry_date", "exit_date", rf.TARGET, "relevance"]
        keep += [f"{prefix}_{h}" for h in rh.HORIZONS for prefix in ("y", "grade", "exit")]
        output = dev[keep].copy()
        for config in MODELS:
            train, valid, develop = splits[config["horizon"]]
            pd.testing.assert_frame_equal(develop[["Date", "symbol"]], dev[["Date", "symbol"]])
            values, record = train_one(config, year, train, valid, develop, plan_hash)
            output[config["id"]] = values
            records.append(record)
            pd.DataFrame(records).to_csv(OUTPUT / "training_summary.csv", index=False)
        output.to_csv(OUTPUT / f"{year}/development_scores.csv", index=False, date_format="%Y-%m-%d")
        blocks.append(output)
    result = pd.concat(blocks, ignore_index=True)
    assert len(result) == 45060 and result.Date.nunique() == 1502 and len(records) == 144
    result.to_csv(OUTPUT / "all_model_scores.csv", index=False, date_format="%Y-%m-%d")
    saved = pd.read_csv(OUTPUT / "all_model_scores.csv", float_precision="round_trip")
    names = [m["id"] for m in MODELS]
    np.testing.assert_array_equal(saved[names].to_numpy(), result[names].to_numpy())
    return result


def ranking_diagnostics(scores):
    native, uniform = [], []
    common = scores[[f"y_{h}" for h in rh.HORIZONS]].notna().all(axis=1)
    for config in MODELS:
        name, h = config["id"], config["horizon"]
        uniform.append(old.score_ranking(scores, scores[name].to_numpy(), name))
        for label, mask in (("native_mature", scores[f"y_{h}"].notna()), ("all_horizons_mature", common)):
            rows = scores.loc[mask].reset_index(drop=True)
            metrics = old.score_ranking(native_rows(rows, h), rows[name].to_numpy(), name)
            native.append({**metrics, "horizon": h, "feature_group": config["feature_group"], "kind": config["kind"],
                           "sample": label, "rows": len(rows), "dates": rows.Date.nunique(),
                           "first_observation": str(rows.Date.min().date()), "last_observation": str(rows.Date.max().date()),
                           "last_exit": str(rows[f"exit_{h}"].max().date())})
    pd.DataFrame(native).to_csv(OUTPUT / "native_ranking_metrics.csv", index=False)
    pd.DataFrame(uniform).to_csv(OUTPUT / "uniform5_ranking_models.csv", index=False)
    return {row["candidate"]: row for row in uniform}


def evaluate(scores):
    costs = json.loads((PREVIOUS / "cost_metrics_all44.json").read_text(encoding="utf-8"))
    stress = json.loads((PREVIOUS / "stress_metrics_all44.json").read_text(encoding="utf-8"))
    equity = pd.read_csv(PREVIOUS / "equity_all44.csv", float_precision="round_trip", index_col="Date", parse_dates=["Date"])
    ranking = pd.read_csv(PREVIOUS / "ranking_all44.csv", float_precision="round_trip")
    opens, spy = rh.adjusted_opens()
    model_ranks = ranking_diagnostics(scores)
    new_ranks, metadata = [], []
    folder = OUTPUT / "backtests"
    folder.mkdir(exist_ok=True)
    for config in MODELS:
        name = config["id"]
        values = scores.pivot(index="Date", columns="symbol", values=name).reindex(columns=SYMBOLS)
        for k in (5, 10):
            candidate = f"{name}_top{k}"
            result = run_backtest(values, opens, spy, top_k=k, cost_bps=10)
            stressed = run_backtest(values, opens, spy, top_k=k, cost_bps=20)
            assert result["daily_equity"].index.equals(equity.index)
            costs[candidate], stress[candidate] = result["metrics"], stressed["metrics"]
            equity[candidate] = result["daily_equity"].equity
            new_ranks.append({**model_ranks[name], "candidate": candidate})
            daily = result["daily_equity"]
            turnover = float((daily.traded_notional / (daily.equity + daily.cost)).sum() /
                             ((daily.index[-1] - daily.index[0]).days / 365.25))
            metadata.append({**config, "candidate": candidate, "model": name, "top_k": k,
                             "annual_traded_fraction": turnover})
            for key in ("daily_equity", "periods", "trades"):
                result[key].to_csv(folder / f"{candidate}_{key}.csv", index=key == "daily_equity", date_format="%Y-%m-%d")
            save_json(folder / f"{candidate}_metrics.json", {"cost10": result["metrics"], "cost20": stressed["metrics"]})
            print(f"{candidate}: CAGR={costs[candidate]['cagr']:.2%}, DD={costs[candidate]['max_drawdown']:.2%}, IC5={model_ranks[name]['mean_rank_ic']:.4f}", flush=True)
    all_ranks = pd.concat([ranking, pd.DataFrame(new_ranks)], ignore_index=True)
    comparison, boot = evaluate_candidates(equity, all_ranks, stress, costs)
    assert len(comparison) == 92 and boot["family_size"] == 92
    comparison.to_csv(OUTPUT / "comparison_all92.csv", index=False)
    comparison.merge(pd.DataFrame(metadata), on="candidate", validate="one_to_one").to_csv(OUTPUT / "comparison_new48.csv", index=False)
    all_ranks.to_csv(OUTPUT / "ranking_all92.csv", index=False)
    equity.to_csv(OUTPUT / "equity_all92.csv", date_format="%Y-%m-%d")
    save_json(OUTPUT / "cost_metrics_all92.json", costs)
    save_json(OUTPUT / "stress_metrics_all92.json", stress)
    save_json(OUTPUT / "bootstrap_all92.json", boot)
    save_json(OUTPUT / "completion.json", {"completed_at_utc": datetime.now(timezone.utc).isoformat(),
              "models": 24, "annual_fits": 144, "new_strategy_entries": 48, "joint_entries": 92,
              "gate_passes": int(comparison.gate_all.sum()), "selected_candidate": boot["selected_candidate"],
              "2026_market_prices_accessed": False, "orders_sent": 0})
    print(f"All-gate passes: {int(comparison.gate_all.sum())}/92; selected={boot['selected_candidate']}", flush=True)


def matching_holding_diagnostics(scores):
    folder = OUTPUT / "holding_diagnostics"
    folder.mkdir(exist_ok=True)
    opens, spy = rh.adjusted_opens()
    rows = []
    dates = pd.DatetimeIndex(scores.Date.unique()).sort_values()
    for h in (20, 60):
        name = f"v3_elastic_h{h}_full"
        values = scores.pivot(index="Date", columns="symbol", values=name).reindex(columns=SYMBOLS)
        for cost in (10, 20):
            bench = run_backtest(pd.DataFrame(0.0, index=dates, columns=SYMBOLS), opens, spy,
                                 top_k=None, cost_bps=cost, rebalance_every=h)
            spy_bench = run_backtest(pd.DataFrame(0.0, index=dates, columns=["SPY"]), spy.to_frame("SPY"), spy,
                                     top_k=None, cost_bps=cost, rebalance_every=h)
            for k in (5, 10):
                result = run_backtest(values, opens, spy, top_k=k, cost_bps=cost, rebalance_every=h)
                assert result["daily_equity"].index.equals(bench["daily_equity"].index)
                candidate = f"{name}_top{k}_hold{h}_cost{cost}"
                row = {"candidate": candidate, "horizon": h, "top_k": k, "cost_bps": cost,
                       **result["metrics"], "matched_equal_cagr": bench["metrics"]["cagr"],
                       "matched_spy_cagr": spy_bench["metrics"]["cagr"], "eligible_for_selection": False}
                rows.append(row)
                combined = pd.DataFrame({"strategy": result["daily_equity"].equity,
                                         "matched_equal": bench["daily_equity"].equity,
                                         "matched_spy": spy_bench["daily_equity"].equity})
                combined.to_csv(folder / f"{candidate}_equity.csv", date_format="%Y-%m-%d")
                result["periods"].to_csv(folder / f"{candidate}_periods.csv", index=False, date_format="%Y-%m-%d")
    pd.DataFrame(rows).to_csv(folder / "comparison.csv", index=False)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    plan_hash = register_plan()
    if "--register-only" in sys.argv:
        print("24 model configurations registered before fitting.")
        return
    if (OUTPUT / "completion.json").exists():
        print("Complete results exist; no retraining or overwrite.")
        return
    path = OUTPUT / "all_model_scores.csv"
    scores = (pd.read_csv(path, float_precision="round_trip", parse_dates=["Date", "entry_date", "exit_date", *[f"exit_{h}" for h in rh.HORIZONS]])
              if path.exists() else fit_all(rh.load_panel(), plan_hash))
    evaluate(scores)
    matching_holding_diagnostics(scores)


if __name__ == "__main__":
    main()
