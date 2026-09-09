"""用已保存的净值画研究图；使用本项目含 matplotlib 的 .venv 解释器。"""
from pathlib import Path
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.ticker import PercentFormatter
import pandas as pd

root = Path(__file__).resolve().parent
font_path = Path("C:/Windows/Fonts/msyh.ttc")
if font_path.exists():
    font_manager.fontManager.addfont(str(font_path))
    plt.rcParams["font.family"] = font_manager.FontProperties(fname=str(font_path)).get_name()
plt.rcParams["axes.unicode_minus"] = False
equity = pd.read_csv(root / "final_evaluation/all_equity.csv", float_precision="round_trip",
                     index_col="Date", parse_dates=["Date"])
metrics = json.loads((root / "final_evaluation/cost_metrics.json").read_text(encoding="utf-8"))
series = [
    ("m16_elastic_rank", "ElasticNet名次回归", "#2563eb"),
    ("e30_ranker_ensemble", "排序模型集成", "#a855f7"),
    ("benchmark_equal", "同池30股等权", "#0f766e"),
    ("benchmark_spy", "SPY", "#64748b"),
]
fig, (top, bottom) = plt.subplots(2, 1, figsize=(12, 8), sharex=True,
                                gridspec_kw={"height_ratios": [1.6, 1]})
fig.patch.set_facecolor("#f8fafc")
for name, label, color in series:
    values = equity[name]
    top.plot(values.index, values, color=color, linewidth=1.7,
             label=f"{label}  年化{metrics[name]['cagr']:.2%}")
    drawdown = values / values.cummax().clip(lower=1.0) - 1.0
    bottom.plot(values.index, drawdown, color=color, linewidth=1.15)
top.set_ylabel("净值（初始资金=1）")
top.legend(loc="upper left", frameon=False, fontsize=10)
bottom.set_ylabel("相对历史高点回撤")
bottom.yaxis.set_major_formatter(PercentFormatter(1))
for axis in (top, bottom):
    axis.set_facecolor("white")
    axis.grid(alpha=0.15)
    axis.spines[["top", "right"]].set_visible(False)
fig.suptitle("收益更高，仍未确认稳定优势", fontsize=19, x=0.095, ha="left", y=0.975)
fig.text(0.095, 0.922, "2020—2025滚动开发评价 · 当前存续30股池 · 买卖各10bp · 下一开盘执行", fontsize=10, color="#475569")
fig.text(0.095, 0.025, "此图来自已研究过的历史数据。32候选均未通过全部门槛；2026尚未使用。回撤按每日开盘估值，非盘中回撤。", fontsize=9, color="#475569")
fig.subplots_adjust(top=0.885, bottom=0.09, left=0.095, right=0.97, hspace=0.14)
fig.savefig(root / "equity_and_drawdown.png", dpi=180, facecolor=fig.get_facecolor())
fig.savefig(root / "equity_and_drawdown.svg", facecolor=fig.get_facecolor())
plt.close(fig)
print("Saved equity_and_drawdown.png and .svg from frozen final NAV.")
