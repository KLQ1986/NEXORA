# RunPod workers for NEXORA

`worker.py` holds a reference worker for each of the five serverless endpoints NEXORA can call. Each one keeps to the
input and output the matching adapter in `src/nexora/adapters/runpod.py` sends and reads.

**As shipped they are stand-ins, not models.** They exist so that the path from NEXORA to an endpoint and back can be
run without a GPU. To make an endpoint useful, replace the `run_*` function of its task with a call to your model.

| Task (`NEXORA_TASK`) | Setting in `nexora.toml` | Gets | Returns | Stand-in does |
|---|---|---|---|---|
| `video` | `runpod_video_endpoint` | prompt, image, seconds, seed, aspect, camera | `video` or `video_url` | pushes in on the still |
| `image` | `runpod_image_endpoint` | prompt, seed, aspect, references, loras | `image` or `image_url` | draws a flat picture |
| `lipsync` | `runpod_lipsync_endpoint` | video, audio | `video` or `video_url` | lays the sound under the picture |
| `upscale` | `runpod_upscale_endpoint` | video, scale | `video` or `video_url` | resamples |
| `train` | `runpod_train_endpoint` | images, name, trigger, steps | `model_url` or `model` | writes a file that is not a model |

Files travel as base64 inside the job, so a request is limited to about 6 MB of media. Returning a `*_url` (https)
instead of base64 lifts that limit on the way back, and for `train` it is the only form an image endpoint can load.

## Deploy

1. Build and push the image: `docker build -t <you>/nexora-worker runpod/ && docker push <you>/nexora-worker`
2. In RunPod, create a serverless endpoint from that image with the environment variable `NEXORA_TASK` set to the task.
3. Put the endpoint's id in the matching setting of `nexora.toml` and restart NEXORA.
4. Run `uv run python -m nexora doctor`: it says whether RunPod knows the endpoint, without starting a job.
