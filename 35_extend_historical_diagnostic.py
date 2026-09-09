"""扩展更早历史的固定诊断：两模型×十年度，不开启2026或替代原准入结果。"""
import hashlib
import importlib
import json
import sys
import time
import warnings
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd
import pandas_market_calendars as mcal
from sklearn.linear_model import Ridge, ElasticNet
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

import research_features as rf
import research_horizons as rh
from research_backtest import run_backtest
from research_evaluation import _returns_from_initial_cash, _annual_returns
from panel_config import ROOT, SYMBOLS, HISTORY_PARAMS

v3 = importlib.import_module("28_train_multihorizon")
risk = importlib.import_module("34_research_risk_controls")
download = importlib.import_module("09_download_panel")
OUT = ROOT/"data/experiments/extended_history_v5"
RAW = ROOT/"data/raw/extended_2012_2025"
PARAMS = {**HISTORY_PARAMS,"start":"2012-01-01"}
CONFIGS = [{"id":"ridge_h60_price","kind":"ridge","horizon":60},
           {"id":"elastic_h5_price","kind":"elastic","horizon":5}]


def register():
    OUT.mkdir(parents=True,exist_ok=True)
    plan = {"download_parameters":PARAMS,"symbols":list(SYMBOLS),"context":list(rf.CONTEXT_SYMBOLS),
            "common_start":"Latest first available stock/ETF session; discard only leading pre-coverage dates, never interior missing prices. Keep30 stock cohort.",
            "models":CONFIGS,"features":rf.EXTENDED_FEATURES,"parameters":{"ridge":v3.RIDGE_PARAMS,"elastic":v3.ELASTIC_PARAMS},
            "years":list(range(2016,2026)),"split":"Expanding train through Y-2, validate Y-1, developY; ownH exit purged strictly before next segment. No parameter selection on validation.",
            "strategies":"Each model top5 with full exposure and fixed vol15; rebalance5, costs10/20; matched EW risk baselines and full SPY.",
            "selection":"Diagnostic only on expanded years; no new champion selection or easier confidence threshold, original all98 gate remains governing and2026 sealed.",
            "point_in_time_limits":"2016-2019 data had been used to train previous experiments; extended walk-forward is not pristine new holdout. Current survivor cohort remains.",
            "snapshot_policy":"New continuous2012-2025 snapshot, do not splice adjusted prices across vintages; preserve original cache and report overlap differences.",
            "training_deadline_utc":v3.TRAINING_DEADLINE.isoformat()}
    path = OUT/"plan.json"
    if path.exists():
        old = json.loads(path.read_text(encoding="utf-8")); old.pop("registered_at_utc")
        assert old==plan
    else:
        v3.save_json(path,{**plan,"registered_at_utc":datetime.now(timezone.utc).isoformat()})


