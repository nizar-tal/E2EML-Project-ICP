#!/usr/bin/env python3
# One profiling point on the VM host (stdlib + kubectl only).
import argparse, json, os, subprocess, sys, time
from pathlib import Path


def sh(cmd, check=True):
    print("+", cmd, flush=True)
    return subprocess.run(cmd, shell=True, check=check)


def out(cmd):
    return subprocess.check_output(cmd, shell=True, text=True).strip()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--variant", default="tesseract_default")
    p.add_argument("--replicas", type=int, default=1)
    p.add_argument("--batch", type=int, default=1)
    p.add_argument("--rate", type=float, required=True)
    p.add_argument("--duration", type=float, default=60)
    p.add_argument("--warmup", type=float, default=15)
    p.add_argument("--seed", type=int, default=8001)
    p.add_argument("--start", type=int, default=0)
    p.add_argument("--slo-ms", type=float, default=None)
    p.add_argument("--tag", required=True)
    p.add_argument("--arrival", default="poisson")
    p.add_argument("--scale-sh", default=os.path.expanduser("~/icp/T3/service/k8s/scale.sh"))
    p.add_argument("--runs-dir", default=os.path.expanduser("~/icp/runs"))
    args = p.parse_args()

    runs = Path(args.runs_dir) / args.tag
    runs.mkdir(parents=True, exist_ok=True)
    # loadgen writes here via hostPath (pod user uid 1000)
    os.chmod(runs, 0o777)

    sh(f"kubectl -n icp set env deploy/icp-ocr VARIANT={args.variant} "
       f"MAX_BATCH={args.batch} BATCH_TIMEOUT_MS=10 GRPC_THREADS=256")
    sh(f"{args.scale_sh} {args.replicas}")
    sh("kubectl -n icp rollout status deploy/icp-ocr --timeout=600s")

    def restart_map():
        raw = out("kubectl -n icp get pods -l app=icp-ocr -o json")
        data = json.loads(raw)
        m = {}
        for item in data.get("items", []):
            name = item["metadata"]["name"]
            cs = item.get("status", {}).get("containerStatuses") or []
            n = int(cs[0].get("restartCount", 0)) if cs else 0
            m[name] = n
        return m

    restarts_before = restart_map()

    job = f"lg-{args.tag}".replace("_", "-").lower()[:40]
    sh(f"kubectl -n icp delete job {job} --ignore-not-found")
    # clear prior outputs for this tag (keep job.yaml rewrite)
    for old in runs.glob(f"{args.tag}.*"):
        old.unlink()

    slo_args = ""
    if args.slo_ms is not None:
        slo_args = f'\n            - --slo-ms\n            - "{args.slo_ms}"'
    host_out = str(runs.resolve())
    man = runs / "job.yaml"
    man.write_text(f"""apiVersion: batch/v1
kind: Job
metadata:
  name: {job}
  namespace: icp
spec:
  backoffLimit: 0
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: loadgen
          image: icp-ocr:dev
          imagePullPolicy: Never
          command: ["python", "/app/loadgen.py"]
          args:
            - --host
            - dns:///icp-ocr.icp.svc.cluster.local:50051
            - --rate
            - "{args.rate}"
            - --duration
            - "{args.duration}"
            - --warmup
            - "{args.warmup}"
            - --arrival
            - {args.arrival}
            - --seed
            - "{args.seed}"
            - --start
            - "{args.start}"
            - --out
            - /out
            - --tag
            - {args.tag}
            - --splits
            - /app/icp/splits.json{slo_args}
          volumeMounts:
            - name: out
              mountPath: /out
          resources:
            requests: {{cpu: "1", memory: 4Gi}}
            limits: {{cpu: "2", memory: 6Gi}}
      volumes:
        - name: out
          hostPath:
            path: {host_out}
            type: DirectoryOrCreate
""")
    t0 = time.time()
    sh(f"kubectl apply -f {man}")
    deadline = time.time() + 3600
    summary = runs / f"{args.tag}.summary.json"
    while time.time() < deadline:
        exists = subprocess.run(
            f"kubectl -n icp get job {job}", shell=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if exists.returncode != 0:
            print("job disappeared", flush=True)
            sys.exit(1)
        succ = out(f"kubectl -n icp get job {job} -o jsonpath='{{.status.succeeded}}'") or "0"
        fail = out(f"kubectl -n icp get job {job} -o jsonpath='{{.status.failed}}'") or "0"
        if summary.exists() and (succ not in ("", "0") or fail not in ("", "0")):
            break
        if fail not in ("", "0") and not summary.exists():
            sh(f"kubectl -n icp logs job/{job}", check=False)
            sys.exit(1)
        time.sleep(3)
    else:
        print("timeout waiting for job", flush=True)
        sys.exit(1)
    wall = time.time() - t0
    pod = out(f"kubectl -n icp get pods -l job-name={job} -o jsonpath='{{.items[0].metadata.name}}'")
    sh(f"kubectl -n icp logs {pod}", check=False)
    if not summary.exists():
        print("missing summary on hostPath", flush=True)
        sys.exit(1)
    restarts_after = restart_map()
    restarted = False
    for name, after_n in restarts_after.items():
        before_n = restarts_before.get(name, 0)
        if after_n > before_n:
            restarted = True
    # new pods appearing mid-run also count if old ones vanished with higher count already captured
    meta = {
        "tag": args.tag, "variant": args.variant, "replicas": args.replicas,
        "batch": args.batch, "cores_per_replica": 1,
        "cost": args.replicas * 1, "rate": args.rate,
        "duration_s": args.duration, "warmup_s": args.warmup,
        "seed": args.seed, "start": args.start,
        "wall_s": wall, "core_seconds": args.replicas * 1 * wall,
        "slo_ms": args.slo_ms,
        "restarts_before": restarts_before,
        "restarts_after": restarts_after,
        "valid": not restarted,
    }
    (runs / "point.json").write_text(json.dumps(meta, indent=2))
    print(json.dumps(meta, indent=2), flush=True)


if __name__ == "__main__":
    main()
