"""固定12个策略对照：3模型×有无SEC特征×持有5/10股；不连接券商。"""

import hashlib
import importlib
import json
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import ElasticNet, Ridge
from sklearn.metrics import ndcg_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

import fundamental_features as ff
import research_features as rf
from panel_config import ROOT, SYMBOLS
from research_backtest import run_backtest
from research_evaluation import evaluate_candidates

old_batch = importlib.import_module("15_run_research_batch")
OUTPUT = ROOT / "data/experiments/automation_research_v2"
OLD = ROOT / "data/experiments/auto_research_45m_v1"
YEARS = tuple(range(2020, 2026))
TRAINING_DEADLINE = datetime.fromisoformat("2026-09-09T05:17:19+00:00")
BASE_MODELS = [
    ("ridge_base", "ridge", "base", "m12_ridge_rank_base"),
    ("ridge_extended", "ridge", "extended", "m13_ridge_rank_extended"),
    ("elastic_extended", "elastic", "extended", "m16_elastic_rank"),
]
MODELS = [dict(id=f"v2_{label}_{'fund' if with_fund else 'price'}", kind=kind,
               feature_group=group, with_fundamentals=with_fund, control=control)
          for label, kind, group, control in BASE_MODELS for with_fund in (False, True)]
STRATEGIES = [dict(id=f"{model['id']}_top{top_k}", model=model["id"], top_k=top_k)
              for model in MODELS for top_k in (5, 10)]


def save_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def features_for(config):
    features = list(rf.BASE_FEATURES if config["feature_group"] == "base" else rf.EXTENDED_FEATURES)
    return features + (list(ff.FUND_FEATURES) if config["with_fundamentals"] else [])


def load_data():
    # 保持旧控制训练的CSV解析口径；评分的保存/重读一律round_trip。
    panel = old_batch.load_panel()
    fund = pd.read_csv(ff.FUNDAMENTAL_PANEL_PATH, parse_dates=["Date"], float_precision="round_trip")
    if fund.duplicated(["Date", "symbol"]).any():
        raise ValueError("财报面板Date/symbol重复。")
    panel = panel.merge(fund[["Date", "symbol", *ff.FUND_FEATURES]], on=["Date", "symbol"],
                        how="left", validate="one_to_one", indicator=True)
    if not panel._merge.eq("both").all():
        raise ValueError("财报面板缺少键；不删除缺记录股票。")
    panel = panel.drop(columns="_merge").sort_values(["Date", "symbol"]).reset_index(drop=True)
    if np.isinf(panel[ff.FUND_FEATURES].to_numpy(dtype=float)).any():
        raise ValueError("财报特征含无限值。")
    if len(panel) != 75240:
        raise ValueError("共同样本与前次控制不一致。")
    old_batch.ranking.check_groups(panel)
    return panel


def register_plan():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    plan = {
        "models": MODELS, "strategies": STRATEGIES, "development_years": list(YEARS),
        "fundamental_columns": list(ff.FUND_FEATURES),
        "price_panel_sha256": hashlib.sha256(rf.RESEARCH_PANEL_PATH.read_bytes()).hexdigest(),
        "fundamental_panel_sha256": hashlib.sha256(ff.FUNDAMENTAL_PANEL_PATH.read_bytes()).hexdigest(),
        "target": "Same five-session next-open excess return, transformed into daily rank in [-0.5,0.5].",
        "split": "Train through Y-2, validate Y-1, develop Y. Train/validation require exits strictly before the next segment; development labels may cross calendar years within the saved 2015-2025 snapshot.",
        "ridge": {"alpha": 100, "solver": "svd"},
        "elastic": {"alpha": 0.001, "l1_ratio": 0.15, "max_iter": 2000, "selection": "random", "random_state": 42},
        "imputation": "Fundamental missing indicators come from source. Training-only median imputer, keep_empty_features=True, no extra indicators; scaler fit on train only.",
        "trading": {"top_k": [5, 10], "rebalance_sessions": 5, "entry": "next_open", "cost_bps": [10,20]},
        "evaluation": "Original32 plus new12 strategies jointly evaluated with unchanged gates and 20-session max-t bootstrap, 2000 draws, seed20260907.",
        "holdout": "This batch does not access 2026 market prices or promote any model to trading; any gate eligibility is reported for a separate frozen validation step.",
        "limitations": "Adaptive followup on already-studied years, survivor universe, current SEC snapshot filtered by filed date, adjusted-open research proxy.",
        "training_deadline_utc": TRAINING_DEADLINE.isoformat(),
    }
    path = OUTPUT / "plan.json"
    if path.exists():
        previous = json.loads(path.read_text(encoding="utf-8"))
        previous.pop("registered_at_utc")
        if previous != plan:
            raise ValueError("计划或数据改变，需要新的实验目录。")
    else:
        save_json(path, {**plan, "registered_at_utc": datetime.now(timezone.utc).isoformat()})


