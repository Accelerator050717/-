"""6 年滚动开发比较：年度重训、两档树容量，与固定旧模型比较。"""

import hashlib
import importlib
import json
import sys
import time
from datetime import datetime, timezone
from importlib.metadata import version

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import ndcg_score

from panel_config import PANEL_PATH, ROOT, SYMBOLS

ranking = importlib.import_module("12_train_ranker")
X_COLUMNS, TARGET = ranking.X_COLUMNS, ranking.TARGET
OUTPUT = ROOT / "data" / "experiments" / "walkforward_ranker_v1"
YEARS = tuple(range(2020, 2026))
CAPACITIES = {"small": 31, "large": 127}
CANDIDATES = ("constant", "momentum_20d", "small", "large")  # 同分按此顺序选择
PARAMS = {**ranking.RANKER_PARAMS, "n_estimators": 3000}
PATIENCE = 100
TOP_K = 5


def save_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")


def fixed_plan():
    plan = {
        "hypothesis": "Compare annual expanding-window retraining and two capacities against a frozen old ranker.",
        "years": list(YEARS), "features": X_COLUMNS, "symbols": list(SYMBOLS),
        "source_target": TARGET, "grades": "Within-date five ordinal levels using average ranks; same as step 12.",
        "panel_sha256": hashlib.sha256(PANEL_PATH.read_bytes()).hexdigest(),
        "capacities": CAPACITIES, "common_parameters": PARAMS, "patience": PATIENCE,
        "candidate_order": list(CANDIDATES), "top_k": TOP_K,
        "fold_rule": "For year Y: train 2015..Y-2, validate Y-1, evaluate Y; exit date strictly before each boundary.",
        "selection": "Highest validation NDCG@5 among four candidates, stable tie break; no validation refit.",
        "static_reference": "Small model of the 2020 fold, trained through 2018 and stopped on 2019; reused unchanged.",
        "aggregation": "Pool daily development metrics, not unweighted annual averages; IC excludes undefined dates.",
        "status": "Retrospective development comparison on a previously studied survivor universe; no unseen-test claim. No 2026 data.",
    }
    path = OUTPUT / "plan.json"
    if path.exists():
        old = json.loads(path.read_text(encoding="utf-8"))
        old.pop("created_at_utc")
        if old != plan:
            raise ValueError("配置或数据变化；请另建实验目录，不能覆盖本轮已见结果。")
    else:
        save_json(path, {**plan, "created_at_utc": datetime.now(timezone.utc).isoformat()})


def load_panel():
    panel = pd.read_csv(PANEL_PATH, parse_dates=["Date", "entry_date", "exit_date"])
    panel = panel.sort_values(["Date", "symbol"]).reset_index(drop=True)
    panel["ready"] = np.isfinite(panel[X_COLUMNS + [TARGET]].to_numpy()).all(axis=1)
    rank = panel.groupby("Date")[TARGET].rank(method="average")
    count = panel.groupby("Date")[TARGET].transform("count")
    panel["relevance"] = np.floor((rank - 1) * 5 / count).astype("Int64")
    return panel


def make_fold(panel, year, folder):
    periods = (("train", "2015-01-01", f"{year - 1}-01-01"),
               ("validation", f"{year - 1}-01-01", f"{year}-01-01"),
               ("development", f"{year}-01-01", f"{year + 1}-01-01"))
    assignment = pd.Series("unused_future", index=panel.index)
    assignment.loc[~panel["ready"]] = "incomplete"
    frames, summaries = {}, []
    for split, start, end in periods:
        observed = panel["ready"] & panel["Date"].ge(start) & panel["Date"].lt(end)
        assignment.loc[observed] = "purged_before_" + end
        mask = observed & panel["exit_date"].lt(end)
        assignment.loc[mask] = split
        rows = panel.loc[mask].copy().reset_index(drop=True)
        rows["relevance"] = rows["relevance"].astype(int)
        groups = ranking.check_groups(rows)
        assert rows["exit_date"].max() < pd.Timestamp(end)
        frames[split] = rows
        summaries.append({"year": year, "split": split, "rows": len(rows),
                          "dates": len(groups), "first_date": str(rows["Date"].min().date()),
                          "last_date": str(rows["Date"].max().date()),
                          "last_exit": str(rows["exit_date"].max().date())})
    assert frames["train"]["exit_date"].max() < frames["validation"]["Date"].min()
    assert frames["validation"]["exit_date"].max() < frames["development"]["Date"].min()
    mapping = panel[["Date", "entry_date", "exit_date"]].assign(assignment=assignment)
    assert mapping.groupby("Date")["assignment"].nunique().eq(1).all()
    mapping.drop_duplicates("Date").to_csv(folder / "date_assignments.csv", index=False, date_format="%Y-%m-%d")
    save_json(folder / "sample_summary.json", summaries)
    return frames, summaries


