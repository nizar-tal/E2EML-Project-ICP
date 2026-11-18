# code to regenerate T5/T6/T7 tables and plots from saved 
# results
# it should have t6 report generation under t6/
import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# chatgpt added this as i had import issues?
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[1]), "/app/icp"]
from t7 import read, summary_path


def table(out, stem, rows):
    columns = list(rows[0])
    with (out / f"{stem}.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)

    def cell(value):
        if value is None:
            return "—"
        return f"{value:.3f}" if isinstance(value, float) else str(value)

    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    lines += ["| " + " | ".join(cell(row[k]) for k in columns) + " |" for row in rows]
    text = "\n".join(lines) + "\n"
    (out / f"{stem}.md").write_text(text)
    return text


def pareto(rows):
    return [r for r in rows if not any(
        other["Cost"] <= r["Cost"] and other["Field exact (%)"] >= r["Field exact (%)"]
        and (other["Cost"] < r["Cost"] or other["Field exact (%)"] > r["Field exact (%)"])
        for other in rows)]


def choose(rows):
    return min(rows, key=lambda r: (r["Cost"], -r["Field exact (%)"], r["ID"])) if rows else None


def make_plots(out, rows, ablations):
    # generate all of the plots for the report
    # we used this to fetch all results once

    fig, ax = plt.subplots(figsize=(9, 5))

    for status, color, marker in (("pass", "#287d46", "o"), ("fail", "#b63434", "X")):
        points = [r for r in rows if r["SLA"] == status]
        ax.scatter([r["Cost"] for r in points], [r["Field exact (%)"] for r in points],
                   color=color, marker=marker, s=85, label=f"SLA {status}", zorder=3)
    for front, color, style, label in ( (pareto(rows), "#888888", "--", "Pareto front (all candidates)"),
                                        (pareto([r for r in rows if r["SLA"] == "pass"]), "#287d46", "-", "Pareto front (SLA passing)")):
        points = sorted({(r["Cost"], r["Field exact (%)"]) for r in front})
        if points:
            ax.plot([p[0] for p in points], [p[1] for p in points], style, color=color, label=label)

    for i, row in enumerate(rows):
        ax.annotate(row["ID"], (row["Cost"], row["Field exact (%)"]), xytext=(7, 8 if i % 2 else -14),
                    textcoords="offset points", fontsize=8)
    ax.set(xlabel="OCR cost (replicas × CPU cores per replica)", ylabel="Test field exact match (%)",
           title="T7: cost and accuracy at the calibrated SLA", xticks=sorted({r["Cost"] for r in rows}))
    ax.margins(x=0.25, y=0.25)
    ax.grid(alpha=0.2)
    ax.legend(fontsize=8)
    fig.tight_layout()
    for ext in ("png", "pdf"):
        fig.savefig(out / f"t7_pareto.{ext}", dpi=180)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 4.5))
    x = list(range(len(ablations)))
    ax.bar([i - 0.18 for i in x], [r["Original field exact (%)"] for r in ablations],
           width=0.36, label="Original image", color="#6a8caf")
    ax.bar([i + 0.18 for i in x], [r["Blue field exact (%)"] for r in ablations],
           width=0.36, label="Blue channel", color="#2c6777")
    ax.set(xticks=x, xticklabels=[r["OCR"] for r in ablations], ylabel="Test field exact match (%)",
           title="Same OCR settings, with and without blue-channel preprocessing")
    ax.legend()
    ax.grid(axis="y", alpha=0.2)
    fig.tight_layout()
    for ext in ("png", "pdf"):
        fig.savefig(out / f"t7_ablation.{ext}", dpi=180)
    plt.close(fig)


