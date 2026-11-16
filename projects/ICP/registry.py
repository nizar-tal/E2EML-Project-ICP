import argparse
import json
import importlib.metadata
import os
import re
from pathlib import Path

from evaluate import artifact_inventory, write_json
from model_artifacts import SOURCE_FILE, artifact_sources, provision_tesseract


def connection():
    import boto3

    required = ["MINIO_ENDPOINT", "MINIO_ACCESS_KEY", "MINIO_SECRET_KEY", "MINIO_BUCKET"]
    missing = [key for key in required if not os.environ.get(key)]
    if missing:
        raise ValueError(f"Missing environment variables: {', '.join(missing)}")
    return boto3.client("s3", endpoint_url=os.environ["MINIO_ENDPOINT"],
                        aws_access_key_id=os.environ["MINIO_ACCESS_KEY"],
                        aws_secret_access_key=os.environ["MINIO_SECRET_KEY"],
                        region_name=os.environ.get("MINIO_REGION", "us-east-1")), os.environ["MINIO_BUCKET"]


def exists(client, bucket, key):
    from botocore.exceptions import ClientError

    try:
        client.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as error:
        if error.response["Error"]["Code"] in {"404", "NoSuchKey", "NotFound"}:
            return False
        raise


def select_variant(args):
    variants = json.loads(Path(args.variants).read_text())
    found = [item for item in variants if item["name"] == args.name]
    if len(found) != 1:
        raise ValueError("Variant name must identify exactly one variant")
    settings = found[0]
    for value in (settings["name"], settings["version"]):
        if not re.fullmatch(r"[a-zA-Z0-9_.-]+", value):
            raise ValueError("Unsafe name/version")
    return settings


def offline_accuracy(args, settings, artifacts):
    if not args.summary:
        return {"status": "unmeasured", "metrics": None}
    path = Path(args.summary)
    summary = json.loads(path.read_text())
    run = json.loads((path.parent / "run.json").read_text())
    if run["slice"] != "test" or run["limit"] is not None or summary["metrics"]["cards"] != 2000:
        raise ValueError("Registry accuracy requires a full 2000-card test evaluation")
    if summary["settings"] != settings or summary["provenance"]["artifacts"] != artifacts:
        raise ValueError("Test result settings or artifact identity do not match upload")
    if summary["provenance"] != run["provenance"][settings["name"]]:
        raise ValueError("Summary provenance does not match its run")
    return {"status": "measured", "metrics": summary["metrics"], "provenance": summary["provenance"],
            "summary_file": path.name}


def make_metadata(args):
    settings = select_variant(args)
    artifacts = artifact_inventory(settings, args.model_dir)
    release = "tessdata_fast-4.1.0" if settings["engine"] == "tesseract" else "easyocr-" + importlib.metadata.version("easyocr")
    references = [{**item, "key": f'artifacts/{release}/{item["file"]}'} for item in artifacts]
    return {"name": settings["name"], "version": settings["version"], "source": settings["source"],
            "engine": settings["engine"], "settings": settings, "artifacts": references,
            "artifact_sources": artifact_sources(settings, args.model_dir, artifacts),
            "size_bytes": sum(item["bytes"] for item in artifacts),
            "size_definition": "Sum of unique referenced model-file bytes; excludes metadata, runtime, and cache",
            "offline_test_accuracy": offline_accuracy(args, settings, artifacts)}


def upload(args):
    metadata = make_metadata(args)
    client, bucket = connection()
    client.head_bucket(Bucket=bucket)
    key = f'variants/{metadata["name"]}/{metadata["version"]}.json'
    if exists(client, bucket, key):
        raise FileExistsError("Published variant version is immutable; increment version before publishing again")
    for artifact in metadata["artifacts"]:
        if exists(client, bucket, artifact["key"]):
            stored = client.head_object(Bucket=bucket, Key=artifact["key"])
            if stored["ContentLength"] != artifact["bytes"]:
                raise ValueError(f"Stored artifact has a different size: {artifact['key']}")
        else:
            client.upload_file(str(Path(args.model_dir) / artifact["file"]), bucket, artifact["key"])
    client.put_object(Bucket=bucket, Key=key, Body=json.dumps(metadata, ensure_ascii=False).encode(),
                      ContentType="application/json", IfNoneMatch="*")
    print(f"Uploaded {key}; model bytes: {metadata['size_bytes']}")


