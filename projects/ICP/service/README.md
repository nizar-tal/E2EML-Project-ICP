# OCR service — T3 + T4

Originally create by Ishan and sent to Nizar so that the latter can pick up the work after T6 and finish T7.

T7 experiments, report generation, and exact VM commands: [t7/README.md](t7/README.md).

## Reproduce our work (for the team)

We assume you already have a VM with SSH. Copy the ICP folder (this tree) to the VM, then:

### 1) Copy to the VM

```bash
rsync -av --exclude __pycache__ ./ icp-vm:~/icp/T3/
```

Expected: files under `~/icp/T3/` including `service/k8s/setup_vm.sh`.

### 2) Run setup

```bash
ssh icp-vm 'chmod +x ~/icp/T3/service/k8s/setup_vm.sh && ~/icp/T3/service/k8s/setup_vm.sh'
```

Expected: builds images, MinIO Ready, registry uploads (or skips), OCR Ready, Prometheus + Grafana Ready, client 5 cards `status=ok`.

### 3) Check pods

```bash
ssh icp-vm 'kubectl -n icp get pods -o wide'
```

Expected: `minio`, `icp-ocr`, `prometheus`, `grafana` Running.

### 4) Send cards

```bash
ssh icp-vm 'kubectl -n icp delete job client-test --ignore-not-found; kubectl apply -f ~/icp/T3/service/k8s/client-job.yaml; kubectl -n icp wait --for=condition=complete job/client-test --timeout=600s; kubectl -n icp logs job/client-test'
```

Expected: five lines with `variant=tesseract_default` and `status=ok`.

### 5) Scale

```bash
ssh icp-vm '~/icp/T3/service/k8s/scale.sh 2'
ssh icp-vm '~/icp/T3/service/k8s/scale.sh 1'
```

Expected: 2 Ready pods, then back to 1.

### 6) Open Grafana

From the laptop:

```bash
ssh -L 3000:localhost:3000 icp-vm 'kubectl -n icp port-forward svc/grafana 3000:3000'
```

Password:

```bash
ssh icp-vm "kubectl -n icp get secret grafana-admin -o jsonpath='{.data.password}' | base64 -d"; echo
```

Expected: http://localhost:3000 login works; dashboard **ICP OCR — stage: icp-ocr** is listed.

Screenshot of that dashboard: [docs/grafana.png](docs/grafana.png).

### 7) Switch the model (no rebuild)

```bash
ssh icp-vm 'kubectl -n icp set env deploy/icp-ocr VARIANT=easyocr_half; kubectl -n icp rollout status deploy/icp-ocr'
```

Expected: log `registry download variant=easyocr_half`. Set `VARIANT=tesseract_default` when done.

---

## 1. What is T3?

T3 is the **OCR model server**.  
It takes one ID-card image and returns text fields + assertion results.  
It runs in Docker. It loads the model from MinIO.  
You change the model with an environment variable (no rebuild).

Milestone 2 says T3 must:

> "Serve each stage as a separate service. Containerize each stage as its own model server and connect stages with gRPC (guide). Each stage service must: load its variant from the registry, selected by an environment variable or configuration so that it can be changed without rebuilding the image; support a configurable batch size (requests wait in a queue up to a maximum batch size or a timeout); expose a Prometheus /metrics endpoint with at least: request count, latency histogram, queue length, current batch size, and an assertion pass/fail counter."

Also:

> "Assertions are checks that can run online, without labels."

---

## 2. The folder

This folder mirrors the repo's `projects/ICP/`.  
In the repo, `service/` sits **inside** `projects/ICP/`, next to Nizar's files.

```
T3/
  SOURCE.txt                 Nizar copies — where they came from (do not edit / do not push)
  image.py … registry.py …   Nizar ICP code (see SOURCE.txt)
  ocr_variants.json          Nizar — the 4 variants
  Dockerfile.registry        Nizar — MinIO image
  compose.registry.yaml      Nizar — local MinIO
  service/                   ours (this is what we push)
    README.md                this file
    DEMO.md                  10-minute screen walkthrough
    ocr.proto                gRPC API
    ocr_pb2.py               protobuf stubs from ocr.proto
    ocr_pb2_grpc.py          gRPC stubs from ocr.proto
    pipeline.py              OCR + find_fields + assertions
    server.py                gRPC server, batch queue, /metrics
    client.py                send test cards
    requirements.txt         grpc / prometheus pins
    Dockerfile               OCR server image
    k8s/                     Kubernetes (T4)
```

