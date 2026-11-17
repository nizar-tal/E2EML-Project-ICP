#!/usr/bin/env python3
"""Small T7 runner. Host orchestration uses only Python's standard library."""
import argparse
import asyncio
import csv
import json
import shutil
import subprocess
import sys
import time
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
ICP = HERE.parents[1]
sys.path[:0] = [str(HERE.parent), str(ICP), "/app", "/app/icp"]
HOST = "dns:///icp-ocr.icp.svc.cluster.local:50051"


def read(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def call(*args):
    print("+", " ".join(map(str, args)), flush=True)
    subprocess.run(list(map(str, args)), check=True)


def kubectl_json(*args):
    return json.loads(subprocess.check_output(["kubectl", "-n", "icp", *args, "-o", "json"]))


def summary_path(work, name, split="test"):
    return work / "accuracy" / split / name / "metadata" / f"{name}.summary.json"


def recipes():
    return read(HERE / "variants.json")


def register(args):
    """Reuse registry weights; publish only the three new recipe definitions."""
    from registry import connection, download, exists, record_accuracy, upload
    from model_artifacts import SOURCE_FILE

    client, bucket = connection()
    model_dir = args.work / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    sources = {}
    for base in ("tesseract_default", "easyocr_original"):
        dest = args.work / "base" / base
        if not dest.exists():
            download(SimpleNamespace(name=base, version="1", destination=str(dest)))
        meta = read(dest / "metadata.json")
        for artifact in meta["artifacts"]:
            shutil.copy2(dest / artifact["file"], model_dir / artifact["file"])
        sources.update(read(dest / SOURCE_FILE))
    save(model_dir / SOURCE_FILE, sources)
    for settings in recipes():
        name = settings["name"]
        key = f"variants/{name}/{settings['version']}.json"
        options = SimpleNamespace(variants=str(HERE / "variants.json"), name=name,
                                  model_dir=str(model_dir), summary=None)
        if not exists(client, bucket, key):
            upload(options)
        meta = json.loads(client.get_object(Bucket=bucket, Key=key)["Body"].read())
        if meta["settings"] != settings:
            raise ValueError(f"Registry settings differ for {name}; use a new variant name/version")
        save(args.work / "registry" / f"{name}.json", meta)
        result = summary_path(args.work, name)
        if args.publish and result.exists() and meta["offline_test_accuracy"]["status"] == "unmeasured":
            options.summary = str(result)
            record_accuracy(options)
    print("Registry ready: five recipes, including the original-image EasyOCR ablation control.")


async def score(args):
    """Call the actual service; ground-truth boxes are used only after its reply."""
    import grpc.aio
    import ocr_pb2
    import ocr_pb2_grpc
    from datasets import load_dataset
    from assertions import check_assertions
    from evaluate import add_card, new_totals, runtime_info, summarize, write_reports
    from metrics import CLASS_NAMES, assign_fields, detailed_ocr_metrics, required_metrics
    from prepare_splits import load_record

    result_path = summary_path(args.work, args.variant, args.split)
    if result_path.exists():
        print("Already scored:", result_path)
        return
    record = load_record("/app/icp/splits.json")
    indices = record["indices"][args.split]
    registry = read(args.work / "registry" / f"{args.variant}.json")
    settings = registry["settings"]
    provenance = {
        "artifacts": [{"file": a["file"], "bytes": a["bytes"]} for a in registry["artifacts"]],
        "artifact_sources": registry["artifact_sources"], "device": "cpu", "runtime": runtime_info(),
        "dataset_revision": record["revision"], "dataset_split": record["split"], "split_seed": record["seed"],
    }
    dataset = load_dataset(record["dataset"], split=record["split"], revision=record["revision"])
    out = result_path.parent.parent
    out.mkdir(parents=True, exist_ok=True)
    fields = list(CLASS_NAMES.values())
    columns = ["index"] + [prefix + name for prefix in ("predicted_", "reference_") for name in fields]
    columns += ["A1", "A2", "A3", "A4", "all", "correct_fields", "nonempty_fields", "card_correct", "cer_sum"]
    totals = new_totals()
    live = dict.fromkeys(("a1", "a2", "a3", "a4", "all"), 0)
    channel = grpc.aio.insecure_channel(HOST, options=(("grpc.lb_policy_name", "round_robin"),))
    await asyncio.wait_for(channel.channel_ready(), timeout=120)
    stub = ocr_pb2_grpc.OCRStub(channel)
    pending = iter(indices)
    with (out / f"{args.variant}.predictions.csv").open("w", newline="", encoding="utf-8-sig") as stream, \
            (out / "detections.jsonl").open("w") as raw:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()

        async def worker():
            for index in pending:
                row = dataset[index]
                png = BytesIO()
                row["image"].convert("RGB").save(png, format="PNG")
                response = await stub.Extract(ocr_pb2.CardRequest(
                    card_id=str(index), image=png.getvalue(), include_detections=True), timeout=300)
                if response.variant != args.variant or not response.detections_json:
                    raise ValueError("Wrong variant or old server image: expected raw OCR detections")
                detections = json.loads(response.detections_json)
                annotations = row["ocr"]
                if isinstance(annotations, str):
                    annotations = json.loads(annotations)
                predictions = assign_fields(detections, annotations)
                required = required_metrics(predictions, annotations)
                assigned = {CLASS_NAMES[int(f["cls"])]: text for f, text in zip(annotations, predictions)}
                checks = check_assertions(assigned)
                result = {"detections": detections, "text": "\n".join(d["text"] for d in detections)}
                add_card(totals, required, detailed_ocr_metrics(result, annotations), checks)
                for key in live:
                    live[key] += int(getattr(response.assertions, key))
                item = {"index": index, **{"predicted_" + k: v for k, v in assigned.items()}, **checks}
                item.update({"reference_" + CLASS_NAMES[int(f["cls"])]: f["word"] for f in annotations})
                item.update({k: required[k] for k in ("correct_fields", "nonempty_fields", "card_correct", "cer_sum")})
                writer.writerow(item)
                raw.write(json.dumps({"index": index, "detections": detections}, ensure_ascii=False) + "\n")
                if totals["cards"] % 100 == 0:
                    print(f"{args.variant} {args.split}: {totals['cards']}/{len(indices)}", flush=True)

        try:
            await asyncio.gather(*(worker() for _ in range(8)))
        finally:
            await channel.close()
    summary = {"name": args.variant, "settings": settings, "provenance": provenance,
               "metrics": summarize(totals), "indices": indices, "scored_via": "gRPC",
               "live_assertion_pass_rates": {k: v / len(indices) for k, v in live.items()}}
    save(result_path, summary)
    save(result_path.parent / "run.json", {
        "slice": args.split, "limit": None, "cards": len(indices), "settings": [settings],
        "provenance": {args.variant: provenance}, "split_record": record,
    })
    # Standard evaluator outputs, including per-class metrics and assertion correlations.
    for filename in ("results.csv", "fields.csv", "comparisons.csv", "rankings.csv"):
        (out / filename).unlink(missing_ok=True)
    write_reports([summary], out)
    print("Saved:", result_path, flush=True)


def reuse_test(directory, work, settings, record):
    """Reuse only a full CPU test run with matching settings, weights and card IDs."""
    name = settings["name"]
    source = directory / "metadata" / f"{name}.summary.json"
    if not source.exists() or not (directory / "metadata" / "run.json").exists():
        return False
    summary, run = read(source), read(directory / "metadata" / "run.json")
    provenance = summary["provenance"]
    meta = read(work / "registry" / f"{name}.json")
    artifacts = [{"file": a["file"], "bytes": a["bytes"]} for a in meta["artifacts"]]
    if not (run["slice"] == "test" and run["limit"] is None and summary["metrics"]["cards"] == 2000
            and summary["settings"] == settings and provenance["device"] == "cpu"
            and provenance["dataset_revision"] == record["revision"]
            and provenance["artifacts"] == artifacts):
        return False
    predictions = directory / f"{name}.predictions.csv"
    if not predictions.exists():
        return False
    with predictions.open(encoding="utf-8-sig", newline="") as stream:
        ids = [int(row["index"]) for row in csv.DictReader(stream)]
    if len(ids) != 2000 or set(ids) != set(record["indices"]["test"]):
        return False
    dest = summary_path(work, name)
    save(dest, {**summary, "indices": record["indices"]["test"], "reused_from": str(source)})
    save(dest.parent / "run.json", run)
    shutil.copy2(predictions, dest.parent.parent / predictions.name)
    print("Reused full test result:", source, flush=True)
    return True


def job(work, image, name, arguments, env):
    """One temporary Kubernetes Job, with results saved on the VM host."""
    work.mkdir(parents=True, exist_ok=True)
    work.chmod(0o777)
    cache = Path.home() / "icp/cache/hf"
    cache.mkdir(parents=True, exist_ok=True)
    cache.chmod(0o777)
    pod = {
        "restartPolicy": "Never",
        "containers": [{
            "name": "t7", "image": image, "imagePullPolicy": "Never",
            "command": ["python", "/app/t7/t7.py", *arguments, "--work", "/work"],
            "env": env + [{"name": "HF_HOME", "value": "/hf"},
                           {"name": "HF_DATASETS_CACHE", "value": "/hf"}],
            "resources": {"requests": {"cpu": "1", "memory": "4Gi"},
                          "limits": {"cpu": "2", "memory": "6Gi"}},
            "volumeMounts": [{"name": "work", "mountPath": "/work"}, {"name": "hf", "mountPath": "/hf"}],
        }],
        "volumes": [{"name": "work", "hostPath": {"path": str(work), "type": "Directory"}},
                    {"name": "hf", "hostPath": {"path": str(cache), "type": "Directory"}}],
    }
    manifest = {"apiVersion": "batch/v1", "kind": "Job", "metadata": {"name": name, "namespace": "icp"},
                "spec": {"backoffLimit": 0, "template": {"spec": pod}}}
    path = work / "jobs" / f"{name}.json"
    save(path, manifest)
    call("kubectl", "-n", "icp", "delete", "job", name, "--ignore-not-found", "--wait=true")
    call("kubectl", "apply", "-f", path)
    for _ in range(300):
        pods = kubectl_json("get", "pods", "-l", f"job-name={name}")["items"]
        if pods and pods[0]["status"]["phase"] in ("Running", "Succeeded", "Failed"):
            break
        time.sleep(2)
    else:
        raise TimeoutError(f"Job {name} did not start; inspect kubectl -n icp describe job {name}")
    # Stream progress while waiting; a failed worker exits nonzero and stops this run.
    try:
        call("kubectl", "-n", "icp", "logs", "-f", f"job/{name}", "--pod-running-timeout=600s")
        call("kubectl", "-n", "icp", "wait", "--for=condition=complete", f"job/{name}", "--timeout=60s")
    finally:
        logs = subprocess.run(["kubectl", "-n", "icp", "logs", f"job/{name}"], capture_output=True, text=True)
        (path.with_suffix(".log")).write_text(logs.stdout + logs.stderr)


def deploy(variant, replicas, image):
    call("kubectl", "-n", "icp", "set", "image", "deployment/icp-ocr", f"ocr={image}")
    call("kubectl", "-n", "icp", "set", "env", "deployment/icp-ocr",
         f"VARIANT={variant}", "VARIANT_VERSION=1", "MAX_BATCH=1", "BATCH_TIMEOUT_MS=10", "GRPC_THREADS=256")
    call("bash", HERE.parent / "k8s/scale.sh", replicas)


def measured_performance(folder, tag, slo):
    summary = read(folder / f"{tag}.summary.json")
    point = read(folder / "point.json")
    valid = point["valid"] and summary["send_lag_ok"]
    p95 = summary["p95_ms"]
    passed = p95 is not None and p95 <= slo and summary["errors"] == 0
    # Count actual completions in the measurement window, not eventual replies / send duration.
    rows = [json.loads(line) for line in (folder / f"{tag}.jsonl").read_text().splitlines()]
    warm, duration = summary["warmup_s"], summary["duration_s"]
    completed = sum(r["status"] == "ok" and warm <= r["receive_s"] < warm + duration for r in rows)
    cohort = [r for r in rows if r["planned_s"] >= warm]
    attainment = sum(r["status"] == "ok" and r["e2e_ms"] <= slo for r in cohort) / len(cohort)
    return {"source": "T7 target-rate check", "status": ("pass" if passed else "fail") if valid else "invalid",
            "rate": summary["rate"], "p50_ms": summary["p50_ms"], "p95_ms": p95,
            "p99_ms": summary["p99_ms"], "throughput": completed / duration,
            "slo_attainment": attainment, "errors": summary["errors"], "core_seconds": point["core_seconds"],
            "max_rate": None, "tag": tag, "seed": summary["seed"], "start": summary["start"]}


def run(args):
    config, variants = read(HERE / "config.json"), recipes()
    record = read(ICP / "splits.json")
    args.work = args.work.resolve()
    sla, t6 = read(args.t6 / "sla.json"), read(args.t6 / "t6/index.json")
    frozen = {"config": config, "variants": variants, "dataset_revision": record["revision"],
              "seed": record["seed"], "SLO_ms": sla["SLO_ms"], "target_rps": sla["target_rps"]}
    manifest = args.work / "experiment.json"
    if manifest.exists() and read(manifest) != frozen:
        raise ValueError("Experiment changed; choose a fresh --work directory")
    evidence = args.work / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    for name in ("sla.json", "t6/index.json"):
        dest = evidence / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(args.t6 / name, dest)
    save(manifest, frozen)
    original = kubectl_json("get", "deployment", "icp-ocr")
    save(args.work / "deployment-before.json", original)
    patch_path = args.work / "restore-deployment.json"
    save(patch_path, {"spec": {"replicas": original["spec"]["replicas"], "template": original["spec"]["template"]}})
    env = [item for item in original["spec"]["template"]["spec"]["containers"][0]["env"]
           if item["name"].startswith("MINIO_")]
    try:
        job(args.work, args.image, "t7-register", ["register"], env)
        # The new blue+PSM6 recipe gets a complete development run before test use.
        new_name = "blue_tesseract_psm6"
        if not summary_path(args.work, new_name, "development").exists():
            deploy(new_name, 8, args.image)
            job(args.work, args.image, "t7-development", ["score", "--variant", new_name, "--split", "development"], env)
        save(args.work / "frozen.json", frozen)
        for settings in variants:
            name = settings["name"]
            if summary_path(args.work, name).exists():
                continue
            directories = [args.test_results] if args.test_results else [ICP / "results/test-all", HERE.parent / "results/test-all"]
            if any(reuse_test(directory, args.work, settings, record) for directory in directories):
                continue
            deploy(name, 8, args.image)
            job(args.work, args.image, "t7-test", ["score", "--variant", name, "--split", "test"], env)
        job(args.work, args.image, "t7-record-accuracy", ["register", "--publish"], env)
        performance_file = args.work / "performance.json"
        performance = read(performance_file) if performance_file.exists() else {}
        for candidate in config["deployments"]:
            name, replicas, key = candidate["variant"], candidate["replicas"], candidate["id"]
            if key in performance:
                continue
            matches = [r for r in t6["selected"] if r["variant"] == name and r["replicas"] == replicas
                       and r["batch"] == 1 and r.get("valid") and r.get("p95_ms") is not None]
            if matches:
                point = matches[0]
                capacity = point["rate"] if point["slo_ok"] and not point["errors"] else 0
                performance[key] = {"source": "T6 capacity", "status": "pass" if capacity >= sla["target_rps"] else "fail",
                                    "rate": point["rate"], "max_rate": capacity, "tag": point["tag"],
                                    **{k: point.get(k) for k in ("p50_ms", "p95_ms", "p99_ms", "throughput", "errors", "core_seconds", "seed", "start")},
                                    "slo_attainment": None}
            else:
                deploy(name, replicas, args.image)
                tag = f"t7-{key}"
                folder = args.work / "load" / tag
                if not (folder / f"{tag}.summary.json").exists():
                    call(sys.executable, HERE.parent / "profile/run_point.py", "--variant", name,
                         "--replicas", replicas, "--batch", 1, "--rate", sla["target_rps"],
                         "--duration", 90, "--warmup", 15, "--seed", 8001, "--start", 0,
                         "--slo-ms", sla["SLO_ms"], "--tag", tag, "--image", args.image,
                         "--scale-sh", HERE.parent / "k8s/scale.sh", "--runs-dir", args.work / "load")
                performance[key] = measured_performance(folder, tag, sla["SLO_ms"])
            save(performance_file, performance)
    finally:
        call("kubectl", "-n", "icp", "patch", "deployment", "icp-ocr", "--type=merge", "--patch-file", patch_path)
        call("kubectl", "-n", "icp", "rollout", "status", "deployment/icp-ocr", "--timeout=600s")
    print("T7 measurements saved. OCR deployment restored.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("run", "register", "score"))
    parser.add_argument("--work", type=Path, default=Path.home() / "icp/t7")
    parser.add_argument("--t6", type=Path, default=HERE.parent / "results")
    parser.add_argument("--image", default="icp-ocr:t7")
    parser.add_argument("--test-results", type=Path)
    parser.add_argument("--variant")
    parser.add_argument("--split", choices=("development", "test"), default="test")
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    if args.action == "score":
        asyncio.run(score(args))
    else:
        {"run": run, "register": register}[args.action](args)


if __name__ == "__main__":
    main()
