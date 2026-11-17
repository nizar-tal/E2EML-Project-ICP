#!/usr/bin/env python3
# Open-loop OCR load generator. Cards from splits.json load_pool only.
import argparse, asyncio, json, math, random, sys, time
from io import BytesIO
from pathlib import Path

import grpc.aio
import numpy as np
from PIL import Image
from datasets import load_dataset

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, "/app/icp")
import ocr_pb2, ocr_pb2_grpc
from metrics import normalize

FIELDS = ("id_number", "gender", "birth_year", "birth_month", "birth_day")
CLS = {0: "name", 1: "gender", 2: "ethnicity", 3: "birth_year",
       4: "birth_month", 5: "birth_day", 6: "address", 7: "id_number"}


def load_pool_indices(splits_path):
    data = json.loads(Path(splits_path).read_text())
    return data["revision"], list(data["indices"]["load_pool"])


def gt_fields(ocr_list):
    out = {k: "" for k in FIELDS}
    for item in ocr_list:
        name = CLS.get(item.get("cls"))
        if name in out:
            out[name] = normalize(item.get("word", ""))
    return out


def percentile(vals, p):
    if not vals:
        return None
    s = sorted(vals)
    k = (len(s) - 1) * p / 100.0
    f, c = math.floor(k), math.ceil(k)
    if f == c:
        return s[int(k)]
    return s[f] * (c - k) + s[c] * (k - f)


def make_schedule(rate, total_s, arrival, seed):
    rng = random.Random(seed)
    times = []
    t = 0.0
    while t < total_s:
        times.append(t)
        if arrival == "constant":
            t += 1.0 / rate
        else:
            t += rng.expovariate(rate)
    return times


async def one_call(stub, card, planned, t0, tag):
    idx, png, gt = card["idx"], card["png"], card["gt"]
    actual = time.perf_counter() - t0
    row = {
        "tag": tag, "card_index": idx,
        "planned_s": planned, "actual_s": actual,
        "receive_s": None, "e2e_ms": None, "status": "ok",
        "queue_ms": None, "preprocess_ms": None, "ocr_ms": None, "total_ms": None,
        "batch_size": None, "variant": None,
        "a1": None, "a2": None, "a3": None, "a4": None, "all": None,
        "fields": {},
    }
    try:
        resp = await stub.Extract(
            ocr_pb2.CardRequest(card_id=str(idx), image=png), timeout=300)
        recv = time.perf_counter() - t0
        t = resp.timing
        a = resp.assertions
        pred = {k: normalize(resp.fields.get(k, "")) for k in FIELDS}
        row.update({
            "receive_s": recv, "e2e_ms": (recv - actual) * 1000.0, "status": "ok",
            "queue_ms": t.queue_ms, "preprocess_ms": t.preprocess_ms,
            "ocr_ms": t.ocr_ms, "total_ms": t.total_ms,
            "batch_size": resp.batch_size, "variant": resp.variant,
            "a1": a.a1, "a2": a.a2, "a3": a.a3, "a4": a.a4, "all": a.all,
            "fields": {
                k: {"pred": pred[k], "gt": gt[k], "exact": pred[k] == gt[k]}
                for k in FIELDS
            },
        })
    except Exception as e:
        recv = time.perf_counter() - t0
        code = getattr(e, "code", None)
        status = code().name if callable(code) else type(e).__name__
        row.update({
            "receive_s": recv, "e2e_ms": (recv - actual) * 1000.0,
            "status": status,
        })
    return row