---

## 3. How one card goes through the server

1. **Picture in** — `client.py` sends PNG bytes in a gRPC `CardRequest`.  
2. **Decode** — `server.py` `OCRService.Extract` opens the PNG → RGB array.  
3. **Queue / batch** — request waits in `Batcher`; when the batch is ready, OCR runs.  
4. **Preprocess** — `pipeline.py` → `image.process_image` (Nizar).  
5. **OCR** — `pipeline.py` → `ocr.run_ocr_detailed` (Nizar).  
6. **Find fields** — `pipeline.py` `find_fields` (content rules, no GT boxes).  
7. **A1–A4** — `assertions.check_assertions` (Nizar); keys lowered to a1..a4, all.  
8. **Answer** — `CardResponse` with fields, assertions, timing, variant, batch_size.  
9. **Metrics** — Prometheus counters/histograms on port 8000 (`/metrics`).

---

## 4. Why we built it this way (T3)

- **Separate server** — M2: each stage is its own service.  
- **gRPC** — M2: connect stages with gRPC.  
- **Model from registry by env var** — M2: change variant without rebuilding.  
- **Batching** — M2: configurable batch size + timeout queue.  
- **/metrics list** — M2: request count, latency, queue, batch size, assertion counters.  
- **Content-based fields** — online we have no labels; M2: "Assertions are checks that can run online, without labels."  
- **Fail-fast + health check** — bad config exits 1; Kubernetes needs SERVING.  
- **Threads = 1** — fair CPU measurement (OMP/MKL = 1).  
- **Docker** — same image on laptop and the VM.

---

## 5. Run T3 locally (Docker, step by step)

Work from the ICP folder (here: `work/T3`, or `~/icp/T3` on the VM).

### 1) Set MinIO keys in the shell

```bash
export MINIO_ACCESS_KEY='<random-key>'
export MINIO_SECRET_KEY='<random-key>'
export MINIO_ENDPOINT=http://127.0.0.1:19000
export MINIO_BUCKET=icp-models
export MINIO_REGION=us-east-1
```

Expected: no output (keys stay in the shell only).

### 2) Start MinIO

```bash
docker compose -f compose.registry.yaml up -d --build
```

Expected: MinIO container up; port `19000` listens.

### 3) Fill the registry (all 4 variants)

```bash
python registry.py init
python registry.py provision-tesseract --model-dir /tmp/models-tess
python registry.py provision-easyocr --name easyocr_original --model-dir /tmp/models-easy
python registry.py upload --name tesseract_default --version 1 --model-dir /tmp/models-tess
python registry.py upload --name tesseract_psm6 --version 1 --model-dir /tmp/models-tess
python registry.py upload --name easyocr_original --version 1 --model-dir /tmp/models-easy
python registry.py upload --name easyocr_half --version 1 --model-dir /tmp/models-easy
```

Expected: `Uploaded variants/…/1.json; …`

### 4) Build the image

```bash
docker build -f service/Dockerfile -t icp-ocr:dev .
```

Expected: `naming to docker.io/library/icp-ocr:dev done` (~2.45GB).

### 5) Start the server

```bash
docker run -d --name icp-ocr --network host \
  -e MINIO_ENDPOINT -e MINIO_ACCESS_KEY -e MINIO_SECRET_KEY -e MINIO_BUCKET -e MINIO_REGION \
  -e VARIANT=tesseract_default -e VARIANT_VERSION=1 -e ICP_PATH=/app/icp \
  icp-ocr:dev
```

Expected: `registry download variant=tesseract_default …` then `warmup done` then `serving on port 50051`.

### 6) Check health

```bash
python - <<'PY'
import grpc
from grpc_health.v1 import health_pb2, health_pb2_grpc
r = health_pb2_grpc.HealthStub(grpc.insecure_channel("127.0.0.1:50051")).Check(health_pb2.HealthCheckRequest())
print(health_pb2.HealthCheckResponse.ServingStatus.Name(r.status))
PY
```

