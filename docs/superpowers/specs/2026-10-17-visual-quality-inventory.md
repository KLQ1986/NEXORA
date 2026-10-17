# Visual Quality: inventory (2026-10-17)

Every feature of Visual Quality, where it runs, and in what state. **Local** runs on this Mac; **RunPod** needs the worker in
`runpod/vq_worker` on the operator's endpoint: its code and NEXORA's side are complete and tested without a GPU, and wait only
for the image to be built and the endpoint started (the debt, `runpod/vq_worker/README.md`).

## Source and measures

| Feature | Runs | State |
|---|---|---|
| Any source: library asset or any file; video, JPEG/PNG/TIFF, HEIC (sips), RAW (LibRaw) | local | done |
| Original first, proxy only while its drive is away (marked, measured again on return) | local | done |
| Encoding from camera and look together: 19 (DJI D-Log M ×4, D-Log, Pocket 4P, Apple Log 1/2, S-Log3, C-Log2/3, V-Log, LogC3/4, Log3G10, BMD Film5, PQ, HLG, Rec.709) | local | done |
| Content: camera / screen / graphics / AI / still; a camera's file is camera | local | done |
| 12 defects with severity and a 4×4 map: noise, soft, blocking, banding, under/over-exposed, crushed, flicker, shake, cast, dull, flat | local | done |
| Scan read from the picture (idet): interlaced even when marked progressive; 3:2 telecine; a split reading is not interlace | local | **new** |
| Tape colour shifted sideways (chroma vs luma edges, 0.1 px) | local | **new** |
| Rows torn at the foot by a tape's head switch (edges two rows apart, same field; short and sudden only) | local | **new**; 0 on all 12 library clips |

## Steps (fixed order)

| Step | Local | RunPod | State |
|---|---|---|---|
| deinterlace / IVTC | bwdif / fieldmatch+decimate | — | IVTC now proposed (from idet) |
| chroma_align, trim_band | chromashift (chroma samples), fillborders | — | **new** |
| deblock / restore (compression) | deblock; Real-ESRGAN for stills | `restore`: RealBasicVSR for old video | remote **ready, not run** |
| remove (objects) | ProPainter (MPS) | — | done |
| deband | deband | — | done |
| denoise | nlmeans (stills), hqdn3d, Apple temporal; strength from method noise | `denoise`: VRT 008 for heavy or lifted noise | local **improved**, remote **ready, not run** |
| tonemap, color_transform | zscale/tonemap; maker LUT or OCIO ACES 2 | — | done |
| levels | baked LUT (black/white, WB, gamma, saturation) | — | **improved**: a picture dark all over lifted to γ 1.7 (was 1.4) |
| relight | guided-filter gain map, judged on dark share and NIQE | — | done |
| match (colour across sources) | look / scene, LUT | — | done (yesterday) |
| deflicker, stabilise | deflicker; Gyroflow, vidstab | — | done |
| deblur | CAS sharpening; NAFNet (MLX) within a 10-minute budget | `deblur`: VRT 006 | local **budgeted**, remote **ready, not run** |
| upscale | lanczos to the height asked; Apple SR ×4; Real-ESRGAN for stills | `upscale`: VRT 001 ×4 → height | **offered** for video under 900p when a model can make it; remote **ready, not run** |
| faces | CodeFormer + Vision (stills) | `faces`: CodeFormer on video | video faces now found per shot; remote **ready, not run** |
| interpolate | Apple FRC, minterpolate | — | done |

## What changed today, measured

- **Noise as it will be seen.** Denoise used the noise of the source, and its strength was tuned on frames already lifted by the
  levels, so the filter's take looked large and it was turned *down* where a lift needed it *up*. Now the slope of the levels at
  the median (`plan.lift`) raises the noise judged (σ 2 lifted 1.74× is σ 3.5, a defect) and the tuning holds the take against
  σ × lift, trying √lift (≤1.5) first.
- **NAFNet budget.** 25 s a 4K frame on an M4: two seconds of 4K would have taken 25 minutes, ten seconds two hours. Over
  10 minutes a shot is sharpened instead and the recipe says why (or goes to VRT when allowed).
- **No resample offered for nothing.** An upscale is offered unasked only where a model makes it; a lanczos step would add
  nothing a cut's own scaling does not (it doubled an enhanced copy in a test).
- **Tried and left out:** NAFNet SIDD (MLX) as a still denoiser lost to nlmeans at every level on foliage (σ 4: 31.0 against
  39.7, below the noisy 36.0), shifting red/blue ~3 and taking leaves for noise.
- **Colour gap kept** per pair of recipes: the project page no longer renders two frames a pair every minute.

## RunPod: ready to run

`runpod_restore_endpoint` (and `runpod_api_key`) in `nexora.toml`, the endpoint built from `runpod/vq_worker`. Then: the tools
list shows *RunPod: deblur, denoise, upscale, restore, faces* while `/health` answers; the planner proposes those steps for a
recording allowed out; spans travel in chunks that fit RunPod's request and answer (8 frames overlap, joined frame-exactly),
three at a time; cost is recorded per run. Tested end to end with the worker's handler behind a local stand-in for RunPod
(`tests/visual_quality/test_runpod_worker.py`). The models themselves have not run: see the worker's README for the steps.
