# Build: docker build -f work/T3/service/Dockerfile -t icp-ocr:dev work/T3
# Context = ICP folder (work/T3 now; projects/ICP in the repo later).
FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    OMP_NUM_THREADS=1 \
    OMP_THREAD_LIMIT=1 \
    MKL_NUM_THREADS=1 \
    MAX_BATCH=1 \
    BATCH_TIMEOUT_MS=10 \
    PORT=50051 \
    METRICS_PORT=8000 \
    ICP_PATH=/app/icp \
    HOME=/home/appuser

RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 appuser
WORKDIR /app

COPY requirements-icp.txt /app/requirements-icp.txt
COPY service/requirements.txt /app/requirements-t3.txt
RUN pip install --no-cache-dir torch==2.7.1 torchvision==0.22.1 --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r /app/requirements-icp.txt \
    && pip install --no-cache-dir -r /app/requirements-t3.txt

COPY image.py ocr.py metrics.py assertions.py registry.py evaluate.py \
     model_artifacts.py prepare_splits.py ocr_variants.json splits.json /app/icp/
COPY service/ocr_pb2.py service/ocr_pb2_grpc.py service/pipeline.py \
     service/server.py service/client.py service/loadgen.py /app/

RUN mkdir -p /models && chown -R appuser:appuser /app /home/appuser /models
USER appuser

EXPOSE 50051 8000
CMD ["python", "server.py"]
