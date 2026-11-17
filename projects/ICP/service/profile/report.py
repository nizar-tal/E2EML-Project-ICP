#!/usr/bin/env python3
# Build T5/T6 tables and plots from work/runs.
import argparse, json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import NullLocator, NullFormatter
import pandas as pd

ACC = {
    "tesseract_default": 0.362,
    "tesseract_psm6": 0.411,
    "easyocr_original": 0.347,
    "easyocr_half": 0.190,
}
ORDER = ["tesseract_default", "tesseract_psm6", "easyocr_original", "easyocr_half"]
COL = {
    "tesseract_default": "#1F4E9E",
    "tesseract_psm6": "#2E7D32",
    "easyocr_original": "#C62828",
    "easyocr_half": "#EF8F00",
}
SHORT = {
    "tesseract_default": "tesseract_default",
    "tesseract_psm6": "tesseract_psm6",
    "easyocr_original": "easyocr_original",
    "easyocr_half": "easyocr_half",
}


def load_index(runs: Path):
    idx = runs / "t6" / "index.json"
    if not idx.exists():
        raise SystemExit(f"missing {idx}")
    return json.loads(idx.read_text())


def offered_max(e):
    if e.get("slo_ok"):
        return float(e.get("rate") or 0.0)
    return 0.0


def keep_point(e):
    if e.get("valid") is False:
        return False
    if e.get("mean_inference_ms") is None:
        return False
    p95 = e.get("p95_ms")
    if p95 is None or (isinstance(p95, (int, float)) and p95 >= 1e17):
        return False
    return True


def csv_tex(df: pd.DataFrame, out: Path, stem: str):
    df.to_csv(out / f"{stem}.csv", index=False)
    # simple latex tabular body (no document wrapper)
    cols = list(df.columns)
    lines = [" & ".join(cols) + r" \\", r"\hline"]
    for _, row in df.iterrows():
        cells = []
        for c in cols:
            v = row[c]
            if isinstance(v, float):
                cells.append(f"{v:.2f}" if abs(v) >= 0.01 or v == 0 else f"{v:.4f}")
            else:
                cells.append(str(v))
        lines.append(" & ".join(cells) + r" \\")
    (out / f"{stem}.tex").write_text("\n".join(lines) + "\n")


def table2(data, slo_ms):
    rows = []
    for e in data.get("selected", []):
        if not keep_point(e):
            continue
        p95 = float(e["p95_ms"])
        miss_low = (e.get("phase") == "low") and (not e.get("slo_ok"))
        p95_s = f"{p95:.1f}*" if miss_low else f"{p95:.1f}"
        thr = e.get("completed_throughput", e.get("throughput"))
        rows.append({
            "Stage": "OCR",
            "Variant": e["variant"],
            "Batch": int(e["batch"]),
            "Replicas": int(e["replicas"]),
            "Cores/replica": 1,
            "Cost": int(e["replicas"]),
            "p50": round(float(e["p50_ms"]), 1),
            "p95": p95_s,
            "p99": round(float(e["p99_ms"]), 1),
            "Throughput": round(float(thr or 0.0), 2),
            "Max within SLA": round(offered_max(e), 2),
            "Accuracy": ACC[e["variant"]],
            "_ord_v": ORDER.index(e["variant"]),
            "_p95_num": p95,
        })
    rows.sort(key=lambda r: (r["_ord_v"], r["Batch"], r["Replicas"]))
    for r in rows:
        r.pop("_ord_v", None)
        r.pop("_p95_num", None)
    return pd.DataFrame(rows)


def table3(data):
    rows = []
    for e in data.get("all_runs", []):
        if e.get("phase") != "low":
            continue
        if e.get("replicas") != 1 or e.get("batch") != 1:
            continue
        if not keep_point(e):
            continue
        rows.append({
            "Variant": e["variant"],
            "mean_queue_ms": round(float(e["mean_queue_ms"]), 1),
            "mean_inference_ms": round(float(e["mean_inference_ms"]), 1),
            "mean_network_ms": round(float(e["mean_network_ms"]), 1),
            "p95_ms": round(float(e["p95_ms"]), 1),
            "_ord": ORDER.index(e["variant"]),
        })
    # one per variant (last wins if duplicates)
    by_v = {}
    for r in rows:
        by_v[r["Variant"]] = r
    ordered = [by_v[v] for v in ORDER if v in by_v]
    for r in ordered:
        r.pop("_ord", None)
    return pd.DataFrame(ordered)


def table1(runs: Path):
    sla = json.loads((runs / "sla.json").read_text())
    slo = float(sla["SLO_ms"])
    rows = []
    # L0 row (very low load) — not always listed in table[]
    l0 = float(sla["L0_ms"])
    # prefer summary p95 if present
    summ = runs / "sla-L0" / "sla-L0.summary.json"
    if summ.exists():
        l0 = float(json.loads(summ.read_text()).get("p95_ms", l0))
    rows.append({"rate": 0.2, "p95": round(l0, 1), "within_SLA": l0 <= slo})
    for t in sla.get("table", []):
        rows.append({
            "rate": float(t["rate"]),
            "p95": round(float(t["p95_ms"]), 1),
            "within_SLA": bool(t.get("ok")),
        })
    rows.sort(key=lambda r: r["rate"])
    return pd.DataFrame(rows), slo


