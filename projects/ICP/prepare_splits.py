import argparse
import json
import re
from pathlib import Path

import numpy as np

DATASET = "lansinuote/ocr_id_card"
# following the requirements in the pipeline eval guide
COUNTS = {"development": 500, "test": 2000, "load_pool": 17500}


def validate_splits(record):
    # a few sanity checks to ensures splits, data, seed are as expected
    if record.get("dataset") != DATASET or record.get("split") != "train" or record.get("seed") != 8001:
        raise ValueError("Unexpected dataset, source split, or seed")
    
    if record.get("count") != 20000 or not re.fullmatch(r"[0-9a-f]{40}", record.get("revision", "")):
        raise ValueError("Expected 20,000 cards and a resolved 40-character dataset commit")
    
    combined = []
    for name, count in COUNTS.items():
        indices = record["indices"][name]
        if len(indices) != count or any(type(i) is not int or not 0 <= i < 20000 for i in indices):
            raise ValueError(f"Invalid {name} count or index bounds")
        combined.extend(indices)

    if len(set(combined)) != 20000:
        raise ValueError("Duplicate or overlapping indices")
    
    expected = np.random.default_rng(8001).permutation(20000).tolist()
    if combined != expected:
        raise ValueError("Indices do not preserve the prescribed seeded permutation")


def load_record(path):
    record = json.loads(Path(path).read_text())
    validate_splits(record)
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="splits.json")
    parser.add_argument("--revision", default="main")
    args = parser.parse_args()
    from datasets import load_dataset
    from huggingface_hub import HfApi

    path = Path(args.output)
    if path.exists():
        raise FileExistsError(f"Refusing to replace {path}; reuse its recorded revision")
    revision = HfApi().dataset_info(DATASET, revision=args.revision).sha
    dataset = load_dataset(DATASET, split="train", revision=revision)
    if len(dataset) != 20000:
        raise ValueError(f"Expected 20000 cards, received {len(dataset)}")
    indices = np.random.default_rng(8001).permutation(len(dataset)).tolist()
    record = {"dataset": DATASET, "split": "train", "revision": revision, "seed": 8001, "count": len(dataset),
              "indices": {"development": indices[:500], "test": indices[500:2500], "load_pool": indices[2500:]}}
    validate_splits(record)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(record, stream, indent=2)
    print(f"Saved verified dataset revision and split indices to {path}")


if __name__ == "__main__":
    main()
