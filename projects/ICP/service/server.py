# gRPC OCR.Extract server — variant artifacts from Nizar's MinIO registry.

import json
import logging
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import traceback
from concurrent import futures
from concurrent.futures import Future
from io import BytesIO
from pathlib import Path

import grpc
import numpy as np
from grpc_health.v1 import health, health_pb2, health_pb2_grpc
from PIL import Image
from prometheus_client import Counter, Gauge, Histogram, start_http_server

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("ocr-server")

_LATENCY_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1, 2, 4, 8, 16, 32, 64)
_BATCH_BUCKETS = (1, 2, 4, 8, 16)

REQUESTS = Counter("ocr_requests_total", "OCR requests", ["variant", "status"])
LATENCY = Histogram(
    "ocr_request_latency_seconds", "Server total time",
    ["variant"], buckets=_LATENCY_BUCKETS,
)
QUEUE_TIME = Histogram(
    "ocr_queue_seconds", "Queue wait time",
    ["variant"], buckets=_LATENCY_BUCKETS,
)
INFERENCE = Histogram(
    "ocr_inference_seconds", "OCR time per batch",
    ["variant"], buckets=_LATENCY_BUCKETS,
)
QUEUE_LEN = Gauge("ocr_queue_length", "Batcher queue size", ["variant"])
BATCH_SIZE = Gauge("ocr_batch_size", "Size of the last batch", ["variant"])
BATCH_SIZE_HIST = Histogram(
    "ocr_batch_size_hist", "Batch size distribution",
    ["variant"], buckets=_BATCH_BUCKETS,
)
ASSERTIONS = Counter(
    "ocr_assertions_total", "Per-card assertion outcomes",
    ["variant", "check", "result"],
)


def download_variant():
    required = ["MINIO_ENDPOINT", "MINIO_ACCESS_KEY", "MINIO_SECRET_KEY", "MINIO_BUCKET", "VARIANT"]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        raise ValueError(f"Missing environment variables: {', '.join(missing)}")
    name = os.environ["VARIANT"]
    version = os.environ.get("VARIANT_VERSION", "1")
    dest = Path("/models") / name
    if dest.exists():
        shutil.rmtree(dest)
    icp = Path(os.environ.get(
        "ICP_PATH",
        str(Path(__file__).resolve().parent.parent),  # parent of service/
    ))
    t0 = time.perf_counter()
    subprocess.check_call(
        [sys.executable, str(icp / "registry.py"), "download",
         "--name", name, "--version", version, "--destination", str(dest)],
        cwd=str(icp),
        env=os.environ.copy(),
    )
    ms = (time.perf_counter() - t0) * 1000.0
    settings = json.loads((dest / "variants.json").read_text())[0]
    n_files = sum(1 for p in dest.iterdir() if p.is_file())
    total = sum(p.stat().st_size for p in dest.rglob("*") if p.is_file())
    log.info("registry download variant=%s version=%s files=%d bytes=%d download_ms=%.1f",
             name, version, n_files, total, ms)
    return settings, str(dest)


class Batcher:
    def __init__(self, settings, model_dir, max_batch, timeout_ms, pipeline):
        self.settings = settings
        self.model_dir = model_dir
        self.variant_name = settings.get("name", "")
        self.max_batch = max_batch
        self.timeout_s = timeout_ms / 1000.0
        self.pipeline = pipeline
        self.q = queue.Queue()
        self._thread = threading.Thread(target=self._loop, name="batcher", daemon=True)
        self._thread.start()

    def _set_qlen(self):
        QUEUE_LEN.labels(variant=self.variant_name).set(self.q.qsize())

    def submit(self, image):
        fut = Future()
        t_enqueue = time.perf_counter()
        self.q.put((image, t_enqueue, fut))
        self._set_qlen()
        return fut

    def _loop(self):
        while True:
            first = self.q.get()
            self._set_qlen()
            batch = [first]
            deadline = time.perf_counter() + self.timeout_s
            while len(batch) < self.max_batch:
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    break
                try:
                    batch.append(self.q.get(timeout=remaining))
                    self._set_qlen()
                except queue.Empty:
                    break
            self._set_qlen()

            t_start = time.perf_counter()
            wait_ms = (t_start - batch[0][1]) * 1000.0
            images = [item[0] for item in batch]
            BATCH_SIZE.labels(variant=self.variant_name).set(len(batch))
            BATCH_SIZE_HIST.labels(variant=self.variant_name).observe(len(batch))
            try:
                results = self.pipeline.extract_batch(images, self.settings, self.model_dir)
            except Exception as exc:
                log.error("extract_batch failed:\n%s", traceback.format_exc())
                for _, _, fut in batch:
                    fut.set_exception(exc)
                continue
            ocr_ms = results[0]["ocr_ms"] if results else 0.0
            INFERENCE.labels(variant=self.variant_name).observe(ocr_ms / 1000.0)
            log.info("batch size=%d wait=%.3f ocr_ms=%.3f", len(batch), wait_ms, ocr_ms)
            for (_, t_enqueue, fut), result in zip(batch, results):
                fut.set_result((result, (t_start - t_enqueue) * 1000.0, len(batch)))


