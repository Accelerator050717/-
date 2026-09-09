"""本批固定准入规则和共同时间区块 bootstrap；不读取文件、不训练模型。

所有收益为小数；max_drawdown 为负数。门槛只是预设研究筛选标准，
不能消除此前多轮研究、当前存续股票清单或行情修订带来的偏差。
"""

import numpy as np
import pandas as pd


BENCHMARKS = ("benchmark_equal", "benchmark_spy")
DEVELOPMENT_YEARS = tuple(range(2020, 2026))
BOOTSTRAP_REPETITIONS = 2000
BLOCK_LENGTH = 20
BOOTSTRAP_SEED = 20260907
ALPHA = 0.05
TRADING_DAYS = 252


def _returns_from_initial_cash(equity):
    """输入逐日 NAV；第一天以前只有 1 元现金，因此首日费用不能丢掉。"""
    returns = equity.pct_change(fill_method=None)
    returns.iloc[0] = equity.iloc[0] - 1.0
    return returns


def _annual_returns(equity):
    """每年末 NAV 除以上年末 NAV；第一年以隐含初始现金 1 为分母。"""
    year_end = equity.groupby(equity.index.year).last()
    previous = year_end.shift(1)
    previous.iloc[0] = 1.0
    return year_end / previous - 1.0


def _simultaneous_lower_bounds(active, repetitions=BOOTSTRAP_REPETITIONS,
                               block_length=BLOCK_LENGTH, seed=BOOTSTRAP_SEED):
    """循环区块联合重采样的 max-t 下界，使用 bootstrap 固定标准误。

    active: 每行是同一交易日，各列是不同候选的日主动收益。
    同一个抽样下所有列共享日期索引，保留候选之间的相关性；每个
    连续区块有 20 个交易日，区块末端按历史数组循环。
    先估计每列 bootstrap 均值的标准误，再对各次重采样计算跨候选
    最大标准化偏差。这是近似的同时置信界，不是独立样本 t 检验。
    """
    values = np.asarray(active, dtype=float)
    if values.ndim != 2 or not np.isfinite(values).all():
        raise ValueError("active 必须是无缺失、有限的二维收益矩阵。")
    n_dates, n_candidates = values.shape
    if n_dates < block_length or n_candidates == 0:
        raise ValueError("收益矩阵必须至少有一个候选和一个完整区块。")
    if repetitions < 2:
        raise ValueError("bootstrap 至少需要两次重采样。")
    means = values.mean(axis=0)
    centered = values - means
    rng = np.random.default_rng(seed)
    block_count = int(np.ceil(n_dates / block_length))
    offsets = np.arange(block_length)
    bootstrap_means = np.empty((repetitions, n_candidates))
    # 不生成 repetitions × dates × candidates 巨型数组，每批最多 32 次。
    for start in range(0, repetitions, 32):
        stop = min(start + 32, repetitions)
        block_starts = rng.integers(0, n_dates, size=(stop - start, block_count))
        indices = (block_starts[:, :, None] + offsets) % n_dates
        indices = indices.reshape(stop - start, -1)[:, :n_dates]
        bootstrap_means[start:stop] = centered[indices].mean(axis=1)
    standard_errors = bootstrap_means.std(axis=0, ddof=1)
    varying = np.ptp(values, axis=0) > 0.0
    usable = varying & (standard_errors > np.finfo(float).tiny)
    standardized = np.zeros_like(bootstrap_means)
    standardized[:, usable] = bootstrap_means[:, usable] / standard_errors[usable]
    maxima = standardized.max(axis=1)
    # higher 使有限次 Monte Carlo 的分位数取值略保守；下界不高于点估计。
    critical = max(0.0, float(np.quantile(maxima, 1 - ALPHA, method="higher")))
    lower = means - critical * standard_errors
    # 恒定序列没有可重采样的波动；明确返回退化区间并在信息中标注。
    standard_errors[~varying] = 0.0
    lower[~varying] = means[~varying]
    return {
        "means": means, "standard_errors": standard_errors, "lower": lower,
        "critical_max_t": critical, "degenerate": ~usable,
    }


