# Demo — ICP OCR on k3s (about 10 minutes)

Show the OCR stage on the VM. Type the commands. Point at the output.

## 0) Tunnel Grafana (laptop, leave open)

```bash
ssh -L 3000:localhost:3000 icp-vm 'kubectl -n icp port-forward svc/grafana 3000:3000'
```

Password (other terminal):

```bash
ssh icp-vm "kubectl -n icp get secret grafana-admin -o jsonpath='{.data.password}' | base64 -d"; echo
```

Open http://localhost:3000 — user `admin`.

## 1) Pods + Guaranteed QoS

```bash
ssh icp-vm 'kubectl -n icp get pods -o wide'
ssh icp-vm 'POD=$(kubectl -n icp get pods -l app=icp-ocr -o jsonpath="{.items[0].metadata.name}"); kubectl -n icp get pod "$POD" -o jsonpath="{.status.qosClass}{\"\\n\"}"'
```

Point at: `icp-ocr` and `minio` Running; QoS `Guaranteed`.

## 2) Model from the registry (no rebuild)

```bash
ssh icp-vm 'kubectl -n icp logs deploy/icp-ocr | grep -E "registry download|serving"'
```

Point at: `registry download variant=tesseract_default …` then `serving on port 50051`.

## 3) Client test (5 cards)

```bash
ssh icp-vm 'kubectl -n icp delete job client-test --ignore-not-found; kubectl apply -f ~/icp/T3/service/k8s/client-job.yaml; kubectl -n icp wait --for=condition=complete job/client-test --timeout=600s; kubectl -n icp logs job/client-test'
```

Point at: five lines, `variant=tesseract_default`, `status=ok`.

## 4) Scale to 2 + load share

```bash
ssh icp-vm 'time ~/icp/T3/service/k8s/scale.sh 2'
ssh icp-vm 'kubectl -n icp run demo-rr --rm -i --restart=Never --image=icp-ocr:dev --image-pull-policy=Never -- python /app/client.py --host dns:///icp-ocr.icp.svc.cluster.local:50051 --n 20 --lb round_robin'
```

Then show per-pod request diffs (before/after `ocr_requests_total`). Point at: both pods get about 10 of 20. Mention: with `--lb pick_first` all 20 hit one pod.

## 5) Grafana panels

In the browser: dashboard **ICP OCR — stage: icp-ocr**.

Point at: latency p50/p95/p99, throughput, queue length, CPU per pod, assertion pass rate, replicas = 2, batch size ≈ 1.

## 6) Switch the model (no rebuild)

```bash
ssh icp-vm 'kubectl -n icp set env deploy/icp-ocr VARIANT=easyocr_half; kubectl -n icp rollout status deploy/icp-ocr'
ssh icp-vm 'kubectl -n icp run demo-half --rm -i --restart=Never --image=icp-ocr:dev --image-pull-policy=Never -- python /app/client.py --host dns:///icp-ocr.icp.svc.cluster.local:50051 --n 2 --lb round_robin'
ssh icp-vm 'kubectl -n icp set env deploy/icp-ocr VARIANT=tesseract_default; kubectl -n icp rollout status deploy/icp-ocr; ~/icp/T3/service/k8s/scale.sh 1'
```

Point at: log `registry download variant=easyocr_half`; client `variant=easyocr_half`; then back to `tesseract_default` and 1 replica.
