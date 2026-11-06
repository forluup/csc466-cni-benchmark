#!/usr/bin/env bash
# Calico via the Tigera operator. Default dataplane is iptables (Linux packet
# filtering); set CALICO_DATAPLANE=BPF to test the eBPF dataplane instead.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/common.sh"
VERSION="${CALICO_VERSION:-v3.29.1}"
DATAPLANE="${CALICO_DATAPLANE:-Iptables}"   # Iptables | BPF

kubectl create -f "https://raw.githubusercontent.com/projectcalico/calico/${VERSION}/manifests/tigera-operator.yaml"
kubectl -n tigera-operator rollout status deploy/tigera-operator --timeout=180s

kubectl apply -f - <<EOF
apiVersion: operator.tigera.io/v1
kind: Installation
metadata:
  name: default
spec:
  calicoNetwork:
    linuxDataplane: ${DATAPLANE}
    ipPools:
      - cidr: 10.244.0.0/16
        encapsulation: VXLANCrossSubnet
---
apiVersion: operator.tigera.io/v1
kind: APIServer
metadata:
  name: default
spec: {}
EOF

echo "waiting for calico-node daemonset..."
# calico-system is created by the operator a few seconds after the Installation CR.
for _ in $(seq 1 30); do
  kubectl -n calico-system get ds/calico-node >/dev/null 2>&1 && break || sleep 5
done
kubectl -n calico-system rollout status ds/calico-node --timeout=300s
wait_nodes_ready
echo "calico $VERSION ($DATAPLANE) ready"
