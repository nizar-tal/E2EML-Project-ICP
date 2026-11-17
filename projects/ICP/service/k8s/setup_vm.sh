#!/usr/bin/env bash
# Run on the VM. Builds images and deploys namespace icp. Safe to re-run.
set -euo pipefail
K8S="$(cd "$(dirname "$0")" && pwd)"
SVC="$(cd "$K8S/.." && pwd)"
ICP="$(cd "$SVC/.." && pwd)"
NS=icp
MINIO=icp-minio:RELEASE.2025-04-22T22-12-26Z
PROM=prom/prometheus:v2.55.1
GRAF=grafana/grafana:11.3.1

echo "== Docker + k3s + firewalld =="
if ! command -v docker >/dev/null; then
  sudo apt-get update
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y docker.io docker-compose-v2 rsync
  sudo usermod -aG docker "$USER" || true
fi
sudo systemctl enable --now docker
command -v k3s >/dev/null || curl -sfL https://get.k3s.io | sh -s - --write-kubeconfig-mode 644
if systemctl is-active --quiet firewalld; then
  sudo firewall-cmd --permanent --zone=trusted --add-source=10.42.0.0/16 --add-source=10.43.0.0/16 || true
  sudo firewall-cmd --reload || true
fi

echo "== Build + import images =="
docker build -f "$SVC/Dockerfile" -t icp-ocr:dev "$ICP"
docker build -f "$ICP/Dockerfile.registry" -t "$MINIO" "$ICP"
docker pull "$PROM"; docker pull "$GRAF"
for img in icp-ocr:dev "$MINIO" "$PROM" "$GRAF"; do docker save "$img" | sudo k3s ctr images import -; done

echo "== Namespace + Secrets =="
kubectl get ns "$NS" >/dev/null 2>&1 || kubectl create namespace "$NS"
if ! kubectl -n "$NS" get secret minio-creds >/dev/null 2>&1; then
  kubectl -n "$NS" create secret generic minio-creds \
    --from-literal=MINIO_ACCESS_KEY="$(openssl rand -hex 16)" \
    --from-literal=MINIO_SECRET_KEY="$(openssl rand -hex 24)"
  echo "created minio-creds (not printed)"
fi
if ! kubectl -n "$NS" get secret grafana-admin >/dev/null 2>&1; then
  kubectl -n "$NS" create secret generic grafana-admin --from-literal=password="$(openssl rand -hex 16)"
  echo "created grafana-admin (not printed)"
fi

echo "== MinIO =="; kubectl apply -f "$K8S/minio.yaml"
kubectl -n "$NS" rollout status deploy/minio --timeout=180s

echo "== Registry =="; kubectl -n "$NS" delete job registry-fill --ignore-not-found
kubectl apply -f "$K8S/registry-job.yaml"
kubectl -n "$NS" wait --for=condition=complete job/registry-fill --timeout=900s
kubectl -n "$NS" logs job/registry-fill | tail -20

echo "== OCR =="; kubectl apply -f "$K8S/ocr.yaml"
kubectl -n "$NS" rollout status deploy/icp-ocr --timeout=300s

echo "== Prometheus + Grafana =="
kubectl -n "$NS" create configmap prometheus-config --from-file=prometheus.yml="$K8S/prometheus.yml" --dry-run=client -o yaml | kubectl apply -f -
kubectl -n "$NS" create configmap grafana-dashboard --from-file=dashboard.json="$K8S/dashboard.json" --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f "$K8S/prometheus.yaml"; kubectl apply -f "$K8S/grafana.yaml"
kubectl -n "$NS" rollout status deploy/prometheus --timeout=180s
kubectl -n "$NS" rollout status deploy/grafana --timeout=180s

echo "== Client test =="; kubectl -n "$NS" delete job client-test --ignore-not-found
kubectl apply -f "$K8S/client-job.yaml"
kubectl -n "$NS" wait --for=condition=complete job/client-test --timeout=600s
kubectl -n "$NS" logs job/client-test

echo "== done =="; kubectl -n "$NS" get pods -o wide
echo "Grafana from a laptop:"
echo "  ssh -L 3000:localhost:3000 cc@<VM-IP> 'kubectl -n icp port-forward svc/grafana 3000:3000'"
echo "  open http://localhost:3000  user=admin"
echo "  password: ssh cc@<VM-IP> \"kubectl -n icp get secret grafana-admin -o jsonpath='{.data.password}' | base64 -d\""