def evaluate_candidates(equity: pd.DataFrame, ranking_metrics: pd.DataFrame,
                        stressed_metrics: dict, cost10metrics: dict):
    """返回 (comparison, bootstrap_info)，不进行任何文件 I/O。

    equity: 唯一、递增 Date 索引的每日 NAV，每列从隐含现金 1 开始；
      含所有候选及 benchmark_equal、benchmark_spy，不能有 NaN。
    ranking_metrics: candidate、mean_rank_ic、positive_ic_years 三列。
      未定义的 IC 可以是 NaN，但不能据此通过准入。
    stressed_metrics: 20 bp 回测的 {candidate: {"cagr": ...}}，也必须
      包括 benchmark_equal；对比同一成本下的同池等权。
    cost10metrics: 10 bp 回测的 {candidate: metrics}，含两个基准；
      每个 metrics 至少含 cagr、max_drawdown、total_return。

    comparison 含 candidate 和逐条 gate；selected_for_holdout 只可能
    有一个 True。无通过者只标 best_development，不准据此打开 2026。
    """
    if not isinstance(equity.index, pd.DatetimeIndex) or equity.empty:
        raise ValueError("equity 必须使用非空 DatetimeIndex。")
    if equity.index.has_duplicates or not equity.index.is_monotonic_increasing:
        raise ValueError("equity 日期必须唯一且严格递增。")
    if equity.columns.has_duplicates or not all(isinstance(c, str) for c in equity.columns):
        raise ValueError("equity 列名必须是唯一字符串。")
    if any(name not in equity.columns for name in BENCHMARKS):
        raise ValueError("缺少 benchmark_equal 或 benchmark_spy 的共同日期 NAV。")
    if not np.isfinite(equity.to_numpy(dtype=float)).all() or (equity <= 0).any().any():
        raise ValueError("NAV 必须全部为有限正数；不允许静默删除缺失日期。")
    if len(equity) < BLOCK_LENGTH:
        raise ValueError("交易日不足一个 bootstrap 区块。")
    candidates = sorted(set(equity.columns) - set(BENCHMARKS))
    if not candidates:
        raise ValueError("没有候选。")
    required_ranking = {"candidate", "mean_rank_ic", "positive_ic_years"}
    if not required_ranking.issubset(ranking_metrics.columns):
        raise ValueError(f"ranking_metrics 缺少列：{required_ranking - set(ranking_metrics.columns)}")
    if ranking_metrics["candidate"].duplicated().any():
        raise ValueError("ranking_metrics 每个 candidate 只能有一行。")
    ranking = ranking_metrics.set_index("candidate")
    for name in list(candidates) + list(BENCHMARKS):
        if name not in cost10metrics:
            raise ValueError(f"cost10metrics 缺少 {name}。")
        for field in ("cagr", "max_drawdown", "total_return"):
            if field not in cost10metrics[name] or not np.isfinite(cost10metrics[name][field]):
                raise ValueError(f"cost10metrics[{name}] 缺少有限的 {field}。")
        if cost10metrics[name]["max_drawdown"] > 0:
            raise ValueError(f"{name} 的 max_drawdown 应是负数或零。")
    for name in candidates + ["benchmark_equal"]:
        if name not in stressed_metrics or not np.isfinite(stressed_metrics[name].get("cagr", np.nan)):
            raise ValueError(f"stressed_metrics 缺少 {name} 的有限 cagr。")
    if not set(candidates).issubset(ranking.index):
        raise ValueError(f"ranking_metrics 缺少候选：{set(candidates) - set(ranking.index)}")

    returns = _returns_from_initial_cash(equity)
    active = returns[candidates].sub(returns["benchmark_equal"], axis=0)
    annual = _annual_returns(equity)
    annual_active = annual[candidates].sub(annual["benchmark_equal"], axis=0)
    complete_year_set = set(annual.index) == set(DEVELOPMENT_YEARS)
    bootstrap = _simultaneous_lower_bounds(active.to_numpy())
    baseline_cagr = max(cost10metrics[b]["cagr"] for b in BENCHMARKS)
    worst_baseline_drawdown = min(cost10metrics[b]["max_drawdown"] for b in BENCHMARKS)
    stress_equal_cagr = float(stressed_metrics["benchmark_equal"]["cagr"])
    rows = []
    for column, name in enumerate(candidates):
        daily_active = active[name]
        daily_std = float(daily_active.std(ddof=1))
        # 无跟踪误差时 IR 无定义；不把相同于基准的候选人为记成有优势。
        information_ratio = (np.sqrt(TRADING_DAYS) * float(daily_active.mean()) / daily_std
                             if daily_std > 0 else np.nan)
        values = cost10metrics[name]
        mean_ic = float(ranking.loc[name, "mean_rank_ic"])
        positive_ic_years = ranking.loc[name, "positive_ic_years"]
        if pd.isna(positive_ic_years):
            positive_ic_years = 0
        elif int(positive_ic_years) != positive_ic_years or not 0 <= int(positive_ic_years) <= 6:
            raise ValueError(f"{name} 的 positive_ic_years 必须是 0—6 的整数。")
        positive_ic_years = int(positive_ic_years)
        positive_active_years = int(annual_active[name].gt(0).sum())
        stress_cagr = float(stressed_metrics[name]["cagr"])
        row = {
            "candidate": name,
            "cagr": float(values["cagr"]), "total_return": float(values["total_return"]),
            "max_drawdown": float(values["max_drawdown"]),
            "cagr_advantage_vs_equal": float(values["cagr"] - cost10metrics["benchmark_equal"]["cagr"]),
            "cagr_advantage_vs_spy": float(values["cagr"] - cost10metrics["benchmark_spy"]["cagr"]),
            "information_ratio": float(information_ratio),
            "positive_active_years": positive_active_years,
            "mean_rank_ic": mean_ic, "positive_ic_years": positive_ic_years,
            "stress_cagr": stress_cagr, "stress_equal_cagr": stress_equal_cagr,
            "mean_daily_active": float(bootstrap["means"][column]),
            "bootstrap_standard_error_daily": float(bootstrap["standard_errors"][column]),
            "simultaneous_lower_daily": float(bootstrap["lower"][column]),
            "gate_cagr": bool(values["cagr"] > baseline_cagr + 0.03),
            "gate_information_ratio": bool(np.isfinite(information_ratio) and information_ratio >= 0.5),
            "gate_positive_years": bool(complete_year_set and positive_active_years >= 4),
            "gate_drawdown": bool(values["max_drawdown"] >= worst_baseline_drawdown - 0.05),
            "gate_rank_ic": bool(np.isfinite(mean_ic) and mean_ic >= 0.03 and positive_ic_years >= 4),
            "gate_stress": bool(stress_cagr > stress_equal_cagr),
            "gate_simultaneous_ci": bool(bootstrap["lower"][column] > 0),
        }
        for year in DEVELOPMENT_YEARS:
            row[f"active_{year}"] = (float(annual_active.loc[year, name])
                                    if year in annual_active.index else np.nan)
        row["gate_all"] = all(value for key, value in row.items() if key.startswith("gate_"))
        rows.append(row)

    comparison = pd.DataFrame(rows).sort_values(
        ["information_ratio", "candidate"], ascending=[False, True], na_position="last"
    ).reset_index(drop=True)
    comparison["development_rank"] = np.arange(1, len(comparison) + 1)
    comparison["selected_for_holdout"] = False
    comparison["selection_status"] = np.where(comparison["gate_all"], "eligible", "rejected")
    eligible = comparison.index[comparison["gate_all"]]
    selected_candidate = None
    if len(eligible):
        selected_index = eligible[0]
        comparison.loc[selected_index, "selected_for_holdout"] = True
        comparison.loc[selected_index, "selection_status"] = "eligible_selected"
        selected_candidate = str(comparison.loc[selected_index, "candidate"])
    else:
        comparison.loc[0, "selection_status"] = "best_development"

    bootstrap_info = {
        "method": "Joint circular-block max-t bootstrap with fixed bootstrap standard errors",
        "repetitions": BOOTSTRAP_REPETITIONS, "block_length_trading_days": BLOCK_LENGTH,
        "seed": BOOTSTRAP_SEED, "one_sided_alpha": ALPHA,
        "critical_max_t": bootstrap["critical_max_t"],
        "dates": len(equity), "first_date": equity.index[0].date().isoformat(),
        "last_date": equity.index[-1].date().isoformat(),
        "family_size": len(candidates), "candidate_order": candidates,
        "development_years_observed": [int(year) for year in annual.index],
        "all_six_development_years_present": complete_year_set,
        "first_return": "NAV_first - 1; initial wealth is 1 before the first observed date",
        "active_returns": "candidate daily net return minus equal-universe daily net return",
        "annual_returns": "calendar-year ending NAV divided by previous year-end NAV; initial denominator 1",
        "degenerate_candidates": [name for name, flag in zip(candidates, bootstrap["degenerate"]) if flag],
        "selected_candidate": selected_candidate,
        "best_development_candidate": str(comparison.loc[0, "candidate"]),
        "selection_rule": "Among candidates passing every gate, highest daily active information ratio; candidate name breaks ties",
        "bounds": {
            name: {"mean_daily_active": float(bootstrap["means"][j]),
                   "standard_error_daily": float(bootstrap["standard_errors"][j]),
                   "simultaneous_lower_daily": float(bootstrap["lower"][j])}
            for j, name in enumerate(candidates)
        },
        "limitations": [
            "The simultaneous bound covers this declared family only, not earlier adaptive research.",
            "Circular blocks assume historical dependence is informative and do not ensure regime stability.",
            "Known survivor-universe and revised-price limitations remain.",
            "Economic gate thresholds are prespecified research choices, not proof of future profitability.",
        ],
    }
    return comparison, bootstrap_info
