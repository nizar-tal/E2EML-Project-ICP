#!/usr/bin/env bash
# One-command ICP OCR demo on the VM.
# Run from the laptop: bash projects/ICP/service/demo.sh [--auto]
set -euo pipefail

AUTO=0
if [[ "${1:-}" == "--auto" ]]; then
  AUTO=1
fi

VM="${DEMO_VM:-icp-vm}"
TUNNEL_PID=""
BG_LOAD_PID=""
GRAFANA_URL="http://localhost:3000/d/icp-ocr-stage/?orgId=1&from=now-5m&to=now&refresh=5s"

stop_bg_load() {
  if [[ -n "${BG_LOAD_PID}" ]] && kill -0 "${BG_LOAD_PID}" 2>/dev/null; then
    kill "${BG_LOAD_PID}" 2>/dev/null || true
    wait "${BG_LOAD_PID}" 2>/dev/null || true
  fi
  BG_LOAD_PID=""
  ssh -o ConnectTimeout=5 -o BatchMode=yes "${VM}" \
    "pkill -f 'run_point.py.*demo-bg-load' 2>/dev/null || true; kubectl -n icp delete job lg-demo-bg-load --ignore-not-found" \
    >/dev/null 2>&1 || true
}

cleanup() {
  stop_bg_load
  if [[ -n "${TUNNEL_PID}" ]] && kill -0 "${TUNNEL_PID}" 2>/dev/null; then
    kill "${TUNNEL_PID}" 2>/dev/null || true
    wait "${TUNNEL_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT

pause() {
  if [[ "${AUTO}" -eq 1 ]]; then
    sleep 5
  else
    read -rp "Enter to continue "
  fi
}

after_step() {
  if [[ "${AUTO}" -eq 1 ]]; then
    sleep 5
  fi
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

start_tunnel() {
  if ! ssh -o ConnectTimeout=10 -o BatchMode=yes "${VM}" true; then
    echo "VM not reachable" >&2
    exit 1
  fi
  # Drop stale grafana forwards (VM :3000) and any local listener on 3000.
  remote 'pkill -f "port-forward.*grafana" 2>/dev/null || true; fuser -k 3000/tcp 2>/dev/null || true' || true
  fuser -k 3000/tcp 2>/dev/null || true
  sleep 1
  ssh -L 3000:localhost:3000 "${VM}" 'kubectl -n icp port-forward svc/grafana 3000:3000' \
    >/tmp/icp-demo-grafana-tunnel.log 2>&1 &
  TUNNEL_PID=$!
  sleep 2
  if ! kill -0 "${TUNNEL_PID}" 2>/dev/null; then
    echo "Grafana tunnel failed to start; see /tmp/icp-demo-grafana-tunnel.log" >&2
    exit 1
  fi
}

print_run_point_summary() {
  local tag="$1"
  remote "python3 -c \"
import json
from pathlib import Path
slo = 1079.0
base = Path.home() / 'icp/runs/demo/${tag}'
summary = json.loads((base / '${tag}.summary.json').read_text())
p50, p95, p99 = summary['p50_ms'], summary['p95_ms'], summary['p99_ms']
thr = summary.get('completed_rate')
print(f'p50_ms={p50:.1f}  p95_ms={p95:.1f}  p99_ms={p99:.1f}')
print(f'throughput={thr:.3f} cards/s  errors={summary.get(\\\"errors\\\")}')
print('PASS' if p95 <= slo else 'FAIL', f'(p95 <= {slo} ms)')
\""
}

run_interactive() {
  echo "=== STEP 0/7: VM reachability + Grafana tunnel ==="
  echo "LOOK FOR: ssh OK; Grafana at http://localhost:3000"
  start_tunnel
  echo "Grafana: http://localhost:3000  (user: admin)"
  echo -n "admin password: "
  remote "kubectl -n icp get secret grafana-admin -o jsonpath='{.data.password}' | base64 -d"
  echo
  pause

  step "1/7" "Pods + Guaranteed QoS" \
    "icp-ocr and minio Running; QoS Guaranteed"
  remote 'kubectl -n icp get pods -o wide'
  remote 'POD=$(kubectl -n icp get pods -l app=icp-ocr -o jsonpath="{.items[0].metadata.name}"); kubectl -n icp get pod "$POD" -o jsonpath="{.status.qosClass}{\"\\n\"}"'

  step "2/7" "Model loaded from MinIO registry (no rebuild)" \
    "registry download variant=tesseract_default; serving on port 50051"
  remote 'kubectl -n icp logs deploy/icp-ocr | grep -E "registry download|serving"'

  step "3/7" "Client test (5 cards)" \
    "5 lines, status=ok"
  remote 'kubectl -n icp delete job client-test --ignore-not-found; kubectl apply -f ~/icp/T3/service/k8s/client-job.yaml; kubectl -n icp wait --for=condition=complete job/client-test --timeout=600s; kubectl -n icp logs job/client-test'

  step "4/7" "Scale OCR to 4 replicas" \
    "4 icp-ocr pods Running"
  remote 'time ~/icp/T3/service/k8s/scale.sh 4'
  remote 'kubectl -n icp get pods'

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
  print_run_point_summary demo-load-r4
  remote 'kubectl -n icp delete job lg-demo-load-r4 --ignore-not-found' || true

  step "6/7" "Switch model to easyocr_half (no rebuild)" \
    "variant=easyocr_half"
  remote 'kubectl -n icp set env deploy/icp-ocr VARIANT=easyocr_half; kubectl -n icp rollout status deploy/icp-ocr'
  remote 'kubectl -n icp run demo-half --rm -i --restart=Never --image=icp-ocr:dev --image-pull-policy=Never -- python /app/client.py --host dns:///icp-ocr.icp.svc.cluster.local:50051 --n 2 --lb round_robin'

  step "7/7" "Cleanup: tesseract_default + scale to 1" \
    "VARIANT=tesseract_default; 1 icp-ocr pod Running"
  remote 'kubectl -n icp set env deploy/icp-ocr VARIANT=tesseract_default; kubectl -n icp rollout status deploy/icp-ocr'
  remote 'time ~/icp/T3/service/k8s/scale.sh 1'
  remote 'kubectl -n icp get pods'

  echo
  echo "=== DEMO DONE ==="
  echo "Grafana tunnel will close when this script exits."
  pause
}

run_auto() {
  echo "=== STEP 0/8: VM reachability + Grafana tunnel ==="
  echo "LOOK FOR: ssh OK; Grafana dashboard open"
  pause
  start_tunnel
  echo "Grafana: ${GRAFANA_URL}"
  echo -n "admin password: "
  remote "kubectl -n icp get secret grafana-admin -o jsonpath='{.data.password}' | base64 -d"
  echo
  echo "Open Grafana now (waiting 20 s)…"
  sleep 20

  step "1/8" "Pods + Guaranteed QoS" \
    "icp-ocr and minio Running; QoS Guaranteed"
  remote 'kubectl -n icp get pods -o wide'
  remote 'POD=$(kubectl -n icp get pods -l app=icp-ocr -o jsonpath="{.items[0].metadata.name}"); kubectl -n icp get pod "$POD" -o jsonpath="{.status.qosClass}{\"\\n\"}"'
  after_step

  step "2/8" "Model loaded from MinIO registry (no rebuild)" \
    "registry download variant=tesseract_default; serving on port 50051"
  remote 'kubectl -n icp logs deploy/icp-ocr | grep -E "registry download|serving"'
  after_step

  step "3/8" "Start light background load (1 card/s, 4 min)" \
    "Grafana latency/throughput start moving"
  ssh "${VM}" 'python3 -u ~/icp/T3/service/profile/run_point.py \
    --variant tesseract_default \
    --replicas 1 \
    --batch 1 \
    --rate 1 \
    --duration 240 \
    --warmup 5 \
    --seed 8002 \
    --start 0 \
    --slo-ms 1079 \
    --tag demo-bg-load \
    --arrival poisson \
    --runs-dir ~/icp/runs/demo' \
    >/tmp/icp-demo-bg-load.log 2>&1 &
  BG_LOAD_PID=$!
  sleep 2
  if ! kill -0 "${BG_LOAD_PID}" 2>/dev/null; then
    echo "Background load failed to start; see /tmp/icp-demo-bg-load.log" >&2
    exit 1
  fi
  echo "Background load PID=${BG_LOAD_PID} (log: /tmp/icp-demo-bg-load.log)"
  after_step

  step "4/8" "Client test (5 cards)" \
    "5 lines, status=ok"
  remote 'kubectl -n icp delete job client-test --ignore-not-found; kubectl apply -f ~/icp/T3/service/k8s/client-job.yaml; kubectl -n icp wait --for=condition=complete job/client-test --timeout=600s; kubectl -n icp logs job/client-test'
  after_step

  step "5/8" "Scale OCR to 4 replicas (light load still running)" \
    "replicas panel goes to 4"
  remote 'time ~/icp/T3/service/k8s/scale.sh 4'
  remote 'kubectl -n icp get pods'
  after_step

  step "6/8" "Main load (6 cards/s, 60 s, 4 replicas)" \
    "Grafana panels move; then p50/p95/p99 and PASS if p95 <= 1079 ms"
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
  print_run_point_summary demo-load-r4
  remote 'kubectl -n icp delete job lg-demo-load-r4 --ignore-not-found' || true
  after_step

  step "7/8" "Stop bg load; switch model to easyocr_half" \
    "variant=easyocr_half; 2 cards"
  stop_bg_load
  remote 'kubectl -n icp set env deploy/icp-ocr VARIANT=easyocr_half; kubectl -n icp rollout status deploy/icp-ocr'
  remote 'kubectl -n icp run demo-half --rm -i --restart=Never --image=icp-ocr:dev --image-pull-policy=Never -- python /app/client.py --host dns:///icp-ocr.icp.svc.cluster.local:50051 --n 2 --lb round_robin'
  remote 'kubectl -n icp get deploy icp-ocr -o jsonpath="{.spec.template.spec.containers[0].env}" ; echo'
  after_step

  step "8/8" "Cleanup: tesseract_default + scale to 1" \
    "VARIANT=tesseract_default; 1 icp-ocr pod Running"
  remote 'kubectl -n icp set env deploy/icp-ocr VARIANT=tesseract_default; kubectl -n icp rollout status deploy/icp-ocr'
  remote 'time ~/icp/T3/service/k8s/scale.sh 1'
  remote 'kubectl -n icp get pods'
  after_step

  echo
  echo "Demo done. Grafana stays open 60 s."
  sleep 60
}

if [[ "${AUTO}" -eq 1 ]]; then
  run_auto
else
  run_interactive
fi
