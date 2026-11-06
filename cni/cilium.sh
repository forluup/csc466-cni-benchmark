#!/usr/bin/env bash
# Cilium (eBPF dataplane). Cilium no longer ships a standalone install manifest,
# so we render the Helm chart with a throwaway container (no host Helm needed)
# and apply it with kubectl. Minimal kind values: kubernetes IPAM + keep images
# that kind already loaded. kube-proxy is left in place for a fair comparison.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/common.sh"
VERSION="${CILIUM_VERSION:-1.16.5}"
RENDERED="$HERE/.cilium-rendered.yaml"

docker run --rm --entrypoint sh alpine/helm -c "
  helm repo add cilium https://helm.cilium.io >/dev/null 2>&1
  helm template cilium cilium/cilium --version ${VERSION} --namespace kube-system \
    --set ipam.mode=kubernetes \
    --set image.pullPolicy=IfNotPresent
" > "$RENDERED"

kubectl apply -f "$RENDERED"
kubectl -n kube-system rollout status ds/cilium --timeout=300s
wait_nodes_ready
echo "cilium $VERSION ready"
