"""收盘评分、下一开盘等权交易的研究回测；价格必须是共同日历的调整开盘价。

调整价格仅为供应商历史收益代理，不是实际成交价或分红现金账本。
所有金额以初始权益 1 为单位；允许碎股，不允许借款或卖空。
"""

import numpy as np
import pandas as pd


def _check_dates(index, name):
    if (not isinstance(index, pd.DatetimeIndex) or index.tz is not None
            or index.hasnans or not index.is_unique
            or not index.is_monotonic_increasing
            or not index.equals(index.normalize())):
        raise ValueError(f"{name}: 需要无时区、无重复、升序的日级 DatetimeIndex。")


def _rebalance(old_values, cash, weights, cost_rate):
    """解扣费后的可投资净值，手续费根据实际漂移持仓的买卖金额计算。"""
    before = float(old_values.sum() + cash)
    low, high = 0.0, before
    # v + fee * sum(abs(v * weights - old_values)) = before
    # cost_rate < 1 时左侧单调；取下界可避免因舍入而借入现金。
    for _ in range(80):
        investable = (low + high) / 2
        fee = cost_rate * np.abs(investable * weights - old_values).sum()
        if investable + fee <= before:
            low = investable
        else:
            high = investable
    target = low * weights
    change = target - old_values
    fee = float(cost_rate * np.abs(change).sum())
    remaining_cash = float(before - target.sum() - fee)
    if remaining_cash < -1e-10:
        raise AssertionError("扣费后现金为负。")
    return target, max(0.0, remaining_cash), change, fee


def reduce_only(old_values, cash, weights, cost_rate):
    """风险减仓：按当前报价计算，任何股票目标金额都不能超过已有金额。

    权重是上限，不是需要双向追踪的目标。求解扣费后权益，并按现仓封顶；
    没有持仓的股票目标恒为0，卖出所得进入现金，不分配给其他股票。
    """
    old_values, weights = np.asarray(old_values, float), np.asarray(weights, float)
    if (old_values.shape != weights.shape or not np.isfinite(old_values).all()
            or not np.isfinite(weights).all() or (old_values < 0).any()
            or (weights < 0).any() or weights.sum() > 1 + 1e-10
            or not np.isfinite(cash) or cash < 0 or not 0 <= cost_rate < 1):
        raise ValueError("只减仓输入非法。")
    before = float(old_values.sum() + cash)
    low, high = 0., before
    for _ in range(80):
        nav = (low + high) / 2
        target = np.minimum(old_values, nav * weights)
        fee = float((old_values - target).sum() * cost_rate)
        if nav + fee <= before:
            low = nav
        else:
            high = nav
    target = np.minimum(old_values, low * weights)
    change = target - old_values
    fee = float(-change.sum() * cost_rate)
    remaining = float(cash - change.sum() - fee)
    assert (change <= 0).all() and remaining >= -1e-10
    return target, max(0., remaining), change, fee