def make_latency_plot(out, rows, slo_ms, target_rate):
    # pareto plot with latency vs accuracy
    # alternative view of the cost vs accuracy plot

    points = [r for r in rows if r["Measured offered rate (cards/s)"] == target_rate]
    front = [r for r in points if not any(
        other["p95 (ms)"] <= r["p95 (ms)"] and other["Field exact (%)"] >= r["Field exact (%)"]
        and (other["p95 (ms)"] < r["p95 (ms)"] or other["Field exact (%)"] > r["Field exact (%)"])
        for other in points)]
    
    fig, ax = plt.subplots(figsize=(9, 5.5))
    colors = {4: "#2c6777", 8: "#b16b2a"}
    for row in points:
        ax.scatter(row["p95 (ms)"], row["Field exact (%)"], s=95,
                   color=colors[row["Cost"]], marker="o" if row["SLA"] == "pass" else "X",
                   label=f"{row['ID']} (cost {row['Cost']}, SLA {row['SLA']})", zorder=3)
        
    front = sorted(front, key=lambda r: r["p95 (ms)"])
    ax.plot([r["p95 (ms)"] for r in front], [r["Field exact (%)"] for r in front],
            "--", color="#555555", label="Latency–accuracy Pareto front")
    
    ax.axvline(slo_ms, color="#b63434", linestyle=":", label=f"Latency limit: {slo_ms:.1f} ms")
    ax.set_xscale("log")
    ax.set(xlabel="p95 end-to-end latency (ms, logarithmic scale)",
           ylabel="Test field exact match (%)",
           title=f"T7: latency and accuracy at {target_rate:g} cards/s")
    
    ax.margins(x=0.15, y=0.25)
    ax.grid(alpha=0.2)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.18), ncol=2, fontsize=8)
    fig.tight_layout()
    fig.savefig(out / "t7_latency_pareto.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


def report(work):
    from evaluate import write_reports

    frozen = read(work / "frozen.json")
    config, variants = frozen["config"], frozen["variants"]
    sla = read(work / "evidence/sla.json")
    performance = read(work / "performance.json")
    summaries = {v["name"]: read(summary_path(work, v["name"])) for v in variants}
    for name, summary in summaries.items():
        if summary["metrics"]["cards"] != 2000 or summary["settings"] != next(v for v in variants if v["name"] == name):
            raise ValueError(f"Incomplete or mismatched test result: {name}")
    out = work / "report"
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for candidate in config["deployments"]:
        name, key = candidate["variant"], candidate["id"]
        metric, perf = summaries[name]["metrics"], performance[key]
        if perf["status"] == "invalid":
            raise ValueError(f"Invalid performance run for {key}; rerun it before producing final plots")
        rows.append({
            "ID": key, "Stage": "OCR", "Variant": name, "Channel": "blue" if name.startswith("blue_") else "original",
            "Batch": 1, "Replicas": candidate["replicas"], "Cores/replica": 1, "Cost": candidate["replicas"],
            "Field exact (%)": metric["field_exact_match"] * 100,
            "Card exact (%)": metric["card_exact_match"] * 100, "Mean CER": metric["mean_field_cer"],
            "All assertions (%)": metric["assertion_pass_rates"]["all"] * 100,
            "p50 (ms)": perf["p50_ms"], "p95 (ms)": perf["p95_ms"], "p99 (ms)": perf["p99_ms"],
            "Measured offered rate (cards/s)": perf["rate"], "Throughput (cards/s)": perf["throughput"],
            "Max within SLO (cards/s)": perf["max_rate"], "SLO attainment (%)": None if perf["slo_attainment"] is None else perf["slo_attainment"] * 100,
            "Errors": perf["errors"], "Core-seconds": perf["core_seconds"], "SLA": perf["status"],
            "Performance source": perf["source"], "Run tag": perf["tag"],
        })
    
    table(out, "t7_configurations", rows)
    summary_columns = ("ID", "Cost", "Field exact (%)", "p95 (ms)", "Measured offered rate (cards/s)", "SLA")
    table(out, "t7_summary", [{key: row[key] for key in summary_columns} for row in rows])

    ablations = []
    for pair in config["ablations"]:
        original, blue = summaries[pair["original"]]["metrics"], summaries[pair["blue"]]["metrics"]
        ablations.append({"OCR": pair["engine"], "Original field exact (%)": original["field_exact_match"] * 100,
                          "Blue field exact (%)": blue["field_exact_match"] * 100,
                          "Blue minus original (percentage points)": (blue["field_exact_match"] - original["field_exact_match"]) * 100,
                          "Original mean CER": original["mean_field_cer"], "Blue mean CER": blue["mean_field_cer"]})
        
    table(out, "t7_ablation", ablations)
    fields = [{"Variant": name, "Field": key, "Exact match (%)": value * 100}
              for name, summary in summaries.items() for key, value in summary["metrics"]["class_exact_match"].items()]
    table(out, "t7_fields", fields)

    checks = []
    for name, summary in summaries.items():
        checks.append({"Variant": name, **{k + " offline (%)": v * 100 for k, v in summary["metrics"]["assertion_pass_rates"].items()},
                       **{k + " live (%)": v * 100 for k, v in summary.get("live_assertion_pass_rates", {}).items()}})
        
    all_keys = list(dict.fromkeys(k for row in checks for k in row))
    table(out, "t7_assertions", [{k: row.get(k) for k in all_keys} for row in checks])
    offline = out / "offline"
    offline.mkdir(exist_ok=True)
    for name in ("results.csv", "fields.csv", "comparisons.csv", "rankings.csv"):
        (offline / name).unlink(missing_ok=True)
    write_reports(list(summaries.values()), offline)
    make_plots(out, rows, ablations)
    make_latency_plot(out, rows, sla["SLO_ms"], sla["target_rps"])

    feasible = [r for r in rows if r["SLA"] == "pass"]

    loads = []
    for rate in (1.5, sla["target_rps"], 12.0, 18.0):
        supported = [r for r in rows if performance[r["ID"]]["max_rate"] is not None
                     and performance[r["ID"]]["max_rate"] >= rate]
        if rate <= sla["target_rps"]:
            supported += [r for r in feasible if performance[r["ID"]]["max_rate"] is None]
        best = choose(supported)
        loads.append({"Offered rate (cards/s)": rate, "Cost-first choice": best["ID"] if best else "No supported candidate",
                      "Cost": best["Cost"] if best else None, "Field exact (%)": best["Field exact (%)"] if best else None})

    table(out, "t7_load_choices", loads)
    t6_script = Path("/app/t6_report.py")
    if not t6_script.exists():
        t6_script = HERE.parent / "profile/report.py"
    subprocess.run([sys.executable, str(t6_script), "--runs", str(work / "evidence"), "--out", str(out / "t6")], check=True)

    print("all of T5/T6/T7 plots/tables:", out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, required=True)
    report(parser.parse_args().work)