Expected: `SERVING`

### 7) Send cards

```bash
python service/client.py --n 3
```

Expected: three lines with `status=ok`.

### 8) Read /metrics

```bash
curl -s localhost:8000/metrics | grep -E '^ocr_requests_total|^ocr_assertions_total'
```

Expected: request + assertion series.

### 9) Switch the model (no rebuild)

```bash
docker rm -f icp-ocr
docker run -d --name icp-ocr --network host \
  -e MINIO_ENDPOINT -e MINIO_ACCESS_KEY -e MINIO_SECRET_KEY -e MINIO_BUCKET -e MINIO_REGION \
  -e VARIANT=easyocr_half -e VARIANT_VERSION=1 -e ICP_PATH=/app/icp \
  icp-ocr:dev
python service/client.py --n 2
```

Expected: `variant=easyocr_half`.

### 10) Stop

```bash
docker rm -f icp-ocr
docker compose -f compose.registry.yaml stop
```

---

## 6. Settings (env vars)

| name | default | what it does |
|------|---------|--------------|
| MINIO_ENDPOINT | (required) | MinIO URL |
| MINIO_ACCESS_KEY | (required) | MinIO access key |
| MINIO_SECRET_KEY | (required) | MinIO secret key |
| MINIO_BUCKET | (required) | bucket name |
| MINIO_REGION | us-east-1 | S3 region string |
| VARIANT | (required) | variant name |
| VARIANT_VERSION | 1 | variant version |
| ICP_PATH | parent of `service/` | Nizar Python folder |
| PORT | 50051 | gRPC port |
| METRICS_PORT | 8000 | /metrics port |
| MAX_BATCH | 1 | max cards per batch |
| BATCH_TIMEOUT_MS | 10 | max wait to fill a batch |
| GRPC_THREADS | 32 | gRPC worker threads |
| OMP_NUM_THREADS | 1 | OpenMP threads |
| OMP_THREAD_LIMIT | 1 | OpenMP limit |
| MKL_NUM_THREADS | 1 | MKL threads |

---

## 7. What is T4?

T4 runs the OCR stage on **Kubernetes on the VM** with monitoring.  
We use k3s, one Deployment for OCR, scripted scale, Prometheus, and Grafana.  
Models still come from MinIO by env var.

Milestone 2 says T4 must:

> "Deploy your pipeline on Kubernetes on your VM (k3s, kind, or minikube is fine)."

> "One Deployment per stage, with CPU and memory requests and limits set explicitly."

> "Scaling a stage must be a scripted operation (Kubernetes API or kubectl scale), not a manual step."

> "Run Prometheus and a Grafana dashboard showing, per stage: p50/p95/p99 latency, throughput, queue length, CPU usage, and assertion pass rate."

Deliverables include:

> "Kubernetes manifests, the Prometheus configuration, and the Grafana dashboard JSON"

---

## 8. The k8s files

All under `service/k8s/`:

| file | what it is |
|------|------------|
| `minio.yaml` | Namespace `icp`, PVC, MinIO Deployment + Service (M2 manifest) |
| `registry-job.yaml` | Job: Nizar `registry.py` init + upload 4 variants |
| `ocr.yaml` | OCR Deployment + headless Service (M2 manifest) |
| `client-job.yaml` | Job: send test cards with `round_robin` |
| `scale.sh` | `scale.sh <n>` — scripted scale (M2) |
| `prometheus.yml` | Prometheus scrape config (M2 deliverable) |
| `prometheus.yaml` | Prometheus RBAC + Deployment + Service (M2 manifest) |
| `grafana.yaml` | Grafana Deployment + Service + provisioning |
| `dashboard.json` | Grafana dashboard (M2 deliverable) |
| `setup_vm.sh` | one-shot: build, import, deploy, client test |

---

## 9. How it fits together

```
client  --gRPC-->  Service icp-ocr (headless, clusterIP: None)
                      |
                      +--> OCR pod(s)  --at start-->  MinIO (download VARIANT)
                      |
Prometheus --scrape--> OCR /metrics :8000
           --scrape--> cAdvisor (CPU)
Grafana    --query-->  Prometheus
```

