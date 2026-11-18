# E2EML Project – ID Card OCR (ICP)
Team 6: Nizar Talty, Ishan Pathak — CS/ECE 8001

## Milestone 2

OCR pipeline deployed as a gRPC service on k3s, profiled for accuracy, latency, throughput and cost.

**Result:** blue-channel Tesseract PSM 6, 4 replicas × 1 core, 46.32% field exact match, p95 490 ms at 6 cards/s (SLA: p95 ≤ 1079 ms at 6 cards/s).

## Deliverables

| Item | Path |
|------|------|
| Report / Slides (M2) | [`projects/ICP/m2/`](projects/ICP/m2/) (place PDF and PPTX here) |
| Dockerfile | [`projects/ICP/service/Dockerfile`](projects/ICP/service/Dockerfile) |
| k8s manifests | [`projects/ICP/service/k8s/`](projects/ICP/service/k8s/) (`ocr.yaml`, `minio.yaml`, `prometheus.yaml`, `grafana.yaml`) |
| Prometheus config | [`projects/ICP/service/k8s/prometheus.yml`](projects/ICP/service/k8s/prometheus.yml) |
| Grafana dashboard JSON | [`projects/ICP/service/k8s/dashboard.json`](projects/ICP/service/k8s/dashboard.json) |
| Load generator | [`projects/ICP/service/loadgen.py`](projects/ICP/service/loadgen.py) |
| Scaling script | [`projects/ICP/service/k8s/scale.sh`](projects/ICP/service/k8s/scale.sh) |
| Single entry point | [`projects/ICP/service/run_all.sh`](projects/ICP/service/run_all.sh) |
| Plot: acc vs p95 | [`projects/ICP/service/results/report/t6_acc_vs_p95.png`](projects/ICP/service/results/report/t6_acc_vs_p95.png) |
| Plot: acc vs max throughput | [`projects/ICP/service/results/report/t6_acc_vs_maxtput.png`](projects/ICP/service/results/report/t6_acc_vs_maxtput.png) |
| Plot: T7 Pareto | [`projects/ICP/service/results/t7/report/t7_pareto.png`](projects/ICP/service/results/t7/report/t7_pareto.png) |
| Table: T6 | [`projects/ICP/service/results/report/t6_table.csv`](projects/ICP/service/results/report/t6_table.csv) ([`.md`](projects/ICP/service/results/report/t6_table.md), [`.tex`](projects/ICP/service/results/report/t6_table.tex)) |
| Table: T7 | [`projects/ICP/service/results/t7/report/t7_configurations.csv`](projects/ICP/service/results/t7/report/t7_configurations.csv) ([`.md`](projects/ICP/service/results/t7/report/t7_configurations.md)) |
| Splits + dataset revision | [`projects/ICP/splits.json`](projects/ICP/splits.json) |
| Demo | [`projects/ICP/service/demo.sh`](projects/ICP/service/demo.sh) |

## How to reproduce

From `projects/ICP`:

1. Build image (from `projects/ICP` on the VM):
   `docker build -f service/Dockerfile -t icp-ocr:dev .`
2. Deploy: `bash service/k8s/setup_vm.sh`
3. Regenerate tables and plots: `bash service/run_all.sh`
   - T5/T6 → `service/results/report/` (`t5_sla.{csv,tex,png}`, `t6_table.*`, `t6_breakdown.{csv,tex}`, `t6_acc_vs_p95.png`, `t6_acc_vs_maxtput.png`)
   - T7 → `$T7_WORK/report/` (default `~/icp/t7/report`: `t7_pareto.{png,pdf}`, `t7_configurations.{csv,md}`); committed copies under `service/results/t7/report/`
4. Demo: `bash service/demo.sh`

Details: [`projects/ICP/service/README.md`](projects/ICP/service/README.md).

## Milestone 1

| Item | Path |
|------|------|
| Report | [`Slides and Report/CS8001_06_Milestone_1_Report.pdf`](Slides%20and%20Report/CS8001_06_Milestone_1_Report.pdf) |
| Slides | [`Slides and Report/ICPMilestone1.pptx`](Slides%20and%20Report/ICPMilestone1.pptx) |
