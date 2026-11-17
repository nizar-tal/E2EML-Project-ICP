#!/usr/bin/env python3
# SLA calibration on the VM (guide procedure). Uses run_point.py.
import json, os, subprocess, sys, time
from pathlib import Path

ROOT = Path(os.path.expanduser("~/icp/T3/service/profile"))
RUNS = Path(os.path.expanduser("~/icp/runs"))
RP = ROOT / "run_point.py"
VARIANT = "tesseract_default"
SEED = 8001


def run_point(tag, rate, duration, warmup, start, slo_ms=None):
    cmd = [
        sys.executable, str(RP),
        "--variant", VARIANT, "--replicas", "1", "--batch", "1",
        "--rate", str(rate), "--duration", str(duration), "--warmup", str(warmup),
        "--seed", str(SEED), "--start", str(start), "--tag", tag, "--arrival", "poisson",
    ]
    if slo_ms is not None:
        cmd += ["--slo-ms", str(slo_ms)]
    print("+", " ".join(cmd), flush=True)
    subprocess.check_call(cmd)
    return json.loads((RUNS / tag / f"{tag}.summary.json").read_text())


def main():
    start = 0
    # L0
    tag = "sla-L0"
    s = run_point(tag, 0.2, 180, 15, start)
    start += s["sent"]
    L0 = s["p95_ms"]
    SLO = 2.0 * L0
    print(f"L0_ms={L0} SLO_ms={SLO}", flush=True)

    # coarse T0 search
    rates = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0]
    last_ok = None
    first_fail = None
    table = []
    over = 0
    for r in rates:
        tag = f"sla-T0-{r}".replace(".", "p")
        s = run_point(tag, r, 120, 15, start, slo_ms=SLO)
        start += s["sent"]
        p95 = s["p95_ms"]
        ok = p95 is not None and p95 <= SLO
        table.append({"rate": r, "p95_ms": p95, "ok": ok, "tag": tag,
                      "mean_queue_ms": s.get("mean_queue_ms"), "seed": SEED, "start": s.get("start", start)})
        print(f"rate={r} p95={p95} ok={ok}", flush=True)
        if ok:
            last_ok = r
            over = 0
        else:
            if first_fail is None:
                first_fail = r
            over += 1
            if over >= 2 and first_fail is not None:
                break

    # refine 0.25 steps between last_ok and first_fail
    if last_ok is not None and first_fail is not None:
        r = last_ok + 0.25
        while r < first_fail - 1e-9:
            tag = f"sla-T0-{r:.2f}".replace(".", "p")
            s = run_point(tag, r, 120, 15, start, slo_ms=SLO)
            start += s["sent"]
            p95 = s["p95_ms"]
            ok = p95 is not None and p95 <= SLO
            table.append({"rate": r, "p95_ms": p95, "ok": ok, "tag": tag,
                          "mean_queue_ms": s.get("mean_queue_ms"), "seed": SEED})
            print(f"refine rate={r} p95={p95} ok={ok}", flush=True)
            if ok:
                last_ok = r
            else:
                first_fail = r
                break
            r += 0.25

    T0 = last_ok if last_ok is not None else 0.2
    mult = 4.0
    target = mult * T0
    # capacity: replicas ≈ target/T0 = 4; VM 48 cores OK
    if target / T0 > 48:
        mult = 48 * T0 / max(target, 1e-9)
        target = mult * T0

    out = {
        "L0_ms": L0, "SLO_ms": SLO, "T0_rps": T0, "target_rps": target,
        "multiplier": mult, "seed": SEED, "variant": VARIANT,
        "vm_cores": 48, "replicas_at_target_est": target / T0 if T0 else None,
        "run_tags": ["sla-L0"] + [t["tag"] for t in table],
        "table": table,
    }
    path = RUNS / "sla.json"
    path.write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2), flush=True)


if __name__ == "__main__":
    main()
