#!/usr/bin/env bash
# One-command ICP OCR demo on the VM.
# Run from the laptop: bash projects/ICP/service/demo.sh
set -euo pipefail

VM="${DEMO_VM:-icp-vm}"
TUNNEL_PID=""

cleanup() {
  if [[ -n "${TUNNEL_PID}" ]] && kill -0 "${TUNNEL_PID}" 2>/dev/null; then
    kill "${TUNNEL_PID}" 2>/dev/null || true
    wait "${TUNNEL_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT

pause() {
  read -rp "Enter to continue "
}

step() {
  local n="$1" title="$2" look="$3"
  echo
  echo "=== STEP ${n}: ${title} ==="
  echo "LOOK FOR: ${look}"
  pause
}

remote() {
  ssh "${VM}" "$@"
}

# --- Step 0: VM + Grafana tunnel ---
echo "=== STEP 0/7: VM reachability + Grafana tunnel ==="
echo "LOOK FOR: ssh OK; Grafana at http://localhost:3000"
if ! ssh -o ConnectTimeout=10 -o BatchMode=yes "${VM}" true; then
  echo "VM not reachable" >&2
  exit 1
fi

# Tunnel Grafana in background
ssh -L 3000:localhost:3000 "${VM}" 'kubectl -n icp port-forward svc/grafana 3000:3000' \
  >/tmp/icp-demo-grafana-tunnel.log 2>&1 &
TUNNEL_PID=$!
sleep 2
if ! kill -0 "${TUNNEL_PID}" 2>/dev/null; then
  echo "Grafana tunnel failed to start; see /tmp/icp-demo-grafana-tunnel.log" >&2
  exit 1
fi
echo "Grafana: http://localhost:3000  (user: admin)"
echo -n "admin password: "
remote "kubectl -n icp get secret grafana-admin -o jsonpath='{.data.password}' | base64 -d"
echo
pause

# --- Step 1: pods + QoS ---
step "1/7" "Pods + Guaranteed QoS" \
  "icp-ocr and minio Running; QoS Guaranteed"
remote 'kubectl -n icp get pods -o wide'
remote 'POD=$(kubectl -n icp get pods -l app=icp-ocr -o jsonpath="{.items[0].metadata.name}"); kubectl -n icp get pod "$POD" -o jsonpath="{.status.qosClass}{\"\\n\"}"'

# --- Step 2: registry ---
step "2/7" "Model loaded from MinIO registry (no rebuild)" \
  "registry download variant=tesseract_default; serving on port 50051"
remote 'kubectl -n icp logs deploy/icp-ocr | grep -E "registry download|serving"'

# --- Step 3: client 5 cards ---
step "3/7" "Client test (5 cards)" \
  "5 lines, status=ok"
remote 'kubectl -n icp delete job client-test --ignore-not-found; kubectl apply -f ~/icp/T3/service/k8s/client-job.yaml; kubectl -n icp wait --for=condition=complete job/client-test --timeout=600s; kubectl -n icp logs job/client-test'

# --- Step 4: scale to 4 ---
step "4/7" "Scale OCR to 4 replicas" \
  "4 icp-ocr pods Running"
remote 'time ~/icp/T3/service/k8s/scale.sh 4'
remote 'kubectl -n icp get pods'

# --- Step 5: live load via run_point (existing loadgen) ---
step "5/7" "Live load for Grafana (6 cards/s, 60 s, 4 replicas)" \
  "Grafana panels move; then p50/p95/p99 and PASS if p95 <= 1079 ms"
echo "Open Grafana now: latency, throughput, queue, CPU, assertion pass rate"
remote 'python3 -u ~/icp/T3/service/profile/run_point.py \
  --variant tesseract_default \
  --replicas 4 \
  --batch 1 \
  --rate 6 \
  --duration 60 \
  --warmup 10 \
  --seed 8001 \
  --start 0 \
  --slo-ms 1079 \
  --tag demo-load-r4 \
  --arrival poisson \
  --runs-dir ~/icp/runs/demo'
remote "python3 -c \"
import json
from pathlib import Path
slo = 1079.0
base = Path.home() / 'icp/runs/demo/demo-load-r4'
summary = json.loads((base / 'demo-load-r4.summary.json').read_text())
p50, p95, p99 = summary['p50_ms'], summary['p95_ms'], summary['p99_ms']
thr = summary.get('completed_rate')
print(f'p50_ms={p50:.1f}  p95_ms={p95:.1f}  p99_ms={p99:.1f}')
print(f'throughput={thr:.3f} cards/s  errors={summary.get(\\\"errors\\\")}')
print('PASS' if p95 <= slo else 'FAIL', f'(p95 <= {slo} ms)')
\""
remote 'kubectl -n icp delete job lg-demo-load-r4 --ignore-not-found' || true

# --- Step 6: switch model ---
step "6/7" "Switch model to easyocr_half (no rebuild)" \
  "variant=easyocr_half"
remote 'kubectl -n icp set env deploy/icp-ocr VARIANT=easyocr_half; kubectl -n icp rollout status deploy/icp-ocr'
remote 'kubectl -n icp run demo-half --rm -i --restart=Never --image=icp-ocr:dev --image-pull-policy=Never -- python /app/client.py --host dns:///icp-ocr.icp.svc.cluster.local:50051 --n 2 --lb round_robin'

# --- Step 7: cleanup ---
step "7/7" "Cleanup: tesseract_default + scale to 1" \
  "VARIANT=tesseract_default; 1 icp-ocr pod Running"
remote 'kubectl -n icp set env deploy/icp-ocr VARIANT=tesseract_default; kubectl -n icp rollout status deploy/icp-ocr'
remote 'time ~/icp/T3/service/k8s/scale.sh 1'
remote 'kubectl -n icp get pods'

echo
echo "=== DEMO DONE ==="
echo "Grafana tunnel will close when this script exits."
pause