---

## 10. Why each choice (T4)

- **requests = limits** — Guaranteed QoS; stable CPU for fair profiling.  
- **headless Service + round_robin** — gRPC keeps one TCP connection; with `pick_first` all 20 cards hit one pod; with `round_robin` we saw 10/10.  
- **Secrets via kubectl** — no keys in files.  
- **registry Job** — repeatable upload with Nizar's `registry.py` (skips if already there).  
- **SSH tunnel for Grafana** — nothing opened to the internet.  
- **1 core per pod, scale by replicas** — matches the later profiling plan (T6).

---

## 11. Run it (on the VM)

Prefer `setup_vm.sh` (section at the top). Manual order we used:

### 1) Namespace + Secrets

```bash
kubectl create namespace icp
kubectl -n icp create secret generic minio-creds \
  --from-literal=MINIO_ACCESS_KEY=$(openssl rand -hex 16) \
  --from-literal=MINIO_SECRET_KEY=$(openssl rand -hex 24)
kubectl -n icp create secret generic grafana-admin \
  --from-literal=password=$(openssl rand -hex 16)
```

Expected: secrets created (do not print values).

### 2) MinIO

```bash
kubectl apply -f service/k8s/minio.yaml
kubectl -n icp rollout status deploy/minio
```

Expected: `deployment "minio" successfully rolled out`.

### 3) Registry fill

```bash
kubectl apply -f service/k8s/registry-job.yaml
kubectl -n icp wait --for=condition=complete job/registry-fill --timeout=900s
kubectl -n icp logs job/registry-fill
```

Expected: `Uploaded variants/tesseract_default/1.json; …` (×4) or `skip existing …`.

### 4) OCR

```bash
kubectl apply -f service/k8s/ocr.yaml
kubectl -n icp rollout status deploy/icp-ocr
```

Expected: Ready; log `registry download variant=tesseract_default …`.

### 5) Client test

```bash
kubectl apply -f service/k8s/client-job.yaml
kubectl -n icp logs job/client-test
```

Expected: 5× `status=ok`.

### 6) Scale

```bash
./service/k8s/scale.sh 2
./service/k8s/scale.sh 4
./service/k8s/scale.sh 1
```

Expected: 2 / 4 / 1 Ready pods (`scale.sh 2` and `4` were ~6 s for us).

### 7) Prometheus + Grafana

```bash
kubectl -n icp create configmap prometheus-config --from-file=prometheus.yml=service/k8s/prometheus.yml --dry-run=client -o yaml | kubectl apply -f -
kubectl -n icp create configmap grafana-dashboard --from-file=dashboard.json=service/k8s/dashboard.json --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f service/k8s/prometheus.yaml
kubectl apply -f service/k8s/grafana.yaml
```

Expected: both Deployments Ready. Images we pinned: `prom/prometheus:v2.55.1`, `grafana/grafana:11.3.1`.

### 8) Open Grafana from the laptop

```bash
ssh -L 3000:localhost:3000 icp-vm 'kubectl -n icp port-forward svc/grafana 3000:3000'
```

Password (never paste the real value into docs):

```bash
ssh icp-vm "kubectl -n icp get secret grafana-admin -o jsonpath='{.data.password}' | base64 -d"; echo
```

Expected: dashboard **ICP OCR — stage: icp-ocr** at http://localhost:3000.

Screenshot: [docs/grafana.png](docs/grafana.png).

---

## 12. What each dashboard panel means

Example numbers from a 200-card run (tesseract_default, 2 pods):

- **Latency p50/p95/p99** — how long one card takes (we saw ~0.38 / 0.81 / 0.96 s).  
- **Throughput** — ok cards per second (~1.4/s) and errors/s (0 if none).  
- **Queue length** — how many cards wait in the batcher (often 0 at rest).  
- **CPU usage** — cores per OCR container (`container="ocr"`) and the total.  
- **Assertion pass rate** — share of checks that pass (all + a1..a4); content A2/A3 stay low.  
- **Replicas serving** — how many OCR pods Prometheus sees as up.  
- **Batch size** — average last batch size (1 with `MAX_BATCH=1`).