def fig_t5_sla(df, slo_ms, out: Path):
    fig, ax = plt.subplots(figsize=(7, 4.2), dpi=160)
    ax.axhline(slo_ms, ls="--", color="#444", lw=1.2, label=f"SLO={slo_ms:.0f} ms")
    for _, r in df.iterrows():
        c = "#2E7D32" if r["within_SLA"] else "#C62828"
        ax.scatter(r["rate"], r["p95"], s=70, color=c, zorder=3, edgecolor="white", lw=0.8)
    ax.plot(df["rate"], df["p95"], color="#888", lw=1, alpha=0.6)
    ax.set_xlabel("Offered rate (req/s)")
    ax.set_ylabel("p95 latency (ms)")
    ax.set_title("T5 SLA calibration (tesseract_default, 1 replica)")
    ax.grid(alpha=0.25)
    ax.legend(fontsize=9)
    fig.tight_layout()
    fig.savefig(out / "t5_sla.png")
    plt.close(fig)


def fig_acc_vs_p95(data, slo_ms, out: Path):
    low = {r["variant"]: r for r in data.get("all_runs", [])
           if r.get("phase") == "low" and r.get("replicas") == 1 and r.get("batch") == 1
           and keep_point(r)}
    plt.rcParams.update({"font.size": 11})
    fig, ax = plt.subplots(figsize=(7, 4.4), dpi=200)
    ax.axvspan(400, slo_ms, color="#2E7D32", alpha=0.07)
    ax.axvspan(slo_ms, 9000, color="#C62828", alpha=0.06)
    ax.axvline(slo_ms, ls="--", color="#444", lw=1.2)
    ax.text(slo_ms * 0.96, 0.158, "meets SLA", ha="right", va="bottom",
            fontsize=10, color="#2E7D32")
    ax.text(slo_ms * 1.04, 0.158, "misses SLA (> 1079 ms)", ha="left", va="bottom",
            fontsize=10, color="#C62828")
    offs = {"tesseract_default": (10, -14), "tesseract_psm6": (10, 4),
            "easyocr_original": (-10, 10), "easyocr_half": (10, -4)}
    for v in ORDER:
        if v not in low:
            continue
        x, y = low[v]["p95_ms"], ACC[v]
        ax.scatter(x, y, s=110, color=COL[v], zorder=3, edgecolor="white", lw=1)
        ax.annotate(f"{v}\n{x:.0f} ms, acc {y:.2f}", (x, y), textcoords="offset points",
                    xytext=offs[v], ha="right" if v == "easyocr_original" else "left",
                    fontsize=9.5, color=COL[v])
    ax.set_xscale("log")
    ax.xaxis.set_minor_locator(NullLocator())
    ax.xaxis.set_minor_formatter(NullFormatter())
    ax.set_xticks([500, 1000, 2000, 5000])
    ax.set_xticklabels(["500", "1000", "2000", "5000"])
    ax.set_xlim(400, 9000)
    ax.set_ylim(0.15, 0.46)
    ax.grid(alpha=0.25)
    ax.set_xlabel("p95 response time at low load, 1 replica (ms, log scale)")
    ax.set_ylabel("Field accuracy (test split)")
    ax.set_title("Accuracy vs. p95 latency per variant", fontsize=12)
    fig.tight_layout()
    fig.savefig(out / "t6_acc_vs_p95.png")
    plt.close(fig)


def fig_acc_vs_maxtput(data, out: Path):
    offs = {"tesseract_default": (-10, -30), "tesseract_psm6": (-10, 8),
            "easyocr_original": (12, -4), "easyocr_half": (12, -4)}
    fig, ax = plt.subplots(figsize=(7, 4.4), dpi=200)
    for v in ORDER:
        hits = [r for r in data.get("selected", [])
                if r.get("variant") == v and r.get("batch") == 1 and r.get("replicas") == 8
                and keep_point(r)]
        if not hits:
            continue
        r = hits[0]
        x = offered_max(r)
        y = ACC[v]
        ax.scatter(x, y, s=110, color=COL[v], zorder=3, edgecolor="white", lw=1)
        txt = (f"{v}\n{x:.1f} cards/s, acc {y:.2f}" if x > 0
               else f"{v}\nnever meets SLA, acc {y:.2f}")
        ax.annotate(txt, (x, y), textcoords="offset points", xytext=offs[v],
                    ha="right" if offs[v][0] < 0 else "left",
                    fontsize=9.5, color=COL[v])
    ax.set_xlabel("Max throughput within SLA with 8 replicas (cards per second)")
    ax.set_ylabel("Field accuracy (test split)")
    ax.set_xlim(-1, 21)
    ax.set_ylim(0.15, 0.46)
    ax.grid(alpha=0.25)
    ax.set_title("Accuracy vs. max throughput per variant", fontsize=12)
    fig.tight_layout()
    fig.savefig(out / "t6_acc_vs_maxtput.png")
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    # Default: committed results/ next to this service folder.
    ap.add_argument("--runs", default=str(Path(__file__).resolve().parents[1] / "results"))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    runs = Path(args.runs)
    out = Path(args.out) if args.out else runs / "report"
    out.mkdir(parents=True, exist_ok=True)

    data = load_index(runs)
    slo = float(data.get("slo_ms") or json.loads((runs / "sla.json").read_text())["SLO_ms"])

    t1, slo1 = table1(runs)
    csv_tex(t1, out, "t5_sla")
    fig_t5_sla(t1, slo1, out)

    t2 = table2(data, slo)
    csv_tex(t2, out, "t6_table")
    try:
        md = t2.to_markdown(index=False)
    except Exception:
        md = t2.to_csv(index=False)
    (out / "t6_table.md").write_text(md + "\n")

    t3 = table3(data)
    csv_tex(t3, out, "t6_breakdown")

    fig_acc_vs_p95(data, slo, out)
    fig_acc_vs_maxtput(data, out)

    print(f"wrote {out} rows_t2={len(t2)} rows_t3={len(t3)} rows_t1={len(t1)}", flush=True)


if __name__ == "__main__":
    main()