def prepare():
    RAW.mkdir(exist_ok=True)
    download.RAW_DIR,download.HISTORY_PARAMS = RAW,PARAMS
    frames = {}
    names = ["SPY",*SYMBOLS,*rf.CONTEXT_SYMBOLS]
    for i,name in enumerate(names,1):
        if datetime.now(timezone.utc)>=v3.TRAINING_DEADLINE:
            raise TimeoutError("到达本轮固定截止时间，不再下载或训练。")
        download.load_prices(name)
        # 首次下载和缓存重跑都从同一无损CSV读取，避免解析差异影响并列排序。
        frames[name] = pd.read_csv(RAW/f"{name}.csv",index_col="Date",parse_dates=["Date"],float_precision="round_trip")
        print(f"Download/cache {i}/{len(names)} {name}: {len(frames[name])} rows, first={frames[name].index[0].date()}",flush=True)
    common_start = max(frame.index.min() for frame in frames.values())
    expected = mcal.get_calendar("NYSE").schedule(start_date=common_start,end_date="2025-12-31").index
    checks,overlap = [],[]
    old_raw,old_context = rf.load_inputs()
    old_frames = {**old_raw,**old_context}
    for name,frame in frames.items():
        retained = frame.loc[frame.index>=common_start].copy()
        check = download.inspect_prices(name,retained,expected)
        checks.append(check)
        if not check["passed"]:
            v3.save_json(OUT/"download_checks.json",checks)
            raise ValueError(f"{name} 完整共同日历检查失败，不补价格。")
        frames[name] = retained
        prior = old_frames[name]
        dates = retained.index.intersection(prior.index)
        relative = retained.loc[dates,"Adj Close"]/prior.loc[dates,"Adj Close"]
        old_returns = prior.loc[dates,"Adj Close"].pct_change(fill_method=None)
        new_returns = retained.loc[dates,"Adj Close"].pct_change(fill_method=None)
        overlap.append({"symbol":name,"overlap_dates":len(dates),"adjusted_level_ratio_min":float(relative.min()),
                        "adjusted_level_ratio_max":float(relative.max()),"max_abs_daily_return_difference":float((new_returns-old_returns).abs().max())})
    v3.save_json(OUT/"download_checks.json",checks)
    pd.DataFrame(overlap).to_csv(OUT/"snapshot_overlap.csv",index=False)
    raw = {name:frames[name] for name in [*SYMBOLS,"SPY"]}
    context = {name:frames[name] for name in rf.CONTEXT_SYMBOLS}
    panel = rf.compute_features(raw,context)
    opened = pd.DataFrame({name:raw[name].Open*raw[name]["Adj Close"]/raw[name].Close for name in SYMBOLS})
    spy = raw["SPY"].Open*raw["SPY"]["Adj Close"]/raw["SPY"].Close
    targets = rh.build_targets(opened,spy)
    panel = panel.merge(targets,on=["Date","symbol"],validate="one_to_one")
    panel = panel.loc[panel.features_ready & panel.label_ready].copy().reset_index(drop=True)
    for h in (5,20,60):
        ranked = panel.groupby("Date")[f"y_{h}"].rank(method="average")
        count = panel.groupby("Date")[f"y_{h}"].transform("count")
        assert count.isin([0,30]).all()
        panel[f"rank_{h}"] = (ranked-1)/(count-1)-.5
        panel[f"grade_{h}"] = np.floor((ranked-1)*5/count.replace(0,np.nan))
    panel["relevance"] = panel.grade_5.astype(int)
    # 特征前缀核对使用仅截至2019年末的物理价格输入。
    cutoff = pd.Timestamp("2019-12-31")
    prefix = rf.compute_features({k:v.loc[:cutoff] for k,v in raw.items()},
                                 {k:v.loc[:cutoff] for k,v in context.items()})
    full = panel.loc[panel.Date.le(cutoff),["Date","symbol",*rf.EXTENDED_FEATURES]].reset_index(drop=True)
    prior_features = prefix.merge(full[["Date","symbol"]],on=["Date","symbol"],validate="one_to_one")
    pd.testing.assert_frame_equal(full,prior_features[full.columns].reset_index(drop=True),check_exact=True)
    panel.to_csv(OUT/"panel.csv",index=False,date_format="%Y-%m-%d")
    opened.to_csv(OUT/"adjusted_opens.csv",date_format="%Y-%m-%d")
    spy.to_frame("SPY").to_csv(OUT/"spy_open.csv",date_format="%Y-%m-%d")
    risk.exposure_rules(raw["SPY"]["Adj Close"]).to_csv(OUT/"exposure.csv",date_format="%Y-%m-%d")
    v3.save_json(OUT/"data_ready.json",{"raw_common_start":str(common_start.date()),"raw_common_dates":len(expected),
                  "ready_rows":len(panel),"ready_dates":panel.Date.nunique(),"ready_first":str(panel.Date.min().date()),
                  "ready_last":str(panel.Date.max().date()),"price_files":len(frames),"prefix_features_passed":True,
                  "panel_sha256":hashlib.sha256((OUT/"panel.csv").read_bytes()).hexdigest(),"2026_prices_read":False})
    return panel


def train(panel):
    records,blocks = [],[]
    for year in range(2016,2026):
        dev = panel.loc[panel.Date.ge(f"{year}-01-01") & panel.Date.lt(f"{year+1}-01-01")].reset_index(drop=True)
        output = dev[["Date","symbol",rf.TARGET,"relevance","y_5","y_60","grade_60"]].copy()
        for config in CONFIGS:
            train,valid,develop = rh.split_fold(panel,year,config["horizon"])
            pd.testing.assert_frame_equal(dev[["Date","symbol"]],develop[["Date","symbol"]])
            if datetime.now(timezone.utc)>=v3.TRAINING_DEADLINE:
                raise TimeoutError("训练到达截止时间。")
            model = make_pipeline(StandardScaler(),Ridge(**v3.RIDGE_PARAMS) if config["kind"]=="ridge" else ElasticNet(**v3.ELASTIC_PARAMS))
            start = time.perf_counter()
            with warnings.catch_warnings(record=True) as caught,threadpool_limits(limits=4):
                warnings.simplefilter("always")
                model.fit(train[rf.EXTENDED_FEATURES],train[f"rank_{config['horizon']}"])
            prediction = model.predict(dev[rf.EXTENDED_FEATURES])
            assert np.isfinite(prediction).all()
            path = OUT/f"{year}_{config['id']}.joblib"
            joblib.dump({"model":model,"features":rf.EXTENDED_FEATURES,"candidate":config,"mode":"diagnostic_only"},path)
            np.testing.assert_array_equal(joblib.load(path)["model"].predict(dev[rf.EXTENDED_FEATURES]),prediction)
            record = {**config,"year":year,"train_rows":len(train),"validation_rows":len(valid),"development_rows":len(dev),
                      "train_first":str(train.Date.min().date()),"train_last_exit":str(train[f"exit_{config['horizon']}"].max().date()),
                      "validation_last_exit":str(valid[f"exit_{config['horizon']}"].max().date()),
                      "fit_seconds":time.perf_counter()-start,"warnings":[str(w.message) for w in caught],
                      "model_sha256":hashlib.sha256(path.read_bytes()).hexdigest()}
            records.append(record)
            output[config["id"]] = prediction
            pd.DataFrame(records).to_csv(OUT/"training_summary.csv",index=False)
            print(f"Fit {year} {config['id']} train={len(train)} seconds={record['fit_seconds']:.2f}",flush=True)
        blocks.append(output)
        output.to_csv(OUT/f"{year}_scores.csv",index=False,date_format="%Y-%m-%d")
    scores = pd.concat(blocks,ignore_index=True)
    scores.to_csv(OUT/"all_scores.csv",index=False,date_format="%Y-%m-%d")
    for config in CONFIGS:
        np.testing.assert_array_equal(pd.read_csv(OUT/"all_scores.csv",float_precision="round_trip")[config["id"]],scores[config["id"]])
    return scores