def fit_all(panel):
    records, blocks, control_checks = [], [], []
    for year in YEARS:
        folder = OUTPUT / str(year)
        folder.mkdir(exist_ok=True)
        train = panel.loc[panel.Date.lt(f"{year-1}-01-01") & panel.exit_date.lt(f"{year-1}-01-01")].copy().reset_index(drop=True)
        valid = panel.loc[panel.Date.ge(f"{year-1}-01-01") & panel.Date.lt(f"{year}-01-01") & panel.exit_date.lt(f"{year}-01-01")].copy().reset_index(drop=True)
        develop = panel.loc[panel.Date.ge(f"{year}-01-01") & panel.Date.lt(f"{year+1}-01-01")].copy().reset_index(drop=True)
        assert train.exit_date.max() < valid.Date.min() and valid.exit_date.max() < develop.Date.min()
        old_scores = pd.read_csv(OLD / str(year) / "development_scores.csv", float_precision="round_trip",
                                 parse_dates=["Date", "entry_date", "exit_date"])
        pd.testing.assert_frame_equal(develop[["Date", "symbol"]], old_scores[["Date", "symbol"]])
        dev_output = develop[["Date", "symbol", "entry_date", "exit_date", rf.TARGET, "relevance"]].copy()
        valid_output = valid[["Date", "symbol", rf.TARGET, "relevance"]].copy()
        for config in MODELS:
            if datetime.now(timezone.utc) >= TRAINING_DEADLINE:
                raise TimeoutError("达到训练预算；已完成记录保留，不继续拟合。")
            features = features_for(config)
            estimator = (Ridge(alpha=100, solver="svd") if config["kind"] == "ridge" else
                         ElasticNet(alpha=0.001, l1_ratio=0.15, max_iter=2000, selection="random", random_state=42))
            steps = [StandardScaler(), estimator]
            if config["with_fundamentals"]:
                steps.insert(0, SimpleImputer(strategy="median", keep_empty_features=True, add_indicator=False))
            model = make_pipeline(*steps)
            started = time.perf_counter()
            with warnings.catch_warnings(record=True) as caught, threadpool_limits(limits=4):
                warnings.simplefilter("always")
                model.fit(train[features], train.rank_target)
            seconds = time.perf_counter() - started
            val_score = model.predict(valid[features])
            dev_score = model.predict(develop[features])
            assert np.isfinite(val_score).all() and np.isfinite(dev_score).all()
            if not config["with_fundamentals"]:
                expected = old_scores[config["control"]].to_numpy()
                max_difference = float(np.max(np.abs(dev_score - expected)))
                np.testing.assert_allclose(dev_score, expected, rtol=0, atol=1e-12)
                control_checks.append({"model": config["id"], "year": year, "original": config["control"], "max_score_difference": max_difference})
            payload = {"model": model, "features": features, "candidate": config,
                       "mode": "research_only", "development_year": year,
                       "train_last_exit": str(train.exit_date.max().date()),
                       "validation_last_exit": str(valid.exit_date.max().date())}
            path = folder / f"{config['id']}.joblib"
            joblib.dump(payload, path)
            np.testing.assert_array_equal(joblib.load(path)["model"].predict(develop[features]), dev_score)
            ndcg = float(ndcg_score(valid.relevance.to_numpy().reshape(-1,30), val_score.reshape(-1,30), k=5, ignore_ties=False))
            last_step = model.steps[-1][1]
            n_iter = getattr(last_step, "n_iter_", None)
            record = {"model": config["id"], "year": year, "status": "trained", "control_reproduction": not config["with_fundamentals"],
                      "feature_count": len(features), "train_rows": len(train), "validation_rows": len(valid),
                      "development_rows": len(develop), "train_first": str(train.Date.min().date()),
                      "train_last_exit": str(train.exit_date.max().date()), "validation_last_exit": str(valid.exit_date.max().date()),
                      "validation_ndcg5": ndcg, "fit_seconds": seconds, "n_iter": int(n_iter) if n_iter is not None else None,
                      "warnings": list(dict.fromkeys(str(w.message) for w in caught)),
                      "model_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "artifact_path": path.as_posix()}
            records.append(record)
            with (OUTPUT / "training_log.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({**record, "utc": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False, allow_nan=False) + "\n")
            dev_output[config["id"]], valid_output[config["id"]] = dev_score, val_score
            print(f"{year} {config['id']}: {len(features)}列, valNDCG={ndcg:.4f}, fit={seconds:.2f}s", flush=True)
        dev_output.to_csv(folder / "development_scores.csv", index=False, date_format="%Y-%m-%d")
        valid_output.to_csv(folder / "validation_scores.csv", index=False, date_format="%Y-%m-%d")
        blocks.append(dev_output)
        pd.DataFrame(records).to_csv(OUTPUT / "training_summary.csv", index=False)
        save_json(OUTPUT / "control_score_checks.json", control_checks)
    result = pd.concat(blocks, ignore_index=True)
    result.to_csv(OUTPUT / "all_model_scores.csv", index=False, date_format="%Y-%m-%d")
    saved = pd.read_csv(OUTPUT / "all_model_scores.csv", float_precision="round_trip")
    names = [config["id"] for config in MODELS]
    np.testing.assert_array_equal(result[names].to_numpy(), saved[names].to_numpy())
    return result


def evaluate(scores):
    previous = OLD / "final_evaluation"
    costs = json.loads((previous / "cost_metrics.json").read_text(encoding="utf-8"))
    stress = json.loads((previous / "stress_metrics.json").read_text(encoding="utf-8"))
    equity = pd.read_csv(previous / "all_equity.csv", float_precision="round_trip", index_col="Date", parse_dates=["Date"])
    ranking = pd.read_csv(previous / "ranking_metrics.csv", float_precision="round_trip")
    raw, _ = rf.load_inputs()
    opens = pd.DataFrame({name: raw[name].Open * raw[name]["Adj Close"] / raw[name].Close for name in SYMBOLS})
    spy = raw["SPY"].Open * raw["SPY"]["Adj Close"] / raw["SPY"].Close
    folder = OUTPUT / "backtests"
    folder.mkdir(exist_ok=True)
    new_ranking, extra_metrics = [], []
    for model_config in MODELS:
        name = model_config["id"]
        values = scores.pivot(index="Date", columns="symbol", values=name).reindex(columns=SYMBOLS)
        model_ranking = old_batch.score_ranking(scores, scores[name].to_numpy(), name)
        for top_k in (5, 10):
            strategy = f"{name}_top{top_k}"
            result = run_backtest(values, opens, spy, top_k=top_k, cost_bps=10)
            stressed = run_backtest(values, opens, spy, top_k=top_k, cost_bps=20)
            assert result["daily_equity"].index.equals(equity.index)
            costs[strategy], stress[strategy] = result["metrics"], stressed["metrics"]
            equity[strategy] = result["daily_equity"].equity
            new_ranking.append({**model_ranking, "candidate": strategy})
            if not model_config["with_fundamentals"] and top_k == 5:
                old_metric = costs[model_config["control"]]
                for key in ("cagr", "max_drawdown", "total_return", "total_cost"):
                    np.testing.assert_allclose(result["metrics"][key], old_metric[key], rtol=0, atol=1e-12)
            daily = result["daily_equity"]
            pre_fee_nav = daily.equity + daily.cost
            annual_turnover = float((daily.traded_notional / pre_fee_nav).sum() /
                                    ((daily.index[-1] - daily.index[0]).days / 365.25))
            extra_metrics.append({"candidate": strategy, "model": name, "top_k": top_k,
                                  "with_fundamentals": model_config["with_fundamentals"],
                                  "annual_traded_fraction": annual_turnover})
            result["daily_equity"].to_csv(folder / f"{strategy}_daily.csv", date_format="%Y-%m-%d")
            result["periods"].to_csv(folder / f"{strategy}_periods.csv", index=False, date_format="%Y-%m-%d")
            result["trades"].to_csv(folder / f"{strategy}_trades.csv", index=False, date_format="%Y-%m-%d")
            save_json(folder / f"{strategy}_metrics.json", {"cost10": result["metrics"], "cost20": stressed["metrics"]})
            print(f"{strategy}: CAGR={costs[strategy]['cagr']:.2%}, MDD={costs[strategy]['max_drawdown']:.2%}, IC={model_ranking['mean_rank_ic']:.4f}", flush=True)
    all_ranks = pd.concat([ranking, pd.DataFrame(new_ranking)], ignore_index=True)
    comparison, boot = evaluate_candidates(equity, all_ranks, stress, costs)
    assert len(comparison) == 44 and boot["family_size"] == 44
    meta = pd.DataFrame(extra_metrics)
    new_comparison = comparison.merge(meta, on="candidate", how="inner", validate="one_to_one")
    new_comparison.to_csv(OUTPUT / "comparison_new12.csv", index=False)
    comparison.to_csv(OUTPUT / "comparison_all44.csv", index=False)
    all_ranks.to_csv(OUTPUT / "ranking_all44.csv", index=False)
    equity.to_csv(OUTPUT / "equity_all44.csv", date_format="%Y-%m-%d")
    save_json(OUTPUT / "cost_metrics_all44.json", costs)
    save_json(OUTPUT / "stress_metrics_all44.json", stress)
    save_json(OUTPUT / "bootstrap_all44.json", boot)
    save_json(OUTPUT / "completion.json", {
        "completed_at_utc": datetime.now(timezone.utc).isoformat(), "new_model_configurations": 3,
        "control_model_configurations_retrained": 3, "annual_fits": 36, "new_strategy_entries": 12,
        "joint_candidate_entries": 44, "gate_passes": int(comparison.gate_all.sum()),
        "2026_market_prices_accessed": False, "automatic_model_promotion": False,
        "source_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    })
    print(new_comparison[["candidate", "cagr", "mean_rank_ic", "gate_all"]].to_string(index=False), flush=True)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    register_plan()
    if "--register-only" in sys.argv:
        print("研究计划已登记，未拟合或评价。")
        return
    if (OUTPUT / "completion.json").exists():
        print("已有完整结果，不重复训练或覆盖。")
        return
    path = OUTPUT / "all_model_scores.csv"
    if path.exists():
        scores = pd.read_csv(path, float_precision="round_trip", parse_dates=["Date", "entry_date", "exit_date"])
    else:
        scores = fit_all(load_data())
    evaluate(scores)


if __name__ == "__main__":
    main()
