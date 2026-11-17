#!/usr/bin/env python3
# Minimal OCR gRPC test client.
import argparse, json, sys
from io import BytesIO
from pathlib import Path

import grpc, numpy as np
from PIL import Image
from datasets import load_dataset

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ocr_pb2, ocr_pb2_grpc

REV = "6a7fd6ba549e99b9a3517fc9a56c4e3377e43e05"
_splits = Path(__file__).resolve().parent.parent / "splits.json"
if _splits.exists():
    REV = json.loads(_splits.read_text()).get("revision", REV)

p = argparse.ArgumentParser()
p.add_argument("--host", default="localhost:50051")
p.add_argument("--n", type=int, default=5)
p.add_argument("--start", type=int, default=0)
p.add_argument("--lb", default="", help="gRPC lb policy, e.g. round_robin")
args = p.parse_args()

ds = load_dataset("lansinuote/ocr_id_card", split="train", revision=REV)
opts = (("grpc.lb_policy_name", args.lb),) if args.lb else ()
stub = ocr_pb2_grpc.OCRStub(grpc.insecure_channel(args.host, options=opts))
for i in range(args.start, args.start + args.n):
    buf = BytesIO()
    Image.fromarray(np.asarray(ds[i]["image"].convert("RGB"))).save(buf, format="PNG")
    try:
        r = stub.Extract(ocr_pb2.CardRequest(card_id=str(i), image=buf.getvalue()), timeout=300)
        t = r.timing
        print(f"card_id={r.card_id} variant={r.variant} batch_size={r.batch_size} "
              f"queue_ms={t.queue_ms:.1f} ocr_ms={t.ocr_ms:.1f} total_ms={t.total_ms:.1f} status=ok")
    except grpc.RpcError as e:
        print(f"card_id={i} variant=? batch_size=? queue_ms=? ocr_ms=? total_ms=? status={e.code().name}")