def evaluate(scores):
    opens = pd.read_csv(OUT/"adjusted_opens.csv",index_col="Date",parse_dates=["Date"],float_precision="round_trip")
    spy = pd.read_csv(OUT/"spy_open.csv",index_col="Date",parse_dates=["Date"],float_precision="round_trip").SPY
    exposure = pd.read_csv(OUT/"exposure.csv",index_col="Date",parse_dates=["Date"],float_precision="round_trip").vol15
    dates = pd.DatetimeIndex(scores.Date.unique()).sort_values()
    exposure = exposure.reindex(dates)
    equity,rows = {},[]
    folder = OUT/"backtests"; folder.mkdir(exist_ok=True)
    for cost in (10,20):
        for model_name in ("equal","spy",*[c["id"] for c in CONFIGS]):
            for policy in (("full",) if model_name=="spy" else ("full","vol15")):
                prices = spy.to_frame("SPY") if model_name=="spy" else opens
                values = (pd.DataFrame(0.0,index=dates,columns=prices.columns) if model_name in ("equal","spy") else
                          scores.pivot(index="Date",columns="symbol",values=model_name).reindex(columns=SYMBOLS))
                result = run_backtest(values,prices,spy,start="2016-01-01",top_k=None if model_name in ("equal","spy") else 5,
                                      cost_bps=cost,gross_exposure=None if policy=="full" else exposure)
                name = f"{model_name}_{policy}_cost{cost}"
                equity[name] = result["daily_equity"].equity
                row = {"candidate":name,"model":model_name,"policy":policy,"cost_bps":cost,**result["metrics"]}
                if model_name not in ("equal","spy"):
                    row.update(v3.old.score_ranking(scores,scores[model_name].to_numpy(),name))
                rows.append(row)
                result["daily_equity"].to_csv(folder/f"{name}_daily.csv",date_format="%Y-%m-%d")
                result["periods"].to_csv(folder/f"{name}_periods.csv",index=False,date_format="%Y-%m-%d")
                result["trades"].to_csv(folder/f"{name}_trades.csv",index=False,date_format="%Y-%m-%d")
    eq = pd.DataFrame(equity)
    returns = _returns_from_initial_cash(eq)
    annual = _annual_returns(eq)
    for row in rows:
        if row["model"] in ("equal","spy"):
            continue
        benchmark = f"equal_{row['policy']}_cost{int(row['cost_bps'])}"
        active = returns[row["candidate"]]-returns[benchmark]
        row["IR_vs_matched_equal"] = float(np.sqrt(252)*active.mean()/active.std(ddof=1))
        row["positive_active_years_out_of_10"] = int((annual[row["candidate"]]-annual[benchmark]).gt(0).sum())
    pd.DataFrame(rows).to_csv(OUT/"comparison.csv",index=False)
    eq.to_csv(OUT/"equity.csv",date_format="%Y-%m-%d")
    annual.to_csv(OUT/"annual_returns.csv")
    v3.save_json(OUT/"completion.json",{"completed_at_utc":datetime.now(timezone.utc).isoformat(),"annual_fits":20,
                  "development_years":list(range(2016,2026)),"score_rows":len(scores),"score_dates":len(dates),
                  "diagnostic_only":True,"main98_selection_unchanged":True,"2026_market_prices_accessed":False,"orders_sent":0})
    print(pd.DataFrame(rows)[["candidate","cagr","max_drawdown","mean_rank_ic","positive_active_years_out_of_10"]].to_string(index=False))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    register()
    if "--register-only" in sys.argv:
        print("Extended history diagnostic registered; no data/results read.")
    elif (OUT/"completion.json").exists():
        print("Already complete, preserved.")
    elif (OUT/"all_scores.csv").exists():
        print("Saved fits/scores found; resume evaluation without repeating training.")
        evaluate(pd.read_csv(OUT/"all_scores.csv",parse_dates=["Date"],float_precision="round_trip"))
    else:
        panel = prepare()
        evaluate(train(panel))
