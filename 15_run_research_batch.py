"""45分钟自动研究：固定30候选，年度训练，真实成本研究回测与完整留档。"""

import hashlib
import importlib
import json
import sys
import time
import traceback
import warnings
from datetime import datetime, timezone

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesRegressor
from sklearn.linear_model import ElasticNet, Ridge
from sklearn.metrics import ndcg_score
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

import research_features as rf
from panel_config import ROOT, SYMBOLS
from research_backtest import run_backtest
from research_evaluation import evaluate_candidates

ranking = importlib.import_module("12_train_ranker")
OUTPUT = ROOT / "data" / "experiments" / "auto_research_45m_v1"
YEARS = tuple(range(2020, 2026))
TRAINING_DEADLINE = datetime.fromisoformat("2026-09-07T09:18:50+00:00")
FEATURE_SETS = {"base": rf.BASE_FEATURES, "extended": rf.EXTENDED_FEATURES, "cs": rf.CS_FEATURES}
CANDIDATES = [
    {"id": "r01_momentum20", "kind": "rule", "column": "ret_20d", "sign": 1},
    {"id": "r02_momentum60", "kind": "rule", "column": "ret_60d", "sign": 1},
    {"id": "r03_momentum12_skip1", "kind": "rule", "column": "mom_252_skip21", "sign": 1},
    {"id": "r04_reversal1", "kind": "rule", "column": "ret_1d", "sign": -1},
    {"id": "r05_reversal5", "kind": "rule", "column": "ret_5d", "sign": -1},
    {"id": "r06_reversal10", "kind": "rule", "column": "ret_10d", "sign": -1},
    {"id": "r07_low_volatility", "kind": "rule", "column": "volatility_20d", "sign": -1},
    {"id": "r08_sector_momentum", "kind": "rule", "column": "relative_sector_20d", "sign": 1},
    {"id": "r09_residual_reversal", "kind": "rule", "column": "beta_residual_5d", "sign": -1},
    {"id": "r10_momentum_lowvol", "kind": "rule", "combo": "momentum_lowvol"},
    {"id": "m11_ridge_return_base", "kind": "ridge", "features": "base", "target": "return", "alpha": 100},
    {"id": "m12_ridge_rank_base", "kind": "ridge", "features": "base", "target": "rank", "alpha": 100},
    {"id": "m13_ridge_rank_extended", "kind": "ridge", "features": "extended", "target": "rank", "alpha": 100},
    {"id": "m14_ridge_rank_cs", "kind": "ridge", "features": "cs", "target": "rank", "alpha": 100},
    {"id": "m15_ridge_recent3", "kind": "ridge", "features": "extended", "target": "rank", "alpha": 100, "recent_years": 3},
    {"id": "m16_elastic_rank", "kind": "elastic", "features": "extended", "target": "rank"},
    {"id": "m17_extra_trees", "kind": "extra", "features": "extended", "target": "rank"},
    {"id": "m18_lgb_return", "kind": "lgb", "features": "extended", "target": "return", "objective": "regression"},
    {"id": "m19_lgb_huber", "kind": "lgb", "features": "extended", "target": "return", "objective": "huber"},
    {"id": "m20_lgb_rank_target", "kind": "lgb", "features": "extended", "target": "rank", "objective": "regression"},
    {"id": "m21_ranker_base", "kind": "ranker", "features": "base", "target": "grade"},
    {"id": "m22_ranker_extended", "kind": "ranker", "features": "extended", "target": "grade"},
    {"id": "m23_ranker_cs", "kind": "ranker", "features": "cs", "target": "grade"},
    {"id": "m24_ranker_recent3", "kind": "ranker", "features": "extended", "target": "grade", "recent_years": 3},
    {"id": "m25_ranker_timeweight", "kind": "ranker", "features": "extended", "target": "grade", "half_life_years": 2},
    {"id": "m26_ranker_capacity63", "kind": "ranker", "features": "extended", "target": "grade", "leaves": 63},
    {"id": "m27_small_mlp", "kind": "mlp", "features": "extended", "target": "rank"},
    {"id": "e28_model_ensemble", "kind": "ensemble", "components": {"m13_ridge_rank_extended": 1/3, "m17_extra_trees": 1/3, "m22_ranker_extended": 1/3}},
    {"id": "e29_rule_model_ensemble", "kind": "ensemble", "components": {"m22_ranker_extended": 0.5, "r05_reversal5": 0.25, "r02_momentum60": 0.25}},
    {"id": "e30_ranker_ensemble", "kind": "ensemble", "components": {"m22_ranker_extended": 1/3, "m23_ranker_cs": 1/3, "m24_ranker_recent3": 1/3}},
]
LGB_PARAMS = dict(n_estimators=1000, learning_rate=0.03, num_leaves=31,
                  min_child_samples=100, reg_lambda=10, colsample_bytree=0.9,
                  random_state=42, n_jobs=4, deterministic=True, force_col_wise=True,
                  metric="None", verbosity=-1)


