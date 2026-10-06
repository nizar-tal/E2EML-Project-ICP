#!/usr/bin/env bash
set -e
sudo apt-get update
sudo apt-get install -y tesseract-ocr tesseract-ocr-chi-sim libgl1 tmux
pip install --upgrade pip
pip install -r requirements-run.txt
echo "setup done"
