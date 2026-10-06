import argparse
import json
import os
import random
import statistics
import subprocess
import sys
import time
import multiprocessing as mp

# Latency baselines use 500 images. Multiprocessing Tesseract and GPU EasyOCR
# run every config on the full dataset. Scores come from Nizar's metrics.py.
# s/img is wall-clock seconds divided by the image count.
# Throughput is images per wall-clock second.

SAMPLE_SIZE = 500
SEED = 0
N_PROC = 40
FIELDS = [
    "name", "gender", "ethnicity", "birth_year",
    "birth_month", "birth_day", "address", "id_number",
]

_current = None
_ds = None


def load_configs():
    raw = open("pipeline_configs.json").read()
    raw = "\n".join(line for line in raw.splitlines() if not line.strip().startswith("//"))
    return json.loads(raw)


def load_indices(full):
    from datasets import load_dataset
    print("loading dataset...", flush=True)
    ds = load_dataset("lansinuote/ocr_id_card", split="train")
    n = len(ds)
    if full:
        indices = list(range(n))
    else:
        indices = random.Random(SEED).sample(range(n), min(SAMPLE_SIZE, n))
    print(f"images: {n}  using: {len(indices)}", flush=True)
    return ds, indices


def _init(cfg):
    global _current
    _current = cfg


def _pack(result):
    return {
        "n_fields": result["n_fields"],
        "n_exact": result["n_exact"],
        "n_located": result["n_located"],
        "n_field_exact": result["n_field_exact"],
        "confidence_sum": result["confidence_sum"],
        "confidence_count": result["confidence_count"],
        "per_class": result["per_class"],
        "per_class_location": result["per_class_location"],
        "per_class_exact": result["per_class_exact"],
    }


def _character_errors(ocr_result, annotations):
    # Edit distance on the text inside each ground-truth box. A field that is one
    # character off still counts here; exact recall does not.
    from Levenshtein import distance
    from metrics import _area, _clean, _intersection, _iou, _normalize
    fields = [field for field in annotations if _clean(field["word"])]
    detections = [item for item in ocr_result["detections"] if str(item["text"]).strip() and _area(item["box"]) > 0]
    groups = [[] for _ in fields]
    for detection in detections:
        candidates = []
        for index, field in enumerate(fields):
            overlap = _intersection(detection["box"], field["box"])
            scale = min(_area(detection["box"]), _area(field["box"]))
            if scale and overlap / scale >= 0.5:
                candidates.append((overlap / scale, _iou(detection["box"], field["box"]), index))
        if candidates:
            groups[max(candidates)[2]].append(detection)
    errors = 0
    total = 0
    for field, group in zip(fields, groups):
        reference = _normalize(field["word"])
        if not reference:
            continue
        ordered = sorted(group, key=lambda item: (item["box"][1], item["box"][0]))
        hypothesis = _normalize("".join(item["text"] for item in ordered))
        errors += distance(hypothesis, reference)
        total += len(reference)
    return errors, total


def _score(i):
    from image import process_image
    from ocr import run_ocr_detailed
    from metrics import detailed_ocr_metrics
    row = _ds[i]
    started = time.perf_counter()
    ocr_result = run_ocr_detailed(process_image(row["image"], _current), _current["ocr"])
    result = detailed_ocr_metrics(ocr_result, row["ocr"])
    char_errors, char_total = _character_errors(ocr_result, row["ocr"])
    packed = _pack(result)
    packed["latency_s"] = time.perf_counter() - started
    packed["image_recall"] = result["recall"]
    packed["char_errors"] = char_errors
    packed["char_total"] = char_total
    return packed


def _accumulate(parts, cfg, elapsed):
    totals = {
        "n_fields": 0, "n_exact": 0, "n_located": 0, "n_field_exact": 0,
        "confidence_sum": 0.0, "confidence_count": 0,
    }
    per_class, per_class_location, per_class_exact = {}, {}, {}
    for result in parts:
        for key in totals:
            totals[key] += result[key]
        for source, target in (
            ("per_class", per_class),
            ("per_class_location", per_class_location),
            ("per_class_exact", per_class_exact),
        ):
            for field, counts in result[source].items():
                accumulated = target.setdefault(field, [0, 0])
                accumulated[0] += counts[0]
                accumulated[1] += counts[1]
    n_fields = totals["n_fields"]
    n_images = len(parts)
    latencies = [part["latency_s"] for part in parts]
    recalls = [part["image_recall"] for part in parts]
    char_errors = sum(part["char_errors"] for part in parts)
    char_total = sum(part["char_total"] for part in parts)
    return {
        "name": cfg["name"],
        "engine": cfg["ocr"],
        "n_images": n_images,
        "n_fields": n_fields,
        "n_exact": totals["n_exact"],
        "n_located": totals["n_located"],
        "n_field_exact": totals["n_field_exact"],
        "text_recall": totals["n_exact"] / n_fields if n_fields else 0.0,
        "location_recall": totals["n_located"] / n_fields if n_fields else 0.0,
        "exact_field_recall": totals["n_field_exact"] / n_fields if n_fields else 0.0,
        "mean_confidence": (totals["confidence_sum"] / totals["confidence_count"]) if totals["confidence_count"] else None,
        "confidence_count": totals["confidence_count"],
        "s_per_img": elapsed / n_images if n_images else 0.0,
        "throughput_img_per_s": n_images / elapsed if elapsed else 0.0,
        "latency_std_s": statistics.pstdev(latencies) if len(latencies) > 1 else 0.0,
        "recall_std": statistics.pstdev(recalls) if len(recalls) > 1 else 0.0,
        "character_error_rate": char_errors / char_total if char_total else 0.0,
        "total_s": elapsed,
        "per_class": per_class,
        "per_class_location": per_class_location,
        "per_class_exact": per_class_exact,
    }


