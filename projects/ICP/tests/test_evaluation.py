import copy

import numpy as np
import pytest

from assertions import check_assertions
from evaluate import comparisons, correlation, new_totals, add_card, summarize
from metrics import assign_fields, detailed_ocr_metrics, normalize, required_metrics
from ocr import map_detections, run_ocr_detailed
from prepare_splits import DATASET, validate_splits


def annotations(words=None):
    words = words or ["王", "男", "汉", "2000", "1", "2", "北京市", "12345620000102123X"]
    return [{"cls": i, "word": word, "box": [i * 100, 0, i * 100 + 90, 40]} for i, word in enumerate(words)]


def detection(text, box):
    return {"text": text, "box": box, "confidence": 0.8}


def fields(year="2000", month="1", day="2"):
    return {"birth_year": year, "birth_month": month, "birth_day": day, "gender": "男",
            "id_number": f"123456{year}{int(month):02d}{int(day):02d}123X"}


def test_overlap_smaller_area_threshold_and_reading_order():
    reference = [{"box": [0, 0, 40, 40]}, {"box": [20, 0, 60, 40]}]
    detections = [detection("下", [0, 20, 10, 30]), detection("右", [10, 0, 20, 10]),
                  detection("左", [[0, 0], [10, 0], [10, 10], [0, 10]]),
                  detection("界", [-10, 0, 10, 10]), detection("弃", [-11, 0, 9, 10]),
                  detection("二", [40, 0, 50, 10])]
    assert assign_fields(detections, reference) == ["界左右下", "二"]


def test_overlap_ties_use_first_annotation_not_iou():
    reference = [{"box": [0, 0, 100, 100]}, {"box": [0, 0, 20, 20]}]
    assert assign_fields([detection("同", [0, 0, 10, 10])], reference) == ["同", ""]
    assert assign_fields([detection("零", [0, 0, 0, 0])], reference) == ["", ""]


def test_normalization():
    assert normalize(" Ａ\tＢ\n１２３\u3000x\u00a0") == "AB123X"
    assert normalize("AbC") != normalize("abc")
    assert normalize(None) == ""


def test_historical_iou_gate_and_casefold_are_preserved():
    reference = annotations()
    result = {"text": "王", "detections": [detection("王", [0, 0, 5, 5])]}
    required = required_metrics(assign_fields(result["detections"], reference), reference)
    historical = detailed_ocr_metrics(result, reference)
    assert required["correct_fields"] == 1
    assert historical["n_field_exact"] == 0
    reference[0]["word"] = "AbC"
    result = {"text": "abc", "detections": [detection("abc", reference[0]["box"])]}
    assert detailed_ocr_metrics(result, reference)["n_field_exact"] == 1
    assert required_metrics(assign_fields(result["detections"], reference), reference)["correct_fields"] == 0


def test_missing_predictions_cer_and_card_exact():
    reference = annotations()
    predictions = [field["word"] for field in reference]
    assert required_metrics(predictions, reference)["card_correct"] is True
    predictions[6] = "北京"
    scored = required_metrics(predictions, reference)
    assert scored["correct_fields"] == 7 and not scored["card_correct"]
    assert scored["cer_sum"] == pytest.approx(1 / 3)
    missing = required_metrics([""] * 8, reference)
    assert missing["nonempty_fields"] == 8 and missing["correct_fields"] == 0
    assert missing["cer_sum"] == 8 and not missing["card_correct"]
    totals = new_totals()
    historical = detailed_ocr_metrics({"text": "", "detections": []}, reference)
    add_card(totals, missing, historical, check_assertions({}))
    assert summarize(totals)["mean_field_cer"] == 1


