# E2EML Project – ID Card OCR (ICP)
Team 6: Nizar Talty, Ishan Pathak — CS/ECE 8001

## Milestone 2

OCR pipeline deployed as a gRPC service on k3s, profiled for accuracy, latency, throughput and cost.

**Result:** blue-channel Tesseract PSM 6, 4 replicas × 1 core, 46.32% field exact match, p95 490 ms at 6 cards/s (SLA: p95 ≤ 1079 ms at 6 cards/s).

### Deliverables (this repo)

| Item | Path |
|------|------|
| Report (M2) | [`Slides and Report/CS8001_06_Milestone_2_Report.pdf`](Slides%20and%20Report/CS8001_06_Milestone_2_Report.pdf) |
| Slides (M2) | [`Slides and Report/CS8001_06_Milestone_2_Slides.pptx`](Slides%20and%20Report/CS8001_06_Milestone_2_Slides.pptx) |
| Dockerfile | [`projects/ICP/service/Dockerfile`](projects/ICP/service/Dockerfile) |
| k8s manifests | [`projects/ICP/service/k8s/`](projects/ICP/service/k8s/) |
| Prometheus config | [`projects/ICP/service/k8s/prometheus.yml`](projects/ICP/service/k8s/prometheus.yml) |
| Grafana dashboard JSON | [`projects/ICP/service/k8s/dashboard.json`](projects/ICP/service/k8s/dashboard.json) |
| Load generator | [`projects/ICP/service/loadgen.py`](projects/ICP/service/loadgen.py) |
| Scaling script | [`projects/ICP/service/k8s/scale.sh`](projects/ICP/service/k8s/scale.sh) |
| Single entry point | [`projects/ICP/service/run_all.sh`](projects/ICP/service/run_all.sh) |
| Plot: acc vs p95 | [`projects/ICP/service/results/report/t6_acc_vs_p95.png`](projects/ICP/service/results/report/t6_acc_vs_p95.png) |
| Plot: acc vs max throughput | [`projects/ICP/service/results/report/t6_acc_vs_maxtput.png`](projects/ICP/service/results/report/t6_acc_vs_maxtput.png) |
| Plot: T7 Pareto | [`projects/ICP/service/results/t7/report/t7_pareto.png`](projects/ICP/service/results/t7/report/t7_pareto.png) |
| Table: T6 | [`projects/ICP/service/results/report/t6_table.csv`](projects/ICP/service/results/report/t6_table.csv) |
| Table: T7 | [`projects/ICP/service/results/t7/report/t7_configurations.csv`](projects/ICP/service/results/t7/report/t7_configurations.csv) |
| Splits | [`projects/ICP/splits.json`](projects/ICP/splits.json) |
| Demo | [`projects/ICP/service/demo.sh`](projects/ICP/service/demo.sh) |

### How to reproduce

From `projects/ICP` on the VM:

1. `docker build -f service/Dockerfile -t icp-ocr:dev .`
2. `bash service/k8s/setup_vm.sh`
3. `bash service/run_all.sh`
4. `bash service/demo.sh` (or `--auto` / `--showcase`)

Details: [`projects/ICP/service/README.md`](projects/ICP/service/README.md).

---

# Milestone 2: Deploying, Monitoring, and Profiling Pipeline Variants

*(from Milestone 2 v3)*

## Learning Goals

In Milestone 1 you built a working pipeline inside a notebook. In this milestone you turn that pipeline into a deployed, scalable, observable service and measure how configuration choices affect accuracy, latency, throughput, and cost.

By the end of this milestone you should be able to answer:

- Which stage of your pipeline is the bottleneck, and why?
- How do model variant, batch size, and number of replicas trade off accuracy against latency, throughput, and cost?
- Which configurations meet your SLA, and which of those is "best"?
- Does the choice of model at an earlier stage change the best choice at a later stage?

The measurements you collect here are the input to the optimizer you will build in Milestone 3. Collect them carefully and make them reproducible.

The Pipeline Evaluation Guide fixes, for each pipeline, the evaluation slices, load pool, offline accuracy metric, required assertions, and SLA unit. These are the same for every team on a pipeline, so that results are comparable. Read the common section and the section for your pipeline before starting.

## Tasks

**T0. Close any Milestone 1 gaps.** If your Milestone 1 feedback lists any missing deliverables (a written report, a Dockerfile in your repository, implemented assertions, a repository link), please complete them under this milestone. Under the pass/fail rule, a Milestone 1 fail becomes a pass if it is fixed by the end of this milestone.

**T1. Fix your evaluation harness.** Before profiling anything, make your accuracy numbers comparable.

- Build the development slice and test slice exactly as defined in the guide for your pipeline, and save their IDs and the dataset version in your repository. Tune thresholds, label mappings, and settings such as top-k only on the development slice; report results only on the test slice.
- Implement the primary offline accuracy metric and the other required metrics for your pipeline, and report the pipeline's baseline (both defined in the guide) next to them.
- Implement the required assertions for your pipeline, tuning any thresholds with the guide's development-slice rule. You may add assertions of your own; justify each one. Assertions are checks that can run online, without labels.
- Report, for your Milestone 1 configurations, both the offline accuracy and the assertion pass rate on the test slice. How well does the assertion pass rate track true accuracy? Do the two rank configurations the same way?

If your Milestone 1 accuracy definition differs from the one in the guide, explain the difference and report both.

**T2. Create model variants.** Create at least four variants for each scalable stage of your pipeline (the guide lists which stages are scalable). Variants can come from:

