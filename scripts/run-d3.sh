#!/usr/bin/env bash
# Deliverable 3 matrix: NetworkPolicy scaling, poor-connection (netem), and
# WireGuard encryption. Each plugin gets a fresh, isolated cluster.
#
#   NetworkPolicy + netem run on a plain cluster per plugin (flannel/calico/cilium).
#   WireGuard runs on a separate encrypted cluster for the plugins that support it
#   (cilium, calico); the non-encrypted baseline comes from Deliverable 2.
#
#   RULE_TRIALS=5 NETEM_TRIALS=5 ./scripts/run-d3.sh
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLUSTER="${CLUSTER:-cni-bench}"
PLUGINS="${PLUGINS:-flannel calico cilium}"
WG_PLUGINS="${WG_PLUGINS:-cilium calico}"
RULE_TRIALS="${RULE_TRIALS:-5}"
NETEM_TRIALS="${NETEM_TRIALS:-5}"
WG_RUNS="${WG_RUNS:-8}"
PY="$HERE/.venv/bin/python"; [ -x "$PY" ] || PY="python3"

install_cni() {
  case "$1" in
    flannel) "$HERE/cni/flannel.sh" ;;
    calico)  "$HERE/cni/calico.sh" ;;
    cilium)  "$HERE/cni/cilium.sh" ;;
    *) echo "unknown plugin: $1" >&2; return 1 ;;
  esac
}

fresh_cluster() {  # $1=plugin, extra env (e.g. WIREGUARD=1) inherited
  kind delete cluster --name "$CLUSTER" >/dev/null 2>&1 || true
  "$HERE/scripts/setup-cluster.sh"
  install_cni "$1"
  "$HERE/cni/metrics-server.sh"
  echo "waiting 20s for first metrics sample..."; sleep 20
}

failed=""

# --- NetworkPolicy scaling + netem (plain clusters) --------------------------
for plugin in $PLUGINS; do
  echo "============================================================"
  echo " $plugin : NetworkPolicy scaling + netem"
  echo "============================================================"
  if fresh_cluster "$plugin" \
     && "$PY" "$HERE/bench/netpol.py" --plugin "$plugin" --trials "$RULE_TRIALS" \
     && "$PY" "$HERE/bench/netem.py"  --plugin "$plugin" --trials "$NETEM_TRIALS"; then
    :
  else
    echo "!! $plugin (netpol/netem) FAILED" >&2; failed="$failed $plugin"
  fi
  kind delete cluster --name "$CLUSTER" >/dev/null 2>&1 || true
done

# --- WireGuard (encrypted clusters) ------------------------------------------
for plugin in $WG_PLUGINS; do
  echo "============================================================"
  echo " $plugin : WireGuard encryption"
  echo "============================================================"
  if WIREGUARD=1 fresh_cluster "$plugin" \
     && "$PY" "$HERE/bench/run.py" --plugin "${plugin}-wg" --runs "$WG_RUNS" --warmup 2; then
    :
  else
    echo "!! ${plugin}-wg FAILED" >&2; failed="$failed ${plugin}-wg"
  fi
  kind delete cluster --name "$CLUSTER" >/dev/null 2>&1 || true
done

"$PY" "$HERE/bench/analyze_d3.py"
echo "done. see results/summary-d3/"
[ -n "$failed" ] && { echo "FAILED:$failed" >&2; exit 1; }
echo "all D3 experiments succeeded"
