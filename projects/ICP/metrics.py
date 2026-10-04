# Ishan Pathak

# 10/4/2026
# score OCR text against the ID-card ground-truth fields

CLASS_NAMES = {
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
