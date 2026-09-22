"""Draw two fixed v16 evidence charts from local derived CSVs; no market access."""
import csv
import calendar
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from matplotlib.ticker import FuncFormatter

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/experiments/momentum_loss_attribution_v16"


def main():
    with (OUT / "monthly_pnl.csv").open(encoding="utf-8") as f:
        months = list(csv.DictReader(f))
    with (OUT / "security_total_pnl.csv").open(encoding="utf-8") as f:
        stocks = list(csv.DictReader(f))
    font_path = Path("C:/Windows/Fonts/msyh.ttc")
    if not font_path.exists():
        raise FileNotFoundError("Chinese chart font not found; reuse saved image or install/configure a font")
    font = FontProperties(fname=str(font_path))
    plt.rcParams.update({"axes.spines.top": False, "axes.spines.right": False,
                         "font.size": 10, "axes.unicode_minus": False})
    fig, (nav, bars) = plt.subplots(1, 2, figsize=(14, 6), gridspec_kw={"width_ratios": [1.35, 1]})
    dates = [datetime(2021, 12, 31)]
    for r in months:
        year, month = map(int, r["month"].split("-"))
        dates.append(datetime(year, month, calendar.monthrange(year, month)[1]))
    b = [100000.] + [float(r["end_equity"]) for r in months]
    c = [100000.]
    for r in months:
        c.append(c[-1] * (1 + float(r["spy_net_return"])))
    nav.plot(dates, c, color="#35668c", label="C10 SPY", lw=2)
    nav.plot(dates, b, color="#bd4040", label="B10 Momentum", lw=2.6)
    nav.axhline(100000, color="#c5c5c5", linestyle="--", lw=.8)
    nav.set_title("同口径月末权益：10万美元到4.59万美元", fontproperties=font, fontsize=14)
    nav.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"${v/1000:,.0f}k"))
    nav.grid(axis="y", alpha=.2)
    nav.legend(frameon=False)
    nav.annotate(f"${b[-1]:,.2f}", (dates[-1], b[-1]), xytext=(-90, -22), textcoords="offset points", color="#bd4040", bbox={"facecolor": "white", "edgecolor": "none", "alpha": .9, "pad": 1})
    nav.annotate(f"${c[-1]:,.2f}", (dates[-1], c[-1]), xytext=(-90, 10), textcoords="offset points", color="#35668c")
    selected = sorted(stocks, key=lambda x: float(x["net_pnl"]))[:10]
    selected.append(max(stocks, key=lambda x: float(x["net_pnl"])))
    labels = ["META (SID: FB)" if r["latest_observed_ticker"] == "FB" else r["latest_observed_ticker"] for r in selected]
    values = [float(r["net_pnl"]) for r in selected]
    bars.barh(labels, values, color=["#bd4040" if v < 0 else "#328067" for v in values])
    bars.invert_yaxis()
    bars.axvline(0, color="#555", lw=.7)
    bars.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"${v/1000:,.0f}k"))
    bars.set_title("净损益：前十亏损来源与最大赢家", fontproperties=font, fontsize=14)
    bars.grid(axis="x", alpha=.15)
    fig.text(.03, .02, "2022—2023开发历史；含费用和引擎股息。C10复用原成交的同收盘参考；月点不展示日内/日度回撤。", fontproperties=font, fontsize=10, color="#555")
    fig.tight_layout(rect=(0, .06, 1, 1))
    fig.savefig(OUT / "loss_attribution.png", dpi=170)
    plt.close(fig)
    print("Wrote loss_attribution.png from saved v16 monthly and security CSVs")


if __name__ == "__main__":
    main()