---

## 13. What we tested and the results

- **T3:** Tesseract ~150–450 ms/card; EasyOCR slower on CPU; batching does not speed up wall-clock on CPU; content A2/A3 weak vs GT assertions.  
- **T4-1v:** MinIO + registry Job + OCR Guaranteed (1 CPU / 4Gi); client 5× ok; variant swap to `easyocr_half` without rebuild.  
- **T4-2v:** `scale.sh 2` ~6 s → round_robin 20 → 10/10; pick_first → 0/20 on one pod; `scale.sh 4` ~6 s → 10/10/10/10; `scale.sh 1` ~32 s.  
- **T4-3v:** Prometheus targets `icp-ocr` + `cadvisor` up; PromQL panels non-empty; Grafana dashboard present.

---

## 14. T5 — load generator and SLA

T5 adds an open-loop load generator (`loadgen.py`) and SLA calibration (`profile/calibrate_sla.py`).

SLA values we use (from `runs/sla.json` after calibration):

| name | value | meaning |
|------|-------|---------|
| L0 | 539.6 ms | unloaded p95 latency |
| SLO | 1079.3 ms | 2×L0 — latency budget under load |
| T0 | 1.5 cards/s | base sustainable rate |
| target | 6 cards/s | 4×T0 — capacity target |

Loadgen checks:

```bash
# from the service folder on the VM host, after OCR is Ready
python3 loadgen.py --host dns:///icp-ocr.icp.svc.cluster.local:50051 \
  --rate 1 --duration 30 --warmup 5 --out /tmp/lg-smoke --tag smoke
```

Or use the Job helper:

```bash
python3 profile/run_point.py --variant tesseract_default --replicas 1 --batch 1 \
  --rate 1.5 --duration 60 --tag sla-check --slo-ms 1079.3
```

Calibrate SLA (writes `~/icp/runs/sla.json`):

```bash
python3 profile/calibrate_sla.py
```

---

## 15. T6 — profiling sweep and report

T6 sweeps (variant × replicas × batch), finds the offered rate within the SLA, then builds tables and figures.

Run the full flow on the VM (SLA + reduced sweep + report):

```bash
cd ~/icp/T3/service
bash profile/run_profile.sh
```

Sweep only (resume / extra grid):

```bash
python3 profile/sweep_t6.py --reduced
python3 profile/sweep_t6.py --extra --resume
```

Rebuild the report from existing run data (laptop or VM; no new load):

```bash
# copy runs/ from the VM first if needed, then:
bash profile/run_profile.sh --report-only
```

Outputs:

| path | contents |
|------|----------|
| `runs/sla.json` | L0 / SLO / T0 |
| `runs/t6/index.json` | selected points + all probe runs |
| `runs/t6/<tag>/` | per-point summary + job.yaml |
| `runs/report/` | `t5_sla.md`, `t6_table.md`, `t6_breakdown.md`, figures |

---

## Results (T5, T6)

Committed copies live under `service/results/` (no raw run folders).

SLA values:

| name | value | meaning |
|------|-------|---------|
| L0 | 539.6 ms | unloaded p95 latency |
| SLO | 1079.3 ms | p95 per card under load (2×L0) |
| T0 | 1.5 cards/s | base sustainable rate |
| target | 6 cards/s | 4×T0 |

Where to look:

| path | contents |
|------|----------|
| `results/sla.json` | SLA numbers |
| `results/t6/index.json` | all selected T6 points |
| `results/report/t6_table.csv` | main table (48 rows) |
| `results/report/t6_breakdown.*` | per-variant breakdown |
| `results/report/t5_sla.*` | SLA calibration table + plot |
| `results/report/t6_acc_vs_p95.png` | accuracy vs p95 |
| `results/report/t6_acc_vs_maxtput.png` | accuracy vs max throughput |
| `docs/grafana.png` | Grafana dashboard screenshot |

Each variant’s test accuracy was written to the registry with `registry.py record-accuracy` (field exact match on the 2,000-card test slice): **tesseract_default 0.362**, **tesseract_psm6 0.411**, **easyocr_original 0.347**, **easyocr_half 0.190**. Commands used (from the ICP folder, after provisioning model dirs and with MinIO env set):

