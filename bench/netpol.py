#!/usr/bin/env python3
"""NetworkPolicy scaling experiment (Deliverable 3).

For an up cluster with a CNI installed, apply a growing number of ingress
NetworkPolicy rules that all target the benchmark server pod, then measure the
cross-node throughput and HTTP latency that traffic still achieves through them,
plus the wall-clock time to apply the rules.

A single "allow-bench" policy always permits the benchmark client, so traffic
keeps flowing no matter how many noise rules are present (NetworkPolicy allow
rules are additive). The noise rules are many distinct ipBlock CIDRs that the
dataplane must compile and evaluate.

Flannel does not enforce NetworkPolicy, so it serves as a "no enforcement"
baseline: the rules apply to the API but cost nothing in the dataplane.

Output: results/raw-d3/netpol/<plugin>.jsonl
"""
import argparse, json, subprocess, sys, time, pathlib, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run  # reuse sh, kexec, ensure_pods, iperf_tcp, fortio_http

ALLOW = """apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-bench
  labels: {bench: netpol}
spec:
  podSelector:
    matchLabels: {role: server}
  policyTypes: [Ingress]
  ingress:
  - from:
    - podSelector:
        matchLabels: {role: client}
"""


def gen_policies(n_rules, cidrs_per_policy=50):
    """Multi-doc YAML: the allow policy + enough noise policies (each a bundle
    of ipBlock CIDRs targeting the server) to reach ~n_rules ingress rules."""
    docs = [ALLOW]
    made, pi = 0, 0
    while made < n_rules:
        take = min(cidrs_per_policy, n_rules - made)
        froms = "\n".join(
            f"    - ipBlock: {{cidr: 10.{((made + k) // 256) % 256}."
            f"{(made + k) % 256}.0/32}}"
            for k in range(take))
        docs.append(
            "apiVersion: networking.k8s.io/v1\n"
            "kind: NetworkPolicy\n"
            f"metadata:\n  name: noise-{pi}\n  labels: {{bench: netpol}}\n"
            "spec:\n  podSelector:\n    matchLabels: {role: server}\n"
            "  policyTypes: [Ingress]\n  ingress:\n  - from:\n" + froms + "\n")
        made += take
        pi += 1
    return "---\n".join(docs)


def clear_policies():
    subprocess.run(["kubectl", "delete", "networkpolicy", "-l", "bench=netpol",
                    "--ignore-not-found"], capture_output=True, text=True)


def apply_policies(yaml_str):
    """Apply the manifest, returning wall-clock seconds for the apply call."""
    t0 = time.time()
    r = subprocess.run(["kubectl", "apply", "-f", "-"], input=yaml_str,
                       text=True, capture_output=True)
    dt = time.time() - t0
    if r.returncode != 0:
        raise RuntimeError(f"policy apply failed: {r.stderr.strip()}")
    return dt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plugin", required=True)
    ap.add_argument("--levels", default="0,100,1000,2000",
                    help="comma-separated rule counts")
    ap.add_argument("--trials", type=int, default=5)
    ap.add_argument("--duration", type=int, default=8)
    ap.add_argument("--qps", type=int, default=500)
    ap.add_argument("--conns", type=int, default=8)
    args = ap.parse_args()
    levels = [int(x) for x in args.levels.split(",")]

    server_ip = run.ensure_pods()
    out = run.ROOT / "results" / "raw-d3" / "netpol" / f"{args.plugin}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)

    with out.open("w") as fh:
        def emit(obj):
            fh.write(json.dumps(obj) + "\n"); fh.flush()

        for rules in levels:
            clear_policies()
            apply_s = apply_policies(gen_policies(rules)) if rules >= 0 else 0.0
            # settle time for the dataplane to compile the policies (iptables/
            # ipset for Calico, eBPF maps for Cilium) before measuring
            time.sleep(8)
            print(f"[{args.plugin}] rules={rules} apply={apply_s:.2f}s",
                  file=sys.stderr)
            emit({"experiment": "netpol", "plugin": args.plugin, "rules": rules,
                  "trial": -1, "metric": "apply_time", "value": apply_s,
                  "unit": "s"})
            for t in range(args.trials):
                tcp = run.iperf_tcp("bench-client-b", server_ip, args.duration)
                http = run.fortio_http("bench-client-b", server_ip,
                                       args.duration, args.qps, args.conns)
                base = {"experiment": "netpol", "plugin": args.plugin,
                        "rules": rules, "trial": t}
                emit({**base, "metric": "throughput", "value": tcp["mbps"],
                      "unit": "Mbit/s"})
                emit({**base, "metric": "p50", "value": http["p50_ms"],
                      "unit": "ms"})
                emit({**base, "metric": "p99", "value": http["p99_ms"],
                      "unit": "ms"})
        clear_policies()
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
