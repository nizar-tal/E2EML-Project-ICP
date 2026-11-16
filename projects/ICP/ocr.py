import os
from pathlib import Path

import cv2
import numpy as np

_READERS = {}
EASYOCR_LANGS = ["ch_sim", "en"]
TESSERACT_LANG = "chi_sim+eng"


def historical_variant(config):
    engine = config["ocr"]
    settings = {"name": config["name"], "group": "original", "version": "1", "engine": engine,
                "scale": 1.0, "enhancement": config["enhancement"], "channels": config["channels"],
                "source": "Milestone 1 settings; current pinned runtime"}
    if engine == "tesseract":
        settings.update(language=TESSERACT_LANG, config="", quantize=False,
                        artifacts=["chi_sim.traineddata", "eng.traineddata"])
    else:
        settings.update(languages=EASYOCR_LANGS, detect_network="craft", recog_network="standard", quantize=True,
                        readtext={}, artifacts=["craft_mlt_25k.pth", "zh_sim_g2.pth"])
    return settings


def get_easyocr_reader(device="cpu", model_dir="models", settings=None, download=False):
    import easyocr
    import torch

    settings = settings or {"languages": EASYOCR_LANGS, "quantize": True}
    if device != "cpu" and not device.startswith("cuda:"):
        raise ValueError("Device must be cpu or cuda:N")
    if device != "cpu":
        if settings["quantize"]:
            raise ValueError("CPU dynamic quantization requires cpu; use a separate unquantized GPU variant")
        if not torch.cuda.is_available() or int(device.split(":")[1]) >= torch.cuda.device_count():
            raise RuntimeError(f"Requested GPU {device} is unavailable")
    key = (device, str(Path(model_dir).resolve()), tuple(settings["languages"]), settings["quantize"],
           settings.get("detect_network", "craft"), settings.get("recog_network", "standard"), download)
    if key not in _READERS:
        _READERS[key] = easyocr.Reader(settings["languages"], gpu=False if device == "cpu" else device,
                                      model_storage_directory=str(model_dir), download_enabled=download,
                                      quantize=settings["quantize"], detect_network=settings.get("detect_network", "craft"),
                                      recog_network=settings.get("recog_network", "standard"), verbose=False)
    return _READERS[key]


def map_detections(detections, original_size, resized_size):
    sx, sy = original_size[0] / resized_size[0], original_size[1] / resized_size[1]
    return [{**item, "box": [float(v) * (sx if i % 2 == 0 else sy) for i, v in enumerate(item["box"])]}
            for item in detections]


def tesseract_detections(image, settings, model_dir):
    import pytesseract

    pytesseract.pytesseract.tesseract_cmd = os.environ.get("TESSERACT_CMD") or "tesseract"
    directory = str(Path(model_dir).resolve())
    if '"' in directory:
        raise ValueError("Model directory cannot contain a double quote")
    config = f'--tessdata-dir "{directory}" ' + settings["config"]
    data = pytesseract.image_to_data(image, lang=settings["language"], config=config, output_type=pytesseract.Output.DICT)
    detections = []
    for i, text in enumerate(data["text"]):
        if not text.strip():
            continue
        left, top, width, height = (int(data[key][i]) for key in ("left", "top", "width", "height"))
        confidence = float(data["conf"][i])
        detections.append({"text": text, "box": [left, top, left + width, top + height],
                           "confidence": confidence / 100 if confidence >= 0 else None})
    return detections


def run_ocr_detailed(image, engine=None, device="cpu", model_dir="models", settings=None):
    if not isinstance(image, np.ndarray) or image.dtype != np.uint8:
        raise ValueError("image must be a uint8 NumPy array")
    if image.ndim not in (2, 3) or (image.ndim == 3 and image.shape[2] != 3):
        raise ValueError("image must have shape (H,W) or (H,W,3)")
    if settings is None:
        settings = historical_variant({"name": "ad_hoc", "ocr": engine, "enhancement": [], "channels": "original"})
    engine = settings["engine"]
    if device != "cpu" and engine == "tesseract":
        raise ValueError("Tesseract supports cpu only; select cpu explicitly")
    for filename in settings["artifacts"]:
        if not (Path(model_dir) / filename).is_file():
            raise FileNotFoundError(f"Missing model artifact: {Path(model_dir) / filename}; provision or download it first")
    height, width = image.shape[:2]
    scale = settings["scale"]
    if not 0 < scale <= 1:
        raise ValueError("Input scale must be in (0,1]")
    resized = (max(1, round(width * scale)), max(1, round(height * scale)))
    if resized != (width, height):
        image = cv2.resize(image, resized, interpolation=cv2.INTER_AREA)
    if engine == "easyocr":
        reader = get_easyocr_reader(device, model_dir, settings)
        image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR) if image.ndim == 3 else image
        results = reader.readtext(image, detail=1, paragraph=False, **settings["readtext"])
        detections = []
        for corners, text, confidence in results:
            xs, ys = zip(*corners)
            detections.append({"text": text, "box": [min(xs), min(ys), max(xs), max(ys)], "confidence": float(confidence)})
    elif engine == "tesseract":
        detections = tesseract_detections(image, settings, model_dir)
    else:
        raise ValueError(f"Unknown OCR engine: {engine}")
    detections = map_detections(detections, (width, height), resized)
    return {"text": "\n".join(item["text"] for item in detections), "detections": detections}


def run_ocr(image, engine, device="cpu", model_dir="models"):
    return run_ocr_detailed(image, engine, device, model_dir)["text"]
