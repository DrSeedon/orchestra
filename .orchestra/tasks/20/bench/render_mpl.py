"""Вариант A: matplotlib (Agg). Запускать интерпретатором scratch-venv с matplotlib."""
import datetime as dt
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.ticker import FuncFormatter

from cases import PALETTE

W, H, DPI = 1200, 750, 100
FS_TITLE, FS_SUB, FS_TICK, FS_VAL = 27, 19, 19, 18


def _fig():
    fig = plt.figure(figsize=(W / DPI, H / DPI), dpi=DPI, facecolor=PALETTE["bg"])
    return fig


def _head(fig, spec):
    fig.text(0.045, 0.945, spec["title"], color=PALETTE["ink"], fontsize=FS_TITLE,
             fontweight="bold", va="top")
    fig.text(0.045, 0.885, spec["subtitle"], color=PALETTE["ink_soft"], fontsize=FS_SUB, va="top")


def _axes(fig):
    ax = fig.add_axes([0.09, 0.14, 0.87, 0.66])
    ax.set_facecolor(PALETTE["bg"])
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(PALETTE["border"])
    ax.tick_params(colors=PALETTE["ink_faint"], labelsize=FS_TICK, length=0)
    ax.grid(axis="y", color=PALETTE["border"], alpha=0.35, linewidth=1)
    ax.set_axisbelow(True)
    return ax


def bars(spec, path, log=False):
    fig = _fig()
    _head(fig, spec)
    ax = _axes(fig)
    n = len(spec["series"])
    width = 0.8 / n
    xs = range(len(spec["categories"]))
    for i, s in enumerate(spec["series"]):
        off = (i - (n - 1) / 2) * width
        pos = [x + off for x in xs]
        ax.bar(pos, s["values"], width=width * 0.9, color=s["color"], label=s["name"], zorder=3)
        for x, v in zip(pos, s["values"]):
            ax.annotate(f"{v:g}", (x, v), textcoords="offset points", xytext=(0, 7),
                        ha="center", color=PALETTE["ink"], fontsize=FS_VAL, fontweight="bold")
    if log:
        ax.set_yscale("log")
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
    ax.set_xticks(list(xs))
    ax.set_xticklabels(spec["categories"])
    ax.set_ylabel(spec["unit"], color=PALETTE["ink_faint"], fontsize=FS_TICK)
    thr = spec.get("threshold")
    if thr:
        ax.axhline(thr["value"], color=PALETTE["warn"], linestyle="--", linewidth=2, zorder=4)
        ax.annotate(thr["label"], (len(spec["categories"]) - 0.45, thr["value"]),
                    color=PALETTE["warn"], fontsize=FS_VAL, va="bottom", ha="right")
    leg = ax.legend(loc="upper left", fontsize=FS_VAL, frameon=False, ncol=n)
    for t in leg.get_texts():
        t.set_color(PALETTE["ink_soft"])
    fig.savefig(path, facecolor=PALETTE["bg"])
    plt.close(fig)


def timeseries(spec, path):
    fig = _fig()
    _head(fig, spec)
    ax = _axes(fig)
    gap = dt.timedelta(minutes=spec["gap_minutes"])
    for s in spec["series"]:
        xs, ys = [], []
        prev = None
        for t, v in s["points"]:
            cur = dt.datetime.fromisoformat(t)
            if prev is not None and cur - prev > gap:
                xs.append(cur)          # разрыв: None в данных рвёт линию
                ys.append(float("nan"))
            xs.append(cur)
            ys.append(v)
            prev = cur
        ax.plot(xs, ys, color=s["color"], linewidth=2.4, label=s["name"])
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
    ax.xaxis.set_major_locator(mdates.DayLocator())
    ax.set_ylabel(spec["unit"], color=PALETTE["ink_faint"], fontsize=FS_TICK)
    ax.set_ylim(0, 105)
    leg = ax.legend(loc="upper left", fontsize=FS_VAL, frameon=False, ncol=2)
    for t in leg.get_texts():
        t.set_color(PALETTE["ink_soft"])
    fig.savefig(path, facecolor=PALETTE["bg"])
    plt.close(fig)


def scorecard(spec, path):
    fig = _fig()
    _head(fig, spec)
    m = spec["metrics"]
    for i, met in enumerate(m):
        x = 0.045 + i * (0.91 / len(m))
        fig.text(x, 0.60, met["value"], color=met["color"], fontsize=76, fontweight="bold", va="center")
        fig.text(x, 0.42, met["label"], color=PALETTE["ink_soft"], fontsize=FS_VAL, va="center")
        fig.text(x, 0.35, met["note"], color=PALETTE["ink_faint"], fontsize=FS_VAL - 2, va="center")
    fig.savefig(path, facecolor=PALETTE["bg"])
    plt.close(fig)


def render(name, spec, path):
    if spec["kind"] == "bars":
        bars(spec, path)
    elif spec["kind"] == "bars_log":
        bars(spec, path, log=True)
    elif spec["kind"] == "timeseries":
        timeseries(spec, path)
    else:
        scorecard(spec, path)


if __name__ == "__main__":
    import time
    from cases import all_cases
    out = sys.argv[1]
    cases = all_cases()
    for name, spec in cases.items():
        t0 = time.perf_counter()
        render(name, spec, f"{out}/mpl_{name}.png")
        print(f"{name}: {(time.perf_counter()-t0)*1000:.0f} ms")
