"""v17 fixed-survivor local research prototype; never a dynamic-universe validation.

Uses only hash-identified local <=2025 adjusted-price snapshots. The small new
adapter reuses the project's fee/cash rebalance solver and marks daily close NAV.
No live/paper API, downloads, unregistered fitting, or changes to old experiments.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys
import time
import warnings

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from h60_research_inputs import load_inputs, save, sha  # noqa: E402
from panel_config import SYMBOLS  # noqa: E402
from research_backtest import _rebalance, _check_dates  # noqa: E402

OUT = ROOT / "data/experiments/adaptive_strategy_research_v17/local_prototype"
FEATURES = ["r5", "r20", "r63_skip20", "r126_skip20", "vol20", "dd63", "relative20", "spy_gap200"]
YEARS = tuple(range(2016, 2026))
INITIAL = 100000.0
BASE_CASES = ("equal", "spy", "medium_trend", "ridge", "ridge_trend_budget")


def now():
    return datetime.now(timezone.utc).isoformat()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def stable(path, value):
    if path.exists():
        if read(path) != value:
            raise ValueError(f"Frozen identity differs: {path}")
    else:
        save(path, value)


def dataframe_sha(frame):
    return hashlib.sha256(frame.to_csv(index=False, date_format="%Y-%m-%d").encode()).hexdigest()


def build_panel(bars, spy_bars):
    """Eight past-only features; forward labels are separate, never predictors."""
    close, opened = bars["Close"], bars["Open"]
    spy_close, spy_open = spy_bars["Close"].iloc[:, 0], spy_bars["Open"].iloc[:, 0]
    if close.index.max() >= pd.Timestamp("2026-01-01"):
        raise ValueError("2026 market data is sealed")
    returns = close.pct_change(fill_method=None)
    vol = returns.rolling(20).std(ddof=1)
    spy20 = spy_close / spy_close.shift(20) - 1
    spy_gap = spy_close / spy_close.rolling(200).mean() - 1
    spy_forward = spy_open.shift(-21) / spy_open.shift(-1) - 1
    dates = pd.Series(close.index, index=close.index)
    blocks = []
    for symbol in close.columns:
        price = close[symbol]
        excess = opened[symbol].shift(-21) / opened[symbol].shift(-1) - 1 - spy_forward
        block = pd.DataFrame({
            "symbol": symbol,
            "r5": price / price.shift(5) - 1,
            "r20": price / price.shift(20) - 1,
            "r63_skip20": price.shift(20) / price.shift(63) - 1,
            "r126_skip20": price.shift(20) / price.shift(126) - 1,
            "vol20": vol[symbol],
            "dd63": price / price.rolling(63).max() - 1,
            "relative20": price / price.shift(20) - 1 - spy20,
            "spy_gap200": spy_gap,
            "excess20": excess,
            "target": excess / (vol[symbol] * np.sqrt(20)),
            "exit20": dates.shift(-21),
        }, index=close.index).rename_axis("Date").reset_index()
        blocks.append(block)
    return pd.concat(blocks, ignore_index=True).sort_values(["Date", "symbol"]).reset_index(drop=True)


def train_rows(panel, year):
    rows = panel.loc[panel.Date.ge("2013-05-22") & panel.Date.lt(f"{year}-01-01")
                     & panel.exit20.lt(f"{year}-01-01")].copy()
    complete = np.isfinite(rows[[*FEATURES, "target"]].to_numpy()).all(axis=1)
    if not complete.all() or rows.empty:
        raise ValueError("Training cohort has missing features/labels; do not silently drop stocks")
    return rows


def make_weights(scores, observations, kind, trend_gap):
    columns = scores.columns
    weights = pd.DataFrame(0.0, index=observations, columns=columns)
    for date in observations:
        budget = .45 if kind == "ridge_trend_budget" and float(trend_gap.loc[date]) < 0 else .90
        selected = list(columns) if kind in ("equal", "spy") else sorted(columns, key=lambda s: (-float(scores.loc[date, s]), s))[:10]
        weights.loc[date, selected] = budget / len(selected)
    return weights


def simulate_weights(weights, bars, final_date, cost_bps, initial=INITIAL):
    """At completed-close signal dates, trade next-open; cash and fills cost actual drift.

    Adjusted OHLC + fractional units are a total-return proxy, not executable quotes.
    Dividend/split effects are already embedded; never add separate cash dividends.
    """
    calendar, names = bars["Open"].index, bars["Open"].columns
    _check_dates(calendar, "prices")
    _check_dates(weights.index, "decisions")
    if not weights.columns.equals(names) or not weights.index.isin(calendar).all():
        raise ValueError("Decision identity/calendar mismatch")
    if not np.isfinite(weights.to_numpy()).all() or weights.lt(0).any().any() or weights.sum(axis=1).gt(1).any():
        raise ValueError("Borrowing, shorting, or invalid weight")
    for field in ("Open", "Close"):
        frame = bars[field]
        if not frame.index.equals(calendar) or not frame.columns.equals(names) or not np.isfinite(frame).all().all() or frame.le(0).any().any():
            raise ValueError("Price missing/invalid; no forward-filled executable price")
    if final_date not in calendar or final_date <= weights.index[-1]:
        raise ValueError("Final date invalid")
    schedule = {calendar.get_loc(date) + 1: date for date in weights.index}
    first, finish = min(schedule), calendar.get_loc(final_date)
    q, cash = np.zeros(len(names)), float(initial)
    rows, holdings, trades, targets = [], [], [], []
    fees = 0.0
    for day in range(first, finish + 1):
        date = calendar[day]
        opened, close = bars["Open"].iloc[day].to_numpy(), bars["Close"].iloc[day].to_numpy()
        fee_today = 0.0
        if day in schedule or day == finish:
            observation = schedule.get(day, calendar[day-1])
            w = np.zeros(len(names)) if day == finish else weights.loc[observation].to_numpy()
            reason = "final_liquidation" if day == finish else "scheduled"
            target, expected_cash, change, fee_today = _rebalance(q * opened, cash, w, cost_bps / 10000)
            for j in np.argsort(change, kind="stable"):
                if abs(change[j]) < 1e-10:
                    continue
                delta = float(change[j] / opened[j])
                fee = float(abs(change[j]) * cost_bps / 10000)
                cash -= float(change[j]) + fee
                q[j] += delta
                trades.append(dict(Date=date, observation_date=observation, symbol=names[j],
                    signed_units=delta, proxy_fill=float(opened[j]), signed_notional=float(change[j]),
                    fee=fee, cash_change=float(-change[j]-fee), reason=reason))
            np.testing.assert_allclose(cash, expected_cash, atol=1e-6, rtol=1e-11)
            cash = expected_cash
            q[np.abs(q) < 1e-10] = 0.0
            np.testing.assert_allclose(q * opened, target, atol=1e-6, rtol=1e-11)
            fees += fee_today
            targets.append(dict(Date=date, observation_date=observation, reason=reason,
                                **{s: float(w[j]) for j, s in enumerate(names)}))
        equity = cash + float(q @ close)
        if cash < -1e-6 or (q < -1e-10).any() or equity <= 0:
            raise AssertionError("Invalid cash/holding/equity")
        rows.append(dict(Date=date, equity=equity, cash=cash, invested=float(q @ close),
                         gross=float(q @ close) / equity, fees=fee_today, cumulative_fees=fees,
                         max_stock_weight=float((q * close / equity).max()),
                         holdings=int((q > 1e-10).sum())))
        holdings.append(dict(Date=date, **{s: float(q[j]) for j, s in enumerate(names)}))
    daily = pd.DataFrame(rows).set_index("Date")
    daily["return"] = daily.equity / daily.equity.shift(1, fill_value=initial) - 1
    daily["drawdown"] = daily.equity / daily.equity.cummax().clip(lower=initial) - 1
    return dict(daily=daily, trades=pd.DataFrame(trades), positions=pd.DataFrame(holdings).set_index("Date"),
                targets=pd.DataFrame(targets))


def audit_result(result, bars):
    daily, positions, trades = (result[k] for k in ("daily", "positions", "trades"))
    cash = trades.groupby("Date").cash_change.sum().reindex(daily.index, fill_value=0).cumsum() + INITIAL
    units = trades.pivot_table(index="Date", columns="symbol", values="signed_units", aggfunc="sum", fill_value=0)
    units = units.reindex(index=daily.index, columns=positions.columns, fill_value=0).cumsum()
    np.testing.assert_allclose(cash, daily.cash, rtol=1e-9, atol=1e-6)
    np.testing.assert_allclose(units, positions, rtol=1e-9, atol=1e-7)
    np.testing.assert_allclose(daily.equity, daily.cash + (positions * bars["Close"].loc[daily.index]).sum(axis=1), atol=1e-6, rtol=1e-10)
    np.testing.assert_allclose(trades.fee.sum(), daily.fees.sum(), atol=1e-6, rtol=1e-10)
    assert positions.iloc[-1].eq(0).all() and result["targets"].observation_date.lt(result["targets"].Date).all()
    return dict(cash_checked=True, shares_checked=True, equity_checked=True, final_flat=True,
                daily_drawdown_never_reset=True, decision_precedes_fill=True)


def summarize(case, result, cost_bps):
    d, trades = result["daily"], result["trades"]
    duration = (d.index[-1] - d.index[0]).days / 365.25
    previous = d.equity.shift(1, fill_value=INITIAL)
    turnover = trades.groupby("Date").signed_notional.apply(lambda a: a.abs().sum()).reindex(d.index, fill_value=0) / previous
    row = dict(case=case, cost_bps=cost_bps, final_equity=float(d.equity.iloc[-1]),
               cumulative_return=float(d.equity.iloc[-1]/INITIAL-1),
               cagr=float((d.equity.iloc[-1]/INITIAL)**(1/duration)-1),
               max_drawdown=float(d.drawdown.min()), annualized_volatility=float(d["return"].std(ddof=1)*np.sqrt(252)),
               average_exposure=float(d.gross.mean()), max_single_stock_weight=float(d.max_stock_weight.max()),
               average_holdings=float(d.holdings.mean()), turnover_two_way_annual=float(turnover.sum()/duration),
               fees_usd=float(trades.fee.sum()), fills=len(trades), cash_interest=0,
               evidence="SURVIVORSHIP_BIASED_DEVELOPMENT_PROTOTYPE")
    annual = []
    for year, part in d.groupby(d.index.year):
        start = float(previous.loc[part.index[0]])
        annual.append(dict(case=case, year=int(year), cost_bps=cost_bps,
            net_return=float(part.equity.iloc[-1]/start-1), pnl_usd=float(part.equity.iloc[-1]-start),
            annualized_volatility=float(part["return"].std(ddof=1)*np.sqrt(252)),
            within_year_drawdown=float((part.equity/part.equity.cummax().clip(lower=start)-1).min()),
            continuous_drawdown_min=float(part.drawdown.min()), average_exposure=float(part.gross.mean()),
            fees_usd=float(part.fees.sum()), turnover_two_way=float(turnover.loc[part.index].sum())))
    contribution = trades.groupby("symbol", as_index=False).agg(net_pnl_usd=("cash_change", "sum"), fees_usd=("fee", "sum"))
    # Final flat permits security cash flows to sum to net P&L without unmarked residuals.
    np.testing.assert_allclose(contribution.net_pnl_usd.sum(), d.equity.iloc[-1]-INITIAL, atol=1e-6)
    contribution["case"] = case
    monthly = []
    for month, part in d.groupby(d.index.to_period("M")):
        start = float(previous.loc[part.index[0]])
        monthly.append(dict(case=case, month=str(month), start_equity=start,
                            end_equity=float(part.equity.iloc[-1]), net_return=float(part.equity.iloc[-1]/start-1),
                            pnl_usd=float(part.equity.iloc[-1]-start), fees_usd=float(part.fees.sum())))
    return row, annual, contribution, monthly


def verify_existing():
    record = read(OUT / "COMPLETE.json")
    for name, digest in record["files_sha256"].items():
        path = ROOT/name
        if sha(path) != digest:
            raise ValueError(f"Changed artifact: {name}")
    print(json.dumps(dict(status="verified", actual_fits=record["actual_fits"], backtests=record["backtests"],
                          current_review_head=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                          generation_head=record["generation_head"], new_fits=0, new_backtests=0)), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    if args.verify:
        verify_existing()
        return
    if (OUT/"COMPLETE.json").exists():
        verify_existing()
        return
    root_plan = OUT.parent/"PLAN.md"
    if not root_plan.exists():
        raise ValueError("Root PLAN must be registered before local training")
    OUT.mkdir(parents=True, exist_ok=True)
    bars, spy_bars, spy, original, observations, final, identity = load_inputs()
    plan = dict(name="v17_local_fixed_survivor_prototype", root_plan_sha256=sha(root_plan),
        data_limitation="Fixed current-survivor 30-stock universe; cannot validate dynamic universe/deployment",
        features=FEATURES, train_start="2013-05-22", years=list(YEARS), model={"kind":"StandardScaler+Ridge","alpha":100,"solver":"svd"},
        label="(adjusted_open[t+21]/adjusted_open[t+1]-1 - SPY_same) / (past20_daily_std_ddof1 * sqrt20)",
        training_cutoff="Date and exit20 strictly before deployment Jan1; train-only scaler; no parameter tuning",
        initial_cash=INITIAL, price_basis="adjusted OHLC total-return proxy/fractional units; dividends not added again",
        schedule="original v5 502 five-session observation dates; following open; final open liquidation",
        first_entry="2016-01-05", final_exit=str(final.date()), exposure=.90, top_k=10,
        overlay="only ridge_trend_budget: scheduled .45 below SPY200SMA, else .90; no individual stop or pause",
        base_cases=list(BASE_CASES), cost10_cases=5, cost20_cases=3,
        finalist_rule="nonbaseline highest CAGR among drawdown >= -30%; if none, highest CAGR diagnosis only; stable case tie",
        max_fits=10, max_backtests=8, no_leverage=True, no_2026=True, no_broker=True,
        goal_cagr=[.20,.30], preferred_drawdown=.20, drawdown_budget=.30)
    stable(OUT/"PLAN.json", plan)
    stable(OUT/"INPUT_IDENTITY.json", identity)
    panel = build_panel(bars, spy_bars)
    prefix_date = pd.Timestamp("2021-12-31")
    prefix = build_panel({k:v.loc[:prefix_date] for k,v in bars.items()}, {k:v.loc[:prefix_date] for k,v in spy_bars.items()})
    pd.testing.assert_frame_equal(prefix[["Date","symbol",*FEATURES]], panel.loc[panel.Date.le(prefix_date),["Date","symbol",*FEATURES]].reset_index(drop=True), check_exact=True)
    keys = original.stack().rename("old_A_unused_prediction").reset_index()[["Date", "symbol"]]
    scoring = keys.merge(panel, on=["Date", "symbol"], validate="one_to_one", how="left")
    assert len(scoring) == 75240 and np.isfinite(scoring[FEATURES]).all().all()
    stable(OUT/"DATA_CHECKS.json", dict(prefix_features_exact=True, score_rows=len(scoring), score_dates=scoring.Date.nunique(),
        last_price=str(spy.index.max().date()), mature_labels=int(scoring.target.notna().sum()),
        immature_scoring_rows_retained=int(scoring.target.isna().sum()), panel_feature_sha256=dataframe_sha(panel[["Date","symbol",*FEATURES]]),
        label_sha256=dataframe_sha(panel[["Date","symbol","target","excess20","exit20"]])))
    if args.prepare_only:
        print("Local prototype plan/input/past-only feature checks saved; no fits/backtests.", flush=True)
        return
    source_paths = (Path(__file__).resolve(), ROOT/"research_backtest.py", ROOT/"h60_research_inputs.py")
    implementation = dict(plan_sha256=sha(OUT/"PLAN.json"), source_sha256={p.relative_to(ROOT).as_posix():sha(p) for p in source_paths},
                          packages={p:importlib.metadata.version(p) for p in ("numpy","pandas","scikit-learn","scipy","joblib")})
    stable(OUT/"IMPLEMENTATION.json", implementation)
    if not (OUT/"GENERATION.json").exists():
        save(OUT/"GENERATION.json", dict(started_at_utc=now(), git_head=subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip()))
    training, predicted, coefficients = [], [], []
    for year in YEARS:
        train = train_rows(panel, year)
        develop = scoring.loc[scoring.Date.dt.year.eq(year)].copy()
        contract = dict(year=year, rows=len(train), first_observation=str(train.Date.min().date()),
            last_observation=str(train.Date.max().date()), last_label_exit=str(train.exit20.max().date()),
            prediction_rows=len(develop), feature_order=FEATURES, training_data_sha256=dataframe_sha(train[["Date","symbol",*FEATURES,"target","exit20"]]),
            implementation_sha256=sha(OUT/"IMPLEMENTATION.json"))
        path = OUT/"models"/f"{year}_ridge_risk_scaled_excess20.joblib"
        meta_path = path.with_suffix(".json")
        if path.exists() or meta_path.exists():
            if not path.exists() or not meta_path.exists():
                raise ValueError("Incomplete model persistence; never silently refit")
            record = read(meta_path)
            assert record["contract"] == contract and record["model_sha256"] == sha(path)
            model = joblib.load(path)["model"]
        else:
            model = make_pipeline(StandardScaler(), Ridge(alpha=100, solver="svd"))
            begin = time.perf_counter()
            with warnings.catch_warnings(record=True) as caught, threadpool_limits(limits=2):
                warnings.simplefilter("always")
                model.fit(train[FEATURES], train.target)
            duration = time.perf_counter()-begin
            path.parent.mkdir(exist_ok=True)
            joblib.dump(dict(model=model, feature_order=FEATURES, contract=contract, research_only=True),path)
            record = dict(contract=contract, model_sha256=sha(path), fit_seconds=duration, fitted_at_utc=now(),
                          warnings=[f"{w.category.__name__}: {w.message}" for w in caught])
            save(meta_path, record)
        np.testing.assert_allclose(model[0].mean_,train[FEATURES].mean(),atol=1e-12,rtol=1e-12)
        assert model[0].n_samples_seen_ == len(train)
        with threadpool_limits(limits=2):
            develop["prediction"] = model.predict(develop[FEATURES])
        assert np.isfinite(develop.prediction).all()
        predicted.append(develop[["Date","symbol","prediction","r126_skip20","target","excess20","exit20"]])
        training.append(dict(**{k:v for k,v in contract.items() if k!="feature_order"}, model_path=path.relative_to(ROOT).as_posix(),
                             model_sha256=record["model_sha256"],fit_seconds=record["fit_seconds"],warnings=json.dumps(record["warnings"]),fitted_at_utc=record["fitted_at_utc"]))
        coefficients.extend(dict(year=year,feature=f,coefficient=float(c)) for f,c in zip(FEATURES,model[-1].coef_))
        pd.DataFrame(training).to_csv(OUT/"training_summary.csv",index=False)
        print(f"FIT {year}: rows={len(train)}, last matured label={contract['last_label_exit']}, seconds={record['fit_seconds']:.3f}",flush=True)
    predictions = pd.concat(predicted,ignore_index=True)
    predictions.to_csv(OUT/"predictions.csv",index=False,date_format="%Y-%m-%d")
    pd.DataFrame(coefficients).to_csv(OUT/"coefficients.csv",index=False)
    ic = []
    for date, part in predictions.dropna(subset=["target"]).groupby("Date"):
        if len(part)!=len(SYMBOLS):
            raise ValueError("Partial mature cross-section")
        ic.append(dict(Date=date,rank_ic=float(part.prediction.rank(method="average").corr(part.target.rank(method="average"))),
                       rank_ic_excess=float(part.prediction.rank(method="average").corr(part.excess20.rank(method="average")))))
    ic = pd.DataFrame(ic)
    ic.to_csv(OUT/"daily_ic.csv",index=False,date_format="%Y-%m-%d")
    ic.groupby(ic.Date.dt.year).agg(rank_ic=("rank_ic","mean"),rank_ic_excess=("rank_ic_excess","mean"),days=("Date","size")).to_csv(OUT/"annual_ic.csv")
    signal = predictions.pivot(index="Date",columns="symbol",values="prediction").reindex(columns=SYMBOLS)
    medium = predictions.pivot(index="Date",columns="symbol",values="r126_skip20").reindex(columns=SYMBOLS)
    trend_gap = panel.drop_duplicates("Date").set_index("Date").spy_gap200
    totals, annual, contributions, monthly, audits = [], [], [], [], {}
    def run(kind,cost):
        case = f"{kind}_cost{cost}"
        prices = spy_bars if kind=="spy" else bars
        source = pd.DataFrame(0., index=signal.index,columns=["SPY"]) if kind=="spy" else (medium if kind=="medium_trend" else signal)
        weights = make_weights(source,observations,kind,trend_gap)
        result = simulate_weights(weights,prices,final,cost)
        audits[case] = audit_result(result,prices)
        folder = OUT/"backtests"/case
        folder.mkdir(parents=True,exist_ok=True)
        for key,frame in result.items():
            frame.to_csv(folder/f"{key}.csv",index=key in ("daily","positions"),date_format="%Y-%m-%d")
        row,years,contribution,months = summarize(case,result,cost)
        totals.append(row); annual.extend(years); contributions.append(contribution); monthly.extend(months)
        save(folder/"metrics.json",row)
        pd.DataFrame(totals).to_csv(OUT/"results.csv",index=False)
        print(f"RESULT {case}: CAGR={row['cagr']:.3%}, DD={row['max_drawdown']:.3%}, final={row['final_equity']:.2f}",flush=True)
    for kind in BASE_CASES:
        run(kind,10)
    candidates = [r for r in totals if not r["case"].startswith(("equal_","spy_"))]
    eligible = [r for r in candidates if r["max_drawdown"]>=-.30]
    winner = sorted(eligible or candidates,key=lambda r:(-r["cagr"],r["case"]))[0]
    selected = winner["case"].removesuffix("_cost10")
    stable(OUT/"FINALIST_SELECTION.json", dict(selected=selected,selected_at_utc=now(),rule=plan["finalist_rule"],
        eligible_cases=[r["case"] for r in eligible], cost10_results_sha256=sha(OUT/"results.csv"),
        before_cost20=True, development_selection_not_independent_validation=True))
    for kind in (selected,"equal","spy"):
        run(kind,20)
    pd.DataFrame(annual).to_csv(OUT/"annual_results.csv",index=False)
    pd.concat(contributions,ignore_index=True).to_csv(OUT/"security_contributions.csv",index=False)
    pd.DataFrame(monthly).to_csv(OUT/"monthly_results.csv",index=False)
    save(OUT/"CHECKS.json",dict(cases=audits,actual_fits=10,backtests=8,training_warnings=sum(len(json.loads(r["warnings"])) for r in training),
        source_unchanged=all(sha(ROOT/p)==digest for p,digest in implementation["source_sha256"].items()),
        surviving30=True, independent_validation=False, no_2026=True, no_broker_orders=True))
    files = [p for p in OUT.rglob("*") if p.is_file() and p.name!="COMPLETE.json"]
    files.extend(source_paths)
    save(OUT/"COMPLETE.json",dict(completed_at_utc=now(),actual_fits=10,backtests=8,
        generation_head=read(OUT/"GENERATION.json")["git_head"],
        files_sha256={p.relative_to(ROOT).as_posix():sha(p) for p in files}))
    verify_existing()


if __name__=="__main__":
    main()
