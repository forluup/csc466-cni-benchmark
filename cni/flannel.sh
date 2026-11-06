#!/usr/bin/env bash
# Flannel: simple VXLAN tunnel design. Default pod CIDR 10.244.0.0/16 matches
# the kind config, so no extra configuration is needed.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/common.sh"
VERSION="${FLANNEL_VERSION:-v0.26.3}"

# kind omits the reference `bridge` plugin that Flannel delegates to; install it.
kubectl apply -f "$HERE/cni-plugins.yaml"
kubectl -n kube-system rollout status ds/install-cni-plugins --timeout=120s

kubectl apply -f "https://github.com/flannel-io/flannel/releases/download/${VERSION}/kube-flannel.yml"
kubectl -n kube-flannel rollout status ds/kube-flannel-ds --timeout=300s
wait_nodes_ready
echo "flannel $VERSION ready"
