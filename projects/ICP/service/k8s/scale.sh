#!/usr/bin/env bash
# Scale icp-ocr Deployment in namespace icp.
# usage: scale.sh <replicas>
set -euo pipefail

if [[ $# -ne 1 ]] || ! [[ "$1" =~ ^[0-9]+$ ]]; then
  echo "usage: scale.sh <replicas>" >&2
  exit 2
fi
n="$1"

kubectl -n icp scale deploy/icp-ocr --replicas="$n"
kubectl -n icp rollout status deploy/icp-ocr --timeout=600s

# Wait until all n pods are Ready
deadline=$((SECONDS + 600))
while true; do
  ready=$(kubectl -n icp get pods -l app=icp-ocr \
    --field-selector=status.phase=Running \
    -o jsonpath='{range .items[*]}{.status.containerStatuses[0].ready}{"\n"}{end}' \
    | grep -c '^true$' || true)
  if [[ "$ready" -eq "$n" ]]; then
    break
  fi
  if (( SECONDS >= deadline )); then
    echo "timeout: want $n Ready pods, have $ready" >&2
    kubectl -n icp get pods -l app=icp-ocr -o wide >&2 || true
    exit 1
  fi
  sleep 2
done

kubectl -n icp get pods -l app=icp-ocr -o wide
