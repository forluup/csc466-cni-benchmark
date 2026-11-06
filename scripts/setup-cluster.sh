#!/usr/bin/env bash
# Create the kind cluster and label the two workers benchrole=a / benchrole=b
# so benchmark pods can be pinned deterministically (same-node vs cross-node).
# Nodes stay NotReady until a CNI is installed (see cni/*.sh).
set -euo pipefail
CLUSTER="${CLUSTER:-cni-bench}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if kind get clusters 2>/dev/null | grep -qx "$CLUSTER"; then
  echo "cluster '$CLUSTER' already exists; delete it first with: kind delete cluster --name $CLUSTER" >&2
  exit 1
fi

kind create cluster --name "$CLUSTER" --config "$HERE/cluster/kind-config.yaml"

# Label workers in a stable order (sorted by node name). bash 3.2 has no mapfile.
workers=$(kubectl get nodes --selector='!node-role.kubernetes.io/control-plane' \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' | sort)
worker_a=$(echo "$workers" | sed -n 1p)
worker_b=$(echo "$workers" | sed -n 2p)
if [ -z "$worker_a" ] || [ -z "$worker_b" ]; then
  echo "expected >=2 worker nodes, got: $workers" >&2
  exit 1
fi
kubectl label node "$worker_a" benchrole=a --overwrite
kubectl label node "$worker_b" benchrole=b --overwrite
echo "labeled $worker_a=a (server + same-node client), $worker_b=b (cross-node client)"
