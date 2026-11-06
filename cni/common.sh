# Shared helpers for CNI install scripts. Sourced, not executed.
wait_nodes_ready() {
  echo "waiting for all nodes Ready..."
  kubectl wait --for=condition=Ready nodes --all --timeout="${1:-300s}"
}
