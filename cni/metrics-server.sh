#!/usr/bin/env bash
# metrics-server provides `kubectl top` (pod/node CPU). kind kubelets use
# self-signed certs, so --kubelet-insecure-tls is required.
set -euo pipefail
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
kubectl -n kube-system patch deployment metrics-server --type=json \
  -p '[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]'
kubectl -n kube-system rollout status deploy/metrics-server --timeout=180s
echo "metrics-server ready"
