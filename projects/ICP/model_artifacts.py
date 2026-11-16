import json
import urllib.request
from pathlib import Path

TESSERACT_SOURCE = {"repository": "tesseract-ocr/tessdata_fast", "revision": "4.1.0"}
SOURCE_FILE = "artifact-sources.json"


def download_artifact(url, destination):
    temporary = destination.with_suffix(destination.suffix + ".part")
    size = 0
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "icp-model-provisioning"})
        with urllib.request.urlopen(request, timeout=60) as response, temporary.open("xb") as stream:
            for chunk in iter(lambda: response.read(1024 * 1024), b""):
                stream.write(chunk)
                size += len(chunk)
        if size == 0:
            raise ValueError(f"Empty model download: {url}")
        temporary.rename(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return {"bytes": size}


def provision_tesseract(model_dir):
    directory = Path(model_dir)
    directory.mkdir(parents=True, exist_ok=True)
    source_path = directory / SOURCE_FILE
    if source_path.exists():
        raise FileExistsError(f"Source record already exists: {source_path}; reuse or choose a fresh model directory")
    filenames = ["chi_sim.traineddata", "eng.traineddata"]
    if any((directory / name).exists() or (directory / (name + ".part")).exists() for name in filenames):
        raise FileExistsError("Refusing to adopt or replace existing Tesseract files; choose a fresh model directory")
    repository, revision = TESSERACT_SOURCE["repository"], TESSERACT_SOURCE["revision"]
    sources = {}
    for filename in filenames:
        url = f"https://raw.githubusercontent.com/{repository}/{revision}/{filename}"
        identity = download_artifact(url, directory / filename)
        sources[filename] = {**TESSERACT_SOURCE, **identity}
    with source_path.open("x") as stream:
        json.dump(sources, stream, indent=2)
    print(f"Provisioned Chinese and English Tesseract artifacts in {directory}; sources: {source_path}")


def artifact_sources(settings, model_dir, inventory):
    path = Path(model_dir) / SOURCE_FILE
    sources = json.loads(path.read_text()) if path.exists() else {}
    # Older source records may have extra fields; new outputs keep only source, version, and size.
    keys = ("repository", "revision", "bytes")
    selected = {item["file"]: {key: sources[item["file"]][key] for key in keys if key in sources[item["file"]]}
                for item in inventory if item["file"] in sources}
    if settings["engine"] == "tesseract":
        for item in inventory:
            source = selected.get(item["file"], {})
            if any(source.get(key) != value for key, value in TESSERACT_SOURCE.items()):
                raise ValueError("Missing or incorrect Tesseract source record; provision official artifacts first")
            if source.get("bytes") != item["bytes"]:
                raise ValueError(f"Model file size no longer matches its source record: {item['file']}")
    return selected
