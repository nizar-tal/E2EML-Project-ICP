import argparse
import csv
import importlib.metadata
import json
import platform
import re
import sys
from pathlib import Path

import numpy as np
from tqdm.auto import tqdm

from assertions import check_assertions
from image import process_image
from metrics import CLASS_NAMES, assign_fields, detailed_ocr_metrics, required_metrics
from model_artifacts import artifact_sources
from ocr import historical_variant, run_ocr_detailed
from prepare_splits import load_record


def write_json(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)


def write_csv(path, rows, columns):
    with Path(path).open("x", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows({key: round(value, 6) if isinstance(value, float) else value for key, value in row.items()}
                         for row in rows)


def artifact_inventory(settings, model_dir):
    result = []
    for filename in sorted(set(settings["artifacts"])):
        path = Path(model_dir) / filename
        if not path.is_file():
            raise FileNotFoundError(f"Missing model artifact: {path}")
        result.append({"file": filename, "bytes": path.stat().st_size})
    return result


def runtime_info(device="cpu"):
    packages = ["numpy", "Pillow", "opencv-python-headless", "easyocr", "pytesseract", "torch", "torchvision",
                "datasets", "huggingface-hub", "pandas", "pyarrow"]
    import pytesseract

    hardware = {"processor": platform.processor(), "device": device}
    if device != "cpu":
        import torch

        hardware.update(gpu=torch.cuda.get_device_name(device), cuda_runtime=torch.version.cuda)
    return {"python": sys.version, "platform": platform.platform(), "machine": platform.machine(), "hardware": hardware,
            "packages": {name: importlib.metadata.version(name) for name in packages},
            "tesseract": str(pytesseract.get_tesseract_version())}


def select_settings(args):
    variants = json.loads(Path(args.variants).read_text())
    historical = [historical_variant(config) for config in json.loads(Path(args.historical).read_text())]
    choices = {"variants": variants, "original": historical, "historical": historical, "all": historical + variants,
               "baseline": [variant for variant in variants if variant["name"] == "tesseract_default"]}
    selected = choices[args.group]
    if args.names:
        names = args.names.split(",")
        available = {variant["name"]: variant for variant in selected}
        if len(set(names)) != len(names) or set(names) - available.keys():
            raise ValueError("Unknown or duplicate --names for the selected group")
        selected = [available[name] for name in names]
    if not selected or len({item["name"] for item in selected}) != len(selected):
        raise ValueError("Empty selection or duplicate configuration names")
    if any(not re.fullmatch(r"[a-zA-Z0-9_.-]+", item["name"]) for item in selected):
        raise ValueError("Configuration identifiers may contain only letters, numbers, underscores, dots, and hyphens")
    if args.device != "cpu" and not re.fullmatch(r"cuda:[0-9]+", args.device):
        raise ValueError("Device must be cpu or cuda:N")
    if args.device != "cpu" and any(s["engine"] == "tesseract" or s["quantize"] for s in selected):
        raise ValueError("Tesseract and quantized historical EasyOCR require --device cpu")
    return selected


def new_totals():
    return {"cards": 0, "card_correct": 0, "correct_fields": 0, "nonempty_fields": 0, "cer_sum": 0.0,
            "empty_reference_fields": 0, "empty_reference_correct": 0,
            "per_class": {name: [0, 0] for name in CLASS_NAMES.values()},
            "assertions": {key: 0 for key in ("A1", "A2", "A3", "A4", "all")},
            "historical": {key: 0 for key in ("n_fields", "n_exact", "n_located", "n_field_exact",
                                             "confidence_sum", "confidence_count")},
            "historical_per_class": {key: {} for key in ("per_class", "per_class_location", "per_class_exact")}}


def add_card(totals, required, historical, checks):
    totals["cards"] += 1
    for key in ("card_correct", "correct_fields", "nonempty_fields", "cer_sum", "empty_reference_fields",
                "empty_reference_correct"):
        totals[key] += required[key]
    for name, counts in required["per_class"].items():
        totals["per_class"][name] = [a + b for a, b in zip(totals["per_class"][name], counts)]
    for key, passed in checks.items():
        totals["assertions"][key] += int(passed)
    for key in totals["historical"]:
        totals["historical"][key] += historical[key]
    for key, classes in totals["historical_per_class"].items():
        for name, counts in historical[key].items():
            classes[name] = [a + b for a, b in zip(classes.get(name, [0, 0]), counts)]


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def summarize(totals):
    fields, cards = totals["nonempty_fields"], totals["cards"]
    historical = totals["historical"]
    return {**totals, "field_exact_match": ratio(totals["correct_fields"], fields),
            "card_exact_match": ratio(totals["card_correct"], cards), "mean_field_cer": ratio(totals["cer_sum"], fields),
            "class_exact_match": {name: ratio(hit, count) for name, (hit, count) in totals["per_class"].items()},
            "assertion_pass_rates": {key: ratio(count, cards) for key, count in totals["assertions"].items()},
            "historical_rates": {"text_recall": ratio(historical["n_exact"], historical["n_fields"]),
                                 "location_recall": ratio(historical["n_located"], historical["n_fields"]),
                                 "exact_field_recall": ratio(historical["n_field_exact"], historical["n_fields"]),
                                 "mean_confidence": ratio(historical["confidence_sum"], historical["confidence_count"])}}


def ranks(values):
    return [1 + sum(other > value for other in values) + (sum(other == value for other in values) - 1) / 2
            for value in values]


def correlation(first, second):
    if len(first) < 2 or any(value is None for value in first + second):
        return {"value": None, "reason": "Fewer than two configurations or missing accuracy denominator"}
    if len(set(first)) == 1 or len(set(second)) == 1:
        return {"value": None, "reason": "Constant-valued series"}
    return {"value": float(np.corrcoef(first, second)[0, 1]), "reason": None}


def comparisons(results):
    output = {}
    for scope, rows in (("all", results), ("original", [r for r in results if r["settings"].get("group") == "original"])):
        if not rows:
            continue
        output[scope] = {}
        for assertion in ("A1", "A2", "A3", "A4", "all"):
            passed = [row["metrics"]["assertion_pass_rates"][assertion] for row in rows]
            for metric in ("field_exact_match", "card_exact_match"):
                accuracy = [row["metrics"][metric] for row in rows]
                pearson = correlation(passed, accuracy)
                valid = len(rows) >= 2 and None not in passed + accuracy
                ar, pr = (ranks(accuracy), ranks(passed)) if valid else ([], [])
                output[scope][assertion + "_vs_" + metric] = {
                    "pearson": pearson, "spearman": correlation(pr, ar),
                    "identical_ranking": pr == ar if valid else None}
    return output


def evaluate_variant(dataset, indices, settings, args, provenance):
    totals = new_totals()
    path = Path(args.output) / (settings["name"] + ".predictions.csv")
    names = list(CLASS_NAMES.values())
    columns = ["index"] + [prefix + name for prefix in ("predicted_", "reference_") for name in names]
    columns += ["A1", "A2", "A3", "A4", "all", "correct_fields", "nonempty_fields", "card_correct", "cer_sum"]
    with path.open("x", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for index in tqdm(indices, desc=settings["name"], unit="card", dynamic_ncols=True):
            row = dataset[index]
            annotations = row["ocr"]
            if isinstance(annotations, str):
                annotations = json.loads(annotations)
            image = process_image(row["image"], settings)
            result = run_ocr_detailed(image, device=args.device, model_dir=args.model_dir, settings=settings)
            predictions = assign_fields(result["detections"], annotations)
            required = required_metrics(predictions, annotations)
            fields = {CLASS_NAMES[int(field["cls"])]: text for field, text in zip(annotations, predictions)}
            checks = check_assertions(fields)
            historical = detailed_ocr_metrics(result, annotations)
            add_card(totals, required, historical, checks)
            card = {"index": index, **{"predicted_" + name: text for name, text in fields.items()}, **checks}
            card.update({"reference_" + CLASS_NAMES[int(field["cls"])]: field["word"] for field in annotations})
            card.update({key: required[key] for key in ("correct_fields", "nonempty_fields", "card_correct", "cer_sum")})
            card["cer_sum"] = round(card["cer_sum"], 6)
            writer.writerow(card)
    summary = {"name": settings["name"], "settings": settings, "provenance": provenance, "metrics": summarize(totals)}
    write_json(Path(args.output) / "metadata" / (settings["name"] + ".summary.json"), summary)
    print(f"{settings['name']}: saved {totals['cards']} cards")
    return summary


def ranking_table(results):
    table = []
    for scope, rows in (("all", results), ("original", [r for r in results if r["settings"].get("group") == "original"])):
        scores = {key: [row["metrics"][key] for row in rows] for key in ("field_exact_match", "card_exact_match")}
        scores.update({key: [row["metrics"]["assertion_pass_rates"][key] for row in rows]
                       for key in ("A1", "A2", "A3", "A4", "all")})
        ranked = {key + "_rank": ranks(values) if None not in values else [None] * len(values)
                  for key, values in scores.items()}
        table.extend({"group": scope, "configuration": row["name"], **{key: values[i] for key, values in ranked.items()}}
                     for i, row in enumerate(rows))
    return table


def write_reports(results, output):
    rows, classes = [], []
    for result in results:
        metrics = result["metrics"]
        row = {"configuration": result["name"], "engine": result["settings"]["engine"]}
        keys = ("cards", "card_correct", "correct_fields", "nonempty_fields", "empty_reference_fields",
                "field_exact_match", "card_exact_match", "mean_field_cer")
        row.update({key: metrics[key] for key in keys})
        row.update({key + "_pass_rate": value for key, value in metrics["assertion_pass_rates"].items()})
        row.update({"m1_" + key: value for key, value in metrics["historical_rates"].items()})
        rows.append(row)
        for name, (correct, total) in metrics["per_class"].items():
            classes.append({"configuration": result["name"], "field": name, "correct": correct,
                            "total": total, "exact_match": ratio(correct, total)})
    write_csv(output / "results.csv", rows, list(rows[0]))
    write_csv(output / "fields.csv", classes, ["configuration", "field", "correct", "total", "exact_match"])
    correlations = []
    for scope, comparisons_by_name in comparisons(results).items():
        for name, comparison in comparisons_by_name.items():
            assertion, accuracy = name.split("_vs_")
            correlations.append({"group": scope, "assertion": assertion, "accuracy": accuracy,
                                 "pearson": comparison["pearson"]["value"], "spearman": comparison["spearman"]["value"],
                                 "reason": comparison["pearson"]["reason"],
                                 "same_ranking": comparison["identical_ranking"]})
    write_csv(output / "comparisons.csv", correlations,
              ["group", "assertion", "accuracy", "pearson", "spearman", "reason", "same_ranking"])
    write_csv(output / "rankings.csv", ranking_table(results),
              ["group", "configuration", "field_exact_match_rank", "card_exact_match_rank",
               "A1_rank", "A2_rank", "A3_rank", "A4_rank", "all_rank"])


def current_settings(settings):
    if settings["name"].startswith("historical_"):
        return {**settings, "name": settings["name"].removeprefix("historical_"), "group": "original"}
    return settings


def read_development_summary(directory, name):
    path = directory / "metadata" / (name + ".summary.json")
    if not path.exists():
        path = directory / "metadata" / ("historical_" + name + ".summary.json")
    summary = json.loads(path.read_text())
    summary["settings"] = current_settings(summary["settings"])
    return summary


def freeze_settings(args, selected, provenance):
    directory = Path(args.freeze_from)
    run = json.loads((directory / "metadata" / "run.json").read_text())
    run["settings"] = [current_settings(settings) for settings in run["settings"]]
    run["provenance"] = {name.removeprefix("historical_"): value for name, value in run["provenance"].items()}
    if run["slice"] != "development" or run["limit"] is not None:
        raise ValueError("Freeze requires a complete 500-card development comparison, not a smoke run")
    for settings in selected:
        summary = read_development_summary(directory, settings["name"])
        if summary["settings"] != settings or summary["metrics"]["cards"] != 500:
            raise ValueError("Development result does not match these settings or is incomplete")
        if summary["provenance"] != provenance[settings["name"]]:
            raise ValueError("Development artifacts, device, runtime, or dataset differ from current setup")
    write_json(args.freeze, {"settings": selected, "provenance": provenance, "development_run": run,
                             "development_results": str(directory.resolve())})
    print(f"Frozen settings saved to {args.freeze}")


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--splits", default="splits.json")
    parser.add_argument("--slice", choices=["development", "test"], default="development")
    parser.add_argument("--group", choices=["all", "original", "historical", "variants", "baseline"], default="variants")
    parser.add_argument("--names", help="Comma-separated stable identifiers")
    parser.add_argument("--variants", default="ocr_variants.json")
    parser.add_argument("--historical", default="pipeline_configs.json")
    parser.add_argument("--device", required=True, help="cpu or cuda:N; Tesseract and quantized historical EasyOCR require cpu")
    parser.add_argument("--model-dir", default="models")
    parser.add_argument("--output", default="results/development")
    parser.add_argument("--limit", type=int, help="Development smoke runs only")
    parser.add_argument("--freeze", help="Frozen settings JSON: write with --freeze-from; required for test")
    parser.add_argument("--freeze-from", help="Complete development output directory")
    return parser.parse_args()


def main():
    args = parse_args()
    record = load_record(args.splits)
    selected = select_settings(args)
    runtime = runtime_info(args.device)
    provenance = {}
    for settings in selected:
        artifacts = artifact_inventory(settings, args.model_dir)
        provenance[settings["name"]] = {"artifacts": artifacts, "device": args.device, "runtime": runtime,
                                       "artifact_sources": artifact_sources(settings, args.model_dir, artifacts),
                                       "dataset_revision": record["revision"], "dataset_split": record["split"],
                                       "split_seed": record["seed"]}
    if args.freeze_from:
        if not args.freeze:
            raise ValueError("--freeze output is required")
        freeze_settings(args, selected, provenance)
        return
    if args.slice == "test":
        if args.limit is not None or not args.freeze:
            raise ValueError("Test requires frozen settings and disallows --limit")
        frozen = json.loads(Path(args.freeze).read_text())
        if frozen["settings"] != selected or frozen["provenance"] != provenance:
            raise ValueError("Settings or provenance changed since freezing; repeat development and freeze")
    if args.limit is not None and not 1 <= args.limit <= 500:
        raise ValueError("Development --limit must be between 1 and 500")
    from datasets import load_dataset

    dataset = load_dataset(record["dataset"], split=record["split"], revision=record["revision"])
    if len(dataset) != record["count"]:
        raise ValueError("Recorded dataset count changed")
    indices = record["indices"][args.slice]
    indices = indices[:args.limit] if args.limit is not None else indices
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    (output / "metadata").mkdir()
    run = {"slice": args.slice, "limit": args.limit, "cards": len(indices), "settings": selected,
           "provenance": provenance, "split_record": str(Path(args.splits).resolve())}
    write_json(output / "metadata" / "run.json", run)
    results = [evaluate_variant(dataset, indices, settings, args, provenance[settings["name"]]) for settings in selected]
    write_reports(results, output)
    print(f"Completed {len(results)} configurations on {len(indices)} {args.slice} cards; outputs: {output}")


if __name__ == "__main__":
    main()