```bash
python registry.py record-accuracy --name tesseract_default --version 1 \
  --summary metadata/tesseract_default.summary.json --model-dir /tmp/models/tess
python registry.py record-accuracy --name tesseract_psm6 --version 1 \
  --summary metadata/tesseract_psm6.summary.json --model-dir /tmp/models/tess
python registry.py record-accuracy --name easyocr_original --version 1 \
  --summary metadata/easyocr_original.summary.json --model-dir /tmp/models/easy
python registry.py record-accuracy --name easyocr_half --version 1 \
  --summary metadata/easyocr_half.summary.json --model-dir /tmp/models/easy
```

Regenerate tables and plots from the repo alone (uses `results/` when `work/runs` is missing):

```bash
cd projects/ICP/service
bash profile/run_profile.sh --report-only
```

Optional: write into a temp folder instead of overwriting `results/report/`:

```bash
REPORT_OUT=/tmp/icp-report bash profile/run_profile.sh --report-only
```

---

## Run one setup live (for T7)

The cluster stays up until **2026-11-19 01:00 UTC**. On the VM host:

```bash
cd ~/icp/T3/service
./k8s/scale.sh 4
python3 profile/run_point.py \
  --variant tesseract_psm6 \
  --replicas 4 \
  --batch 1 \
  --rate 6 \
  --duration 90 \
  --warmup 15 \
  --seed 8001 \
  --slo-ms 1079.3 \
  --tag t7-psm6-r4-b1-r6
```

Summary file (hostPath):

```text
~/icp/runs/t7-psm6-r4-b1-r6/t7-psm6-r4-b1-r6.summary.json
```

Also written: `point.json` and `job.yaml` in that folder.

How to read p95 vs the SLO:

```bash
python3 - <<'PY'
import json
from pathlib import Path
s = json.loads(Path.home().joinpath(
    "icp/runs/t7-psm6-r4-b1-r6/t7-psm6-r4-b1-r6.summary.json").read_text())
slo = 1079.3
print(f"p95_ms={s['p95_ms']:.1f}  SLO={slo}  within_SLA={s['p95_ms'] <= slo}")
print(f"throughput={s.get('completed_rate')}  errors={s.get('errors')}")
PY
```

If `p95_ms` ≤ 1079.3 ms, the setup meets the SLA at that offered rate.

**Preprocessing:** enhancement and channel come from the variant’s settings in the MinIO registry, not from an env var. To try a new preprocessing + OCR combination live:

1. Build a model dir and upload a new variant with `registry.py upload --name <new_name> ...`
2. `kubectl -n icp set env deploy/icp-ocr VARIANT=<new_name>`
3. `kubectl -n icp rollout status deploy/icp-ocr`
4. Re-run `run_point.py` with `--variant <new_name>`.

---

## 16. Known limits

- The live assertion check finds only **ID, gender, and birth date** by format, because A1–A4 use only these fields and there are no labels at serving time. **Name, ethnicity, and address** are scored offline on the test slice (all 8 fields).  
- Low A2/A3 — OCR often misses small month/day digits.  
- OCR image ~2.45GB.  
- EasyOCR is slow on CPU.

---

## 17. If something breaks

**T3 / Docker**

1. MinIO not running — `docker compose -f compose.registry.yaml up -d`.  
2. Wrong keys — use the same shell exports; never put keys in files.  
3. Wrong VARIANT — server exits 1; use a name from `ocr_variants.json`.  
4. Port in use — `docker rm -f icp-ocr`.  
5. Health not SERVING yet — wait for download + warmup.

**T4 / k3s**

1. **ImagePullBackOff** — image not in k3s: `docker save <img> | sudo k3s ctr images import -`.  
2. **registry Job failed** — check MinIO Ready + Secret keys; re-apply Job after delete.  
3. **OCR not Ready** — startupProbe waits for registry download; `kubectl -n icp logs deploy/icp-ocr`.  
4. **Grafana empty** — check Prometheus targets; CPU panel needs `container="ocr"` (not `icp-ocr`).  
5. **port-forward in use** — stop the old forward (`kill` the kubectl process) and retry.
