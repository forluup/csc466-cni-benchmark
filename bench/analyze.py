#!/usr/bin/env python3
"""Aggregate raw benchmark trials into a summary (mean + 95% CI) and plots.

Reads every results/raw/**/*.jsonl, drops warmup trials, groups by
(plugin, test, path, metric), and writes results/summary/summary.csv plus
a few comparison bar charts (error bars = 95% CI).
"""
import json, csv, math, statistics, pathlib, collections

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "results" / "raw"
SUMMARY = ROOT / "results" / "summary"

# two-sided 95% Student-t critical values by degrees of freedom (n-1)
T95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365,
       8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160,
       14: 2.145, 15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093,
       20: 2.086, 25: 2.060, 30: 2.042}


def t95(df):
    if df <= 0:
        return float("nan")
    if df in T95:
        return T95[df]
    return 2.042 if df < 40 else 1.96  # large-sample approximation


def ci95(values):
    n = len(values)
    mean = statistics.fmean(values)
    if n < 2:
        return mean, float("nan")
    half = t95(n - 1) * statistics.stdev(values) / math.sqrt(n)
    return mean, half


def load():
    groups = collections.defaultdict(list)  # (plugin,test,path,metric,unit) -> [values]
    for f in sorted(RAW.rglob("*.jsonl")):
        for line in f.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("warmup"):
                continue
            key = (r["plugin"], r["test"], r["path"], r["metric"], r["unit"])
            groups[key].append(r["value"])
    return groups


def write_summary(groups):
    SUMMARY.mkdir(parents=True, exist_ok=True)
    path = SUMMARY / "summary.csv"
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["plugin", "test", "path", "metric", "unit",
                    "n", "mean", "ci95", "min", "max"])
        for key in sorted(groups):
            plugin, test, p, metric, unit = key
            vals = groups[key]
            mean, half = ci95(vals)
            w.writerow([plugin, test, p, metric, unit, len(vals),
                        f"{mean:.3f}", f"{half:.3f}",
                        f"{min(vals):.3f}", f"{max(vals):.3f}"])
    print(f"wrote {path} ({len(groups)} rows)")
    return path


def plot(groups):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not installed; skipping plots "
              "(pip install -r bench/requirements.txt)")
        return

    def plugins_for(sel):
        return sorted({k[0] for k in groups if sel(k)})

    def bar(ax, title, ylabel, series):
        # series: list of (label, {plugin: (mean, ci)})
        plugins = sorted({p for _, d in series for p in d})
        x = range(len(plugins))
        w = 0.8 / max(len(series), 1)
        for i, (label, d) in enumerate(series):
            means = [d.get(p, (0, 0))[0] for p in plugins]
            errs = [d.get(p, (0, float("nan")))[1] for p in plugins]
            errs = [0 if (e != e) else e for e in errs]  # NaN -> 0
            ax.bar([xi + i * w for xi in x], means, w, yerr=errs,
                   capsize=3, label=label)
        ax.set_xticks([xi + 0.4 - w / 2 for xi in x])
        ax.set_xticklabels(plugins)
        ax.set_title(title)
        ax.set_ylabel(ylabel)
        if len(series) > 1:
            ax.legend()

    def agg(test, path, metric):
        return {k[0]: ci95(groups[k]) for k in groups
                if k[1] == test and k[2] == path and k[3] == metric}

    panels = [
        ("TCP throughput", "Mbit/s",
         [("same-node", agg("iperf-tcp", "same-node", "throughput")),
          ("cross-node", agg("iperf-tcp", "cross-node", "throughput"))]),
        ("HTTP latency (cross-node)", "ms",
         [("p50", agg("fortio-http", "cross-node", "p50")),
          ("p99", agg("fortio-http", "cross-node", "p99"))]),
        ("Node CPU during load", "millicores",
         [("node-a (server)", agg("cpu", "node-a", "node_cpu")),
          ("node-b (client)", agg("cpu", "node-b", "node_cpu"))]),
    ]
    panels = [p for p in panels if any(d for _, d in p[2])]
    if not panels:
        print("no data to plot")
        return

    fig, axes = plt.subplots(1, len(panels), figsize=(5 * len(panels), 4))
    if len(panels) == 1:
        axes = [axes]
    for ax, (title, yl, series) in zip(axes, panels):
        bar(ax, title, yl, series)
    fig.tight_layout()
    out = SUMMARY / "comparison.png"
    fig.savefig(out, dpi=120)
    print(f"wrote {out}")


def main():
    groups = load()
    if not groups:
        print(f"no measured trials found under {RAW}")
        return
    write_summary(groups)
    plot(groups)


if __name__ == "__main__":
    main()
