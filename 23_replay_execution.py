"""用冻结的历史研究模型演练离线执行闭环，不推广为可交易策略。"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import uuid

import joblib
import numpy as np
import pandas as pd

from offline_execution import ReplayExecutor
from panel_config import RAW_DIR, SYMBOLS


ROOT = Path(__file__).resolve().parent
RESEARCH = ROOT / "data" / "experiments" / "auto_research_45m_v1"
MODEL = RESEARCH / "2025" / "m16_elastic_rank.joblib"
# 在编写本次工程演练前核对的冻结文件，不在运行时自动接受新模型哈希。
MODEL_SHA256 = "5dc11e8e3280f29669aa990fac5e4dd264c683a08c64538add7369791485bea4"
OUTPUT = ROOT / "data" / "replays" / "offline_v1"
START, END = "2025-01-02", "2025-02-14"


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def main():
    if hashlib.sha256(MODEL.read_bytes()).hexdigest() != MODEL_SHA256:
        raise ValueError("冻结模型哈希变化，禁止回放。")
    bundle = joblib.load(MODEL)
    model, features = bundle["model"], bundle["features"]
    plan = json.loads((RESEARCH / "plan.json").read_text(encoding="utf-8"))
    if features != plan["feature_sets"]["extended"] or bundle["candidate"]["id"] != "m16_elastic_rank":
        raise ValueError("保存模型或特征顺序与冻结研究定义不一致。")
    training = pd.read_csv(RESEARCH / "training_summary.csv")
    training = training.loc[training.candidate.eq("m16_elastic_rank") & training.year.eq(2025)]
    if len(training) != 1:
        raise ValueError("无法唯一确认模型训练记录。")
    training = training.iloc[0]
    if not training.train_last_exit < "2024-01-01" or not training.validation_last_exit < "2025-01-01":
        raise ValueError("模型训练或验证标签跨入本次历史回放区间。")
    panel_path = ROOT / "data" / "processed" / "research_panel_v1.csv"
    if hashlib.sha256(panel_path.read_bytes()).hexdigest() != plan["panel_sha256"]:
        raise ValueError("冻结特征面板哈希不符。")
    # 评分仅读取已保存的历史 X；不读取 y、未来收益或未来入场/退出价格列。
    rows = pd.read_csv(panel_path, usecols=["Date", "symbol", *features])
    rows = rows.loc[rows.Date.ge(START) & rows.Date.le(END)].copy()

    prices = {}
    for symbol in (*SYMBOLS, "SPY"):
        path = RAW_DIR / f"{symbol}.csv"
        metadata = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        if hashlib.sha256(path.read_bytes()).hexdigest() != metadata["sha256"]:
            raise ValueError(f"{symbol}: 历史缓存哈希不符。")
        raw = pd.read_csv(path, index_col="Date")
        prices[symbol] = raw.Open * raw["Adj Close"] / raw.Close
    calendar = prices.pop("SPY").index.tolist()
    for symbol, series in prices.items():
        if series.index.tolist() != calendar or not np.isfinite(series).all() or series.le(0).any():
            raise ValueError(f"{symbol}: 调整开盘价缺失或交易日历不一致。")
    opened = pd.DataFrame(prices).reindex(columns=SYMBOLS)
    selected_dates = [date for date in calendar if START <= date <= END]
    observation_dates = selected_dates[::5]
    observation_dates = [date for date in observation_dates if calendar[calendar.index(date) + 1] <= END]
    due = {calendar[calendar.index(date) + 1]: date for date in observation_dates}

    OUTPUT.mkdir(parents=True, exist_ok=True)
    executor = ReplayExecutor(OUTPUT / "state.json", calendar, SYMBOLS, features,
                              MODEL, MODEL_SHA256, initial_cash=10000, cost_bps=10)
    before = executor.read_state()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "_" + uuid.uuid4().hex[:8]
    snapshots, decisions, responses = [], [], []
    for date in selected_dates:
        today_prices = opened.loc[date].to_dict()
        if date in due:
            batch_key = f"offline_v1:m16:{due[date]}"
            responses.append(executor.fill_next_open(batch_key, date, date, today_prices))
        snapshots.append(executor.reconcile_snapshot(date, date, today_prices))
        if date in observation_dates:
            x = rows.loc[rows.Date.eq(date)].set_index("symbol").reindex(SYMBOLS)
            if len(x) != len(SYMBOLS) or not np.isfinite(x[features].to_numpy()).all():
                raise ValueError(f"{date}: 模型历史特征缺失，拒绝生成目标。")
            scores = pd.Series(model.predict(x[features]), index=SYMBOLS)
            if not np.isfinite(scores).all():
                raise ValueError("模型分数非有限，拒绝生成目标。")
            ranked = sorted(SYMBOLS, key=lambda symbol: (-float(scores[symbol]), symbol))
            weights = {symbol: 0.2 for symbol in ranked[:5]}
            key = f"offline_v1:m16:{date}"
            responses.append(executor.submit_target(key, date, date, weights, features))
            decisions.append(dict(observed_date=date, asof=date, phase="close", scores=scores.to_dict(),
                                  target_weights=weights, batch_key=key,
                                  input="historical_features_only_no_future_prices"))
    after = executor.read_state()
    report = dict(
        run_id=run_id, mode="historical_replay", status="completed",
        start=START, end=END, model_path=MODEL.as_posix(), model_sha256=MODEL_SHA256,
        model_role="engineering_replay_only_research_gate_not_passed",
        train_last_exit=training.train_last_exit, validation_last_exit=training.validation_last_exit,
        feature_count=len(features), initial_cash=10000, cost_bps=10, top_k=5,
        observation_count=len(observation_dates), snapshot_count=len(snapshots),
        new_fills=len(after["fills"]) - len(before["fills"]), total_fills=len(after["fills"]),
        new_processed_batches=len(after["processed_keys"]) - len(before["processed_keys"]),
        new_events=len(after["events"]) - len(before["events"]),
        events=after["events"][len(before["events"]):], decisions=decisions, responses=responses,
        final_snapshot=snapshots[-1], state_version=after["version"],
        final_positions="kept_open_at_last_snapshot_no_forced_liquidation_or_exit_fee",
        price_and_units="Supplier adjusted-open research proxies; not contemporaneous executable quotes or actual historical share counts.",
        boundary="Local offline persistence and simulated fills only; no broker, network orders, or external fill/retry guarantees.",
        blocked_requests_path=executor.blocked_path.as_posix(),
    )
    write_json(OUTPUT / f"run_{run_id}.json", report)
    write_json(OUTPUT / "completion.json", {key: value for key, value in report.items() if key not in ("events", "decisions", "responses")})
    pd.DataFrame([{key: snapshot[key] for key in ("date", "cash", "nav", "cumulative_fees")}
                  for snapshot in snapshots]).to_csv(OUTPUT / "daily_account.csv", index=False)
    print(json.dumps({key: report[key] for key in ("run_id", "status", "new_fills", "total_fills", "new_processed_batches", "new_events", "snapshot_count")}, indent=2))
    print(json.dumps({key: snapshots[-1][key] for key in ("date", "cash", "nav", "cumulative_fees")}, indent=2))


if __name__ == "__main__":
    main()
