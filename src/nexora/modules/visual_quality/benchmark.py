"""The engine measured on cases whose answer is known (Visual Quality, design 2026-10-16 §3.1, Benchmark).

A clean frame (from any source, or from the library) is damaged on purpose by BasicSR's degradations: noise, compression,
banding, blur, under-exposure, a colour cast. For each damage the benchmark asks two things:

- is it found? the defect map of the damaged frame must name it;
- is it undone? the step the planner proposes for it, run through the very FFmpeg filters a recipe uses, must bring the
  frame closer to the clean one (PSNR and SSIM against the clean frame) without making it less natural (NIQE).

Its table is how a filter earns its default, and how a change to a filter is known to be better or worse.
"""
import json
import tempfile
import time
from pathlib import Path

import numpy as np
from PIL import Image

from nexora.core.adapter import AdapterRegistry, Request
from nexora.core.visual_quality import filters_of
from nexora.modules.visual_quality import assess as A
from nexora.modules.visual_quality import measure as M
from nexora.modules.visual_quality import plan as P
from nexora.third_party.basicsr import degradations as D
from nexora.third_party.basicsr.metrics import psnr, ssim

VERSION = "1"

# damage name -> (how it is made, the defect it should be found as, the step that should undo it)
# The planner's own choices are used (the same parameters a recipe would get from the measured damage); `judge` is how a
# fix is known to help: closer to the clean frame (PSNR and SSIM), or, for banding, more natural (NIQE), since smoothing the
# steps of a quantised gradient cannot bring back the levels it lost.
CASES = {
    "noise": (lambda f: D.add_gaussian_noise(f, 12.0, seed=3), "noise", lambda lk: {"op": "denoise", "tier": "ffmpeg", "params": {"sigma": lk["noise"], "method": "nlmeans"}}, "fidelity"),
    "noise_strong": (lambda f: D.add_gaussian_noise(f, 25.0, seed=4), "noise", lambda lk: {"op": "denoise", "tier": "ffmpeg", "params": {"sigma": lk["noise"], "method": "nlmeans"}}, "fidelity"),
    "jpeg": (lambda f: D.jpeg(f, 12), "blocking", lambda lk: {"op": "deblock", "tier": "ffmpeg", "params": {}}, "fidelity"),
    "banding": (lambda f: D.band(D.blur(f, 6.0), 28), "banding", lambda lk: {"op": "deband", "tier": "ffmpeg", "params": {"threshold": 0.04, "range": 24}}, "naturalness"),
    "blur": (lambda f: D.blur(f, 1.4), "soft", lambda lk: {"op": "sharpen", "tier": "ffmpeg", "params": {"strength": 0.25}}, "fidelity"),
    "dark": (lambda f: D.exposure(f, -1.3), "underexposed", lambda lk: P.exposure_balance(lk, content="camera", parts=frozenset({"black", "white", "gamma"})), "fidelity"),
    "cast": (lambda f: D.colour_cast(f, (1.12, 1.0, 0.86)), "cast", lambda lk: P.exposure_balance(lk, content="camera", parts=frozenset({"wb"})), "fidelity"),
}


def _png(img: np.ndarray, path: Path) -> Path:
    Image.fromarray((np.clip(img, 0, 1) * 255).round().astype(np.uint8)).save(path)
    return path