def save_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str, allow_nan=False), encoding="utf-8")


def record(event):
    event["utc"] = datetime.now(timezone.utc).isoformat()
    with (OUTPUT / "training_log.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, default=str, allow_nan=False) + "\n")


def fixed_plan():
    assert len(CANDIDATES) == 30
    plan = {"candidates": CANDIDATES, "feature_sets": FEATURE_SETS, "years": list(YEARS),
            "panel_sha256": hashlib.sha256(rf.RESEARCH_PANEL_PATH.read_bytes()).hexdigest(),
            "lgb_parameters": LGB_PARAMS, "early_stopping_rounds": 50,
            "elastic_parameters": {"alpha": 0.001, "l1_ratio": 0.15, "max_iter": 2000, "selection": "random", "random_state": 42},
            "extra_parameters": {"n_estimators": 128, "min_samples_leaf": 100, "max_depth": 12, "max_features": 0.7, "random_state": 42, "n_jobs": 4},
            "mlp_parameters": {"hidden_layer_sizes": [32,16], "max_iter": 100, "batch_size": 1024, "alpha": 1.0, "early_stopping": False, "random_state": 42},
            "validation": "Train through Y-2, early stop on Y-1 with exit_date before Y; evaluate entire Y, allowing year-end holding across development years.",
            "trading": {"top_k": 5, "rebalance_sessions": 5, "entry": "next_open", "single_side_cost_bps": 10, "stress_cost_bps": 20, "tie_break": "ticker_alphabetical"},
            "benchmarks": ["same_universe_equal_weight", "SPY"],
            "gate": {"cagr_advantage_over_both": 0.03, "information_ratio": 0.5,
                     "positive_active_years": 4, "max_drawdown_extra_allowance": 0.05,
                     "mean_rank_ic": 0.03, "positive_ic_years": 4,
                     "stress_20bp_beats_equal": True, "simultaneous_block_bootstrap_lower_positive": True},
            "bootstrap": {"samples": 2000, "block_sessions": 20, "confidence": 0.95, "seed": 20260907},
            "holdout_policy": "Only one frozen development gate-passing candidate may access 2026; no candidate matrix on holdout; no passing candidate leaves 2026 sealed.",
            "limits": "Current survivor stock list and static proxy mapping; vendor adjusted-open return proxy; 2015-2025 previously studied; no execution authorization.",
            "training_deadline_utc": TRAINING_DEADLINE.isoformat()}
    path = OUTPUT / "plan.json"
    if path.exists():
        previous = json.loads(path.read_text(encoding="utf-8"))
        previous.pop("created_at_utc")
        if previous != plan:
            raise ValueError("实验配置变化，需要新目录，不能覆盖已见结果。")
    else:
        save_json(path, {**plan, "created_at_utc": datetime.now(timezone.utc).isoformat()})


def load_panel():
    panel = pd.read_csv(rf.RESEARCH_PANEL_PATH, parse_dates=["Date", "entry_date", "exit_date"])
    panel = panel.loc[np.isfinite(panel[rf.ALL_FEATURES + [rf.TARGET]].to_numpy()).all(axis=1)].copy()
    panel = panel.sort_values(["Date", "symbol"]).reset_index(drop=True)
    ranks = panel.groupby("Date")[rf.TARGET].rank(method="average")
    counts = panel.groupby("Date")[rf.TARGET].transform("count")
    panel["rank_target"] = (ranks - 1) / (counts - 1) - 0.5
    panel["relevance"] = np.floor((ranks - 1) * 5 / counts).astype(int)
    ranking.check_groups(panel)
    return panel


def target_column(candidate):
    return {"return": rf.TARGET, "rank": "rank_target", "grade": "relevance"}[candidate["target"]]


def train_model(candidate, train, validation, year, folder):
    if candidate.get("recent_years"):
        train = train.loc[train.Date.ge(f"{year - 1 - candidate['recent_years']}-01-01")].copy()
    features = FEATURE_SETS[candidate["features"]]
    target = target_column(candidate)
    kind = candidate["kind"]
    if kind == "ridge":
        model = make_pipeline(StandardScaler(), Ridge(alpha=candidate["alpha"], solver="svd"))
    elif kind == "elastic":
        model = make_pipeline(StandardScaler(), ElasticNet(alpha=0.001, l1_ratio=0.15,
                               max_iter=2000, selection="random", random_state=42))
    elif kind == "extra":
        model = ExtraTreesRegressor(n_estimators=128, min_samples_leaf=100, max_depth=12,
                                    max_features=0.7, random_state=42, n_jobs=4)
    elif kind == "mlp":
        model = make_pipeline(StandardScaler(), MLPRegressor(hidden_layer_sizes=(32,16),
                               max_iter=100, batch_size=1024, alpha=1.0,
                               early_stopping=False, random_state=42))
    else:
        params = {**LGB_PARAMS, "num_leaves": candidate.get("leaves", 31)}
        if kind == "ranker":
            model = lgb.LGBMRanker(**params, objective="lambdarank", label_gain=[0,1,2,3,4], lambdarank_truncation_level=10)
        else:
            model = lgb.LGBMRegressor(**params, objective=candidate["objective"])
    started = time.perf_counter()
    with warnings.catch_warnings(record=True) as caught, threadpool_limits(limits=4):
        warnings.simplefilter("always")
        if kind in ("lgb", "ranker"):
            args = {}
            if kind == "ranker":
                args.update(group=ranking.check_groups(train), eval_group=[ranking.check_groups(validation)], eval_at=[5])
            if candidate.get("half_life_years"):
                age = (train.Date.max() - train.Date).dt.days / 365.25
                args["sample_weight"] = np.power(0.5, age / candidate["half_life_years"])
            model.fit(train[features], train[target], eval_X=validation[features], eval_y=validation[target],
                      eval_names=["validation"], eval_metric=ranking.make_ranking_metric(validation),
                      callbacks=[lgb.early_stopping(50, first_metric_only=True, verbose=False)], **args)
            curve = model.evals_result_["validation"]["daily_ndcg5"]
            assert int(np.argmax(curve)) + 1 == model.best_iteration_
            save_json(folder / f"{candidate['id']}_curve.json", model.evals_result_)
            (folder / f"{candidate['id']}_model.txt").write_text(model.booster_.model_to_string(), encoding="utf-8")
        else:
            model.fit(train[features], train[target])
    scores = model.predict(validation[features])
    ndcg = float(ndcg_score(validation.relevance.to_numpy().reshape(-1,30), np.asarray(scores).reshape(-1,30), k=5, ignore_ties=False))
    details = {"candidate": candidate["id"], "year": year, "status": "trained",
               "kind": kind, "feature_group": candidate["features"], "features": features,
               "train_rows": len(train), "validation_rows": len(validation),
               "train_first": str(train.Date.min().date()), "train_last_exit": str(train.exit_date.max().date()),
               "validation_last_exit": str(validation.exit_date.max().date()),
               "validation_ndcg5": ndcg, "seconds": time.perf_counter() - started,
               "best_iteration": int(model.best_iteration_) if kind in ("lgb", "ranker") else None,
               "attempted_iterations": len(curve) if kind in ("lgb", "ranker") else None,
               "warnings": list(dict.fromkeys(str(item.message) for item in caught))}
    joblib.dump({"model": model, "features": features, "candidate": candidate}, folder / f"{candidate['id']}.joblib")
    record(details)
    return model, scores, details


def within_date_rank(scores, dates):
    return pd.Series(np.asarray(scores), index=dates.index).groupby(dates).rank(pct=True, method="average") - 0.5


def rule_scores(candidate, rows):
    if candidate.get("combo") == "momentum_lowvol":
        return (within_date_rank(rows.ret_60d, rows.Date) - within_date_rank(rows.volatility_20d, rows.Date)).to_numpy()
    return candidate["sign"] * rows[candidate["column"]].to_numpy()


def score_ranking(rows, scores, candidate):
    report = rows[["Date", "symbol", rf.TARGET]].rename(columns={rf.TARGET: "y_true"})
    daily = ranking.previous.daily_rank_ic(report, np.asarray(scores))
    grades = rows.relevance.to_numpy().reshape(-1,30)
    matrix = np.asarray(scores).reshape(-1,30)
    ndcg = float(ndcg_score(grades, matrix, k=5, ignore_ties=False))
    annual_ic = daily.groupby(daily.index.year).rank_ic.mean()
    return {"candidate": candidate, "mean_rank_ic": float(daily.rank_ic.mean()),
            "positive_ic_years": int(annual_ic.gt(0).sum()), "ndcg5": ndcg}


def run_batch():
    panel = load_panel()
    blocks, metadata = [], []
    for year in YEARS:
        folder = OUTPUT / str(year)
        folder.mkdir(exist_ok=True)
        train = panel.loc[panel.Date.lt(f"{year-1}-01-01") & panel.exit_date.lt(f"{year-1}-01-01")].copy().reset_index(drop=True)
        validation = panel.loc[panel.Date.ge(f"{year-1}-01-01") & panel.Date.lt(f"{year}-01-01") & panel.exit_date.lt(f"{year}-01-01")].copy().reset_index(drop=True)
        development = panel.loc[panel.Date.ge(f"{year}-01-01") & panel.Date.lt(f"{year+1}-01-01")].copy().reset_index(drop=True)
        assert train.exit_date.max() < validation.Date.min() and validation.exit_date.max() < development.Date.min()
        for rows in (train, validation, development):
            ranking.check_groups(rows)
        scores_val, scores_dev = {}, {}
        print(f"{year}: 训练{len(train):,} 验证{len(validation):,} 连续开发{len(development):,}", flush=True)
        for candidate in CANDIDATES:
            name, kind = candidate["id"], candidate["kind"]
            try:
                if kind == "rule":
                    scores_val[name], scores_dev[name] = rule_scores(candidate, validation), rule_scores(candidate, development)
                    record({"candidate": name, "year": year, "status": "rule_no_fit"})
                elif kind == "ensemble":
                    scores_val[name] = sum(weight * within_date_rank(scores_val[component], validation.Date).to_numpy() for component, weight in candidate["components"].items())
                    scores_dev[name] = sum(weight * within_date_rank(scores_dev[component], development.Date).to_numpy() for component, weight in candidate["components"].items())
                    record({"candidate": name, "year": year, "status": "fixed_ensemble_no_fit"})
                else:
                    if datetime.now(timezone.utc) >= TRAINING_DEADLINE:
                        raise TimeoutError("训练预算已到，保留完整完成的候选。")
                    model, val, details = train_model(candidate, train, validation, year, folder)
                    scores_val[name] = val
                    scores_dev[name] = model.predict(development[FEATURE_SETS[candidate["features"]]])
                    metadata.append(details)
                    print(f"  {name}: valNDCG={details['validation_ndcg5']:.4f}, {details['seconds']:.1f}s", flush=True)
            except Exception as exc:
                record({"candidate": name, "year": year, "status": "failed", "error": repr(exc), "traceback": traceback.format_exc()})
                print(f"  {name}: FAILED {type(exc).__name__}: {exc}", flush=True)
        base = development[["Date", "symbol", "entry_date", "exit_date", rf.TARGET, "relevance"]].copy()
        for name, values in scores_dev.items():
            base[name] = values
        base.to_csv(folder / "development_scores.csv", index=False, date_format="%Y-%m-%d")
        val_base = validation[["Date", "symbol", "entry_date", "exit_date", rf.TARGET, "relevance"]].copy()
        for name, values in scores_val.items():
            val_base[name] = values
        val_base.to_csv(folder / "validation_scores.csv", index=False, date_format="%Y-%m-%d")
        save_json(folder / "fold_metadata.json", {"year": year, "train_rows": len(train), "validation_rows": len(validation),
                  "development_rows": len(development), "train_last_exit": str(train.exit_date.max().date()),
                  "validation_last_exit": str(validation.exit_date.max().date()), "development_cross_year_labels_allowed": True})
        blocks.append(base)
    result = pd.concat(blocks, ignore_index=True)
    assert not result.duplicated(["Date", "symbol"]).any()
    result.to_csv(OUTPUT / "all_development_scores.csv", index=False, date_format="%Y-%m-%d")
    pd.DataFrame(metadata).to_csv(OUTPUT / "training_summary.csv", index=False)
    return result


def evaluate_batch(predictions):
    raw, _ = rf.load_inputs()
    opens = pd.DataFrame({name: raw[name].Open * raw[name]["Adj Close"] / raw[name].Close for name in SYMBOLS})
    spy = raw["SPY"].Open * raw["SPY"]["Adj Close"] / raw["SPY"].Close
    dates = pd.DatetimeIndex(predictions.Date.unique()).sort_values()
    rows = predictions.sort_values(["Date", "symbol"]).reset_index(drop=True)
    cost_metrics, stress, equities, ranks = {}, {}, {}, []
    folder = OUTPUT / "backtests"
    folder.mkdir(exist_ok=True)
    names = [candidate["id"] for candidate in CANDIDATES if candidate["id"] in rows and np.isfinite(rows[candidate["id"]]).all()]
    for name in ["benchmark_equal", "benchmark_spy", *names]:
        if name == "benchmark_equal":
            score = pd.DataFrame(0.0, index=dates, columns=SYMBOLS)
            prices, top_k = opens, None
        elif name == "benchmark_spy":
            score = pd.DataFrame(0.0, index=dates, columns=["SPY"])
            prices, top_k = spy.to_frame("SPY"), None
        else:
            score = rows.pivot(index="Date", columns="symbol", values=name).reindex(columns=SYMBOLS)
            prices, top_k = opens, 5
            ranks.append(score_ranking(rows, rows[name].to_numpy(), name))
        result = run_backtest(score, prices, spy, top_k=top_k, cost_bps=10)
        stressed = run_backtest(score, prices, spy, top_k=top_k, cost_bps=20)
        cost_metrics[name], stress[name] = result["metrics"], stressed["metrics"]
        equities[name] = result["daily_equity"].equity
        result["daily_equity"].to_csv(folder / f"{name}_daily.csv", date_format="%Y-%m-%d")
        result["periods"].to_csv(folder / f"{name}_periods.csv", index=False, date_format="%Y-%m-%d")
        result["trades"].to_csv(folder / f"{name}_trades.csv", index=False, date_format="%Y-%m-%d")
        save_json(folder / f"{name}_metrics.json", {"cost_10bp": result["metrics"], "cost_20bp": stressed["metrics"]})
        print(f"回测 {name}: CAGR={result['metrics']['cagr']:.2%}, MDD={result['metrics']['max_drawdown']:.2%}", flush=True)
    equity = pd.DataFrame(equities)
    assert equity.notna().all().all()
    rank_metrics = pd.DataFrame(ranks)
    comparison, bootstrap_info = evaluate_candidates(equity, rank_metrics, stress, cost_metrics)
    equity.to_csv(OUTPUT / "all_equity.csv", date_format="%Y-%m-%d")
    rank_metrics.to_csv(OUTPUT / "ranking_metrics.csv", index=False)
    comparison.to_csv(OUTPUT / "comparison.csv", index=False)
    save_json(OUTPUT / "bootstrap_and_selection.json", bootstrap_info)
    save_json(OUTPUT / "cost_metrics.json", cost_metrics)
    save_json(OUTPUT / "stress_metrics.json", stress)
    print(comparison[["candidate", "cagr", "information_ratio", "mean_rank_ic", "gate_all"]].to_string(index=False))
    print("完成：2026数据尚未读取。开发准入结果见 comparison.csv。")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    fixed_plan()
    if (OUTPUT / "comparison.csv").exists():
        print("已有完整结果；不重新训练或重新选择。")
        return
    path = OUTPUT / "all_development_scores.csv"
    predictions = (pd.read_csv(path, parse_dates=["Date", "entry_date", "exit_date"])
                   if path.exists() else run_batch())
    evaluate_batch(predictions)


if __name__ == "__main__":
    main()
