
"""
this runs only blue PSM 6 at four replicas on the VM and summarizes the results
it was a last minute addition as Ishan pointed out to me it could be interesting to add
"""
import argparse
import json
import shutil
import sys
import time
from pathlib import Path

from t7 import HERE, call, deploy, kubectl_json, measured_performance, read, save


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, default=Path.home() / "icp/t7")
    parser.add_argument("--image", default="icp-ocr:t7")
    args = parser.parse_args()
    work = args.work.resolve()
    frozen = read(work / "frozen.json")
    if frozen["variants"] != read(HERE / "variants.json"):
        raise ValueError("Recipe settings changed since the original T7 run")
    config = read(HERE / "config.json")
    key = "psm6-blue-r4"
    previous = [c for c in config["deployments"] if c["id"] != key]
    if frozen["config"]["deployments"] not in (previous, config["deployments"]):
        raise ValueError("Expected the original six deployments or this seven-deployment extension")
    if frozen["config"]["ablations"] != config["ablations"]:
        raise ValueError("The preprocessing comparisons changed")

    tag = "t7-blue-r4-" + time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    backup = work / "extensions" / tag
    for filename in ("experiment.json", "frozen.json", "performance.json"):
        backup.mkdir(parents=True, exist_ok=True)
        shutil.copy2(work / filename, backup / filename)
    original = kubectl_json("get", "deployment", "icp-ocr")
    container = next(c for c in original["spec"]["template"]["spec"]["containers"] if c["name"] == "ocr")
    if any(container["resources"][kind]["cpu"] != "1" for kind in ("requests", "limits")):
        raise ValueError("This experiment requires one CPU core per OCR replica")
    restore = backup / "restore-deployment.json"
    save(restore, {"spec": {"replicas": original["spec"]["replicas"], "template": original["spec"]["template"]}})
    sla = read(work / "evidence/sla.json")
    try:
        deploy("blue_tesseract_psm6", 4, args.image)
        call(sys.executable, HERE.parent / "profile/run_point.py",
             "--variant", "blue_tesseract_psm6", "--replicas", 4, "--batch", 1,
             "--rate", sla["target_rps"], "--duration", 90, "--warmup", 15,
             "--seed", 8001, "--start", 0, "--slo-ms", sla["SLO_ms"],
             "--tag", tag, "--image", args.image,
             "--scale-sh", HERE.parent / "k8s/scale.sh", "--runs-dir", work / "load")
        result = measured_performance(work / "load" / tag, tag, sla["SLO_ms"])
        if result["status"] == "invalid":
            raise ValueError(f"Invalid measurement; existing results kept. Inspect {work / 'load' / tag}")
        performance = read(work / "performance.json")
        performance[key] = result
        save(work / "performance.json", performance)
        for filename in ("experiment.json", "frozen.json"):
            manifest = read(work / filename)
            manifest["config"] = config
            save(work / filename, manifest)
        print(json.dumps(result, indent=2), flush=True)
        print("Four-replica result added. Accuracy results and T7_REPORT.md were not changed.", flush=True)
    finally:
        call("kubectl", "-n", "icp", "patch", "deployment", "icp-ocr", "--type=merge", "--patch-file", restore)
        call("kubectl", "-n", "icp", "rollout", "status", "deployment/icp-ocr", "--timeout=600s")


if __name__ == "__main__":
    main()
