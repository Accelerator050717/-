"""复核扩展历史的20份模型，并补存固定参数模型的验证评分。"""
import hashlib
import importlib
import json
import sys

import joblib
import numpy as np
import pandas as pd

import research_horizons as rh
import research_features as rf

study = importlib.import_module("35_extend_historical_diagnostic")
v3 = importlib.import_module("28_train_multihorizon")
OUT = study.OUT


def main():
    ready = json.loads((OUT/"data_ready.json").read_text(encoding="utf-8"))
    assert hashlib.sha256((OUT/"panel.csv").read_bytes()).hexdigest()==ready["panel_sha256"]
    panel = pd.read_csv(OUT/"panel.csv",parse_dates=["Date","entry_date","exit_date","exit_5","exit_20","exit_60"],float_precision="round_trip")
    records = pd.read_csv(OUT/"training_summary.csv",float_precision="round_trip")
    folder = OUT/"validation"; folder.mkdir(exist_ok=True)
    checks,metrics = [],[]
    for record in records.itertuples():
        train,valid,dev = rh.split_fold(panel,record.year,record.horizon)
        path = OUT/f"{record.year}_{record.id}.joblib"
        assert hashlib.sha256(path.read_bytes()).hexdigest()==record.model_sha256
        payload = joblib.load(path)
        assert payload["mode"]=="diagnostic_only" and payload["features"]==rf.EXTENDED_FEATURES
        model = payload["model"]
        assert model[0].n_samples_seen_==len(train)==record.train_rows
        assert len(valid)==record.validation_rows
        assert str(train[f"exit_{record.horizon}"].max().date())==record.train_last_exit
        assert str(valid[f"exit_{record.horizon}"].max().date())==record.validation_last_exit
        np.testing.assert_allclose(model[0].mean_,train[rf.EXTENDED_FEATURES].mean(axis=0),rtol=0,atol=1e-10)
        np.testing.assert_allclose(model[0].var_,train[rf.EXTENDED_FEATURES].var(axis=0,ddof=0),rtol=1e-12,atol=1e-10)
        saved = pd.read_csv(OUT/f"{record.year}_scores.csv",parse_dates=["Date"],float_precision="round_trip")
        pd.testing.assert_frame_equal(saved[["Date","symbol"]],dev[["Date","symbol"]])
        np.testing.assert_allclose(model.predict(dev[rf.EXTENDED_FEATURES]),saved[record.id],rtol=0,atol=1e-12)
        val_score = model.predict(valid[rf.EXTENDED_FEATURES])
        view = v3.native_rows(valid,record.horizon)
        values = v3.old.score_ranking(view,val_score,record.id)
        view["score"] = val_score
        view.to_csv(folder/f"{record.year}_{record.id}.csv",index=False,date_format="%Y-%m-%d")
        last = model[-1]
        n_iter = getattr(last,"n_iter_",None)
        metrics.append({**values,"year":record.year,"horizon":record.horizon,"validation_rows":len(valid),
                        "n_iter":int(n_iter) if n_iter is not None else None,"used_for_model_selection":False})
        checks.append({"model":record.id,"year":record.year,"status":"passed"})
    assert len(checks)==20
    pd.DataFrame(metrics).to_csv(OUT/"validation_metrics.csv",index=False)
    v3.save_json(OUT/"CHECKS.json",{"status":"passed","models_checked":len(checks),"checks":checks,
                 "validation_scores_saved":True,"validation_metric_timing":"Calculated after fixed-parameter fits; never used for selecting parameters or changing model.",
                 "prediction_tolerance":1e-12,"source_panel_hash_verified":True})
    print("20/20 saved models, splits, train-only scalers, restored development and validation predictions checked.")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
