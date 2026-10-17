# NEXORA Visual Quality worker (RunPod serverless)

The models Visual Quality cannot run well on the Mac, behind one RunPod serverless endpoint. NEXORA's client is
`src/nexora/adapters/runpod_restore.py`; the planner proposes these steps only while the endpoint answers its health check and
only for a recording the operator allowed to leave the machine (*Cho gửi footage lên GPU thuê*, or `--allow-cloud`).

| task | model | when Visual Quality proposes it |
|---|---|---|
| `deblur` | VRT 006 (GoPro) | blur sharpening cannot undo, on video (NAFNet on the Mac would take too long or is not set up) |
| `denoise` | VRT 008 (DAVIS, non-blind) | heavy noise on video, or noise a large lift of a dark shot will show |
| `upscale` | VRT 001 (REDS ×4), then to the height asked | a height asked (or offered for footage under 900p) that Apple's ×4 does not suit |
| `restore` | RealBasicVSR (×4), then to the height asked | old footage: ≤720p with blocks, softness, noise or banding |
| `faces` | CodeFormer | faces small or damaged in a video shot |

## What is done and what is not (2026-10-17)

Done and tested without a GPU (`tests/visual_quality/test_runpod_worker.py`): the job protocol, the chunking of a span into
requests that fit RunPod's ~10 MB limit with 8 frames of overlap, the frame-exact join, the health check, the routing of each
task from the planner through the preview, with `VQ_WORKER_FAKE=1` standing in for the models.

**Not done yet (the debt):** the image has not been built, and the five models have not been run on a GPU. Before trusting it:

1. Build and push the image (an x86-64 machine or a builder; the Mac cannot build CUDA images natively):
   `docker build --platform linux/amd64 -t <registry>/nexora-vq-worker:1 runpod/vq_worker && docker push <registry>/nexora-vq-worker:1`
   The build stops if any weight differs from `pins.txt`.
2. On RunPod: a serverless endpoint from that image, a GPU with 24 GB or more (A5000/L4/A10 for 1080p, 48 GB for 4K upscaling),
   idle timeout short (5 s), max workers 3 (the client sends three chunks at a time).
3. In `nexora.toml`: `runpod_api_key`, `runpod_restore_endpoint = "<endpoint id>"`; restart NEXORA. *Chất lượng hình* lists
   "RunPod: …" among the tools, green while the endpoint answers.
4. Run each task once on a short real span (a VQ preview with *Cho gửi footage lên GPU thuê*) and look at it: the model code
   paths (`models.py`: VRT's `test_video`, mmagic's `MMagicInferencer("real_basicvsr")`, CodeFormer's
   `inference_codeformer.py` on a folder) are written to their projects' interfaces at the pinned commits but have never run.
   Things that may need adjusting: mmcv/mmagic against the image's torch, CodeFormer's output names, VRT's memory with
   `tile` (lower `[12,128,128]` in `models.py` if a 24 GB card runs out).
5. Note the cost of each (RunPod reports execution time; NEXORA records it per run) and set `runpod_price_per_second`.

## Running the protocol here

    VQ_WORKER_FAKE=1 python -c "import sys; sys.path.insert(0,'runpod/vq_worker'); import handler; print(handler.handler({'input': {'task': 'capabilities'}}))"

## Safety

Weights are fixed by SHA-256 (`pins.txt`), checked when the image is built and again before each is loaded; they are loaded
with `weights_only` (and `TORCH_FORCE_WEIGHTS_ONLY_LOAD=1` for every library in the image). The code of VRT and CodeFormer is
fixed at the commits in the `Dockerfile`, packages at the versions in `requirements.txt`. Footage reaches the endpoint only
for a recording the operator allowed out, never in privacy mode; nothing is kept on the worker after a job.