class OCRService:
    def __init__(self, batcher, variant_name):
        self.batcher = batcher
        self.variant_name = variant_name

    def Extract(self, request, context):
        import ocr_pb2
        t0 = time.perf_counter()
        try:
            image = Image.open(BytesIO(request.image)).convert("RGB")
            arr = np.asarray(image, dtype=np.uint8)
        except Exception as exc:
            REQUESTS.labels(variant=self.variant_name, status="error").inc()
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        try:
            result, queue_ms, batch_size = self.batcher.submit(arr).result()
        except Exception as exc:
            REQUESTS.labels(variant=self.variant_name, status="error").inc()
            context.abort(grpc.StatusCode.INTERNAL, str(exc))
        total_ms = (time.perf_counter() - t0) * 1000.0
        REQUESTS.labels(variant=self.variant_name, status="ok").inc()
        LATENCY.labels(variant=self.variant_name).observe(total_ms / 1000.0)
        QUEUE_TIME.labels(variant=self.variant_name).observe(queue_ms / 1000.0)
        for check in ("a1", "a2", "a3", "a4", "all"):
            outcome = "pass" if result["assertions"][check] else "fail"
            ASSERTIONS.labels(variant=self.variant_name, check=check, result=outcome).inc()
        return ocr_pb2.CardResponse(
            card_id=request.card_id,
            fields=result["fields"],
            assertions=ocr_pb2.Assertions(**result["assertions"]),
            timing=ocr_pb2.Timing(
                queue_ms=queue_ms,
                preprocess_ms=result["preprocess_ms"],
                ocr_ms=result["ocr_ms"],
                total_ms=total_ms,
            ),
            variant=self.variant_name,
            batch_size=batch_size,
        )


def main():
    import ocr_pb2_grpc

    port = int(os.environ.get("PORT", "50051"))
    max_batch = int(os.environ.get("MAX_BATCH", "1"))
    batch_timeout_ms = float(os.environ.get("BATCH_TIMEOUT_MS", "10"))
    grpc_threads = int(os.environ.get("GRPC_THREADS", "32"))
    metrics_port = int(os.environ.get("METRICS_PORT", "8000"))

    try:
        settings, model_dir = download_variant()
    except Exception:
        log.exception("variant download/load failed")
        sys.exit(1)
    log.info("loaded variant: %s", json.dumps(settings, ensure_ascii=False))

    import pipeline

    dummy = np.zeros((64, 64, 3), dtype=np.uint8)
    try:
        pipeline.extract(dummy, settings, model_dir)
        log.info("warmup done")
    except Exception:
        log.exception("warmup failed")
        sys.exit(1)

    start_http_server(metrics_port)
    log.info("metrics on port %s", metrics_port)

    batcher = Batcher(settings, model_dir, max_batch, batch_timeout_ms, pipeline)
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=grpc_threads))
    ocr_pb2_grpc.add_OCRServicer_to_server(OCRService(batcher, settings.get("name", "")), server)
    health_servicer = health.HealthServicer()
    health_pb2_grpc.add_HealthServicer_to_server(health_servicer, server)
    server.add_insecure_port(f"[::]:{port}")
    server.start()
    health_servicer.set("", health_pb2.HealthCheckResponse.SERVING)
    health_servicer.set("icp.OCR", health_pb2.HealthCheckResponse.SERVING)
    log.info("serving on port %s max_batch=%s", port, max_batch)
    server.wait_for_termination()


if __name__ == "__main__":
    main()
