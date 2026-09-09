"""v6只新增H20 Ridge十个年度拟合；H60复用相同快照已有模型。"""
import hashlib
import json
import sys
import time
import warnings
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

import research_features as rf
import research_horizons as rh
from panel_config import ROOT
from robust_strategy import Policy
from dataclasses import asdict

OUT = ROOT / "data/experiments/robust_strategy_v6"
PRIOR = ROOT / "data/experiments/extended_history_v5"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def register():
    OUT.mkdir(exist_ok=True)
    plan = dict(design_sha256=sha(OUT/"DESIGN.md"),
                input_sha256={p.name:sha(p) for p in (PRIOR/"panel.csv", PRIOR/"all_scores.csv")},
                new_fit_count=10, years=list(range(2016,2026)), features=rf.EXTENDED_FEATURES,
                model=dict(kind="Ridge", alpha=100, solver="svd", horizon=20),
                score="50% cross-sectional percentile H20 + 50% H60; ties=average",
                policy=asdict(Policy()), cost_bps=[10,20], stop_extra_bps=10,
                selection="Diagnostic only; previous 0/98 stays; no live enablement; 2026 prices sealed")
    path = OUT/"plan.json"
    if path.exists():
        prior = json.loads(path.read_text(encoding="utf-8"))
        prior.pop("registered_at_utc")
        assert prior == plan, "计划或输入发生改变，不能混入已登记实验。"
    else:
        save(path, dict(registered_at_utc=datetime.now(timezone.utc).isoformat(), **plan))


def main():
    register()
    if (OUT/"training_complete.json").exists():
        print("v6 training already complete; saved models preserved.")
        return
    panel = pd.read_csv(PRIOR/"panel.csv", parse_dates=["Date","exit_5","exit_20","exit_60"], float_precision="round_trip")
    prior = pd.read_csv(PRIOR/"all_scores.csv", parse_dates=["Date"], float_precision="round_trip")
    records, blocks = [], []
    for year in range(2016,2026):
        train, valid, dev = rh.split_fold(panel, year, 20)
        path = OUT/f"{year}_ridge_h20.joblib"
        started = time.perf_counter()
        if path.exists():
            model = joblib.load(path)["model"]
            record = json.loads((OUT/f"{year}_fit.json").read_text(encoding="utf-8"))
            assert record["model_sha256"] == sha(path)
        else:
            model = make_pipeline(StandardScaler(), Ridge(alpha=100, solver="svd"))
            with warnings.catch_warnings(record=True) as caught, threadpool_limits(limits=4):
                warnings.simplefilter("always")
                model.fit(train[rf.EXTENDED_FEATURES], train.rank_20)
            joblib.dump(dict(model=model, features=rf.EXTENDED_FEATURES, horizon=20, research_only=True), path)
            record = dict(year=year, horizon=20, train_rows=len(train), validation_rows=len(valid),
                          development_rows=len(dev), train_last_exit=str(train.exit_20.max().date()),
                          validation_last_exit=str(valid.exit_20.max().date()),
                          seconds=time.perf_counter()-started, warnings=[str(w.message) for w in caught],
                          model_sha256=sha(path))
            save(OUT/f"{year}_fit.json", record)
        prediction = model.predict(dev[rf.EXTENDED_FEATURES])
        np.testing.assert_array_equal(prediction, joblib.load(path)["model"].predict(dev[rf.EXTENDED_FEATURES]))
        np.testing.assert_allclose(model[0].mean_, train[rf.EXTENDED_FEATURES].mean(), rtol=1e-12, atol=1e-12)
        old = prior.loc[prior.Date.dt.year.eq(year)].reset_index(drop=True)
        pd.testing.assert_frame_equal(dev[["Date","symbol"]],old[["Date","symbol"]])
        old_model_path = PRIOR/f"{year}_ridge_h60_price.joblib"
        old_record = pd.read_csv(PRIOR/"training_summary.csv").query("year == @year and id == 'ridge_h60_price'").iloc[0]
        assert sha(old_model_path) == old_record.model_sha256
        restored = joblib.load(old_model_path)["model"].predict(dev[rf.EXTENDED_FEATURES])
        np.testing.assert_array_equal(restored, old.ridge_h60_price.to_numpy())
        _, old_valid, _ = rh.split_fold(panel, year, 60)
        assert old_valid.exit_60.max() < dev.Date.min()
        output = old.copy()
        output["ridge_h20_price"] = prediction
        for h in (20,60):
            output[f"percentile_{h}"] = output.groupby("Date")[f"ridge_h{h}_price"].rank(method="average", pct=True)
        output["ensemble"] = (output.percentile_20+output.percentile_60)/2
        output["momentum"] = (dev.groupby("Date").ret_20d.rank(pct=True)+dev.groupby("Date").ret_60d.rank(pct=True))/2
        output.to_csv(OUT/f"{year}_scores.csv", index=False, date_format="%Y-%m-%d")
        valid_output = valid[["Date","symbol","y_20","rank_20"]].copy()
        valid_output["prediction"] = model.predict(valid[rf.EXTENDED_FEATURES])
        valid_output.to_csv(OUT/f"{year}_validation.csv", index=False, date_format="%Y-%m-%d")
        record["old_h60_exact_reproduced"] = True
        records.append(record); blocks.append(output)
        pd.DataFrame(records).to_csv(OUT/"training_summary.csv", index=False)
        print(f"H20 fit/check {year}: train={len(train)}, {record['seconds']:.2f}s, H60 exact", flush=True)
    result = pd.concat(blocks, ignore_index=True)
    result.to_csv(OUT/"all_scores.csv", index=False, date_format="%Y-%m-%d")
    reread = pd.read_csv(OUT/"all_scores.csv", float_precision="round_trip")
    np.testing.assert_array_equal(reread.ensemble, result.ensemble)
    save(OUT/"training_complete.json", dict(completed_at_utc=datetime.now(timezone.utc).isoformat(),
         new_fits=10, existing_h60_reused_and_reproduced=10, rows=len(result), dates=result.Date.nunique(),
         warning_count=sum(len(r["warnings"]) for r in records), input_plan_verified=True,
         prices_2026_accessed=False, orders_sent=0))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
