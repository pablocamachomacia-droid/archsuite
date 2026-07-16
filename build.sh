#!/usr/bin/env bash
set -e
pip install --upgrade pip
pip install -r requirements.txt
echo "uvicorn instalado en: $(which uvicorn || echo 'no encontrado')"
echo "python path: $(python -m uvicorn --version 2>&1)"