def test_empty_references_and_denominators():
    reference = annotations([""] * 8)
    scored = required_metrics([""] * 8, reference)
    assert scored["nonempty_fields"] == 0 and scored["empty_reference_fields"] == 8
    assert scored["card_correct"] and scored["empty_reference_correct"] == 8
    predictions = [""] * 7 + ["unexpected"]
    assert not required_metrics(predictions, reference)["card_correct"]
    assert summarize(new_totals())["field_exact_match"] is None
    with pytest.raises(ValueError):
        required_metrics([], reference)


def test_cer_can_exceed_one_and_is_per_field_mean():
    reference = annotations()
    predictions = [field["word"] for field in reference]
    predictions[0] = "王王王王"
    scored = required_metrics(predictions, reference)
    assert scored["cer_sum"] == 3
    assert scored["cer_sum"] / scored["nonempty_fields"] == 3 / 8


def test_assertion_id_format_and_birth_match():
    good = fields()
    assert all(check_assertions(good).values())
    good["id_number"] = good["id_number"][:-1] + "x"
    assert check_assertions(good)["A1"]
    good["id_number"] = "12345620000103123X"
    assert check_assertions(good)["A1"] and not check_assertions(good)["A2"]
    for identifier in ("", "123", "12345620000102123Y", "1234562000010212345"):
        assert not check_assertions({**fields(), "id_number": identifier})["A1"]
    assert not any(check_assertions({}).values())
    assert not check_assertions({**fields(), "birth_month": "Jan"})["A2"]


@pytest.mark.parametrize("year,month,day,valid", [
    ("1900", "1", "1", True), ("2030", "12", "31", True), ("1899", "12", "31", False),
    ("2031", "1", "1", False), ("2000", "2", "29", True), ("1900", "2", "29", False),
    ("2001", "2", "29", False), ("2000", "4", "31", False), ("2000", "0", "1", False)])
def test_assertion_date_boundaries(year, month, day, valid):
    assert check_assertions(fields(year, month, day))["A3"] is valid


@pytest.mark.parametrize("gender,valid", [(" 男\n", True), ("女", True), ("男女", False), ("", False), (None, False)])
def test_assertion_gender(gender, valid):
    assert check_assertions({**fields(), "gender": gender})["A4"] is valid


def test_resize_coordinates_use_actual_rounded_dimensions():
    original = [detection("字", [1, 2, 30, 40])]
    mapped = map_detections(original, (101, 99), (50, 50))
    assert mapped[0]["box"] == pytest.approx([2.02, 3.96, 60.6, 79.2])
    assert original[0]["box"] == [1, 2, 30, 40]
    assert map_detections(original, (100, 100), (100, 100)) == original


def split_record():
    indices = np.random.default_rng(8001).permutation(20000).tolist()
    return {"dataset": DATASET, "split": "train", "seed": 8001, "revision": "a" * 40, "count": 20000,
            "indices": {"development": indices[:500], "test": indices[500:2500], "load_pool": indices[2500:]}}


def test_split_integrity():
    # Synthetic in-memory fixture only; not a prepared dataset revision or a saved split file.
    record = split_record()
    validate_splits(record)
    for key, value in (("revision", "main"), ("count", 19999), ("seed", 42)):
        broken = {**record, key: value}
        with pytest.raises(ValueError):
            validate_splits(broken)
    for problem in ("duplicate", "bounds", "count", "order"):
        broken = copy.deepcopy(record)
        if problem == "duplicate":
            broken["indices"]["test"][0] = broken["indices"]["development"][0]
        elif problem == "bounds":
            broken["indices"]["test"][0] = 20000
        elif problem == "count":
            broken["indices"]["load_pool"].pop()
        else:
            broken["indices"]["load_pool"].reverse()
        with pytest.raises(ValueError):
            validate_splits(broken)


def test_undefined_correlations_are_explicit():
    assert correlation([1, 1], [0, 1])["reason"] == "Constant-valued series"
    assert correlation([1], [1])["value"] is None
    assert correlation([None, 1], [0, 1])["value"] is None
    assert comparisons([]) == {}


