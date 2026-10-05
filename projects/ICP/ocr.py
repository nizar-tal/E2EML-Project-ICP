# Ishan Pathak
# Nizar Talty

# 10/4/2026
# run OCR on a processed image (step 3 of the pipeline)

import os

import cv2
import numpy as np
import easyocr
import pytesseract


EASYOCR_LANGS = ["ch_sim", "en"]
TESSERACT_LANG = "chi_sim+eng"

# EasyOCR's Reader is slow to build, so make it once and reuse it
# not sure if we should include it in the pipeline timing but for now excluded
_easyocr_reader = None


def get_easyocr_reader():
    # built on the first call, then reused for the whole run
    global _easyocr_reader
    if _easyocr_reader is None:
        gpu = os.environ.get("EASYOCR_GPU", "0").strip().lower() in {"1", "true", "yes"}
        _easyocr_reader = easyocr.Reader(EASYOCR_LANGS, gpu=gpu)
    return _easyocr_reader


def run_ocr(image, engine):
    return run_ocr_detailed(image, engine)["text"]


def run_ocr_detailed(image, engine):
    if not isinstance(image, np.ndarray) or image.dtype != np.uint8:
        raise ValueError("image must be a uint8 NumPy array")
    if image.ndim not in (2, 3) or (image.ndim == 3 and image.shape[2] != 3):
        raise ValueError("image must have shape (H, W) or (H, W, 3)")

    if engine == "easyocr":
        if image.ndim == 3:
            image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        # get the deetails using detail=1 (prev detail=0)
        results = get_easyocr_reader().readtext(image, detail=1, paragraph=False)
        detections = []
        # fetch the detections
        for corners, text, confidence in results:
            xs = [point[0] for point in corners]
            ys = [point[1] for point in corners]
            detections.append({"text": text, "box": [min(xs), min(ys), max(xs), max(ys)], "confidence": float(confidence)})
        return {"text": "\n".join(item["text"] for item in detections), "detections": detections}

    if engine == "tesseract":
        pytesseract.pytesseract.tesseract_cmd = os.environ.get("TESSERACT_CMD") or "tesseract"
        data = pytesseract.image_to_data(image, lang=TESSERACT_LANG, output_type=pytesseract.Output.DICT)
        detections = []
        for i, text in enumerate(data["text"]):
            if not text.strip():
                continue
            left, top, width, height = (data[key][i] for key in ("left", "top", "width", "height"))
            confidence = float(data["conf"][i])
            detections.append({"text": text, "box": [left, top, left + width, top + height], "confidence": confidence / 100 if confidence >= 0 else None})
        return {"text": "\n".join(item["text"] for item in detections), "detections": detections}

    else: print(f"unknown ocr engine: {engine!r}")