async def run(args):
    rev, pool = load_pool_indices(args.splits)
    total_s = args.warmup + args.duration
    schedule = make_schedule(args.rate, total_s, args.arrival, args.seed)
    n = len(schedule)
    # preload needed cards (cycle pool from --start)
    need = []
    for i in range(n):
        need.append(pool[(args.start + i) % len(pool)])
    uniq = sorted(set(need))
    print(f"preload cards={len(uniq)} requests={n} rev={rev}", flush=True)
    ds = load_dataset("lansinuote/ocr_id_card", split="train", revision=rev)
    cache = {}
    for idx in uniq:
        row = ds[idx]
        buf = BytesIO()
        Image.fromarray(np.asarray(row["image"].convert("RGB"))).save(buf, format="PNG")
        cache[idx] = {"idx": idx, "png": buf.getvalue(), "gt": gt_fields(row["ocr"])}
    cards = [cache[i] for i in need]

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    lines_path = out / f"{args.tag}.jsonl"
    summary_path = out / f"{args.tag}.summary.json"

    opts = (("grpc.lb_policy_name", "round_robin"),)
    channel = grpc.aio.insecure_channel(args.host, options=opts)
    stub = ocr_pb2_grpc.OCRStub(channel)
    tasks = []
    t0 = time.perf_counter()
    for i, planned in enumerate(schedule):
        now = time.perf_counter() - t0
        delay = planned - now
        if delay > 0:
            await asyncio.sleep(delay)
        tasks.append(asyncio.create_task(
            one_call(stub, cards[i], planned, t0, args.tag)))
    rows = list(await asyncio.gather(*tasks))
    await channel.close()
    rows.sort(key=lambda r: r["planned_s"])
    with lines_path.open("w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    warm = args.warmup
    after = [r for r in rows if r["planned_s"] >= warm]
    ok = [r for r in after if r["status"] == "ok"]
    err = [r for r in after if r["status"] != "ok"]
    e2e = [r["e2e_ms"] for r in ok if r["e2e_ms"] is not None]
    qms = [r["queue_ms"] for r in ok if r["queue_ms"] is not None]
    inf = [(r["ocr_ms"] or 0) + (r["preprocess_ms"] or 0) for r in ok]
    net = [(r["e2e_ms"] or 0) - (r["total_ms"] or 0) for r in ok]
    lags = [abs(r["actual_s"] - r["planned_s"]) * 1000.0 for r in rows]
    wall = rows[-1]["receive_s"] if rows and rows[-1]["receive_s"] else total_s
    sent = len(rows)
    done = len(after)
    send_rate = sent / total_s if total_s else 0
    completed_rate = len(ok) / args.duration if args.duration else 0

    def rate_pass(key):
        vals = [r[key] for r in ok if r.get(key) is not None]
        return (sum(1 for v in vals if v) / len(vals)) if vals else None

    field_exact = {}
    for k in FIELDS:
        hits = [r["fields"][k]["exact"] for r in ok if k in r.get("fields", {})]
        field_exact[k] = (sum(hits) / len(hits)) if hits else None

    slo_pct = None
    if args.slo_ms is not None and e2e:
        slo_pct = sum(1 for x in e2e if x <= args.slo_ms) / len(e2e)

    summary = {
        "tag": args.tag, "seed": args.seed, "start": args.start,
        "rate": args.rate, "duration_s": args.duration, "warmup_s": args.warmup,
        "arrival": args.arrival, "host": args.host,
        "target_rate": args.rate,
        "achieved_send_rate": send_rate,
        "completed_rate": completed_rate,
        "sent": sent, "completed_after_warmup": len(ok), "errors": len(err),
        "p50_ms": percentile(e2e, 50), "p95_ms": percentile(e2e, 95),
        "p99_ms": percentile(e2e, 99),
        "mean_queue_ms": (sum(qms) / len(qms)) if qms else None,
        "mean_inference_ms": (sum(inf) / len(inf)) if inf else None,
        "mean_network_ms": (sum(net) / len(net)) if net else None,
        "slo_ms": args.slo_ms, "slo_attainment": slo_pct,
        "assertion_pass": {
            "all": rate_pass("all"), "a1": rate_pass("a1"), "a2": rate_pass("a2"),
            "a3": rate_pass("a3"), "a4": rate_pass("a4"),
        },
        "field_exact": field_exact,
        "send_lag_max_ms": max(lags) if lags else None,
        "send_lag_ok": (max(lags) < 50.0) if lags else False,
        "wall_s": wall, "pool_size": len(pool),
    }
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(json.dumps(summary, indent=2), flush=True)
    if summary["send_lag_max_ms"] is not None and summary["send_lag_max_ms"] >= 50:
        print("WARN send_lag_max_ms >= 50", flush=True)
        # keep exit 0 so profiling Jobs still yield a summary; check send_lag_ok in JSON


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="dns:///icp-ocr.icp.svc.cluster.local:50051")
    p.add_argument("--rate", type=float, required=True)
    p.add_argument("--duration", type=float, required=True)
    p.add_argument("--warmup", type=float, default=15.0)
    p.add_argument("--arrival", choices=("poisson", "constant"), default="poisson")
    p.add_argument("--seed", type=int, default=8001)
    p.add_argument("--start", type=int, default=0)
    p.add_argument("--out", default="/tmp/loadgen-out")
    p.add_argument("--tag", default="run")
    p.add_argument("--slo-ms", type=float, default=None)
    p.add_argument("--splits", default="/app/icp/splits.json")
    args = p.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
