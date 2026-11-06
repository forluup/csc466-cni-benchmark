#!/usr/bin/env bash
# Full benchmark matrix: for each plugin, build a fresh cluster, install the
# CNI + metrics-server, run the benchmark, then tear the cluster down. Finally
# aggregate everything. Each plugin gets an identical, isolated environment.
#
#   PLUGINS="flannel cilium" RUNS=10 ./scripts/run-all.sh
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLUSTER="${CLUSTER:-cni-bench}"
PLUGINS="${PLUGINS:-flannel calico cilium}"
RUNS="${RUNS:-10}"
WARMUP="${WARMUP:-2}"
# Prefer the venv python (has matplotlib for plots); fall back to system python3.
PY="$HERE/.venv/bin/python"; [ -x "$PY" ] || PY="python3"

install_cni() {
  case "$1" in
    flannel)    "$HERE/cni/flannel.sh" ;;
    calico)     "$HERE/cni/calico.sh" ;;
    calico-bpf) CALICO_DATAPLANE=BPF "$HERE/cni/calico.sh" ;;
    cilium)     "$HERE/cni/cilium.sh" ;;
    *) echo "unknown plugin: $1" >&2; return 1 ;;
  esac
}

for plugin in $PLUGINS; do
  echo "============================================================"
  echo " $plugin"
  echo "============================================================"
  kind delete cluster --name "$CLUSTER" >/dev/null 2>&1 || true
  "$HERE/scripts/setup-cluster.sh"
  install_cni "$plugin"
  "$HERE/cni/metrics-server.sh"
  echo "waiting 20s for metrics-server to collect a first sample..."
  sleep 20
  "$PY" "$HERE/bench/run.py" --plugin "$plugin" --runs "$RUNS" --warmup "$WARMUP"
  kind delete cluster --name "$CLUSTER" >/dev/null 2>&1 || true
done

"$PY" "$HERE/bench/analyze.py"
echo "done. see results/summary/"
