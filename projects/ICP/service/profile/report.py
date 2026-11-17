#!/usr/bin/env python3
# Build T6 tables/plots from work/runs/t6 (or ~/icp/runs/t6).
import argparse, json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

OFFLINE = {
    "tesseract_default": 0.0905,
    "tesseract_psm6": 0.12,
    "easyocr_original": 0.0145,
    "easyocr_half": 0.0045,
}


def load_index(runs: Path):
    idx = runs / "t6" / "index.json"
    if not idx.exists():
        raise SystemExit(f"missing {idx}")
    return json.loads(idx.read_text())


def rows_from_index(data):
    rows = []
    for e in data.get("selected", []):
        v = e["variant"]
        acc = OFFLINE.get(v)
        acc_label = "offline_test (assertion all)" if acc is not None else "online (5 fields)"
        if acc is None:
            fe = e.get("field_exact") or {}
            # mean of found-field exact if present
            vals = [fe[k] for k in fe if isinstance(fe.get(k), (int, float))]
            acc = sum(vals) / len(vals) if vals else None
        rows.append({
            "Stage": "icp-ocr",
            "Variant": v,
            "Batch": e.get("batch"),
            "Replicas": e.get("replicas"),
            "Cores/replica": 1,
            "Cost": e.get("replicas"),
            "p50": e.get("p50_ms"),
            "p95": e.get("p95_ms"),
            "p99": e.get("p99_ms"),
            "throughput": e.get("throughput"),
            "Max throughput meeting SLO": e.get("max_throughput_slo", 0.0),
            "Accuracy": acc,
            "Accuracy source": acc_label,
            "mean_queue_ms": e.get("mean_queue_ms"),
            "mean_inference_ms": e.get("mean_inference_ms"),
            "mean_network_ms": e.get("mean_network_ms"),
            "errors": e.get("errors"),
            "seed": e.get("seed"),
            "start": e.get("start"),
            "tag": e.get("tag"),
            "rate": e.get("rate"),
            "valid": e.get("valid"),
        })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default=str(Path(__file__).resolve().parents[2] / "runs"))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    runs = Path(args.runs)
    out = Path(args.out) if args.out else runs / "report"
    out.mkdir(parents=True, exist_ok=True)

    data = load_index(runs)
    rows = rows_from_index(data)
    df = pd.DataFrame(rows)
    df.to_csv(out / "t6_table.csv", index=False)
    (out / "t6_table.md").write_text(df.to_markdown(index=False) + "\n")

    # accuracy vs p95 (1 replica, batch 1 preferred)
    sub = df[(df["Replicas"] == 1) & (df["Batch"] == 1)]
    if sub.empty:
        sub = df.drop_duplicates("Variant")
    fig, ax = plt.subplots(figsize=(6, 4))
    for _, r in sub.iterrows():
        ax.scatter(r["p95"], r["Accuracy"], label=r["Variant"])
    ax.set_xlabel("p95 latency (ms)")
    ax.set_ylabel("Accuracy")
    ax.set_title("Accuracy vs p95 latency")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out / "acc_vs_p95.png", dpi=120)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(6, 4))
    for _, r in sub.iterrows():
        ax.scatter(r["Max throughput meeting SLO"], r["Accuracy"], label=r["Variant"])
    ax.set_xlabel("Max throughput meeting SLO (req/s)")
    ax.set_ylabel("Accuracy")
    ax.set_title("Accuracy vs max throughput")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out / "acc_vs_maxtput.png", dpi=120)
    plt.close(fig)

    # latency breakdown at 1 replica, batch 1
    b = df[(df["Replicas"] == 1) & (df["Batch"] == 1)].copy()
    if not b.empty:
        fig, ax = plt.subplots(figsize=(7, 4))
        x = range(len(b))
        q = b["mean_queue_ms"].fillna(0)
        inf = b["mean_inference_ms"].fillna(0)
        net = b["mean_network_ms"].fillna(0)
        ax.bar(x, q, label="queue")
        ax.bar(x, inf, bottom=q, label="inference")
        ax.bar(x, net, bottom=q + inf, label="network")
        ax.set_xticks(list(x))
        ax.set_xticklabels(b["Variant"], rotation=20, ha="right")
        ax.set_ylabel("ms")
        ax.set_title("Latency breakdown (1 replica, batch 1)")
        ax.legend()
        fig.tight_layout()
        fig.savefig(out / "latency_breakdown.png", dpi=120)
        plt.close(fig)

    print(f"wrote {out}", flush=True)


if __name__ == "__main__":
    main()
