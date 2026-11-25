#!/usr/bin/env python3
"""Aggregate Deliverable 3 experiments into summary CSVs and plots.

Reads:
  results/raw-d3/netpol/*.jsonl   (NetworkPolicy scaling)
  results/raw-d3/netem/*.jsonl    (poor-connection)
  results/raw/<plugin>[-wg]/*.jsonl (WireGuard vs Deliverable-2 baseline)

Writes results/summary-d3/{netpol,netem,wireguard}.csv and comparison plots.
"""
import json, csv, math, statistics, collections, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAWD3 = ROOT / "results" / "raw-d3"
RAW = ROOT / "results" / "raw"
OUT = ROOT / "results" / "summary-d3"

T95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365,
       8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160,
       14: 2.145, 15: 2.131, 19: 2.093, 20: 2.086, 25: 2.060, 30: 2.042}


def t95(df):
    if df <= 0:
        return float("nan")
    return T95.get(df, 2.042 if df < 40 else 1.96)


def ci95(vals):
    n = len(vals)
    mean = statistics.fmean(vals)
    if n < 2:
        return mean, float("nan")
    return mean, t95(n - 1) * statistics.stdev(vals) / math.sqrt(n)


def load(globpath, keyfields, valuefilter=lambda r: not r.get("warmup")):
    groups = collections.defaultdict(list)
    for f in sorted(globpath):
        for line in f.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if not valuefilter(r):
                continue
            key = tuple(r[k] for k in keyfields)
            groups[key].append(r["value"])
    return groups


def mpl():
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        return plt
    except ImportError:
        return None


# ---- NetworkPolicy scaling --------------------------------------------------

def do_netpol():
    files = list((RAWD3 / "netpol").glob("*.jsonl"))
    if not files:
        return
    # apply_time rows have trial == -1; keep them, drop nothing by warmup
    g = load(files, ("plugin", "rules", "metric"), valuefilter=lambda r: True)
    rows = []
    for (plugin, rules, metric), vals in sorted(g.items()):
        mean, half = ci95(vals)
        rows.append([plugin, rules, metric, len(vals),
                     f"{mean:.3f}", f"{half:.3f}"])
    with (OUT / "netpol.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["plugin", "rules", "metric", "n", "mean", "ci95"])
        w.writerows(rows)
    print(f"wrote {OUT/'netpol.csv'} ({len(rows)} rows)")

    plt = mpl()
    if not plt:
        return
    plugins = sorted({r[0] for r in rows})
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    for metric, ax, yl in (("throughput", axes[0], "Mbit/s"),
                           ("apply_time", axes[1], "seconds")):
        for p in plugins:
            pts = sorted((rules, ci95(g[(p, rules, metric)]))
                         for (pp, rules, m) in g if pp == p and m == metric)
            if not pts:
                continue
            xs = [x for x, _ in pts]
            ys = [mc[0] for _, mc in pts]
            es = [0 if mc[1] != mc[1] else mc[1] for _, mc in pts]
            ax.errorbar(xs, ys, yerr=es, marker="o", capsize=3, label=p)
        ax.set_xlabel("NetworkPolicy rules")
        ax.set_ylabel(yl)
        ax.set_title("Throughput vs rule count" if metric == "throughput"
                     else "Rule apply time vs rule count")
        ax.legend()
    fig.tight_layout()
    fig.savefig(OUT / "netpol.png", dpi=120)
    print(f"wrote {OUT/'netpol.png'}")


# ---- netem ------------------------------------------------------------------

ORDER = ["baseline", "loss-1pct", "loss-5pct", "delay-50ms", "delay-100ms"]


def do_netem():
    files = list((RAWD3 / "netem").glob("*.jsonl"))
    if not files:
        return
    g = load(files, ("plugin", "condition", "metric"),
             valuefilter=lambda r: True)
    with (OUT / "netem.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["plugin", "condition", "metric", "n", "mean", "ci95"])
        for (plugin, cond, metric), vals in sorted(g.items()):
            mean, half = ci95(vals)
            w.writerow([plugin, cond, metric, len(vals),
                        f"{mean:.3f}", f"{half:.3f}"])
    print(f"wrote {OUT/'netem.csv'}")

    plt = mpl()
    if not plt:
        return
    plugins = sorted({k[0] for k in g})
    conds = [c for c in ORDER if any(k[1] == c for k in g)]
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
    for metric, ax, yl in (("throughput", axes[0], "Mbit/s"),
                           ("retransmits", axes[1], "count")):
        x = range(len(conds))
        w = 0.8 / max(len(plugins), 1)
        for i, p in enumerate(plugins):
            means = [ci95(g[(p, c, metric)])[0] if (p, c, metric) in g else 0
                     for c in conds]
            errs = [ci95(g[(p, c, metric)])[1] if (p, c, metric) in g else 0
                    for c in conds]
            errs = [0 if e != e else e for e in errs]
            ax.bar([xi + i * w for xi in x], means, w, yerr=errs, capsize=2,
                   label=p)
        ax.set_xticks([xi + 0.4 - w / 2 for xi in x])
        ax.set_xticklabels(conds, rotation=20, ha="right")
        ax.set_ylabel(yl)
        ax.set_title("Throughput under netem (CUBIC)" if metric == "throughput"
                     else "TCP retransmits under netem (CUBIC)")
        ax.legend()
    fig.tight_layout()
    fig.savefig(OUT / "netem.png", dpi=120)
    print(f"wrote {OUT/'netem.png'}")


# ---- WireGuard --------------------------------------------------------------

def _plugin_metric(plugin, test, path, metric):
    d = RAW / plugin
    if not d.exists():
        return None
    vals = []
    for f in d.glob("*.jsonl"):
        for line in f.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if (not r.get("warmup") and r["test"] == test
                    and r["path"] == path and r["metric"] == metric):
                vals.append(r["value"])
    return ci95(vals) if vals else None


def do_wireguard():
    pairs = [("cilium", "cilium-wg"), ("calico", "calico-wg")]
    rows = []
    for base, wg in pairs:
        for test, path, metric, unit in (
                ("iperf-tcp", "same-node", "throughput", "Mbit/s"),
                ("iperf-tcp", "cross-node", "throughput", "Mbit/s"),
                ("cpu", "node-a", "node_cpu", "millicores"),
                ("cpu", "node-b", "node_cpu", "millicores")):
            b = _plugin_metric(base, test, path, metric)
            e = _plugin_metric(wg, test, path, metric)
            if not b or not e:
                continue
            overhead = ((e[0] - b[0]) / b[0] * 100.0) if b[0] else float("nan")
            rows.append([base, f"{test}/{path}", metric, unit,
                         f"{b[0]:.2f}", f"{e[0]:.2f}", f"{overhead:+.1f}"])
    if not rows:
        return
    with (OUT / "wireguard.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["plugin", "test", "metric", "unit",
                    "plain", "wireguard", "change_%"])
        w.writerows(rows)
    print(f"wrote {OUT/'wireguard.csv'} ({len(rows)} rows)")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    do_netpol()
    do_netem()
    do_wireguard()


if __name__ == "__main__":
    main()
