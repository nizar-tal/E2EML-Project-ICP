FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# Added tesseract-ocr-chi-sim for Chinese language support in Tesseract
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential software-properties-common curl wget git unzip nano vim \
    python3 python3-pip python3-venv python3-dev \
    libgl1-mesa-glx \
    tesseract-ocr \
    tesseract-ocr-chi-sim \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /

COPY README.md .
COPY requirements-icp.txt .

# Install Jupyter and dependencies from requirements file
RUN pip install --upgrade pip && \
    pip install -r requirements-icp.txt && \
    pip install jupyter

COPY image.py .
COPY ocr.py .
COPY metrics.py .
COPY pipeline_configs.json .
COPY sample.ipynb .
COPY ICP.ipynb .

# Expose Jupyter port
EXPOSE 8888

# Default command: start Jupyter Notebook
CMD ["jupyter", "notebook", "--ip=0.0.0.0", "--port=8888", "--no-browser", "--allow-root"]