def run_backtest(scores, adjusted_open, spy_open, start="2020-01-01",
                 end="2026-01-01", top_k=5, cost_bps=10,
                 rebalance_every=5, gross_exposure=None):
    """运行一个只做多、每次等权的固定交易日间隔组合。

    输入：scores 的行是收盘后可用的评分日期，列与 adjusted_open 完全一致；
    adjusted_open、spy_open 必须提供同一个完整交易日历的有限正价格。
    函数检查输入日历相同，不自行推断交易所假日，也绝不补价。

    start 包含观察日，end 不包含观察和出场日。首次观察锚定在 start 后
    第一个全部评分完整、能持有 rebalance_every 个开盘区间的交易日。
    此后始终沿价格日历每 rebalance_every 日观察；缺评分直接报错，不能
    压缩或移动日历。观察 t 的订单在 t+1 开盘执行，默认持有 5 个区间。

    top_k=None 表示全池等权；排序同分时使用预先确定的 ticker 字母顺序。
    gross_exposure 可指定观察日可知的股票总目标比例 [0,1]，余款留在零息现金；
    None 保持原满仓行为。函数不证明传入信号的历史可用性，调用方须核查。
    同日平旧仓和建新仓合并成实际净交易，费用包含首次建仓和末次清仓。
    daily_equity 首行收益包含首次建仓费，最后一行包含清仓费；回撤从
    费用发生前的初始权益 1 起算。SPY 仅校验共同日历，不用于评分。

    返回 daily_equity、periods、逐笔 trades 和 metrics；本函数不读写文件。
    """
    if not isinstance(scores, pd.DataFrame) or not isinstance(adjusted_open, pd.DataFrame):
        raise TypeError("scores 和 adjusted_open 必须是 DataFrame。")
    if not isinstance(spy_open, pd.Series):
        raise TypeError("spy_open 必须是 Series。")
    for table, name in ((scores, "scores"), (adjusted_open, "adjusted_open"),
                        (spy_open, "spy_open")):
        _check_dates(table.index, name)
    if adjusted_open.empty or scores.empty:
        raise ValueError("价格或评分为空。")
    if (not adjusted_open.columns.is_unique or not scores.columns.is_unique
            or not scores.columns.equals(adjusted_open.columns)
            or not all(isinstance(symbol, str) for symbol in scores.columns)):
        raise ValueError("评分与价格的股票列必须相同且顺序一致，ticker 必须为唯一字符串。")
    if not adjusted_open.index.equals(spy_open.index):
        raise ValueError("股票与 SPY 价格必须使用完全相同的交易日历。")
    if not scores.index.isin(adjusted_open.index).all():
        raise ValueError("评分包含价格日历以外的日期。")
    prices = adjusted_open.to_numpy(dtype=float)
    benchmark = spy_open.to_numpy(dtype=float)
    if (not np.isfinite(prices).all() or not np.isfinite(benchmark).all()
            or (prices <= 0).any() or (benchmark <= 0).any()):
        raise ValueError("调整开盘价格必须全部有限且大于零；禁止补价。")
    if (not isinstance(rebalance_every, int) or isinstance(rebalance_every, bool)
            or rebalance_every < 1):
        raise ValueError("rebalance_every 必须为正整数。")
    count = len(adjusted_open.columns)
    if top_k is not None and (not isinstance(top_k, int) or isinstance(top_k, bool)
                             or not 1 <= top_k <= count):
        raise ValueError("top_k 必须为 1 至股票数之间的整数，或 None。")
    if not np.isfinite(cost_bps) or not 0 <= cost_bps < 10000:
        raise ValueError("cost_bps 必须在 [0, 10000) 内。")
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    if start.tz is not None or end.tz is not None or start >= end:
        raise ValueError("start/end 必须无时区且 start < end。")

    calendar = adjusted_open.index
    tickers = adjusted_open.columns
    if gross_exposure is not None:
        if not isinstance(gross_exposure, pd.Series):
            raise TypeError("gross_exposure 必须为观察日索引的 Series。")
        _check_dates(gross_exposure.index, "gross_exposure")
        if not gross_exposure.index.equals(scores.index):
            raise ValueError("仓位比例日期必须与评分日期完全一致，不能填补或错位。")
        exposure_values = gross_exposure.to_numpy(dtype=float)
        if not np.isfinite(exposure_values).all() or ((exposure_values < 0) | (exposure_values > 1)).any():
            raise ValueError("仓位比例必须在 [0,1]，不允许缺失、借款或负仓位。")
        exposure_by_calendar = gross_exposure.reindex(calendar).to_numpy(dtype=float)
    score_values = scores.reindex(calendar).to_numpy(dtype=float)
    ready = np.isfinite(score_values).all(axis=1)
    # 提前排除不能在 end 之前完成全部持有区间的观察日。
    last_observation = int(calendar.searchsorted(end, side="left")) - rebalance_every - 2
    candidates = np.flatnonzero(ready & (calendar >= start))
    candidates = candidates[candidates <= last_observation]
    if not len(candidates):
        raise ValueError("区间内没有评分完整且能持有完整区间的观察日。")
    anchor = int(candidates[0])
    observations = list(range(anchor, last_observation + 1, rebalance_every))
    if not ready[observations].all():
        missing = calendar[np.array(observations)[~ready[observations]]]
        raise ValueError(f"固定调仓日期缺失完整评分，不能移动调仓日：{missing.strftime('%Y-%m-%d').tolist()}")

    units = np.zeros(count)
    cash = 1.0
    cost_rate = float(cost_bps) / 10000
    daily_rows, period_rows, trade_rows = [], [], []
    cumulative_cost = 0.0
    cumulative_notional = 0.0
    alphabet = np.argsort(tickers.to_numpy(), kind="stable")

    def append_trades(date, observation, kind, price, old_values, changes):
        for j in np.flatnonzero(np.abs(changes) > 1e-14):
            trade_rows.append(dict(
                Date=date, observation_date=observation, kind=kind,
                symbol=tickers[j], adjusted_open=float(price[j]),
                old_value=float(old_values[j]), new_value=float(old_values[j] + changes[j]),
                signed_notional=float(changes[j]), traded_notional=float(abs(changes[j])),
                signed_units=float(changes[j] / price[j]),
                cost=float(abs(changes[j]) * cost_rate),
            ))

    for number, observation in enumerate(observations):
        entry, exit_position = observation + 1, observation + 1 + rebalance_every
        old_values = units * prices[entry]
        start_equity = float(old_values.sum() + cash)
        if top_k is None:
            selected = alphabet
        else:
            # 先按字母，再稳定排序分数；并列不会受原文件行序影响。
            order = np.argsort(-score_values[observation, alphabet], kind="stable")
            selected = alphabet[order[:top_k]]
        weights = np.zeros(count)
        target_exposure = 1.0 if gross_exposure is None else float(exposure_by_calendar[observation])
        weights[selected] = target_exposure / len(selected)
        target, cash, changes, entry_cost = _rebalance(old_values, cash, weights, cost_rate)
        units = target / prices[entry]
        entry_notional = float(np.abs(changes).sum())
        cumulative_cost += entry_cost
        cumulative_notional += entry_notional
        append_trades(calendar[entry], calendar[observation], "rebalance", prices[entry], old_values, changes)
        invested_equity = float(target.sum() + cash)

        for position in range(entry, exit_position):
            invested = float((units * prices[position]).sum())
            daily_rows.append(dict(
                Date=calendar[position], equity=invested + cash, cash=cash,
                invested=invested, cost=entry_cost if position == entry else 0.0,
                traded_notional=entry_notional if position == entry else 0.0,
                cumulative_cost=cumulative_cost, cumulative_traded_notional=cumulative_notional,
            ))

        exit_values = units * prices[exit_position]
        exit_before_cost = float(exit_values.sum() + cash)
        exit_cost = 0.0
        exit_notional = 0.0
        if number == len(observations) - 1:
            exit_notional = float(exit_values.sum())
            exit_cost = exit_notional * cost_rate
            cash = exit_before_cost - exit_cost
            cumulative_cost += exit_cost
            cumulative_notional += exit_notional
            append_trades(calendar[exit_position], calendar[observation], "liquidation",
                          prices[exit_position], exit_values, -exit_values)
            units = np.zeros(count)
            daily_rows.append(dict(
                Date=calendar[exit_position], equity=cash, cash=cash, invested=0.0,
                cost=exit_cost, traded_notional=exit_notional,
                cumulative_cost=cumulative_cost, cumulative_traded_notional=cumulative_notional,
            ))
        end_equity = exit_before_cost - exit_cost
        period_rows.append(dict(
            observation_date=calendar[observation], entry_date=calendar[entry],
            exit_date=calendar[exit_position], holdings="|".join(tickers[selected]) if target_exposure > 0 else "",
            n_holdings=len(selected) if target_exposure > 0 else 0, start_equity=start_equity,
            target_gross_exposure=target_exposure,
            invested_equity=invested_equity, exit_equity_before_cost=exit_before_cost,
            end_equity=end_equity, entry_cost=entry_cost, exit_cost=exit_cost,
            total_cost=entry_cost + exit_cost,
            entry_traded_notional=entry_notional, exit_traded_notional=exit_notional,
            gross_return=exit_before_cost / invested_equity - 1,
            net_return=end_equity / start_equity - 1,
        ))

    daily = pd.DataFrame(daily_rows).set_index("Date")
    previous = daily["equity"].shift(1, fill_value=1.0)
    daily["daily_return"] = daily["equity"] / previous - 1
    high_watermark = daily["equity"].cummax().clip(lower=1.0)
    daily["drawdown"] = daily["equity"] / high_watermark - 1
    periods = pd.DataFrame(period_rows)
    trades = pd.DataFrame(trade_rows)
    if not daily.index.is_unique or (daily["cash"] < -1e-10).any():
        raise AssertionError("日线重复或现金为负。")
    expected_index = calendar[observations[0] + 1:observations[-1] + rebalance_every + 2]
    if not daily.index.equals(expected_index):
        raise AssertionError("组合估值日期没有覆盖完整交易日历。")
    if not np.isclose(np.prod(1 + periods["net_return"]), daily["equity"].iloc[-1], rtol=1e-11):
        raise AssertionError("持有区间净收益与日度净值无法复合对齐。")
    if not np.isclose(daily["cost"].sum(), cumulative_cost, rtol=1e-11, atol=1e-13):
        raise AssertionError("费用明细不一致。")

    elapsed_years = (daily.index[-1] - daily.index[0]).days / 365.25
    volatility = float(daily["daily_return"].std(ddof=1))
    metrics = dict(
        first_observation=calendar[anchor].strftime("%Y-%m-%d"),
        first_entry=daily.index[0].strftime("%Y-%m-%d"),
        final_exit=daily.index[-1].strftime("%Y-%m-%d"),
        total_return=float(daily["equity"].iloc[-1] - 1),
        cagr=float(daily["equity"].iloc[-1] ** (1 / elapsed_years) - 1),
        annualized_vol=volatility * np.sqrt(252),
        sharpe_zero_rf=(float(daily["daily_return"].mean()) / volatility * np.sqrt(252)
                        if volatility > 0 else None),
        max_drawdown=float(daily["drawdown"].min()),
        cumulative_traded_notional=cumulative_notional, total_cost=cumulative_cost,
        period_count=len(periods), daily_row_count=len(daily),
        initial_equity=1.0, final_equity=float(daily["equity"].iloc[-1]),
        cost_bps=float(cost_bps), rebalance_every=rebalance_every,
        top_k=top_k, universe_size=count,
        tie_break="ticker_alphabetical", risk_free_rate=0.0,
        price_basis="supplier_adjusted_open_return_proxy",
        daily_return_convention="first_row_includes_entry_cost_last_row_includes_liquidation_cost",
    )
    return dict(daily_equity=daily, periods=periods, trades=trades, metrics=metrics)


if __name__ == "__main__":
    print("这是纯函数模块。由研究脚本提供真实价格与评分后调用 run_backtest。")
