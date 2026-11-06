# Environment Log

Testbed used for all benchmark runs. Record changes here (logbook requirement).

## Host

| Item | Value |
|------|-------|
| Machine | Apple Silicon (arm64) laptop, macOS (Darwin 25.6.0) |
| Container runtime | Docker Desktop, server 29.8.0 |
| kind | v0.30.0 (Kubernetes in Docker) |
| kubectl | client v1.36.1 |
| Python | 3.13.5 |
| Helm | not installed on host — Cilium chart rendered via `alpine/helm` container |

## Docker Desktop Linux VM (where kind nodes actually run)

| Capability | Status | Notes |
|------------|--------|-------|
| Kernel | `7.0.12-linuxkit aarch64` | all kind nodes share this one kernel |
| BPF filesystem | present | Cilium eBPF dataplane works |
| WireGuard module | present | available for deliverable-3 encrypted runs |
| TCP congestion control | `reno`, `cubic` only | **BBR is NOT available** in this kernel |

> **BBR caveat:** the CUBIC-vs-BBR comparison (deliverable 3) cannot run on this
> Docker Desktop kernel as-is — `tcp_bbr` is not built in and cannot be
> `modprobe`d. Options for later: a Lima/Colima VM with a BBR-capable kernel, or
> run that experiment on a Linux host. Deliverable 2 only needs CUBIC (default),
> so it is unaffected.

## Cluster topology

- 1 control-plane + 2 workers (`cluster/kind-config.yaml`), default CNI disabled.
- Workers labeled `benchrole=a` and `benchrole=b` by `scripts/setup-cluster.sh`.
- Benchmark server + same-node client pinned to node **a**; cross-node client on node **b**.
- Pod CIDR `10.244.0.0/16` for all plugins.

## Plugin / image versions

| Component | Version | Source |
|-----------|---------|--------|
| Flannel | v0.26.3 | GitHub release manifest |
| Calico | v3.29.1 | Tigera operator (Iptables default; `CALICO_DATAPLANE=BPF` for eBPF) |
| Cilium | 1.16.5 | Helm chart, `ipam.mode=kubernetes`, kube-proxy kept |
| metrics-server | latest | `--kubelet-insecure-tls` (kind self-signed kubelet certs) |
| Benchmark image | `nicolaka/netshoot:latest` | ships iperf3 + fortio (arm64) |

## Known limitations

- All simulated nodes share one kernel; traffic crosses software veth links, not
  a real NIC. Absolute speeds are not comparable to hardware — results are
  **plugin-vs-plugin comparisons** on identical conditions.
- CPU is measured via metrics-server (`kubectl top`, ~15 s window), so it is a
  coarse average, not an instantaneous per-transfer figure.
- `netperf` is not in the netshoot image; HTTP response time is measured with
  `fortio` (p50/p99/QPS), which covers the response-time metric. netperf TCP_RR
  can be added later with a dedicated image if a second latency tool is wanted.
