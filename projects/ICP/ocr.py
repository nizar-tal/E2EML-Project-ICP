# Ishan Pathak

# 10/4/2026
# run OCR on a processed image (step 3 of the pipeline)

import os

import cv2
import numpy as np
import easyocr
import pytesseract


EASYOCR_LANGS = ["ch_sim", "en"]
TESSERACT_LANG = "chi_sim+eng"

# EasyOCR's Reader is slow to build, so make it once and reuse it.
_easyocr_reader = None


def get_easyocr_reader():
    # built on the first call, then reused for the whole run
    global _easyocr_reader
    if _easyocr_reader is None:
        gpu = os.environ.get("EASYOCR_GPU", "0").strip().lower() in {"1", "true", "yes"}
        _easyocr_reader = easyocr.Reader(EASYOCR_LANGS, gpu=gpu)
    return _easyocr_reader


def run_ocr(image, engine):
    """Read the text on one processed image with the engine named in the config."""
    if not isinstance(image, np.ndarray) or image.dtype != np.uint8:
        raise ValueError("image must be a uint8 NumPy array")
    if image.ndim not in (2, 3) or (image.ndim == 3 and image.shape[2] != 3):
        raise ValueError("image must have shape (H, W) or (H, W, 3)")

    if engine == "easyocr":
        # process_image returns RGB; EasyOCR reads a 3-channel array as BGR
        if image.ndim == 3:
            image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        return "\n".join(get_easyocr_reader().readtext(image, detail=0))

    if engine == "tesseract":
        pytesseract.pytesseract.tesseract_cmd = os.environ.get("TESSERACT_CMD") or "tesseract"
        return pytesseract.image_to_string(image, lang=TESSERACT_LANG)

    raise ValueError(f"unknown ocr engine: {engine!r}")
