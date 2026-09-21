"""Fictional v12 regression: episode recovery does not erase account drawdown.

No market files, models, downloads, or broker APIs are used. This exercises the
existing research simulator; the checkpoint below is a diagnostic statistic,
not an implemented persistent broker risk controller.
"""
from dataclasses import replace
import json
from pathlib import Path

import numpy as np
import pandas as pd

from profit_priority_strategy import Policy, simulate


OUT = Path(__file__).resolve().parent / "data/experiments/h60_training_cutoff_v12/drawdown_check"


def fictional_inputs():
    """Eight invented stocks suffer two 30% gaps, with time to resume between."""
    dates = pd.bdate_range("2020-01-01", periods=335)
    time = np.arange(len(dates))
    level = 100 + .01 * time + .3 * np.sin(time * .3)
    level[255:] *= .7
    level[295:] *= .7
    names = [f"FICTIONAL_{i}" for i in range(8)]
    close = pd.DataFrame({name: level * (1 + i / 10) for i, name in enumerate(names)}, index=dates)
    bars = {"Open": close.copy(), "High": close * 1.002,
            "Low": close * .998, "Close": close}
    spy = pd.Series(100 + time * .1 + .05 * np.sin(time), index=dates, name="FICTIONAL_SPY")
    scores = pd.DataFrame({name: 8 - i for i, name in enumerate(names)}, index=dates)
    return dates, bars, spy, scores, {name: name for name in names}


def continued_statistic(equity, high_water=1., worst_drawdown=0.):
    """Independent streaming calculation; caller must preserve its checkpoint."""
    drawdowns = []
    for value in equity:
        high_water = max(high_water, float(value))
        drawdown = float(value) / high_water - 1
        worst_drawdown = min(worst_drawdown, drawdown)
        drawdowns.append(drawdown)
    return drawdowns, {"account_high_water": high_water, "worst_account_drawdown": worst_drawdown}


def run_check():
    dates, bars, spy, scores, groups = fictional_inputs()
    result = simulate(scores, bars, spy, groups, dates[250:326:5], dates[330],
                      policy=replace(Policy(), soft_enabled=False))
    daily, events = result["daily"], result["events"]
    expected, checkpoint = continued_statistic(daily.equity)
    np.testing.assert_allclose(daily.drawdown, expected, rtol=0, atol=1e-14)
    resumes = events.loc[events.event.eq("portfolio_resume"), "Date"]
    assert len(resumes) == 2
    assert result["metrics"]["halts"] == 2
    assert result["metrics"]["gap_stops"] == 16
    assert result["metrics"]["max_drawdown"] < -.30
    for date in resumes:
        previous = daily.index[daily.index.get_loc(date) - 1]
        assert daily.loc[date, "episode_peak"] < daily.loc[previous, "episode_peak"]
        assert daily.loc[date, "drawdown"] < -.20

    # Serialize exactly the existing cumulative statistic; a replacement model
    # is metadata and cannot change previously observed equity or its high water.
    split = daily.index.get_loc(resumes.iloc[0])
    prefix, before = continued_statistic(daily.equity.iloc[:split])
    persisted = json.loads(json.dumps({**before, "source": "fictional_diagnostic_only"}))
    suffix, after = continued_statistic(daily.equity.iloc[split:],
                                       persisted["account_high_water"],
                                       persisted["worst_account_drawdown"])
    np.testing.assert_allclose(prefix + suffix, daily.drawdown, rtol=0, atol=1e-14)
    assert checkpoint == after
    daily = daily.copy()
    daily["account_high_water"] = daily.equity.cummax().clip(lower=1.)
    daily["episode_drawdown"] = daily.equity / daily.episode_peak - 1
    summary = {
        "data_kind": "FICTIONAL: invented prices, scores, symbols and dates; not historical performance",
        "engine": "profit_priority_strategy.simulate, unchanged v8 protected policy with soft disabled",
        "initial_equity": 1., "gap_count": 2, "fictional_stock_gap_fraction": -.30,
        "halts": result["metrics"]["halts"], "resumes": len(resumes),
        "gap_stop_exits": result["metrics"]["gap_stops"],
        "final_equity": result["metrics"]["final_equity"],
        "full_history_max_drawdown": result["metrics"]["max_drawdown"],
        "minimum_reported_episode_drawdown": float(daily.episode_drawdown.min()),
        "full_history_budget_30_breached": True,
        "engine_statistic_matches_independent_stream": True,
        "serialized_statistic_continuation_matches_whole_history": True,
        "diagnostic_checkpoint": persisted,
        "checkpoint_after_continuation": after,
        "resume_rows": [dict(Date=str(date.date()),
                             equity=float(daily.loc[date, "equity"]),
                             episode_peak=float(daily.loc[date, "episode_peak"]),
                             account_high_water=float(daily.loc[date, "account_high_water"]),
                             episode_drawdown=float(daily.loc[date, "episode_drawdown"]),
                             full_history_drawdown=float(daily.loc[date, "drawdown"])) for date in resumes],
        "boundary": "Checkpoint tests statistic continuity only. Existing simulator has no persistent live account high-water control; a new simulate call starts equity and episode state at 1. Do not concatenate separately rebased runs or treat a 20% episode pause as a 30% account-loss guarantee.",
    }
    return result, daily, summary


