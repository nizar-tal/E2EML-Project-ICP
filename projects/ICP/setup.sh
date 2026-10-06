#!/usr/bin/env bash
set -e
sudo apt-get update
sudo apt-get install -y tesseract-ocr tesseract-ocr-chi-sim libgl1 tmux
pip install --upgrade pip
pip install -r requirements-run.txt
# This host's driver is CUDA 12.6. A default pip torch wheel is CUDA 13 and silently falls back to CPU.
pip install torch==2.14.0 torchvision==0.29.0 --index-url https://download.pytorch.org/whl/cu126
python3 -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available())"
echo "setup done"
