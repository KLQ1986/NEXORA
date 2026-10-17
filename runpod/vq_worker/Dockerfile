# NEXORA Visual Quality worker for RunPod serverless. Build, push, and point an endpoint at it (README.md).
FROM pytorch/pytorch:2.1.2-cuda12.1-cudnn8-runtime

ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1 VQ_WORKER_ROOT=/opt/vq \
    # every checkpoint any library loads is read as data, never as code
    TORCH_FORCE_WEIGHTS_ONLY_LOAD=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg git curl ca-certificates libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/vq
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && pip install --no-cache-dir -U openmim && mim install "mmcv==2.1.0" && pip install --no-cache-dir "mmagic==1.2.0"

# The model code at the commits that were read (2026-10-17).
RUN git clone https://github.com/JingyunLiang/VRT.git VRT && git -C VRT checkout ed9498a9de21d80cde744b9ab5d3986e1a3bac83 \
 && git clone https://github.com/sczhou/CodeFormer.git CodeFormer && git -C CodeFormer checkout b33cc7d639d6545bfcccc7e0bc6ae51f24e79c2b \
 && pip install --no-cache-dir -r CodeFormer/requirements.txt && (cd CodeFormer && python basicsr/setup.py develop)

# The weights, each checked against pins.txt; a file that differs stops the build.
COPY pins.txt .
RUN mkdir -p weights && cd weights \
 && curl -fsSLO https://github.com/JingyunLiang/VRT/releases/download/v0.0/001_VRT_videosr_bi_REDS_6frames.pth \
 && curl -fsSLO https://github.com/JingyunLiang/VRT/releases/download/v0.0/006_VRT_videodeblurring_GoPro.pth \
 && curl -fsSLO https://github.com/JingyunLiang/VRT/releases/download/v0.0/008_VRT_videodenoising_DAVIS.pth \
 && curl -fsSLO https://download.openmmlab.com/mmediting/restorers/real_basicvsr/realbasicvsr_c64b20_1x30x8_lr5e-5_150k_reds_20211104-52f77c2c.pth \
 && curl -fsSLO https://github.com/sczhou/CodeFormer/releases/download/v0.1.0/codeformer.pth \
 && curl -fsSLO https://github.com/sczhou/CodeFormer/releases/download/v0.1.0/detection_Resnet50_Final.pth \
 && curl -fsSLO https://github.com/sczhou/CodeFormer/releases/download/v0.1.0/parsing_parsenet.pth \
 && grep -v '^#' ../pins.txt | sha256sum -c - \
 && mkdir -p ../CodeFormer/weights/CodeFormer ../CodeFormer/weights/facelib \
 && ln -s /opt/vq/weights/codeformer.pth ../CodeFormer/weights/CodeFormer/codeformer.pth \
 && ln -s /opt/vq/weights/detection_Resnet50_Final.pth ../CodeFormer/weights/facelib/detection_Resnet50_Final.pth \
 && ln -s /opt/vq/weights/parsing_parsenet.pth ../CodeFormer/weights/facelib/parsing_parsenet.pth

COPY handler.py models.py ./
CMD ["python", "-u", "handler.py"]
