FROM pytorch/pytorch:2.6.0-cuda12.4-cudnn9-runtime

ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /app

RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsndfile1 \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir --extra-index-url https://aiinfra.pkgs.visualstudio.com/PublicPackages/_packaging/onnxruntime-cuda-12/pypi/simple/ -r requirements.txt \
    && pip install --no-cache-dir --no-deps resemble-enhance>=0.0.1

ARG HF_TOKEN
ENV HF_TOKEN=${HF_TOKEN}

COPY . .

RUN python scripts/cache_models.py

EXPOSE 8000
CMD ["python", "-u", "runpod_worker.py"]