def _load(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB"), np.float32) / 255.0


def run(adapters: AdapterRegistry, clean: np.ndarray, *, cases: list[str] | None = None, lut_dir: str | Path | None = None) -> dict:
    """The benchmark on one clean frame (RGB in [0, 1]); returns a row per case."""
    rows = []
    work = Path(tempfile.mkdtemp(prefix="vq_bench_"))
    clean = clean[: clean.shape[0] // 2 * 2, : clean.shape[1] // 2 * 2]
    for name in cases or list(CASES):
        make, expect, fix, judge = CASES[name]
        bad = make(clean).astype(np.float32)
        lk = M.look(bad)
        found = A.defects_of(A.ShotScore(0.0, 0.0, lk, 0.0, 0.0, None), content="camera", frame=bad)
        kinds = {d["kind"]: d["severity"] for d in found}
        step = fix(M.as_dict(lk))
        row = {"case": name, "expected": expect, "found": expect in kinds, "severity": kinds.get(expect, 0.0), "others": sorted(k for k in kinds if k != expect),
               "psnr_bad": round(psnr(clean * 255, bad * 255), 2), "ssim_bad": round(ssim(clean * 255, bad * 255), 4),
               "niqe_clean": _n(clean), "niqe_bad": _n(bad)}
        if step:
            if step["op"] == "denoise":
                # The strength a recipe would get: tuned on the picture by its method noise (plan.tune_denoise).
                def frame(strength, step=step, name=name, bad=bad):
                    if strength is None:
                        return bad
                    trial = {**step, "params": {**step["params"], "strength": strength}}
                    src, out = _png(bad, work / f"{name}_bad.png"), work / f"{name}_tune.png"
                    adapters.submit("ffmpeg", Request("vq_render", inputs={"path": str(src)}, params={"kind": "still", "out": str(out), "filters": filters_of([trial]) or []}))
                    return _load(out)
                step["params"]["strength"], _ = P.tune_denoise(frame, float(step["params"]["sigma"]))
            if step["op"] == "levels" and lut_dir:
                step["params"]["lut"] = P.levels_lut(step["params"], lut_dir)
            chain = filters_of([step]) or []
            src, out = _png(bad, work / f"{name}_bad.png"), work / f"{name}_fixed.png"
            adapters.submit("ffmpeg", Request("vq_render", inputs={"path": str(src)}, params={"kind": "still", "out": str(out), "filters": chain}))
            fixed = _load(out)
            row.update({"step": step["op"], "params": {k: v for k, v in step["params"].items() if k != "lut"},
                        "psnr_fixed": round(psnr(clean * 255, fixed * 255), 2), "ssim_fixed": round(ssim(clean * 255, fixed * 255), 4), "niqe_fixed": _n(fixed)})
            if judge == "naturalness":
                row["helps"] = bool(row["niqe_fixed"] is not None and row["niqe_bad"] is not None and row["niqe_fixed"] < row["niqe_bad"] - 0.2
                                    and row["ssim_fixed"] >= row["ssim_bad"] - 0.01)
            else:
                row["helps"] = bool(row["psnr_fixed"] > row["psnr_bad"] and row["ssim_fixed"] >= row["ssim_bad"] - 0.002)
            row["judged_by"] = judge
        else:
            row.update({"step": None, "helps": False})
        rows.append(row)
    found = sum(r["found"] for r in rows)
    helped = sum(r["helps"] for r in rows)
    result = {"version": VERSION, "at": round(time.time()), "size": list(clean.shape[:2]), "found": f"{found}/{len(rows)}", "helped": f"{helped}/{len(rows)}", "rows": rows}
    try:
        ai_here = bool((adapters.environment().get("restore_local") or {}).get("available"))
    except Exception:
        ai_here = False
    if ai_here:
        result["ai"] = run_ai(adapters, clean, work)
    return result


def run_ai(adapters: AdapterRegistry, clean: np.ndarray, work: Path) -> list[dict]:
    """The AI steps against the classic ones they stand beside, on the same damage: a crushed JPEG (Real-ESRGAN ×4 and back
    against `deblock`) and a picture made four times smaller (Real-ESRGAN ×4 against lanczos). Fidelity (PSNR, SSIM against
    the clean frame) and naturalness (NIQE) are both kept: an AI that makes detail up may win the one and lose the other."""
    h, w = clean.shape[:2]
    small = D.downscale(clean, 4.0, back=False)
    cases = {"jpeg": (D.jpeg(clean, 12), [{"op": "deblock", "tier": "ffmpeg", "params": {}}], (w, h)),
             "small_x4": (small, [{"op": "upscale", "tier": "ffmpeg", "params": {"factor": 4}}], (w, h))}
    rows = []
    for name, (bad, classic, size) in cases.items():
        src = _png(bad, work / f"ai_{name}_bad.png")
        out_c, out_a = work / f"ai_{name}_classic.png", work / f"ai_{name}_ai.png"
        adapters.submit("ffmpeg", Request("vq_render", inputs={"path": str(src)}, params={"kind": "still", "out": str(out_c), "filters": [*(filters_of(classic) or []), f"scale={size[0]}:{size[1]}:flags=lanczos"]}))
        adapters.submit("restore_local", Request("esrgan", inputs={"path": str(src)}, params={"out": str(out_a), "model": P.AI_MODEL, "size": list(size)}))
        row = {"case": name}
        for tag, file in (("classic", out_c), ("ai", out_a)):
            img = _load(file)[:h, :w]
            row[tag] = {"psnr": round(psnr(clean * 255, img * 255), 2), "ssim": round(ssim(clean * 255, img * 255), 4), "niqe": _n(img)}
        c, a = row["classic"], row["ai"]
        row["ai_more_natural"] = bool(a["niqe"] is not None and c["niqe"] is not None and a["niqe"] < c["niqe"] - 0.5)
        row["ai_more_faithful"] = bool(a["psnr"] > c["psnr"] and a["ssim"] >= c["ssim"])
        rows.append(row)
    return rows


def _n(img: np.ndarray) -> float | None:
    v = A.niqe_of(img)
    return None if v is None else round(v, 3)


def table(result: dict) -> str:
    lines = [f"Phát hiện đúng {result['found']}, sửa có ích {result['helped']} (khung {result['size'][1]}×{result['size'][0]})",
             f"{'lỗi':14s} {'thấy':5s} {'bước':10s} {'PSNR':>14s} {'SSIM':>16s} {'NIQE':>16s}"]
    for r in result["rows"]:
        lines.append(f"{r['case']:14s} {'✓' if r['found'] else '✗':5s} {str(r['step']):10s} "
                     f"{r['psnr_bad']:6.2f}→{r.get('psnr_fixed', float('nan')):6.2f} {r['ssim_bad']:.4f}→{r.get('ssim_fixed', float('nan')):.4f} "
                     f"{r['niqe_bad'] or 0:6.2f}→{(r.get('niqe_fixed') or 0):6.2f} {'có ích' if r['helps'] else 'KHÔNG'}")
    for r in result.get("ai", []):
        c, a = r["classic"], r["ai"]
        lines.append(f"AI {r['case']:11s} cổ điển PSNR {c['psnr']:.2f} SSIM {c['ssim']:.4f} NIQE {c['niqe'] or 0:.2f} | "
                     f"Real-ESRGAN PSNR {a['psnr']:.2f} SSIM {a['ssim']:.4f} NIQE {a['niqe'] or 0:.2f}"
                     f"{' · tự nhiên hơn' if r['ai_more_natural'] else ''}{' · sát gốc hơn' if r['ai_more_faithful'] else ''}")
    return "\n".join(lines)


def save(result: dict, folder: str | Path) -> Path:
    out = Path(folder) / f"bench_{result['at']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    return out
