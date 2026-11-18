import math
import unicodedata
from numbers import Real

from PIL import Image, ImageDraw


# Ishan Pathak
# Nizar Talty

# 10/4/2026
# edited on 15/11/2026 by nizar talty
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

def normalize(text):
    # required nkfc normlation and white space removal
    return "".join(unicodedata.normalize("NFKC", "" if text is None else str(text)).split()).replace("x", "X")


def enclosing_box(box):
    if len(box) == 4 and all(isinstance(value, Real) for value in box):
        result = [float(value) for value in box]
    else:
        result = [min(p[0] for p in box), min(p[1] for p in box), max(p[0] for p in box), max(p[1] for p in box)]
    if not all(math.isfinite(value) for value in result) or result[2] < result[0] or result[3] < result[1]:
        raise ValueError(f"Invalid box: {box}")
    return result


def assign_fields(detections, annotations):
    # new way from M2 to assign fields that is slightely different from how we did it in M1
    groups = [[] for _ in annotations]
    # fetch the boxes
    boxes = [enclosing_box(field["box"]) for field in annotations]

    for detection in detections:
        item = {**detection, "box": enclosing_box(detection["box"])}
        overlaps = []
        for box in boxes:
            scale = min(_area(item["box"]), _area(box))
            overlaps.append(_intersection(item["box"], box) / scale if scale else 0.0)
        if overlaps:
            # First annotation wins equal-overlap ties & input order breaks equal-position ties
            index = max(range(len(overlaps)), key=lambda i: overlaps[i])
            if overlaps[index] >= 0.5:
                groups[index].append(item)

    return ["".join(item["text"] for item in sorted(group, key=lambda d: (d["box"][1], d["box"][0]))) for group in groups]


def edit_distance(first, second):
    previous = list(range(len(second) + 1))
    for i, a in enumerate(first, 1):
        current = [i]
        for j, b in enumerate(second, 1):
            # had an issue with the indices so chatgpt fixed it for me
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (a != b)))
        previous = current
    return previous[-1]


def required_metrics(predictions, annotations):
    if len(predictions) != len(annotations):
        raise ValueError("One prediction is required per annotated field, including missing predictions as empty strings")
    classes = [int(field["cls"]) for field in annotations]
    if sorted(classes) != list(CLASS_NAMES):
        raise ValueError("Expected exactly one annotation for each of the eight field classes")
    counts = {name: [0, 0] for name in CLASS_NAMES.values()}
    hits, cer_sum, nonempty, empty = [], 0.0, 0, 0
    for prediction, field in zip(predictions, annotations):
        predicted, reference = normalize(prediction), normalize(field["word"])
        hit = predicted == reference
        hits.append(hit)
        if not reference:
            empty += 1
            continue
        name = CLASS_NAMES[int(field["cls"])]
        counts[name][0] += int(hit)
        counts[name][1] += 1
        nonempty += 1
        cer_sum += edit_distance(predicted, reference) / len(reference)
    return {"correct_fields": sum(v[0] for v in counts.values()), "nonempty_fields": nonempty,
            "empty_reference_fields": empty, "cer_sum": cer_sum, "per_class": counts,
            "card_correct": all(hits), "empty_reference_correct": sum(hits) - sum(v[0] for v in counts.values())}
