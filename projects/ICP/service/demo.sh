#!/usr/bin/env bash
# One-command ICP OCR demo on the VM.
# Run from the laptop: bash projects/ICP/service/demo.sh [--auto|--showcase]
set -euo pipefail

MODE="interactive"
case "${1:-}" in
  --auto) MODE="auto" ;;
  --showcase) MODE="showcase" ;;
  "") ;;
  *)
    echo "usage: $0 [--auto|--showcase]" >&2
    exit 2
    ;;
esac

VM="${DEMO_VM:-icp-vm}"
TUNNEL_PID=""
BG_LOAD_PID=""
BG_LOAD_TAG=""
SLO_MS=1079
GRAFANA_URL="http://localhost:3000/d/icp-ocr-stage/?orgId=1&from=now-5m&to=now&refresh=5s"
GRAFANA_URL_SHOWCASE="http://localhost:3000/d/icp-ocr-stage/?orgId=1&from=now-15m&to=now&refresh=5s"
SHOWCASE_RESULTS=()

stop_bg_load() {
  if [[ -n "${BG_LOAD_PID}" ]] && kill -0 "${BG_LOAD_PID}" 2>/dev/null; then
    kill "${BG_LOAD_PID}" 2>/dev/null || true
    wait "${BG_LOAD_PID}" 2>/dev/null || true
  fi
  BG_LOAD_PID=""
  local tag="${BG_LOAD_TAG}"
  BG_LOAD_TAG=""
  if [[ -n "${tag}" ]]; then
    local job="lg-${tag}"
    job="${job//_/-}"
    job="$(echo "${job}" | tr '[:upper:]' '[:lower:]' | cut -c1-40)"
    ssh -o ConnectTimeout=5 -o BatchMode=yes "${VM}" \
      "pkill -f 'run_point.py.*${tag}' 2>/dev/null || true; kubectl -n icp delete job ${job} --ignore-not-found" \
      >/dev/null 2>&1 || true
  else
    ssh -o ConnectTimeout=5 -o BatchMode=yes "${VM}" \
      "pkill -f 'run_point.py.*demo-bg-load' 2>/dev/null || true; kubectl -n icp delete job lg-demo-bg-load --ignore-not-found" \
      >/dev/null 2>&1 || true
  fi
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
  if [[ "${MODE}" == "auto" ]]; then
    sleep 5
  elif [[ "${MODE}" == "showcase" ]]; then
    return 0
  else
    read -rp "Enter to continue "
  fi
}

