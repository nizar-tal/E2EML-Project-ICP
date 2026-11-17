#!/usr/bin/env python3
"""Regenerate T5/T6/T7 tables, plots, and the T7 report from saved results."""
import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path

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
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(9, 5))
    for status, color, marker in (("pass", "#287d46", "o"), ("fail", "#b63434", "X")):
        points = [r for r in rows if r["SLA"] == status]
        ax.scatter([r["Cost"] for r in points], [r["Field exact (%)"] for r in points],
                   color=color, marker=marker, s=85, label=f"SLA {status}", zorder=3)
    for front, color, style, label in (
        (pareto(rows), "#888888", "--", "Pareto front (all candidates)"),
        (pareto([r for r in rows if r["SLA"] == "pass"]), "#287d46", "-", "Pareto front (SLA passing)"),
    ):
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
    configs_md = table(out, "t7_summary", [{key: row[key] for key in summary_columns} for row in rows])
    ablations = []
    for pair in config["ablations"]:
        original, blue = summaries[pair["original"]]["metrics"], summaries[pair["blue"]]["metrics"]
        ablations.append({"OCR": pair["engine"], "Original field exact (%)": original["field_exact_match"] * 100,
                          "Blue field exact (%)": blue["field_exact_match"] * 100,
                          "Blue minus original (percentage points)": (blue["field_exact_match"] - original["field_exact_match"]) * 100,
                          "Original mean CER": original["mean_field_cer"], "Blue mean CER": blue["mean_field_cer"]})
    ablation_md = table(out, "t7_ablation", ablations)
    fields = [{"Variant": name, "Field": key, "Exact match (%)": value * 100}
              for name, summary in summaries.items() for key, value in summary["metrics"]["class_exact_match"].items()]
    table(out, "t7_fields", fields)
    checks = []
    for name, summary in summaries.items():
        checks.append({"Variant": name, **{k + " offline (%)": v * 100 for k, v in summary["metrics"]["assertion_pass_rates"].items()},
                       **{k + " live (%)": v * 100 for k, v in summary.get("live_assertion_pass_rates", {}).items()}})
    # Reused offline results may not contain live counters; represent these as unmeasured.
    all_keys = list(dict.fromkeys(k for row in checks for k in row))
    table(out, "t7_assertions", [{k: row.get(k) for k in all_keys} for row in checks])
    offline = out / "offline"
    offline.mkdir(exist_ok=True)
    for name in ("results.csv", "fields.csv", "comparisons.csv", "rankings.csv"):
        (offline / name).unlink(missing_ok=True)
    write_reports(list(summaries.values()), offline)
    make_plots(out, rows, ablations)

    feasible = [r for r in rows if r["SLA"] == "pass"]
    recommended = choose(feasible)
    accurate = max(feasible, key=lambda r: (r["Field exact (%)"], -r["Cost"])) if feasible else None
    # Existing T6 maxima also support a comparison at other loads without another sweep.
    loads = []
    for rate in (1.5, sla["target_rps"], 12.0, 18.0):
        supported = [r for r in rows if performance[r["ID"]]["max_rate"] is not None
                     and performance[r["ID"]]["max_rate"] >= rate]
        if rate <= sla["target_rps"]:
            supported += [r for r in feasible if performance[r["ID"]]["max_rate"] is None]
        best = choose(supported)
        loads.append({"Offered rate (cards/s)": rate, "Cost-first choice": best["ID"] if best else "No supported candidate",
                      "Cost": best["Cost"] if best else None, "Field exact (%)": best["Field exact (%)"] if best else None})
    loads_md = table(out, "t7_load_choices", loads)
    originals = [(p["engine"], summaries[p["original"]]["metrics"]["field_exact_match"]) for p in config["ablations"]]
    blues = [(p["engine"], summaries[p["blue"]]["metrics"]["field_exact_match"]) for p in config["ablations"]]
    original_best = [r for r in originals if r[1] == max(value for _, value in originals)]
    blue_best = [r for r in blues if r[1] == max(value for _, value in blues)]
    original_winners = ", ".join(f"{name} ({value * 100:.2f}%)" for name, value in original_best)
    blue_winners = ", ".join(f"{name} ({value * 100:.2f}%)" for name, value in blue_best)
    changed = {r[0] for r in original_best} != {r[0] for r in blue_best}
    conclusion = "No tested deployment meets the calibrated SLA."
    if recommended:
        conclusion = (f"Using a cost-first policy, deploy **{recommended['ID']}**: cost **{recommended['Cost']} CPU cores**, "
                      f"field exact match **{recommended['Field exact (%)']:.2f}%**. "
                      "Choose the cheapest qualifying allocation, then the most accurate recipe at that cost. "
                      f"If accuracy takes priority, **{accurate['ID']}** provides **{accurate['Field exact (%)']:.2f}%** "
                      f"at cost **{accurate['Cost']} cores**.")
    text = f"""# T7: End-to-end configurations

We compare four main image-to-OCR recipes and six deployments. All use batch 1 and one CPU core per replica.
The additional original-image historical EasyOCR run is an accuracy-only ablation control.
The reference baseline is `tesseract_default` (`chi_sim`, no enhancement, original image), not `original_tesseract`.
Historical EasyOCR preserves its original quantization and reader settings; it is distinct from T6's `easyocr_original`.

## Evaluation

Offline accuracy uses all eight fields on the fixed 2,000-card test slice. Dataset revision: `{frozen['dataset_revision']}`;
split seed: {frozen['seed']}. The new blue-channel PSM 6 recipe was checked on the 500-card development slice
before test evaluation. Recipes were fixed before final scoring; no test-set tuning was performed by these scripts.
The service receives only images. Its OCR detections are assigned to annotated boxes by the evaluator after the response.
The live five-field assertion layer and the eight-field offline evaluation are reported separately.

The SLA is p95 <= **{sla['SLO_ms']:.3f} ms** with target traffic **{sla['target_rps']:g} cards/s**.
Matching T6 measurements are reused. Their latency is reported at their actual measured offered rate, not at the target rate.
Only previously unprofiled recipes receive a new target-rate check on the separate load pool (seed 8001, start 0,
15-second warmup and 90-second measurement). SLO attainment includes failed requests in its denominator.
T7 throughput counts completions inside that measurement window; T6 throughput retains the original T6 definition.
Core-seconds are the OCR allocation integrated over the recorded run window.
A blank maximum-throughput or attainment value means that quantity was not measured in the reused source.

## End-to-end configurations

{configs_md}

The [full configuration table](t7_configurations.md) also records batch size, replicas, CPU per replica,
card accuracy, CER, assertions, p50/p99, throughput, SLO attainment, core-seconds and the source run.

![Cost and accuracy](t7_pareto.png)

The dashed front includes all candidates; the green front considers only SLA-passing candidates.
One candidate dominates another when it costs no more and is at least as accurate, with one strict improvement.

## Preprocessing ablation

For ICP, the prescribed stage-contribution experiment compares preprocessing enabled versus disabled with the same OCR settings.
No gold text is substituted for the card image. The two pairs hold model weights, language, resolution,
quantization and recognition settings fixed; only channel selection changes.

{ablation_md}

![Preprocessing contribution](t7_ablation.png)

On original images the highest field accuracy is **{original_winners}**.
On blue-channel images it is **{blue_winners}**.
The best downstream OCR choice **{'changes' if changed else 'does not change'}** between these preprocessing choices
in this selected comparison. If multiple models tie, all are listed.

## Choosing a deployment

**{len(feasible)} of {len(rows)} deployments meet the target SLA.** {conclusion}

Optimality depends on the objective and incoming rate. The following choices use the same cost-first policy,
among this report's selected candidates and only at rates supported by their measured results.
For new recipes a passing target-rate check establishes support up to the target; it does not establish a higher maximum.

{loads_md}

## Reproduction and supporting tables

Run `bash service/run_milestone2.sh --report-only` from the ICP directory to regenerate this report,
the ablation and Pareto plots, the eight-field and assertion tables, the rankings/correlations in `offline/`,
and the existing T5/T6 tables and plots in `t6/`. Raw predictions and performance evidence remain outside this report folder.
"""
    (out / "T7_REPORT.md").write_text(text)
    t6_script = Path("/app/t6_report.py")
    if not t6_script.exists():
        t6_script = HERE.parent / "profile/report.py"
    subprocess.run([sys.executable, str(t6_script), "--runs", str(work / "evidence"), "--out", str(out / "t6")], check=True)
    print("Report and all T5/T6/T7 plots/tables:", out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, required=True)
    report(parser.parse_args().work)
