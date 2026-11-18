# OCR swap point — Nizar's ICP image/ocr + content-based fields / A1–A4.

import os
import re
import sys
import time
from pathlib import Path

import numpy as np

_REPO = Path(os.environ.get(
    "ICP_PATH",
    str(Path(__file__).resolve().parent.parent),  # parent of service/ (= ICP folder)
))
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from assertions import check_assertions
from image import process_image
from metrics import normalize
from ocr import run_ocr_detailed

_FIELDS = (
    "name", "gender", "ethnicity", "birth_year",
    "birth_month", "birth_day", "address", "id_number",
)


def find_fields(detections):
    ordered = sorted(detections, key=lambda d: (d["box"][1], d["box"][0]))
    texts = [normalize(d["text"]) for d in ordered]
    fields = {name: "" for name in _FIELDS}

    def digitx_count(s):
        return sum(ch.isdigit() or ch == "X" for ch in s)

    id_idx = None
    best = 14
    for i, s in enumerate(texts):
        n = digitx_count(s)
        if n >= 15 and n > best:
            best, id_idx = n, i
    if id_idx is not None:
        fields["id_number"] = texts[id_idx]

    for s in texts:
        if "男" in s or "女" in s:
            fields["gender"] = s[2:] if s.startswith("性别") else s
            break

    rest = [s for i, s in enumerate(texts) if i != id_idx]
    joined = "".join(rest)
    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})", joined)
    if m:
        fields["birth_year"], fields["birth_month"], fields["birth_day"] = m.group(1), m.group(2), m.group(3)
    else:
        year_i = next((i for i, s in enumerate(rest) if re.match(r"^(19|20)\d{2}$", s)), None)
        if year_i is not None:
            fields["birth_year"] = rest[year_i]
            nums = [s for s in rest[year_i + 1:] if re.match(r"^\d{1,2}$", s)]
            if len(nums) >= 1:
                fields["birth_month"] = nums[0]
            if len(nums) >= 2:
                fields["birth_day"] = nums[1]
    return fields


def extract(image_rgb: np.ndarray, settings: dict, model_dir: str) -> dict:
    t0 = time.perf_counter()
    processed = process_image(image_rgb, settings)
    preprocess_ms = (time.perf_counter() - t0) * 1000.0

    t1 = time.perf_counter()
    ocr_result = run_ocr_detailed(processed, settings=settings, model_dir=model_dir, device="cpu")
    ocr_ms = (time.perf_counter() - t1) * 1000.0

    fields = find_fields(ocr_result["detections"])
    raw = check_assertions(fields)
    assertions = {
        "a1": bool(raw["A1"]), "a2": bool(raw["A2"]), "a3": bool(raw["A3"]),
        "a4": bool(raw["A4"]), "all": bool(raw["all"]),
    }
    return {
        "fields": fields,
        "assertions": assertions,
        "preprocess_ms": preprocess_ms,
        "ocr_ms": ocr_ms,
        "text": ocr_result["text"],
        "detections": ocr_result["detections"],
    }


def extract_batch(images: list, settings: dict, model_dir: str) -> list:
    # Tesseract/EasyOCR: plain loop (no readtext_batched).
    return [extract(image, settings, model_dir) for image in images]