after_step() {
  if [[ "${MODE}" == "auto" ]]; then
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

banner() {
  echo
  echo "========== $1 =========="
}

remote() {
  ssh "${VM}" "$@"
}

start_tunnel() {
  if ! ssh -o ConnectTimeout=10 -o BatchMode=yes "${VM}" true; then
    echo "VM not reachable" >&2
    exit 1
  fi
  # Free :3000 on the VM and locally (fuser only — pkill -f can kill this ssh itself).
  remote 'fuser -k 3000/tcp >/dev/null 2>&1 || true' || true
  fuser -k 3000/tcp >/dev/null 2>&1 || true
  sleep 1
  ssh -L 3000:localhost:3000 "${VM}" 'kubectl -n icp port-forward svc/grafana 3000:3000' \
    >/tmp/icp-demo-grafana-tunnel.log 2>&1 &
  TUNNEL_PID=$!
  sleep 3
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
slo = ${SLO_MS}.0
base = Path.home() / 'icp/runs/demo/${tag}'
summary = json.loads((base / '${tag}.summary.json').read_text())
p50, p95, p99 = summary['p50_ms'], summary['p95_ms'], summary['p99_ms']
thr = summary.get('completed_rate')
print(f'p50_ms={p50:.1f}  p95_ms={p95:.1f}  p99_ms={p99:.1f}')
print(f'throughput={thr:.3f} cards/s  errors={summary.get(\\\"errors\\\")}')
print('PASS' if p95 <= slo else 'FAIL', f'(p95 <= {slo} ms)')
\""
}

# Prints: p95_ms VERDICT
fetch_p95_verdict() {
  local tag="$1"
  remote "python3 -c \"
import json
from pathlib import Path
slo = ${SLO_MS}.0
base = Path.home() / 'icp/runs/demo/${tag}'
summary = json.loads((base / '${tag}.summary.json').read_text())
p95 = float(summary['p95_ms'])
verdict = 'PASS' if p95 <= slo else 'FAIL'
print(f'{p95:.1f} {verdict}')
\""
}

start_bg_run_point() {
  local tag="$1" variant="$2" replicas="$3" batch="$4" rate="$5" duration="$6" warmup="$7" seed="$8"
  stop_bg_load
  BG_LOAD_TAG="${tag}"
  ssh "${VM}" "python3 -u ~/icp/T3/service/profile/run_point.py \
    --variant ${variant} \
    --replicas ${replicas} \
    --batch ${batch} \
    --rate ${rate} \
    --duration ${duration} \
    --warmup ${warmup} \
    --seed ${seed} \
    --start 0 \
    --slo-ms ${SLO_MS} \
    --tag ${tag} \
    --arrival poisson \
    --runs-dir ~/icp/runs/demo" \
    >/tmp/icp-demo-bg-load.log 2>&1 &
  BG_LOAD_PID=$!
  sleep 2
  if ! kill -0 "${BG_LOAD_PID}" 2>/dev/null; then
    echo "Background load failed to start; see /tmp/icp-demo-bg-load.log" >&2
    exit 1
  fi
}

wait_bg_run_point() {
  if [[ -z "${BG_LOAD_PID}" ]]; then
    return 0
  fi
  set +e
  wait "${BG_LOAD_PID}"
  local rc=$?
  set -e
  BG_LOAD_PID=""
  if [[ "${rc}" -ne 0 ]]; then
    echo "Background run_point failed (rc=${rc}); see /tmp/icp-demo-bg-load.log" >&2
    exit 1
  fi
}

run_point_fg() {
  local tag="$1" variant="$2" replicas="$3" batch="$4" rate="$5" duration="$6" warmup="$7" seed="$8"
  remote "python3 -u ~/icp/T3/service/profile/run_point.py \
    --variant ${variant} \
    --replicas ${replicas} \
    --batch ${batch} \
    --rate ${rate} \
    --duration ${duration} \
    --warmup ${warmup} \
    --seed ${seed} \
    --start 0 \
    --slo-ms ${SLO_MS} \
    --tag ${tag} \
    --arrival poisson \
    --runs-dir ~/icp/runs/demo"
  remote "kubectl -n icp delete job lg-${tag//_/-} --ignore-not-found" || true
}

record_showcase() {
  # phase|variant|replicas|batch|rate|p95|verdict
  SHOWCASE_RESULTS+=("$1|$2|$3|$4|$5|$6|$7")
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
  BG_LOAD_TAG="demo-bg-load"
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

run_showcase() {
  local seed=9100
  local tag p95 verdict line next_reps

  banner "PHASE 0 — VM + Grafana tunnel"
  start_tunnel
  echo "Grafana: ${GRAFANA_URL_SHOWCASE}"
  echo -n "admin password: "
  remote "kubectl -n icp get secret grafana-admin -o jsonpath='{.data.password}' | base64 -d"
  echo
  echo "Open Grafana now (waiting 20 s)…"
  sleep 20

  banner "PHASE 1 — replicas scale (tesseract_default, batch 1)"
  echo "LOOK FOR: latency stays flat as replicas and rate climb together"
  local reps_list=(1 2 4 8)
  local rate_list=(1.5 3 6 12)
  local i
  for i in 0 1 2 3; do
    local reps="${reps_list[$i]}"
    local rate="${rate_list[$i]}"
    tag="showcase-r${reps}"
    seed=$((seed + 1))
    echo
    echo "--- Phase 1.${i}: ${reps} replicas @ ${rate} cards/s (60 s) ---"
    if [[ "${i}" -gt 0 ]]; then
      # Scale while previous load is still running, then stop it and start the new rate.
      next_reps="${reps}"
      echo "Scaling to ${next_reps} while previous load still runs…"
      remote "time ~/icp/T3/service/k8s/scale.sh ${next_reps}"
      stop_bg_load
    fi
    start_bg_run_point "${tag}" tesseract_default "${reps}" 1 "${rate}" 60 8 "${seed}"
    wait_bg_run_point
    line="$(fetch_p95_verdict "${tag}")"
    p95="${line%% *}"
    verdict="${line##* }"
    echo "replicas=${reps}  rate=${rate}  p95_ms=${p95}  ${verdict} (SLO ${SLO_MS} ms)"
    record_showcase "1-r${reps}" tesseract_default "${reps}" 1 "${rate}" "${p95}" "${verdict}"
    remote "kubectl -n icp delete job lg-${tag} --ignore-not-found" || true
    # Keep this load's process only if we background a bridge — here we start a short
    # bridge load so Grafana stays live while we prepare the next step (except last).
    if [[ "${i}" -lt 3 ]]; then
      start_bg_run_point "showcase-bridge-${reps}" tesseract_default "${reps}" 1 "${rate}" 120 0 "$((seed + 50))"
    fi
  done
  stop_bg_load

  banner "PHASE 2 — overload (SLA break)"
  echo "LOOK FOR: queue and latency spike"
  tag="showcase-overload"
  seed=$((seed + 1))
  run_point_fg "${tag}" tesseract_default 1 1 2.5 45 5 "${seed}"
  line="$(fetch_p95_verdict "${tag}")"
  p95="${line%% *}"
  verdict="${line##* }"
  echo "replicas=1  rate=2.5  p95_ms=${p95}  ${verdict} (expect FAIL)"
  record_showcase "2-overload" tesseract_default 1 1 2.5 "${p95}" "${verdict}"

  banner "PHASE 3 — batch sizes (4 replicas, 6 cards/s)"
  echo "LOOK FOR: p95 vs MAX_BATCH 1 / 4 / 8"
  local batch
  for batch in 1 4 8; do
    tag="showcase-b${batch}"
    seed=$((seed + 1))
    echo
    echo "--- Phase 3: MAX_BATCH=${batch} ---"
    remote "kubectl -n icp set env deploy/icp-ocr MAX_BATCH=${batch} BATCH_TIMEOUT_MS=10; kubectl -n icp rollout status deploy/icp-ocr --timeout=600s"
    run_point_fg "${tag}" tesseract_default 4 "${batch}" 6 45 5 "${seed}"
    line="$(fetch_p95_verdict "${tag}")"
    p95="${line%% *}"
    verdict="${line##* }"
    echo "batch=${batch}  rate=6  p95_ms=${p95}  ${verdict}"
    record_showcase "3-b${batch}" tesseract_default 4 "${batch}" 6 "${p95}" "${verdict}"
  done

  banner "PHASE 4 — models under load (4 replicas, batch 1, 6 cards/s)"
  echo "LOOK FOR: tesseract_psm6 vs easyocr_half (expect FAIL)"
  local variant
  for variant in tesseract_psm6 easyocr_half; do
    tag="showcase-${variant}"
    tag="${tag//_/-}"
    seed=$((seed + 1))
    echo
    echo "--- Phase 4: variant=${variant} ---"
    remote "kubectl -n icp set env deploy/icp-ocr VARIANT=${variant} MAX_BATCH=1 BATCH_TIMEOUT_MS=10; kubectl -n icp rollout status deploy/icp-ocr --timeout=600s"
    run_point_fg "${tag}" "${variant}" 4 1 6 45 5 "${seed}"
    line="$(fetch_p95_verdict "${tag}")"
    p95="${line%% *}"
    verdict="${line##* }"
    echo "variant=${variant}  p95_ms=${p95}  ${verdict}"
    record_showcase "4-${variant}" "${variant}" 4 1 6 "${p95}" "${verdict}"
  done

  banner "PHASE 5 — cleanup + summary"
  remote 'kubectl -n icp set env deploy/icp-ocr VARIANT=tesseract_default MAX_BATCH=1 BATCH_TIMEOUT_MS=10; kubectl -n icp rollout status deploy/icp-ocr --timeout=600s'
  remote 'time ~/icp/T3/service/k8s/scale.sh 1'
  remote 'kubectl -n icp get pods'

  echo
  printf '%-16s %-20s %9s %5s %6s %10s %8s\n' \
    "phase" "variant" "replicas" "batch" "rate" "p95_ms" "result"
  printf '%-16s %-20s %9s %5s %6s %10s %8s\n' \
    "----------------" "--------------------" "---------" "-----" "------" "----------" "--------"
  local row
  for row in "${SHOWCASE_RESULTS[@]}"; do
    IFS='|' read -r p v r b rt p95 vdict <<<"${row}"
    printf '%-16s %-20s %9s %5s %6s %10s %8s\n' "${p}" "${v}" "${r}" "${b}" "${rt}" "${p95}" "${vdict}"
  done

  echo
  echo "Showcase done. Grafana stays open 30 s."
  sleep 30
}

case "${MODE}" in
  auto) run_auto ;;
  showcase) run_showcase ;;
  *) run_interactive ;;
esac