def test_tesseract_rejects_gpu_before_loading_artifacts(tmp_path):
    settings = {"engine": "tesseract"}
    with pytest.raises(ValueError, match="cpu only"):
        run_ocr_detailed(np.zeros((10, 10, 3), dtype=np.uint8), settings=settings, device="cuda:0", model_dir=tmp_path)


def test_portable_tesseract_source_record(tmp_path):
    import json
    from model_artifacts import SOURCE_FILE, TESSERACT_SOURCE, artifact_sources

    settings = {"engine": "tesseract"}
    inventory = [{"file": "chi_sim.traineddata", "bytes": 123}]
    with pytest.raises(ValueError, match="source record"):
        artifact_sources(settings, tmp_path, inventory)
    source = {**TESSERACT_SOURCE, "bytes": 123}
    (tmp_path / SOURCE_FILE).write_text(json.dumps({"chi_sim.traineddata": source}))
    assert artifact_sources(settings, tmp_path, inventory)["chi_sim.traineddata"] == source
    with pytest.raises(ValueError, match="no longer matches"):
        artifact_sources(settings, tmp_path, [{**inventory[0], "bytes": 124}])


def test_tesseract_provisioning_refuses_existing_files_without_network(tmp_path, monkeypatch):
    import model_artifacts

    def reject_network(url, destination):
        pytest.fail("Existing artifacts must be rejected before any network request")

    monkeypatch.setattr(model_artifacts, "download_artifact", reject_network)
    (tmp_path / "chi_sim.traineddata").write_bytes(b"existing")
    with pytest.raises(FileExistsError, match="existing Tesseract"):
        model_artifacts.provision_tesseract(tmp_path)


def test_csv_reports_have_counts_and_undefined_correlation_reasons(tmp_path):
    import csv
    from evaluate import write_reports

    reference = annotations()
    required = required_metrics([field["word"] for field in reference], reference)
    historical = detailed_ocr_metrics({"text": "", "detections": []}, reference)
    totals = new_totals()
    add_card(totals, required, historical, check_assertions(fields()))
    result = {"name": "synthetic", "settings": {"engine": "tesseract"}, "metrics": summarize(totals)}
    write_reports([result], tmp_path)
    with (tmp_path / "results.csv").open(encoding="utf-8-sig") as stream:
        row = next(csv.DictReader(stream))
    assert row["cards"] == "1" and row["nonempty_fields"] == "8"
    assert float(row["field_exact_match"]) == 1
    with (tmp_path / "comparisons.csv").open(encoding="utf-8-sig") as stream:
        comparison = next(csv.DictReader(stream))
    assert comparison["pearson"] == "" and "Fewer than two" in comparison["reason"]
    assert not (tmp_path / "comparison.json").exists()


def test_csv_preserves_text_and_quotes(tmp_path):
    import csv
    from evaluate import write_csv

    path = tmp_path / "predictions.csv"
    write_csv(path, [{"id": "00123456789012345X", "address": "北京,上海\n地址"}], ["id", "address"])
    with path.open(encoding="utf-8-sig", newline="") as stream:
        row = next(csv.DictReader(stream))
    assert row == {"id": "00123456789012345X", "address": "北京,上海\n地址"}


def test_original_names_are_preserved_and_do_not_collide_with_variants():
    import json
    from pathlib import Path
    from ocr import historical_variant
    from evaluate import current_settings

    root = Path(__file__).resolve().parents[1]
    configurations = json.loads((root / "pipeline_configs.json").read_text())
    variants = json.loads((root / "ocr_variants.json").read_text())
    original = [historical_variant(config) for config in configurations]
    assert len(original) == 16 and len(variants) == 4
    assert [item["name"] for item in original] == [config["name"] for config in configurations]
    assert len({item["name"] for item in original + variants}) == 20
    old = {key: value for key, value in original[0].items() if key != "group"}
    old["name"] = "historical_" + old["name"]
    assert current_settings(old) == original[0]