def record_accuracy(args):
    if not args.summary:
        raise ValueError("--summary from a complete test evaluation is required")
    metadata = make_metadata(args)
    client, bucket = connection()
    key = f'variants/{metadata["name"]}/{metadata["version"]}.json'
    response = client.get_object(Bucket=bucket, Key=key)
    previous = json.loads(response["Body"].read())
    old_accuracy = previous.pop("offline_test_accuracy")
    accuracy = metadata.pop("offline_test_accuracy")
    if previous != metadata or old_accuracy["status"] != "unmeasured":
        raise ValueError("Only unmeasured accuracy may be filled; published settings and artifacts cannot change")
    metadata["offline_test_accuracy"] = accuracy
    client.put_object(Bucket=bucket, Key=key, Body=json.dumps(metadata, ensure_ascii=False).encode(),
                      ContentType="application/json", IfMatch=response["ETag"])
    print(f"Recorded measured test accuracy for {key}")


def download(args):
    if not all(re.fullmatch(r"[a-zA-Z0-9_.-]+", value) for value in (args.name, args.version)):
        raise ValueError("Unsafe name/version")
    
    client, bucket = connection()
    key = f"variants/{args.name}/{args.version}.json"
    metadata = json.loads(client.get_object(Bucket=bucket, Key=key)["Body"].read())

    if metadata["name"] != args.name or metadata["version"] != args.version:
        raise ValueError("Registry metadata identity mismatch")
    
    destination = Path(args.destination)
    destination.mkdir(parents=True, exist_ok=False)

    for artifact in metadata["artifacts"]:
        filename = artifact["file"]
        if Path(filename).name != filename or filename in {".", ".."}:
            raise ValueError("Unsafe artifact filename")
        client.download_file(bucket, artifact["key"], str(destination / filename))

    actual = artifact_inventory(metadata["settings"], destination)
    expected = [{key: item[key] for key in ("file", "bytes")} for item in metadata["artifacts"]]

    if actual != expected:
        raise ValueError("Downloaded artifact sizes do not match metadata; do not use this directory")
    
    write_json(destination / SOURCE_FILE, metadata["artifact_sources"])
    artifact_sources(metadata["settings"], destination, actual)
    write_json(destination / "metadata.json", metadata)
    write_json(destination / "variants.json", [metadata["settings"]])
    print(f"Downloaded artifacts and checked file sizes in {destination}; run the clean-directory OCR check next")


def main():
    parser = argparse.ArgumentParser()
    actions = ["provision-tesseract", "provision-easyocr", "metadata", "init", "upload", "download", "record-accuracy"]
    parser.add_argument("action", choices=actions)
    parser.add_argument("--variants", default="ocr_variants.json")
    parser.add_argument("--name", default="easyocr_original")
    parser.add_argument("--version", default="1")
    parser.add_argument("--model-dir", default="models")
    parser.add_argument("--summary")
    parser.add_argument("--output", default="variant.metadata.json")
    parser.add_argument("--destination", default="models-clean")
    args = parser.parse_args()
    if args.action == "provision-tesseract":
        provision_tesseract(args.model_dir)
    elif args.action == "provision-easyocr":
        from ocr import get_easyocr_reader

        settings = select_variant(args)
        if settings["engine"] != "easyocr":
            raise ValueError("Provisioning command requires an EasyOCR variant")
        Path(args.model_dir).mkdir(parents=True, exist_ok=True)
        get_easyocr_reader("cpu", args.model_dir, settings, download=True)
        artifact_inventory(settings, args.model_dir)
        print("Provisioned EasyOCR weights; record their identities with the metadata command")
    elif args.action == "metadata":
        write_json(args.output, make_metadata(args))
    elif args.action == "init":
        client, bucket = connection()
        from botocore.exceptions import ClientError

        try:
            client.head_bucket(Bucket=bucket)
        except ClientError as error:
            if error.response["Error"]["Code"] not in {"404", "NoSuchBucket", "NotFound"}:
                raise
            client.create_bucket(Bucket=bucket)
    elif args.action == "upload":
        upload(args)
    elif args.action == "record-accuracy":
        record_accuracy(args)
    else:
        download(args)


if __name__ == "__main__":
    main()
