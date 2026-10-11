# YuE2 song worker for Runpod serverless. Built by Runpod's GitHub integration (or: docker build --platform linux/amd64 .)
# The 7.3 GB YuE2-3B model is NOT in the image: attach it to the endpoint as a cached model
# (https://huggingface.co/m-a-p/YuE2-3B). Only the 0.5 GB VAE is baked in.
FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONUNBUFFERED=1 \
    HF_HOME=/tmp/hf HF_HUB_DISABLE_TELEMETRY=1

# torch first, from the CUDA 12.8 index, so yue2-infer's torch==2.10.0 pin is already met
RUN pip install --index-url https://download.pytorch.org/whl/cu128 torch==2.10.0
# YuE2 at the commit the bake-off ran (2026-10-06)
RUN pip install "yue2-infer @ git+https://github.com/multimodal-art-projection/YuE@1647252d68b70cbead046ffd3f7caf036dde47ee" \
    runpod==1.10.1

RUN python -c "from huggingface_hub import snapshot_download as d; d('m-a-p/YuE2-Vae', \
    revision='152733a19ad43aa67e367f9b5503ef8075bb5126', local_dir='/models/YuE2-Vae', \
    allow_patterns=['config.json', '*.safetensors', 'weights_manifest.json', 'modeling_vae.py', \
                    'LICENSE', 'THIRD_PARTY_NOTICES.md', 'licenses/*'])" \
    && rm -rf /tmp/hf

WORKDIR /app
COPY handler.py lyrics.py ./
CMD ["python", "-u", "handler.py"]
