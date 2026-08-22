FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies needed for audio & ffmpeg processing
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsndfile1 \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install dependencies
# Pre-install CPU PyTorch (~180MB) instead of default CUDA wheels (~2.5GB) to speed up Docker build from 35 mins to <1 min
COPY requirements.txt .
RUN pip install --no-cache-dir "torch>=2.3.0,<2.6.0" "torchaudio>=2.3.0,<2.6.0" --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source code
COPY . .

# Expose port
EXPOSE 8000

# Start FastAPI web server on Railway
CMD ["python", "main.py"]