def run_config(cfg, indices, parallel):
    global _current
    _current = cfg
    start = time.perf_counter()
    if parallel:
        ctx = mp.get_context("fork")
        with ctx.Pool(N_PROC, initializer=_init, initargs=(cfg,)) as pool:
            parts = pool.map(_score, indices, chunksize=10)
    else:
        parts = [_score(i) for i in indices]
    elapsed = time.perf_counter() - start
    return _accumulate(parts, cfg, elapsed)


def find_config(configs, name):
    for cfg in configs:
        if cfg["name"] == name:
            return cfg
    raise SystemExit(f"missing config {name}")


def require_cuda():
    import torch
    available = torch.cuda.is_available()
    print(f"torch {torch.__version__} cuda {torch.version.cuda} available {available}", flush=True)
    if not available:
        raise SystemExit("CUDA is not available. Install torch==2.14.0+cu126 for this machine's CUDA 12.6 driver.")
    print("gpu", torch.cuda.get_device_name(0), flush=True)


def warmup_easyocr():
    from ocr import get_easyocr_reader
    start = time.perf_counter()
    get_easyocr_reader()
    print(f"easyocr ready in {time.perf_counter() - start:.1f}s", flush=True)


def _conf(value):
    return f"{value:.3f}" if value is not None else "N/A"


def print_metrics(rows):
    print(
        f'{"config":<32}{"engine":<11}{"text":>8}{"r_std":>8}{"location":>10}{"exact":>8}{"cer":>8}'
        f'{"conf":>8}{"n_conf":>9}{"s/img":>9}{"l_std":>9}{"img/s":>9}{"total_s":>10}',
        flush=True,
    )
    for row in rows:
        print(
            f'{row["name"]:<32}{row["engine"]:<11}{row["text_recall"]:>8.3f}{row["recall_std"]:>8.3f}'
            f'{row["location_recall"]:>10.3f}{row["exact_field_recall"]:>8.3f}{row["character_error_rate"]:>8.3f}'
            f'{_conf(row["mean_confidence"]):>8}{row["confidence_count"]:>9}'
            f'{row["s_per_img"]:>9.3f}{row["latency_std_s"]:>9.3f}{row["throughput_img_per_s"]:>9.2f}{row["total_s"]:>10.1f}',
            flush=True,
        )


def print_fields(rows):
    for row in rows:
        print(row["name"], flush=True)
        for field in FIELDS:
            text_hits, total = row["per_class"].get(field, [0, 0])
            location_hits = row["per_class_location"].get(field, [0, 0])[0]
            exact_hits = row["per_class_exact"].get(field, [0, 0])[0]
            print(f"{field:<13} text {text_hits}/{total}  location {location_hits}/{total}  exact {exact_hits}/{total}", flush=True)


def write_job(name, rows):
    with open(f"results_job_{name}.json", "w") as handle:
        json.dump(rows, handle)
    print_metrics(rows)
    print_fields(rows)
    print(f"wrote results_job_{name}.json", flush=True)


def run_job(job):
    global _ds
    configs = load_configs()
    full = job in {"metrics-tesseract", "easyocr-gpu"}
    _ds, indices = load_indices(full)
    if job == "tesseract-serial":
        rows = [run_config(find_config(configs, "original_tesseract"), indices, parallel=False)]
    elif job == "metrics-tesseract":
        rows = [run_config(cfg, indices, parallel=True) for cfg in configs if cfg["ocr"] == "tesseract"]
    elif job == "easyocr-cpu":
        os.environ["EASYOCR_GPU"] = "0"
        warmup_easyocr()
        rows = [run_config(find_config(configs, "original_easyocr"), indices, parallel=False)]
    elif job == "easyocr-gpu":
        os.environ["EASYOCR_GPU"] = "1"
        require_cuda()
        warmup_easyocr()
        rows = [run_config(cfg, indices, parallel=False) for cfg in configs if cfg["ocr"] == "easyocr"]
    else:
        raise SystemExit(f"unknown job {job}")
    write_job(job, rows)


def _latency_row(mode, row, speedup):
    return {"mode": mode, "speedup": speedup, **row}