def metrics_for(rows, scores):
    grades = rows["relevance"].to_numpy().reshape(-1, len(SYMBOLS))
    prediction = np.asarray(scores).reshape(grades.shape)
    ndcg = float(ndcg_score(grades, prediction, k=TOP_K, ignore_ties=False))
    daily = ranking.previous.daily_rank_ic(rows.rename(columns={TARGET: "y_true"}), np.asarray(scores))
    mean_ic = daily["rank_ic"].mean()
    return {"ndcg5": ndcg, "rank_ic": float(mean_ic) if np.isfinite(mean_ic) else None,
            "valid_ic_dates": int(daily["rank_ic"].notna().sum())}


def train_candidate(train, validation, name, folder):
    params = {**PARAMS, "num_leaves": CAPACITIES[name]}
    model = lgb.LGBMRanker(**params)
    started = time.perf_counter()
    model.fit(
        train[X_COLUMNS], train["relevance"], group=ranking.check_groups(train),
        eval_X=validation[X_COLUMNS], eval_y=validation["relevance"],
        eval_group=[ranking.check_groups(validation)], eval_names=["validation"], eval_at=[TOP_K],
        eval_metric=ranking.make_ranking_metric(validation),
        callbacks=[lgb.early_stopping(PATIENCE, first_metric_only=True, verbose=False),
                   lgb.log_evaluation(period=500)],
    )
    curve = model.evals_result_["validation"]["daily_ndcg5"]
    assert list(model.evals_result_["validation"]) == ["daily_ndcg5"]
    assert model.best_iteration_ == int(np.argmax(curve)) + 1
    model_text = model.booster_.model_to_string(num_iteration=model.best_iteration_)
    path = folder / f"{name}_model.txt"
    path.write_text(model_text, encoding="utf-8")
    restored = lgb.Booster(model_str=model_text)
    validation_scores = model.predict(validation[X_COLUMNS])
    np.testing.assert_allclose(restored.predict(validation[X_COLUMNS], num_threads=4), validation_scores,
                               atol=1e-14, rtol=1e-12)
    train_metrics = metrics_for(train, model.predict(train[X_COLUMNS]))
    details = {"name": name, "max_leaves": CAPACITIES[name],
               "best_iteration": int(model.best_iteration_), "attempted_iterations": len(curve),
               "fit_and_reload_seconds": time.perf_counter() - started,
               "train_ndcg5": train_metrics["ndcg5"], "train_rank_ic": train_metrics["rank_ic"],
               "validation_ndcg5": float(max(curve)),
               "model_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    save_json(folder / f"{name}_learning_curve.json", model.evals_result_)
    save_json(folder / f"{name}_details.json", details)
    print(f"  {name}: 保留 {model.best_iteration_}/{len(curve)} 轮，训练NDCG={train_metrics['ndcg5']:.4f}，验证={max(curve):.4f}", flush=True)
    return model, validation_scores, details


def prediction_frame(rows, scores, year):
    frame = rows[["Date", "symbol", "entry_date", "exit_date", TARGET, "relevance"]].copy()
    frame = frame.rename(columns={TARGET: "y_true"})
    frame["year"] = year
    for name, values in scores.items():
        frame[f"score_{name}"] = np.asarray(values)
    return frame


def evaluate_development(rows, scores, year):
    grades = rows["relevance"].to_numpy().reshape(-1, len(SYMBOLS))
    records = []
    for name, values in scores.items():
        matrix = np.asarray(values).reshape(grades.shape)
        daily = ranking.previous.daily_rank_ic(rows.rename(columns={TARGET: "y_true"}), np.asarray(values))
        daily["ndcg5"] = [ndcg_score(g[None, :], p[None, :], k=TOP_K, ignore_ties=False)
                          for g, p in zip(grades, matrix)]
        daily["year"], daily["method"] = year, name
        records.append(daily.reset_index())
    return pd.concat(records, ignore_index=True)


def aggregate(daily, by):
    result = daily.groupby(by, sort=False).agg(
        dates=("Date", "size"), ndcg5=("ndcg5", "mean"), rank_ic=("rank_ic", "mean"),
        valid_ic_dates=("rank_ic", "count"), positive_ic_dates=("rank_ic", lambda values: int(values.gt(0).sum())),
    ).reset_index()
    return result


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    fixed_plan()
    if (OUTPUT / "overall_metrics.csv").exists():
        print("复用本轮已保存的开发比较，没有重新训练。")
        print(pd.read_csv(OUTPUT / "overall_metrics.csv").to_string(index=False))
        return
    panel = load_panel()
    all_daily, all_predictions, all_validation, all_validation_predictions = [], [], [], []
    all_samples, all_details, selections = [], [], []
    static_model, static_hash = None, None
    for year in YEARS:
        folder = OUTPUT / str(year)
        folder.mkdir(exist_ok=True)
        frames, sample_summary = make_fold(panel, year, folder)
        train, validation, development = (frames[name] for name in ("train", "validation", "development"))
        all_samples.extend(sample_summary)
        print(f"{year} 折：训练 {len(train):,}，验证 {len(validation):,}，开发评估 {len(development):,}", flush=True)
        models = {}
        validation_scores = {"constant": np.zeros(len(validation)), "momentum_20d": validation["ret_20d"].to_numpy()}
        for name in CAPACITIES:
            model, scores, details = train_candidate(train, validation, name, folder)
            models[name], validation_scores[name] = model, scores
            all_details.append({"year": year, **details})
        if static_model is None:
            # 只使用第一折的模型，不能调用此前已经学过2020年之后数据的模型。
            static_model = models["small"]
            static_hash = hashlib.sha256((folder / "small_model.txt").read_bytes()).hexdigest()
        val_metrics = [{"year": year, "method": name, **metrics_for(validation, validation_scores[name])}
                       for name in CANDIDATES]
        selected = max(val_metrics, key=lambda record: record["ndcg5"])["method"]
        assert hashlib.sha256((OUTPUT / str(YEARS[0]) / "small_model.txt").read_bytes()).hexdigest() == static_hash
        selection = {"year": year, "selected_method": selected, "validation_metrics": val_metrics,
                     "frozen_before_development_at_utc": datetime.now(timezone.utc).isoformat(),
                     "static_model_sha256": static_hash, "train_last_exit": sample_summary[0]["last_exit"],
                     "validation_last_exit": sample_summary[1]["last_exit"]}
        save_json(folder / "frozen_selection.json", selection)
        selections.append(selection)
        all_validation.extend(val_metrics)
        all_validation_predictions.append(prediction_frame(validation, validation_scores, year))

        # 选择已冻结，下面才对当前评估年生成预测和统计。
        development_scores = {"constant": np.zeros(len(development)),
                              "momentum_20d": development["ret_20d"].to_numpy(),
                              "static_small": static_model.predict(development[X_COLUMNS]),
                              **{name: model.predict(development[X_COLUMNS]) for name, model in models.items()}}
        if year == YEARS[0]:
            np.testing.assert_array_equal(development_scores["static_small"], development_scores["small"])
        development_scores["selected"] = development_scores[selected].copy()
        daily = evaluate_development(development, development_scores, year)
        predictions = prediction_frame(development, development_scores, year)
        predictions.to_csv(folder / "development_predictions.csv", index=False, date_format="%Y-%m-%d")
        daily.to_csv(folder / "daily_metrics.csv", index=False, date_format="%Y-%m-%d")
        metrics = aggregate(daily, ["year", "method"])
        metrics.to_csv(folder / "development_metrics.csv", index=False)
        print(f"  验证选择 {selected}；开发NDCG={metrics.loc[metrics.method.eq('selected'), 'ndcg5'].iloc[0]:.4f}", flush=True)
        all_daily.append(daily)
        all_predictions.append(predictions)

    daily = pd.concat(all_daily, ignore_index=True)
    annual = aggregate(daily, ["year", "method"])
    overall = aggregate(daily, ["method"])
    for name, frame in (("daily_metrics.csv", daily), ("annual_metrics.csv", annual),
                        ("validation_metrics.csv", pd.DataFrame(all_validation)),
                        ("training_details.csv", pd.DataFrame(all_details)),
                        ("sample_summary.csv", pd.DataFrame(all_samples)),
                        ("development_predictions.csv", pd.concat(all_predictions, ignore_index=True)),
                        ("validation_predictions.csv", pd.concat(all_validation_predictions, ignore_index=True))):
        frame.to_csv(OUTPUT / name, index=False, date_format="%Y-%m-%d")
    save_json(OUTPUT / "run_summary.json", {"models_trained": len(all_details), "selections": selections,
              "static_model_sha256": static_hash,
              "versions": {name: version(name) for name in ("lightgbm", "scikit-learn", "pandas", "numpy")}})
    overall.to_csv(OUTPUT / "overall_metrics.csv", index=False)
    print("\n按全部开发评估日汇总（不是策略收益）：")
    print(overall.to_string(index=False, float_format=lambda value: f"{value:.6f}"))
    print(f"12次固定训练完成，保存到 {OUTPUT}；2026未使用。")


if __name__ == "__main__":
    main()
