#!/usr/bin/env python3
"""Poor-connection experiment using tc netem (Deliverable 3).

Applies packet loss / delay to the cross-node client's egress interface, then
measures the TCP throughput and the time to complete a fixed-size transfer to
the benchmark server. Congestion control is pinned to CUBIC (iperf3 -C cubic);
BBR is not available in the Docker Desktop VM kernel, so the CUBIC-vs-BBR
comparison is documented as an environment limitation rather than run here.

Requires the bench-netem-client pod (manifests/netem-client.yaml), which has
NET_ADMIN so it can program its own qdisc.

Output: results/raw-d3/netem/<plugin>.jsonl
"""
import argparse, json, sys, time, pathlib, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run  # reuse sh, kexec, ensure_pods

CLIENT = "bench-netem-client"
NETEM_YAML = run.ROOT / "manifests" / "netem-client.yaml"

# name -> tc netem argument list ("" = clear qdisc / clean link)
CONDITIONS = {
    "baseline":  "",
    "loss-1pct": "loss 1%",
    "loss-5pct": "loss 5%",
    "delay-50ms": "delay 50ms",
    "delay-100ms": "delay 100ms",
}


def set_netem(spec):
    # replace is idempotent whether or not a qdisc already exists
    if spec:
        run.kexec(CLIENT, ["tc", "qdisc", "replace", "dev", "eth0", "root",
                           "netem"] + spec.split())
    else:
        run.kexec(CLIENT, ["tc", "qdisc", "del", "dev", "eth0", "root"],
                  timeout=30)


def iperf_cubic(server_ip, dur, retries=4):
    """TCP throughput + retransmits under CUBIC for a timed run. Retransmits
    isolate the loss response: near-zero on a clean or delay-only link, large
    under packet loss as CUBIC repeatedly backs off and recovers.

    Under heavy loss the server's teardown lags, so a back-to-back test can hit
    iperf3's "the server is busy" refusal (exit 1); retry a few times."""
    for attempt in range(retries):
        try:
            j = json.loads(run.kexec(CLIENT, ["iperf3", "-c", server_ip,
                                              "-C", "cubic", "-t", str(dur),
                                              "-J"], timeout=dur + 30))
            end = j["end"]
            return (end["sum_received"]["bits_per_second"] / 1e6,
                    end["sum_sent"].get("retransmits", 0))
        except RuntimeError:
            if attempt == retries - 1:
                raise
            time.sleep(3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plugin", required=True)
    ap.add_argument("--trials", type=int, default=5)
    ap.add_argument("--duration", type=int, default=8)
    args = ap.parse_args()

    server_ip = run.ensure_pods()
    run.sh(["kubectl", "apply", "-f", str(NETEM_YAML)])
    # generous cap: the netem client may also pull netshoot on a fresh node
    run.sh(["kubectl", "wait", "--for=condition=Ready", f"pod/{CLIENT}",
            "--timeout=300s"], timeout=320)

    out = run.ROOT / "results" / "raw-d3" / "netem" / f"{args.plugin}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)

    with out.open("w") as fh:
        def emit(obj):
            fh.write(json.dumps(obj) + "\n"); fh.flush()

        for cond, spec in CONDITIONS.items():
            try:
                set_netem(spec)
            except RuntimeError as e:
                # clearing a non-existent qdisc errors harmlessly on baseline
                if "del" not in str(e):
                    raise
            print(f"[{args.plugin}] netem={cond or 'clean'}", file=sys.stderr)
            for t in range(args.trials):
                mbps, retr = iperf_cubic(server_ip, args.duration)
                time.sleep(1)  # let the iperf3 server free up between tests
                base = {"experiment": "netem", "plugin": args.plugin,
                        "condition": cond, "trial": t}
                emit({**base, "metric": "throughput", "value": mbps,
                      "unit": "Mbit/s"})
                emit({**base, "metric": "retransmits", "value": retr,
                      "unit": "count"})
        # leave the link clean
        try:
            set_netem("")
        except RuntimeError:
            pass
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