- different model families or sizes (e.g., YOLOv8n/s/m, Whisper tiny/base/small);
- quantization or graph optimization (e.g., ONNX Runtime dynamic INT8, OpenVINO). Note that TensorRT requires an NVIDIA GPU; on CPU-only VMs, use ONNX Runtime or OpenVINO instead;
- input-side knobs (image resolution, chunk size and top-k, frame skipping).

Store every variant in a model registry such as MinIO, together with metadata: name, version, source, size on disk, and offline accuracy on the test slice.

**T3. Serve each stage as a separate service.** Containerize each stage as its own model server and connect stages with gRPC (guide). Each stage service must:

- load its variant from the registry, selected by an environment variable or configuration so that it can be changed without rebuilding the image;
- support a configurable batch size (requests wait in a queue up to a maximum batch size or a timeout);
- expose a Prometheus `/metrics` endpoint with at least: request count, latency histogram, queue length, current batch size, and an assertion pass/fail counter.

Video pipeline only: the tracker is stateful. Frames from one stream must reach the same tracker instance in order. Explain how you route frames (e.g., by stream ID).

**T4. Deploy on Kubernetes with monitoring.** Deploy your pipeline on Kubernetes on your VM (k3s, kind, or minikube is fine).

- One Deployment per stage, with CPU and memory requests and limits set explicitly.
- Scaling a stage must be a scripted operation (Kubernetes API or `kubectl scale`), not a manual step.
- Run Prometheus and a Grafana dashboard showing, per stage: p50/p95/p99 latency, throughput, queue length, CPU usage, and assertion pass rate.

**T5. Build a load generator and set your SLA.** Write an open-loop load generator: it sends requests at a target rate whether or not earlier requests have returned. (A closed-loop client that waits for each response hides queueing delay and will make your system look faster than it is.) Requests must be drawn from your pipeline's labeled load pool (defined in the guide), so that accuracy can be measured under load.

Then set your SLA using the calibration procedure in the guide, and report it. The SLA is a latency objective (p95, in your pipeline's natural unit) plus a target request rate. It is set so that meeting it requires scaling beyond a single replica.

**T6. Profile each stage.** For each scalable stage, sweep at least four variants × four resource configurations, and batch sizes of at least {1, 4, 8}. Cost is defined as replicas × CPU cores per replica. For each point, report:

| Stage | Variant | Batch | Replicas | Cores/replica | Cost | p50 | p95 | p99 | throughput | Max throughput meeting SLO | Accuracy |
|-------|---------|-------|----------|---------------|------|-----|-----|-----|------------|----------------------------|----------|

Notes:

- Run all profiling on the course VM's CPUs, with an explicit number of cores per replica. GPU or multi-process numbers may be reported in addition, clearly labeled, but not instead.
- Cache upstream outputs when profiling a downstream stage. For example, transcribe or detect once per upstream variant and reuse the outputs, rather than recomputing them for every downstream variant.
- Accuracy depends on the variant (and, for some pipelines, on batch-dependent input knobs). It does not change with the number of replicas. If it appears to, something is wrong with your measurement.
- "Max throughput meeting SLO" is the highest request rate at which p95 latency stays within your SLO.
- Break latency down into queueing time, inference time, and network/serialization time. Identify the bottleneck stage and explain it.

**T7. Analyze end-to-end configurations.** Now combine stages.

- Run end-to-end configurations (the full cross-product if it is small, or a well-chosen subset if not) on the test slice.
- Run the gold-input ablation described in the guide: feed the downstream stage ground-truth input instead of upstream output, to measure how much error each stage contributes.
- Plot all end-to-end configurations by cost and accuracy, mark which meet the SLA, and draw the Pareto front.
- Answer: Do multiple configurations meet the SLA? What makes one "optimal", and is that a single answer or does it depend on the load? Does the upstream choice change the best downstream choice? Support your answer with numbers.

## Deliverables (assignment)

1. **Code** in your team repository:
   - a Dockerfile per stage service;
   - Kubernetes manifests, the Prometheus configuration, and the Grafana dashboard JSON;
   - the load generator;
   - a single entry point (e.g., `make profile` or `run_profile.sh`) that regenerates every table and plot in your report. A notebook may drive these scripts, but the scaling logic must be in code, not manual steps.
2. **Plots:**
   - accuracy vs. p95 latency per variant;
   - accuracy vs. max throughput per variant;
   - the end-to-end cost–accuracy Pareto plot from T7.
3. **Tables:** the per-stage profiling table (T6) and the end-to-end configuration table (T7).
4. **Report** covering T0–T7. Conclude with which configuration you would deploy at your SLA's target rate, and at what cost, taking both the SLA and accuracy into account.
5. **Project presentation** of your work through Milestone 2.

## Grading

This milestone is worth 100 points.

- 20 points: evaluation harness and assertions (T1).
- 30 points: model variants, services, gRPC, Kubernetes deployment, and monitoring are runnable from your repository (T2–T5).
- 20 points: profiling tables and plots are regenerated by your entry point (T6–T7).
- 30 points: report and presentation. Analysis is clear, complete, precise, and supported by your measurements (T6–T7).

---

## Milestone 1 (archive)

| Item | Path |
|------|------|
| Report | [`Slides and Report/CS8001_06_Milestone_1_Report.pdf`](Slides%20and%20Report/CS8001_06_Milestone_1_Report.pdf) |
| Slides | [`Slides and Report/ICPMilestone1.pptx`](Slides%20and%20Report/ICPMilestone1.pptx) |