def merge():
    serial = json.load(open("results_job_tesseract-serial.json"))
    tesseract = json.load(open("results_job_metrics-tesseract.json"))
    cpu = json.load(open("results_job_easyocr-cpu.json"))
    gpu = json.load(open("results_job_easyocr-gpu.json"))
    original_mp = next(row for row in tesseract if row["name"] == "original_tesseract")
    original_gpu = next(row for row in gpu if row["name"] == "original_easyocr")
    tesseract_speedup = serial[0]["s_per_img"] / original_mp["s_per_img"] if original_mp["s_per_img"] else 0.0
    easyocr_speedup = cpu[0]["s_per_img"] / original_gpu["s_per_img"] if original_gpu["s_per_img"] else 0.0
    latency = [
        _latency_row("tesseract_no_multiprocessing", serial[0], 1.0),
        _latency_row("tesseract_multiprocessing", original_mp, tesseract_speedup),
        _latency_row("easyocr_no_gpu", cpu[0], 1.0),
        _latency_row("easyocr_gpu", original_gpu, easyocr_speedup),
    ]
    metrics = tesseract + gpu
    with open("results_latency.csv", "w") as handle:
        handle.write("mode,engine,n_images,s_per_img,latency_std_s,throughput_img_per_s,speedup,total_s,text_recall,recall_std,location_recall,exact_field_recall,character_error_rate,mean_confidence,confidence_count\n")
        for row in latency:
            confidence = "" if row["mean_confidence"] is None else f'{row["mean_confidence"]:.4f}'
            handle.write(
                f'{row["mode"]},{row["engine"]},{row["n_images"]},{row["s_per_img"]:.4f},{row["latency_std_s"]:.4f},'
                f'{row["throughput_img_per_s"]:.4f},{row["speedup"]:.2f},{row["total_s"]:.1f},{row["text_recall"]:.4f},'
                f'{row["recall_std"]:.4f},{row["location_recall"]:.4f},{row["exact_field_recall"]:.4f},'
                f'{row["character_error_rate"]:.4f},{confidence},{row["confidence_count"]}\n'
            )
    with open("results_metrics.csv", "w") as handle:
        handle.write("config,engine,n_images,text_recall,recall_std,location_recall,exact_field_recall,character_error_rate,mean_confidence,confidence_count,s_per_img,latency_std_s,throughput_img_per_s,total_s\n")
        for row in metrics:
            confidence = "" if row["mean_confidence"] is None else f'{row["mean_confidence"]:.4f}'
            handle.write(
                f'{row["name"]},{row["engine"]},{row["n_images"]},{row["text_recall"]:.4f},{row["recall_std"]:.4f},'
                f'{row["location_recall"]:.4f},{row["exact_field_recall"]:.4f},{row["character_error_rate"]:.4f},{confidence},'
                f'{row["confidence_count"]},{row["s_per_img"]:.4f},{row["latency_std_s"]:.4f},{row["throughput_img_per_s"]:.4f},{row["total_s"]:.1f}\n'
            )
    with open("results_per_class.csv", "w") as handle:
        handle.write("config,engine,field,text_hits,location_hits,exact_hits,total\n")
        for row in metrics:
            for field in FIELDS:
                text_hits, total = row["per_class"].get(field, [0, 0])
                location_hits = row["per_class_location"].get(field, [0, 0])[0]
                exact_hits = row["per_class_exact"].get(field, [0, 0])[0]
                handle.write(f'{row["name"]},{row["engine"]},{field},{text_hits},{location_hits},{exact_hits},{total}\n')
    print("\nlatency comparison (original image; serial and CPU are 500 images, the other two are the full set)", flush=True)
    print(f'{"mode":<32}{"n":>8}{"s/img":>10}{"l_std":>10}{"img/s":>10}{"speedup":>9}{"text":>8}{"r_std":>8}{"cer":>8}', flush=True)
    for row in latency:
        print(
            f'{row["mode"]:<32}{row["n_images"]:>8}{row["s_per_img"]:>10.4f}{row["latency_std_s"]:>10.4f}'
            f'{row["throughput_img_per_s"]:>10.2f}{row["speedup"]:>9.2f}{row["text_recall"]:>8.3f}'
            f'{row["recall_std"]:>8.3f}{row["character_error_rate"]:>8.3f}',
            flush=True,
        )
    print("\nall configs", flush=True)
    print_metrics(metrics)
    print_fields(metrics)
    print("DONE -> results_latency.csv results_metrics.csv results_per_class.csv", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", choices=["tesseract-serial", "metrics-tesseract", "easyocr-cpu", "easyocr-gpu", "merge"])
    args = parser.parse_args()
    if args.job == "merge":
        merge()
        return
    if args.job:
        run_job(args.job)
        return
    for job in ("tesseract-serial", "easyocr-cpu", "metrics-tesseract", "easyocr-gpu"):
        print(f"\n=== {job} ===", flush=True)
        subprocess.check_call([sys.executable, os.path.abspath(__file__), "--job", job])
    merge()


if __name__ == "__main__":
    main()