def main():
    result, daily, summary = run_check()
    OUT.mkdir(parents=True, exist_ok=True)
    daily.to_csv(OUT / "FICTIONAL_daily.csv")
    result["events"].to_csv(OUT / "FICTIONAL_events.csv", index=False)
    result["trades"].to_csv(OUT / "FICTIONAL_trades.csv", index=False)
    (OUT / "FICTIONAL_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (OUT / "README.md").write_text(
        "# 虚构连续亏损与恢复检查\n\n"
        "全部价格、信号、标的、日期均为虚构，不是历史收益、2026行情或券商成交。"
        "使用现有 `profit_priority_strategy.simulate`，保留8股、15%保护、20%周期硬暂停、20日冷却及10日恢复，仅按主候选关闭软减仓。\n\n"
        "八个虚构标的在两次相隔40个交易日的开盘分别下跌30%；中间满足原有趋势、冷却和计划调仓条件后恢复。跳空保护按原开盘滑点成交。\n\n"
        f"实际虚构输出：{summary['halts']}次暂停、{summary['resumes']}次恢复、{summary['gap_stop_exits']}笔跳空止损；全历史最大回撤 {summary['full_history_max_drawdown']:.6%}，最深周期回撤 {summary['minimum_reported_episode_drawdown']:.6%}。\n\n"
        "现有 `DrawdownState.resume` 重置 episode_peak；但同次 `simulate` 输出的收盘回撤由完整权益路径的累计最大值（至少为初始权益1）计算，并不读取 episode_peak。`research_backtest.py` 也采用该累计高水位口径。因此用户30%预算须检查 `max_drawdown`，不能用重置后的周期回撤替代。\n\n"
        "脚本同时用逐条累计的独立计算核对实际引擎结果，并将累计高水位/最深回撤经过JSON序列化后接续计算，证明保留统计状态时结果一致。这个检查不是新增的线上账户风险控制，也不能证明现有执行模块已经在长期断线、换模型或重启时保持账户高水位。重新调用 simulate 会从权益1开始；独立重启的归一化结果不能直接充当连续账户历史。\n\n"
        "下一项独立风控设计应明确持久化账户高水位、现金流调整、重启/换模型的状态沿用及提前减仓/恢复规则，并另做收益代价实验；本轮单因素训练截止比较不混入该改动。跳空仍可能越过阈值。\n\n"
        "运行：`.venv\\Scripts\\python.exe v12_drawdown_check.py`；测试：`.venv\\Scripts\\python.exe -m unittest discover -s tests -p test_v12_drawdown.py -v`。\n",
        encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
