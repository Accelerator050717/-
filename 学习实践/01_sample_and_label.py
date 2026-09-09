# 第 1 课：一条训练样本的特征 X 和标签 y。
# 运行：python 01_sample_and_label.py（Windows 也可使用 py）。
# 所有数字均为虚构，不是行情或模型预测；本文件不会联网或交易。
# 教学简化：无分红拆股，按指定开盘价成交，暂不计手续费与滑点。

# A. 决策时点：某个周五收盘后。下面两个价格此时已经知道。
past_close = 90.0       # 决策日之前第 5 个交易日的收盘价
signal_close = 99.0     # 决策日的收盘价

# B. 后来才发生的价格，只用于计算这个历史样本的答案。
stock_entry = 100.0     # 决策后的下一交易日开盘价
stock_exit = 98.0      # 入场再过 5 个交易日的开盘价
market_entry = 500.0    # 市场基准在相同入场时点的价格
market_exit = 510.0     # 市场基准在相同出场时点的价格

# C. 特征 X：这里只放一个特征，之后再逐步扩展。
X = {"past_return_5d": signal_close / past_close - 1}

# D. 标签 y：股票与市场在同一未来区间的简单收益率之差。
stock_return = stock_exit / stock_entry - 1
market_return = market_exit / market_entry - 1
y = stock_return - market_return

print(f"X：过去 5 个交易日收益 = {X['past_return_5d']:.2%}")
print(f"股票未来区间收益 = {stock_return:.2%}")
print(f"市场同期收益 = {market_return:.2%}")
print(f"y：未来超额收益 = {y * 100:.2f} 个百分点")

# 你的练习：先预测，再把 stock_exit 从 106.0 改成 98.0 并运行。
# 观察：X 会改变吗？股票收益和 y 各是多少？为什么？
