#!/usr/bin/env python3
"""Run speed / response-time / CPU benchmarks for one CNI plugin.

Assumes a kind cluster is up with a CNI installed and metrics-server running
(see scripts/setup-cluster.sh + cni/*.sh). Deploys the bench pods if needed,
then runs `--warmup` discarded trials followed by `--runs` measured trials.

Output: one JSON object per metric sample (long form) to
results/raw/<plugin>/run-<UTC>.jsonl, consumed by analyze.py.
"""
import argparse, json, subprocess, sys, time, datetime, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
BENCH_YAML = ROOT / "manifests" / "bench.yaml"

# How to find each plugin's dataplane agent pods (for per-node CPU attribution).
CNI_AGENT = {
    "flannel": ("kube-flannel", "app=flannel"),
    "calico":  ("calico-system", "k8s-app=calico-node"),
    "calico-bpf": ("calico-system", "k8s-app=calico-node"),
    "cilium":  ("kube-system", "k8s-app=cilium"),
}


def sh(args, timeout=120):
    """Run a command, return stdout; raise with context on failure."""
    r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"cmd failed ({r.returncode}): {' '.join(args)}\n{r.stderr.strip()}")
    return r.stdout


def kexec(pod, cmd, timeout=120):
    return sh(["kubectl", "exec", pod, "--"] + cmd, timeout=timeout)


def ensure_pods():
    sh(["kubectl", "apply", "-f", str(BENCH_YAML)])
    for pod in ("bench-server", "bench-client-a", "bench-client-b"):
        sh(["kubectl", "wait", "--for=condition=Ready", f"pod/{pod}", "--timeout=180s"])
    ip = sh(["kubectl", "get", "pod", "bench-server",
             "-o", "jsonpath={.status.podIP}"]).strip()
    if not ip:
        raise RuntimeError("bench-server has no pod IP")
    # iperf3/fortio servers start a moment after the pod is Ready.
    time.sleep(3)
    return ip


def node_names():
    out = sh(["kubectl", "get", "nodes", "-L", "benchrole", "--no-headers"])
    roles = {}
    for line in out.splitlines():
        f = line.split()
        if f and f[-1] in ("a", "b"):
            roles[f[-1]] = f[0]
    return roles  # {"a": nodename, "b": nodename}


# ---- individual measurements -------------------------------------------------

def iperf_tcp(client, server_ip, dur):
    j = json.loads(kexec(client, ["iperf3", "-c", server_ip, "-t", str(dur), "-J"],
                         timeout=dur + 30))
    end = j["end"]
    return {
        "mbps": end["sum_received"]["bits_per_second"] / 1e6,
        "retransmits": end["sum_sent"].get("retransmits", 0),
    }


def iperf_udp(client, server_ip, dur):
    # -b 0 = send as fast as possible (no artificial rate cap).
    j = json.loads(kexec(client, ["iperf3", "-c", server_ip, "-u", "-b", "0",
                                   "-t", str(dur), "-J"], timeout=dur + 30))
    s = j["end"]["sum"]
    return {
        "mbps": s["bits_per_second"] / 1e6,
        "lost_percent": s.get("lost_percent", 0.0),
        "jitter_ms": s.get("jitter_ms", 0.0),
    }


def fortio_http(client, server_ip, dur, qps, conns):
    out = kexec(client, ["fortio", "load", "-c", str(conns), "-qps", str(qps),
                         "-t", f"{dur}s", "-p", "50,99", "-quiet",
                         "-json", "-", f"http://{server_ip}:8080"],
                timeout=dur + 30)
    j = json.loads(out)
    pct = {p["Percentile"]: p["Value"] * 1000.0  # seconds -> ms
           for p in j["DurationHistogram"]["Percentiles"]}
    return {
        "p50_ms": pct.get(50),
        "p99_ms": pct.get(99),
        "qps": j["ActualQPS"],
    }


def node_cpu_millicores():
    """{nodename: cpu_millicores} from `kubectl top node`."""
    out = sh(["kubectl", "top", "node", "--no-headers"])
    cpu = {}
    for line in out.splitlines():
        f = line.split()
        if len(f) >= 2 and f[1].endswith("m"):
            cpu[f[0]] = int(f[1][:-1])
    return cpu


