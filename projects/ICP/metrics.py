import math
import unicodedata

from PIL import Image, ImageDraw


# Ishan Pathak
# Nizar Talty

# 10/4/2026
# score OCR text against the ID-card ground-truth fields

CLASS_NAMES = {
    # map cls to the class name
    0: "name", 1: "gender", 2: "ethnicity", 3: "birth_year",
    4: "birth_month", 5: "birth_day", 6: "address", 7: "id_number",
}


def _clean(text):
    # drop all whitespace so spacing differences don't matter
    return "".join(str(text).split())


def score_ocr(ocr_text, annotations):
    """Count how many ground-truth fields appear in the OCR text.

    A field is correct when its value (whitespace removed) is found inside the
    OCR text (whitespace removed). Returns overall recall and per-field counts.
    Short fields like 女 or a one-digit month hit easily, so per-class keeps that visible.
    """
    text = _clean(ocr_text)
    n_fields = 0
    n_exact = 0
    per_class = {}

    for field in annotations:
        word = _clean(field["word"])
        if not word:
            continue
        hit = word in text
        n_fields += 1
        n_exact += int(hit)
        name = CLASS_NAMES.get(field["cls"], f"cls_{field['cls']}")
        counts = per_class.setdefault(name, [0, 0])  # [hits, total]
        counts[0] += int(hit)
        counts[1] += 1

    recall = n_exact / n_fields if n_fields else 0.0
    return {"n_fields": n_fields, "n_exact": n_exact, "recall": recall, "per_class": per_class}


def _normalize(text):
    # normalize the text
    return "".join(unicodedata.normalize("NFKC", str(text)).casefold().split())


def _area(box):
    # this is just to get the area of a given boundaing box
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def _intersection(first, second):
    # find the intersection of two bbx
    return max(0.0, min(first[2], second[2]) - max(first[0], second[0])) * max(0.0, min(first[3], second[3]) - max(first[1], second[1]))


def _iou(first, second):
    # caluclate intersection over union
    # iou = overalap/(area(bbx1) + area(bbx2) - overlap)
    ovrlap=_intersection(first, second)
    union=_area(first)+_area(second) - ovrlap
    return ovrlap/union if union else 0.0


def detailed_ocr_metrics(ocr_result, annotations, iou_threshold=0.3):
    if not 0 <= iou_threshold <= 1:
        raise ValueError("iou_threshold must be between 0 and 1")

    result=score_ocr(ocr_result["text"], annotations)
    f=[field for field in annotations if _clean(field["word"])]
    detections = [item for item in ocr_result["detections"] if str(item["text"]).strip() and _area(item["box"]) > 0]
    groups = [[] for _ in f]
    confidences = [float(item["confidence"]) for item in detections if item["confidence"] is not None and math.isfinite(float(item["confidence"])) and 0 <= float(item["confidence"]) <= 1]

    for detection in detections:
        candidates = []
        for index, field in enumerate(f):
            overlap = _intersection(detection["box"], field["box"])
            scale = min(_area(detection["box"]), _area(field["box"]))
            if scale and overlap / scale >= 0.5:
                candidates.append((overlap / scale, _iou(detection["box"], field["box"]), index))
        if candidates:
            groups[max(candidates)[2]].append(detection)

    located = 0
    exact = 0
    per_class_location = {}
    per_class_exact = {}

    for field, group in zip(f, groups):
        name = CLASS_NAMES.get(field["cls"], f"cls_{field['cls']}")
        location_counts = per_class_location.setdefault(name, [0, 0])
        exact_counts = per_class_exact.setdefault(name, [0, 0])
        location_counts[1] += 1
        exact_counts[1] += 1
        if not group:
            continue

        box = [min(item["box"][0] for item in group), min(item["box"][1] for item in group), max(item["box"][2] for item in group), max(item["box"][3] for item in group)]
        location_hit = _iou(box, field["box"]) >= iou_threshold
        ordered = sorted(group, key=lambda item: (item["box"][1], item["box"][0]))
        exact_hit = location_hit and _normalize("".join(item["text"] for item in ordered)) == _normalize(field["word"])
        located += int(location_hit)
        exact += int(exact_hit)
        location_counts[0] += int(location_hit)
        exact_counts[0] += int(exact_hit)

    result.update({"n_located": located, "n_field_exact": exact, "location_recall": located / len(f) if f else 0.0, "exact_field_recall": exact / len(f) if f else 0.0, "per_class_location": per_class_location, "per_class_exact": per_class_exact, "confidence_sum": sum(confidences), "confidence_count": len(confidences), "mean_confidence": sum(confidences) / len(confidences) if confidences else None})
    return result


def visualize_boxes(image, annotations, detections):
    # this is just for visualize checks in the ipynb not part of the pipeline
    original = image.convert("RGB") if isinstance(image, Image.Image) else Image.fromarray(image).convert("RGB")
    canvas = Image.new("RGB", (original.width * 2, original.height))
    canvas.paste(original, (0, 0))
    canvas.paste(original, (original.width, 0))
    draw = ImageDraw.Draw(canvas)
    for field in annotations:
        draw.rectangle(tuple(field["box"]), outline="lime", width=2)
    for detection in detections:
        box = detection["box"]
        draw.rectangle((box[0] + original.width, box[1], box[2] + original.width, box[3]), outline="red", width=2)
    return canvas
