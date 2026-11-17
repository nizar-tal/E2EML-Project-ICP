#!/usr/bin/env python3
# T6 profiling sweep on the VM host (stdlib + kubectl + run_point.py).
import argparse, json, os, subprocess, sys
from pathlib import Path

VARIANTS = [
    "tesseract_default",
    "tesseract_psm6",
    "easyocr_original",
    "easyocr_half",
]
RUN_POINT = os.path.expanduser("~/icp/T3/service/profile/run_point.py")
RUNS = Path(os.path.expanduser("~/icp/runs"))
T6 = RUNS / "t6"
SLA = RUNS / "sla.json"
INDEX = T6 / "index.json"


def sh(cmd, check=True):
    print("+", cmd, flush=True)
    return subprocess.run(cmd, shell=True, check=check)


def load_summary(tag):
    return json.loads((T6 / tag / f"{tag}.summary.json").read_text())


def load_point(tag):
    return json.loads((T6 / tag / "point.json").read_text())


def run_point(variant, replicas, batch, rate, duration, warmup, seed, start, slo_ms, tag):
    cmd = (
        f"python3 {RUN_POINT} --variant {variant} --replicas {replicas} "
        f"--batch {batch} --rate {rate} --duration {duration} --warmup {warmup} "
        f"--seed {seed} --start {start} --tag {tag} --arrival poisson "
        f"--runs-dir {T6}"
    )
    if slo_ms is not None:
        cmd += f" --slo-ms {slo_ms}"
    sh(cmd)
    point = load_point(tag)
    if not point.get("valid", True):
        print(f"invalid point (restart); retry once: {tag}", flush=True)
        tag2 = (tag + "-retry")[:60]
        cmd2 = cmd.replace(f"--tag {tag}", f"--tag {tag2}")
        sh(cmd2)
        point = load_point(tag2)
        tag = tag2
    summary = load_summary(tag)
    return tag, point, summary


def meets_slo(summary, slo_ms):
    return summary.get("p95_ms", 1e18) <= slo_ms and summary.get("errors", 0) == 0


def pack(variant, replicas, batch, phase, rate, tag, point, summary, slo_ms, seed, start):
    return {
        "variant": variant, "replicas": replicas, "batch": batch,
        "phase": phase, "rate": rate, "tag": tag,
        "p50_ms": summary.get("p50_ms"), "p95_ms": summary.get("p95_ms"),
        "p99_ms": summary.get("p99_ms"),
        "throughput": summary.get("completed_rate"),
        "mean_queue_ms": summary.get("mean_queue_ms"),
        "mean_inference_ms": summary.get("mean_inference_ms"),
        "mean_network_ms": summary.get("mean_network_ms"),
        "errors": summary.get("errors"),
        "assertion_pass": summary.get("assertion_pass"),
        "field_exact": summary.get("field_exact"),
        "seed": seed, "start": start,
        "valid": point.get("valid"),
        "core_seconds": point.get("core_seconds"),
        "slo_ok": meets_slo(summary, slo_ms),
    }


def search_max(variant, replicas, batch, t0, slo_ms, seed, sc, results):
    low_rate = max(0.2 * replicas, 0.2)
    start = next(sc)
    tag0 = f"{variant}_r{replicas}_b{batch}_low"
    tag, point, summary = run_point(
        variant, replicas, batch, low_rate, 60, 15, seed, start, slo_ms, tag0)
    entry = pack(variant, replicas, batch, "low", low_rate, tag, point, summary, slo_ms, seed, start)
    results.append(entry)
    if not entry["slo_ok"]:
        entry["selected"] = True
        entry["max_throughput_slo"] = 0.0
        return entry

    rate = max(t0 * replicas, low_rate)
    best = entry
    lo_pass = low_rate
    hi_fail = None
    for _ in range(6):
        start = next(sc)
        rate_tag = f"{rate:g}".replace(".", "p")
        tag_s = f"{variant}_r{replicas}_b{batch}_r{rate_tag}"
        tag, point, summary = run_point(
            variant, replicas, batch, rate, 90, 15, seed, start, slo_ms, tag_s)
        ok = meets_slo(summary, slo_ms)
        e = pack(variant, replicas, batch, "search", rate, tag, point, summary, slo_ms, seed, start)
        results.append(e)
        if ok:
            best = e
            lo_pass = rate
            rate = rate * 2.0 if hi_fail is None else (lo_pass + hi_fail) / 2.0
        else:
            hi_fail = rate
            rate = max(rate / 2.0, low_rate) if lo_pass is None else (lo_pass + hi_fail) / 2.0
        if hi_fail is not None and lo_pass is not None and (hi_fail - lo_pass) < 0.15 * max(lo_pass, 0.5):
            break
        if rate <= low_rate and not ok and lo_pass is None:
            break

    for r in results:
        if r["tag"] == best["tag"]:
            r["selected"] = True
            r["max_throughput_slo"] = r["throughput"] if r.get("slo_ok") else 0.0
            return r
    best["selected"] = True
    best["max_throughput_slo"] = best["throughput"] if best.get("slo_ok") else 0.0
    return best


def grid(reduced):
    pts = []
    for v in VARIANTS:
        for r in (1, 2, 4, 8):
            pts.append((v, r, 1))
    if reduced:
        for v in VARIANTS:
            for r in (1, 4):
                for b in (4, 8):
                    pts.append((v, r, b))
    else:
        for v in VARIANTS:
            for r in (1, 2, 4, 8):
                for b in (4, 8):
                    pts.append((v, r, b))
    return pts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reduced", action="store_true")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--seed", type=int, default=8001)
    args = ap.parse_args()

    sla = json.loads(SLA.read_text())
    slo = float(sla["SLO_ms"])
    t0 = float(sla["T0_rps"])
    T6.mkdir(parents=True, exist_ok=True)

    n = [0]

    def sc():
        while True:
            n[0] = (n[0] + 37) % 17000
            yield n[0]

    counter = sc()
    results = []
    selected = []
    if args.resume and INDEX.exists():
        prev = json.loads(INDEX.read_text())
        selected = list(prev.get("selected") or [])
        results = list(prev.get("all_runs") or [])
        print(f"resume: kept selected={len(selected)} runs={len(results)}", flush=True)
    done = {(s["variant"], s["replicas"], s["batch"]) for s in selected}
    pts = grid(args.reduced)
    print(f"points={len(pts)} reduced={args.reduced} slo={slo} t0={t0}", flush=True)

    for i, (variant, replicas, batch) in enumerate(pts):
        if (variant, replicas, batch) in done:
            print(f"=== skip [{i+1}/{len(pts)}] {variant} r={replicas} b={batch} ===", flush=True)
            continue
        print(f"=== [{i+1}/{len(pts)}] {variant} r={replicas} b={batch} ===", flush=True)
        best = search_max(variant, replicas, batch, t0, slo, args.seed, counter, results)
        selected.append(best)
        INDEX.write_text(json.dumps({
            "reduced": args.reduced, "slo_ms": slo, "t0_rps": t0,
            "selected": selected, "all_runs": results,
        }, indent=2))

    print("DONE", len(selected), "selected", flush=True)


if __name__ == "__main__":
    main()