def cni_agent_cpu(plugin):
    """{nodename: cpu_millicores} for the CNI dataplane agent pods."""
    ns_sel = CNI_AGENT.get(plugin)
    if not ns_sel:
        return {}
    ns, sel = ns_sel
    try:
        wide = sh(["kubectl", "get", "pod", "-n", ns, "-l", sel, "-o",
                   "jsonpath={range .items[*]}{.metadata.name}{\" \"}{.spec.nodeName}{\"\\n\"}{end}"])
        pod_node = dict(l.split() for l in wide.splitlines() if l.strip())
        top = sh(["kubectl", "top", "pod", "-n", ns, "-l", sel, "--no-headers"])
    except RuntimeError:
        return {}
    out = {}
    for line in top.splitlines():
        f = line.split()
        if len(f) >= 2 and f[1].endswith("m") and f[0] in pod_node:
            out[pod_node[f[0]]] = int(f[1][:-1])
    return out


# ---- trial -------------------------------------------------------------------

def run_trial(plugin, trial, warmup, server_ip, nodes, args, emit):
    def row(test, path, metric, value, unit):
        emit({"plugin": plugin, "trial": trial, "warmup": warmup,
              "test": test, "path": path, "metric": metric,
              "value": value, "unit": unit})

    # Throughput: TCP same-node and cross-node, UDP cross-node.
    for path, client in (("same-node", "bench-client-a"),
                         ("cross-node", "bench-client-b")):
        t = iperf_tcp(client, server_ip, args.duration)
        row("iperf-tcp", path, "throughput", t["mbps"], "Mbit/s")
        row("iperf-tcp", path, "retransmits", t["retransmits"], "count")

    u = iperf_udp("bench-client-b", server_ip, args.duration)
    row("iperf-udp", "cross-node", "throughput", u["mbps"], "Mbit/s")
    row("iperf-udp", "cross-node", "loss", u["lost_percent"], "%")
    row("iperf-udp", "cross-node", "jitter", u["jitter_ms"], "ms")

    # Response time: HTTP p50/p99/QPS, cross-node. Node CPU sampled during load.
    cpu_before = node_cpu_millicores()
    h = fortio_http("bench-client-b", server_ip, args.duration, args.qps, args.conns)
    cpu_after = node_cpu_millicores()
    row("fortio-http", "cross-node", "p50", h["p50_ms"], "ms")
    row("fortio-http", "cross-node", "p99", h["p99_ms"], "ms")
    row("fortio-http", "cross-node", "qps", h["qps"], "req/s")

    # CPU: node-level (primary) + CNI agent (best effort), server node = "a".
    for role in ("a", "b"):
        n = nodes.get(role)
        if n and n in cpu_after:
            row("cpu", f"node-{role}", "node_cpu", cpu_after[n], "millicores")
    for n, m in cni_agent_cpu(plugin).items():
        role = next((r for r, nn in nodes.items() if nn == n), n)
        row("cpu", f"node-{role}", "cni_agent_cpu", m, "millicores")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plugin", required=True,
                    help="label for output (flannel|calico|calico-bpf|cilium)")
    ap.add_argument("--runs", type=int, default=10, help="measured trials")
    ap.add_argument("--warmup", type=int, default=2, help="discarded warmup trials")
    ap.add_argument("--duration", type=int, default=10, help="seconds per test")
    ap.add_argument("--qps", type=int, default=500, help="fortio target QPS")
    ap.add_argument("--conns", type=int, default=8, help="fortio concurrent connections")
    ap.add_argument("--out", default=None, help="output .jsonl path")
    args = ap.parse_args()

    server_ip = ensure_pods()
    nodes = node_names()
    print(f"server pod IP {server_ip}; nodes {nodes}", file=sys.stderr)

    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = pathlib.Path(args.out) if args.out else \
        ROOT / "results" / "raw" / args.plugin / f"run-{stamp}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)

    with out.open("w") as fh:
        def emit(obj):
            fh.write(json.dumps(obj) + "\n")

        total = args.warmup + args.runs
        for i in range(total):
            warmup = i < args.warmup
            trial = i - args.warmup  # measured trials start at 0
            tag = "warmup" if warmup else f"trial {trial + 1}/{args.runs}"
            print(f"[{args.plugin}] {tag}", file=sys.stderr)
            run_trial(args.plugin, trial, warmup, server_ip, nodes, args, emit)
            fh.flush()

    print(f"wrote {out}")


if __name__ == "__main__":
    main()
