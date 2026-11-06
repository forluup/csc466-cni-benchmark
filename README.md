# CSC 466 — Kubernetes CNI Data-Plane Benchmark

Comparing **Flannel**, **Calico**, and **Cilium** on a local `kind` cluster:
speed (iperf3), response time (fortio), and processor use (`kubectl top`), with
repeated runs and 95% confidence intervals.

See `docs/ENVIRONMENT.md` for the recorded testbed and known limitations.

## Prerequisites

- Docker running, `kubectl`, and `kind` (`~/.local/bin/kind`) on `PATH`.
- `python3` with matplotlib for plots: `pip install -r bench/requirements.txt`.
- No host Helm / benchmark tools needed: CNIs install from manifests (Cilium is
  rendered with a throwaway `alpine/helm` container) and the load tools run
  inside pods.

## Quick start — one plugin

```bash
./scripts/setup-cluster.sh            # create cluster, label workers a/b
./cni/flannel.sh                      # or calico.sh / cilium.sh
./cni/metrics-server.sh
python3 bench/run.py --plugin flannel --runs 10 --warmup 2
kind delete cluster --name cni-bench
```

## Full matrix — all plugins

Fresh isolated cluster per plugin, then aggregate:

```bash
PLUGINS="flannel calico cilium" RUNS=10 ./scripts/run-all.sh
```

Outputs:
- `results/raw/<plugin>/run-<UTC>.jsonl` — one JSON object per metric sample.
- `results/summary/summary.csv` — mean, 95% CI, min/max per metric.
- `results/summary/comparison.png` — throughput / latency / CPU bar charts.

## What is measured

| Experiment | Tool | Paths | Metrics |
|------------|------|-------|---------|
| Bulk transfer | iperf3 TCP | same-node, cross-node | throughput (Mbit/s), retransmits |
| Bulk transfer | iperf3 UDP | cross-node | throughput, loss %, jitter |
| Response time | fortio HTTP | cross-node | p50, p99 latency (ms), QPS |
| Processor use | `kubectl top` | node a / b | node CPU + CNI-agent CPU (millicores) |

Warm-up trials (`--warmup`) are discarded. Each measured trial runs every test
once; `--runs` controls how many measured trials.

## Layout

```
cluster/kind-config.yaml   1 control + 2 workers, default CNI disabled
scripts/setup-cluster.sh   create cluster, label workers benchrole=a/b
scripts/run-all.sh         full matrix driver
cni/{flannel,calico,cilium,metrics-server}.sh
manifests/bench.yaml       server + same/cross-node client pods (netshoot)
bench/run.py               orchestrator (repeated runs -> JSONL)
bench/analyze.py           mean + 95% CI -> summary.csv + plots
docs/ENVIRONMENT.md        testbed log
```

## Scope

This repo covers **deliverable 2** (automated speed / response-time / CPU across
all plugins, repeated runs). NetworkPolicy scaling, `tc netem` poor-connection
tests, CUBIC-vs-BBR, and WireGuard belong to deliverable 3. Note BBR is absent
from the current Docker Desktop kernel (see `docs/ENVIRONMENT.md`).
