"""登记后补做 Huber 阈值尺度对照；保留原30候选，最终32候选联合筛选。"""

import hashlib
import importlib
import json
import sys
import time
from datetime import datetime, timezone

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd

batch = importlib.import_module("15_run_research_batch")
ORIGINAL = batch.OUTPUT
OUTPUT = ORIGINAL / "huber_scale_followup"
EXTRAS = [
    {"id": "f31_huber_1pp", "kind": "lgb", "features": "extended", "target": "return", "objective": "huber", "huber_alpha": 0.01},
    {"id": "f32_huber_3pp", "kind": "lgb", "features": "extended", "target": "return", "objective": "huber", "huber_alpha": 0.03},
]


def register_plan():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    plan = {"reason": "Default Huber alpha=.9 equals a 90pp residual threshold; audits found identical L2 predictions. Two explicitly scaled followups, preserving original results.",
            "candidates": EXTRAS, "original_plan_sha256": hashlib.sha256((ORIGINAL / "plan.json").read_bytes()).hexdigest(),
            "parameters": batch.LGB_PARAMS, "years": list(batch.YEARS),
            "evaluation": "Combine all original30 and extra2 for the same cost assumptions, gates and joint max-t bootstrap before any 2026 access.",
            "code_sha256": hashlib.sha256(__import__("pathlib").Path(__file__).read_bytes()).hexdigest()}
    path = OUTPUT / "plan.json"
    if path.exists():
        old = json.loads(path.read_text(encoding="utf-8"))
        old.pop("registered_at_utc")
        assert old == plan
    else:
        batch.save_json(path, {**plan, "registered_at_utc": datetime.now(timezone.utc).isoformat()})


def train_followups():
    panel = batch.load_panel()
    records, blocks = [], []
    for year in batch.YEARS:
        folder = OUTPUT / str(year)
        folder.mkdir(exist_ok=True)
        train = panel.loc[panel.Date.lt(f"{year-1}-01-01") & panel.exit_date.lt(f"{year-1}-01-01")].copy().reset_index(drop=True)
        validation = panel.loc[panel.Date.ge(f"{year-1}-01-01") & panel.Date.lt(f"{year}-01-01") & panel.exit_date.lt(f"{year}-01-01")].copy().reset_index(drop=True)
        development = panel.loc[panel.Date.ge(f"{year}-01-01") & panel.Date.lt(f"{year+1}-01-01")].copy().reset_index(drop=True)
        result = development[["Date", "symbol"]].copy()
        for candidate in EXTRAS:
            if datetime.now(timezone.utc) >= batch.TRAINING_DEADLINE:
                raise TimeoutError("补充实验到达训练时间上限。")
            columns = batch.FEATURE_SETS[candidate["features"]]
            model = lgb.LGBMRegressor(**batch.LGB_PARAMS, objective="huber", alpha=candidate["huber_alpha"])
            started = time.perf_counter()
            model.fit(train[columns], train[batch.rf.TARGET], eval_X=validation[columns], eval_y=validation[batch.rf.TARGET],
                      eval_names=["validation"], eval_metric=batch.ranking.make_ranking_metric(validation),
                      callbacks=[lgb.early_stopping(50, first_metric_only=True, verbose=False)])
            curve = model.evals_result_["validation"]["daily_ndcg5"]
            assert model.best_iteration_ == int(np.argmax(curve)) + 1
            text = model.booster_.model_to_string()
            (folder / f"{candidate['id']}_model.txt").write_text(text, encoding="utf-8")
            restored = lgb.Booster(model_str=text)
            validation_scores = model.predict(validation[columns])
            np.testing.assert_allclose(restored.predict(validation[columns], num_threads=4), validation_scores, atol=1e-14)
            joblib.dump({"model": model, "features": columns, "candidate": candidate}, folder / f"{candidate['id']}.joblib")
            batch.save_json(folder / f"{candidate['id']}_curve.json", model.evals_result_)
            record = {"candidate": candidate["id"], "year": year, "status": "trained", "kind": "huber_followup",
                      "feature_group": "extended", "train_rows": len(train), "validation_rows": len(validation),
                      "train_last_exit": str(train.exit_date.max().date()), "validation_last_exit": str(validation.exit_date.max().date()),
                      "huber_alpha": candidate["huber_alpha"], "best_iteration": int(model.best_iteration_),
                      "attempted_iterations": len(curve), "validation_ndcg5": float(max(curve)), "seconds": time.perf_counter()-started}
            records.append(record)
            result[candidate["id"]] = model.predict(development[columns])
            validation[["Date", "symbol"]].assign(score=validation_scores).to_csv(folder / f"{candidate['id']}_validation_scores.csv", index=False)
            print(f"补充 {year} {candidate['id']}: best={model.best_iteration_}, valNDCG={max(curve):.4f}", flush=True)
        blocks.append(result)
        pd.DataFrame(records).to_csv(OUTPUT / "training_summary.csv", index=False)
    extra_scores = pd.concat(blocks, ignore_index=True)
    extra_scores.to_csv(OUTPUT / "extra_scores.csv", index=False, date_format="%Y-%m-%d")
    return extra_scores


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    register_plan()
    if "--register-only" in sys.argv:
        print("补充实验已登记，未拟合或评分。")
        return
    if (OUTPUT / "comparison.csv").exists():
        print("补充实验已有完整结果。")
        return
    path = OUTPUT / "extra_scores.csv"
    extra = pd.read_csv(path, parse_dates=["Date"]) if path.exists() else train_followups()
    original = pd.read_csv(ORIGINAL / "all_development_scores.csv", parse_dates=["Date", "entry_date", "exit_date"])
    combined = original.merge(extra, on=["Date", "symbol"], how="left", validate="one_to_one")
    assert combined[[item["id"] for item in EXTRAS]].notna().all().all()
    combined.to_csv(OUTPUT / "all_development_scores.csv", index=False, date_format="%Y-%m-%d")
    # 只修改当前进程的输出目标，不覆盖原批次任何结果。
    batch.OUTPUT = OUTPUT
    batch.CANDIDATES = batch.CANDIDATES + EXTRAS
    batch.evaluate_batch(combined)


if __name__ == "__main__":
    main()
