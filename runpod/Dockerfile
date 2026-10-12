# One image for all five reference workers; the task is chosen with NEXORA_TASK when the endpoint is created.
# Start from the image of the model you will run instead of this one once you replace a stand-in.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir runpod pillow
COPY worker.py /worker.py
CMD ["python", "-u", "/worker.py"]
