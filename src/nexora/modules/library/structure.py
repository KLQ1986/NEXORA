"""The structure of a recording, worked out from what was measured in it: where one camera shot ends and the next begins,
and, inside each shot, the beats: stretches of two to fifteen seconds in which one thing is going on.

Nothing here asks a model anything and nothing here reads a file: every function takes the measures of `signals` and
returns boundaries and labels, so each rule can be tried on numbers written by hand. A model later says what a beat shows;
where the beat starts and ends is decided here.

The rule for a hard cut (a jump above an absolute level and well above the activity around it) follows the method read in
FilmCraft's crates/render/src/scene.rs, rewritten from its description.
"""
from dataclasses import dataclass, asdict

import numpy as np

from nexora.core.timebase import to_seconds, to_ticks
from nexora.modules.library.signals import Signals, difference

VERSION = 1


@dataclass(frozen=True)
class Rules:
    """Every level a boundary or a label is decided against. The values are first guesses, to be set against the operator's own
    marks with the benchmark; they live here together so that one change can be measured at a time."""
    cut_sensitivity: float = 50.0          # 0 finds only the plainest cuts, 100 also the faint ones
    min_shot_seconds: float = 0.25         # a cut closer than this to the one before is a flash or a bad frame
    dissolve_level: float = 0.22           # how far the colours must have moved in half a second for a slow change to be looked into
    dissolve_min_seconds: float = 0.25
    dissolve_max_seconds: float = 3.0
    same_picture: float = 0.6              # how alike the picture before and after a change may be for it still to be a change of shot
    blend_error: float = 0.4               # how far the middle of a dissolve may be from a mix of its two ends, as a share of their difference
    blend_colours: float = 0.3             # how far the colours before and after a dissolve must differ; a hand over the lens moves them less
    faint_cut_level: float = 0.16          # the least jump a faint cut must make; real ones measured from 0.18, a turn of the camera while walking 0.13
    min_beat_seconds: float = 3.0
    max_beat_seconds: float = 15.0
    drift_level: float = 0.28              # how far the picture must have moved from the start of a beat for a new one to begin
    move_on: float = 0.05                  # frame widths a second above which the camera counts as moving
    move_off: float = 0.025                # and below which it counts as still again
    zoom_on: float = 0.05                  # growth a second above which the camera counts as pushing in or pulling out
    subject_on: float = 0.07
    subject_off: float = 0.035
    settle_seconds: float = 0.8            # a change of state must last this long to count
    join_seconds: float = 1.0              # boundaries closer than this are one boundary
    speech_reach: float = 0.4              # a boundary moves this far at most to fall between two sentences
    shake_fair: float = 0.08               # set against real footage: on a tripod about 0.01 to 0.03, walking with the camera 0.15 to 0.9
    shake_poor: float = 0.25
    blur_fair: float = 9.0                 # FFmpeg's blurdetect: sharp footage reads about 5 to 6, soft or motion-blurred 9 to 13
    blur_poor: float = 15.0
    burnt_fair: float = 0.08
    burnt_poor: float = 0.25
    crushed_fair: float = 0.30
    crushed_poor: float = 0.60
    still_level: float = 0.004             # mean difference between frames below which the picture is standing still
    travel: float = 0.12                   # how far across the frame the subject must go for its direction to be named
    slow_motion_rate: float = 100.0

    def cut_threshold(self) -> float:
        return 0.45 - 0.33 * min(max(self.cut_sensitivity, 0.0), 100.0) / 100.0


def _stands_out(diff: np.ndarray, i: int, fps: float) -> bool:
    """Whether the jump at frame i is well above the activity around it. Busy footage needs a bigger jump than still footage.
    Frames that repeat the one before (footage shot at a lower rate than it is stored at) say nothing about the activity."""
    window = max(5, round(0.35 * fps))
    around = np.concatenate([diff[max(1, i - window):i], diff[i + 1:i + window + 1]])
    around = around[around > 1e-4]
    return float(diff[i]) >= 2.5 * (float(np.median(around)) if len(around) else 0.0) + 0.05


def detect_cuts(diff: np.ndarray, fps: float, rules: Rules = Rules()) -> list[int]:
    """The frames that begin a new shot. `diff[i]` is how different frame i is from frame i - 1."""
    threshold = rules.cut_threshold()
    shortest = max(1, round(rules.min_shot_seconds * fps))
    cuts: list[int] = []
    for i in range(1, len(diff)):
        d = float(diff[i])
        if d < threshold:
            continue
        if not _stands_out(diff, i, fps):
            continue
        if (i + 1 < len(diff) and diff[i + 1] > d) or (i > 1 and diff[i - 1] > d and (not cuts or cuts[-1] != i - 1)):
            continue
        if i - (cuts[-1] if cuts else 0) < shortest:
            continue
        cuts.append(i)
    return cuts


def detect_dissolves(far: np.ndarray, fps: float, cuts: list[int], rules: Rules = Rules()) -> list[tuple[int, int]]:
    """Stretches in which one picture gives way to another gradually. `far[i]` compares the colours of frame i with those of
    the frame half a second before: over a dissolve it stays high for the length of the dissolve and half a second more, then
    falls back. A run that holds a hard cut is that cut seen from further away, not a dissolve."""
    lag = max(1, round(fps * 0.5))
    shortest, longest = round(rules.dissolve_min_seconds * fps), round(rules.dissolve_max_seconds * fps)
    high = far >= rules.dissolve_level
    out, start = [], None
    for i in range(len(far) + 1):
        if i < len(far) and high[i]:
            start = i if start is None else start
            continue
        if start is not None:
            end = i                                            # the run is far[start:end]
            lasted = max(1, end - start - lag)                 # the change itself: the run is half a second longer than it
            if shortest <= end - start and lasted <= longest and not any(start - 1 <= c <= end for c in cuts):
                out.append((start, start + lasted))
            start = None
    return out


def _alike(grid_a: np.ndarray, grid_b: np.ndarray) -> float:
    """How alike two pictures are in where their light and dark lie, whatever their overall brightness: 1 the same, 0 unrelated."""
    a, b = grid_a - grid_a.mean(), grid_b - grid_b.mean()
    scale = float(np.sqrt((a * a).sum() * (b * b).sum()))
    return float((a * b).sum() / scale) if scale > 1e-9 else 1.0


def detect_changes(sig: Signals, cuts: list[int], rules: Rules = Rules()) -> tuple[list[int], list[tuple[int, int]]]:
    """Changes of shot that a jump between two frames does not show: a cut between two pictures much alike, and a dissolve.
    Each is first a stretch in which the colours moved far in half a second, and then has to be told from what else does
    that. A flicker or a change of light leaves the picture where it was: before and after are alike. A sweep of the camera or
    a hand across the lens is not a mix of what came before and what comes after. Returns the frames of the faint cuts
    and the stretches of the dissolves."""
    fps, grids, hists = sig.fps, sig.sig_grid.astype(np.float32), sig.sig_hist.astype(np.float32)
    if not len(grids):
        return [], []
    place = lambda frame: min(len(grids) - 1, max(0, int(round(frame / fps * sig.sig_rate))))
    at = lambda frame: grids[place(frame)]
    faint, blends, lag = [], [], max(1, round(fps * 0.5))
    # A jump too small for the plain rule is still a cut when it stands out from the activity around it and the picture after
    # it is another picture. A flash or a bad frame stands out as much, and leaves the picture as it was.
    for i in range(1, len(sig.diff) - 1):
        d = float(sig.diff[i])
        if rules.faint_cut_level <= d < rules.cut_threshold() and d >= sig.diff[i - 1] and d >= sig.diff[i + 1] and _stands_out(sig.diff, i, fps) \
                and _alike(at(i - lag), at(i + lag)) < rules.same_picture:
            faint.append(i)
    for a, b in detect_dissolves(sig.far, fps, [*cuts, *faint], rules):
        # The stretch found is the middle of the change: half a second further out on each side the picture is what it was
        # before the change began and what it is once the change is over.
        before, after = at(a - lag), at(b + lag)
        if _alike(before, after) >= rules.same_picture:
            continue                                               # the same picture, lit or coloured differently
        lo, hi = max(1, a - 2), min(len(sig.diff), b + 3)
        peak = lo + int(np.argmax(sig.diff[lo:hi]))
        if float(sig.diff[peak]) >= rules.faint_cut_level and _stands_out(sig.diff, peak, fps) and _alike(at(peak - lag), at(peak + lag)) < rules.same_picture:
            faint.append(peak)                                     # one frame carries the change: a cut, between two pictures much alike
            continue
        span = after - before
        size = float((span * span).sum())
        middle = at((a + b) / 2) - before
        share = float((middle * span).sum() / size) if size > 1e-9 else 0.0
        error = float(np.abs(middle - share * span).mean() / max(float(np.abs(span).mean()), 1e-9))
        colours = float(np.abs(hists[place(a - lag)] - hists[place(b + lag)]).sum() / 6.0)
        if 0.15 < share < 0.85 and error <= rules.blend_error and colours >= rules.blend_colours:    # the middle is a mix of two different pictures: a dissolve or a fade
            if blends and a - blends[-1][1] <= fps:                # out through dark and in again is one change, not two
                blends[-1] = (blends[-1][0], max(b, a + 1))
            else:
                blends.append((a, max(b, a + 1)))
    return faint, blends


def _smooth(values: np.ndarray, width: int, how=np.mean) -> np.ndarray:
    if width <= 1 or len(values) == 0:
        return values.astype(np.float32)
    pad = width // 2
    padded = np.pad(values.astype(np.float32), (pad, width - 1 - pad), mode="edge")
    return how(np.lib.stride_tricks.sliding_window_view(padded, width), axis=1).astype(np.float32)


def _switches(level: np.ndarray, on: float, off: float, hold: int) -> list[int]:
    """The frames at which a measure crosses from quiet to busy or back, with two levels so that it does not flicker between
    them, and counting only a state that lasts `hold` frames."""
    state, out, since = bool(level[0] > on) if len(level) else False, [], 0
    for i in range(1, len(level)):
        wanted = True if level[i] > on else False if level[i] < off else state
        if wanted != state:
            if all((level[j] > on) == wanted or (level[j] < off) == (not wanted) for j in range(i, min(i + hold, len(level)))) and i - since >= hold:
                state, since = wanted, i
                out.append(i)
    return out


def _mean_signature(sig: Signals, t0: float, t1: float) -> tuple[np.ndarray, np.ndarray]:
    a, b = int(t0 * sig.sig_rate), max(int(t0 * sig.sig_rate) + 1, int(np.ceil(t1 * sig.sig_rate)))
    return sig.sig_grid[a:b].astype(np.float32).mean(0), sig.sig_hist[a:b].astype(np.float32).mean(0)


def _drift(sig: Signals, t0: float, t1: float, rules: Rules) -> list[float]:
    """Where the picture has moved far enough from how a beat began for another to begin."""
    a, b = int(np.ceil(t0 * sig.sig_rate)), int(t1 * sig.sig_rate)
    if b - a < 2:
        return []
    grid, hist = sig.sig_grid[a:b].astype(np.float32), sig.sig_hist[a:b].astype(np.float32)
    out, ref = [], 0
    for j in range(1, len(grid)):
        if float(difference(grid[ref], hist[ref], grid[j], hist[j])) >= rules.drift_level:
            out.append((a + j) / sig.sig_rate)
            ref = j
    return out


def _between_words(t: float, words: list[tuple[float, float]], reach: float) -> float:
    """Move a boundary so that it does not fall inside a word: to the nearest silence within reach, else to the nearer end of the word."""
    inside = next(((a, b) for a, b in words if a < t < b), None)
    gaps = [((words[i][1] + words[i + 1][0]) / 2, words[i + 1][0] - words[i][1]) for i in range(len(words) - 1) if words[i + 1][0] - words[i][1] >= 0.15]
    near = [g for g in gaps if abs(g[0] - t) <= reach]
    if near:
        return max(near, key=lambda g: (g[1], -abs(g[0] - t)))[0]            # the longest pause within reach
    if inside:
        return inside[0] if t - inside[0] <= inside[1] - t else inside[1]
    return t


def _label(value, confidence: str = "high", **more) -> dict:
    return {"value": value, "source": "measured", "confidence": confidence, **more}


def _sure(measure: float, *levels: float) -> str:
    """A measure close to a level it is judged against could have fallen either side of it."""
    return "medium" if any(level and abs(measure - level) <= 0.3 * abs(level) for level in levels) else "high"


def _grade(measure: float, fair: float, poor: float) -> str:
    return "poor" if measure >= poor else "fair" if measure >= fair else "good"


WORST = {"good": 0, "fair": 1, "poor": 2}


def measure_beat(sig: Signals, t0: float, t1: float, *, words: list[tuple[float, float]] = (), source_rate: float | None = None, rules: Rules = Rules()) -> dict:
    """Everything about one beat that can be measured: how the camera moves, how steady, sharp and well exposed the picture is,
    whether anyone speaks, where the subject is and which way it goes."""
    a, b = int(round(t0 * sig.fps)), max(int(round(t0 * sig.fps)) + 1, int(round(t1 * sig.fps)))
    b = min(b, sig.frames)
    a = min(a, max(b - 1, 0))
    px, py, zoom = sig.pan_x[a:b], sig.pan_y[a:b], sig.zoom[a:b]
    vx, vy, grow = float(px.mean()), float(py.mean()), float(zoom.mean())
    second = max(1, round(sig.fps))
    jitter = float(np.sqrt(((px - _smooth(px, second)) ** 2 + (py - _smooth(py, second)) ** 2).mean()))
    travel = float(np.hypot(vx, vy))
    if abs(grow) >= rules.zoom_on and abs(grow) >= travel:
        camera, sure = ("push_in" if grow > 0 else "pull_out"), _sure(abs(grow), rules.zoom_on)
    elif travel >= rules.move_on:
        camera, sure = ("pan" if abs(vx) >= abs(vy) else "tilt"), _sure(travel, rules.move_on)
    elif jitter >= rules.shake_fair:
        camera, sure = "handheld", _sure(jitter, rules.shake_fair)
    else:
        camera, sure = "static", _sure(max(travel, 1e-6), rules.move_on)

    shake = _grade(jitter, rules.shake_fair, rules.shake_poor)
    burnt, crushed = float(sig.clip_hi[a:b].mean()), float(sig.clip_lo[a:b].mean())
    exposure = max(_grade(burnt, rules.burnt_fair, rules.burnt_poor), _grade(crushed, rules.crushed_fair, rules.crushed_poor), key=WORST.get)
    labels = {
        "camera": _label(camera, sure, speed=round(travel, 4), zoom=round(grow, 4)),
        "shake": _label(shake, _sure(jitter, rules.shake_fair, rules.shake_poor), measure=round(jitter, 4)),
        "exposure": _label(exposure, _sure(burnt, rules.burnt_fair, rules.burnt_poor), burnt=round(burnt, 3), crushed=round(crushed, 3),
                           **({"fault": "burnt" if _grade(burnt, rules.burnt_fair, rules.burnt_poor) != "good" else "dark"} if exposure != "good" else {})),
    }
    grades = [shake, exposure]
    if sig.blur_rate and len(sig.blur):
        ba, bb = int(t0 * sig.blur_rate), max(int(t0 * sig.blur_rate) + 1, int(np.ceil(t1 * sig.blur_rate)))
        blur = sig.blur[ba:bb]
        if len(blur):
            soft = float(np.median(blur))
            sharp = _grade(soft, rules.blur_fair, rules.blur_poor)
            labels["sharpness"] = _label(sharp, _sure(soft, rules.blur_fair, rules.blur_poor), measure=round(soft, 2))
            grades.append(sharp)
    quality = max(grades, key=WORST.get)
    labels["quality"] = _label(quality)
    labels["speech"] = _label(any(wa < t1 and wb > t0 for wa, wb in words))
    if source_rate:
        labels["speed"] = _label("slow_motion" if source_rate >= rules.slow_motion_rate else "normal")
    labels["still"] = _label(bool(float(sig.diff[a:b].mean()) < rules.still_level and float(sig.subject[a:b].mean()) < rules.subject_off))

    third = max(1, (b - a) // 3)
    cx, cy = sig.cx[a:b], sig.cy[a:b]
    went = float(cx[-third:].mean() - cx[:third].mean())
    if camera == "pan" and abs(vx) >= rules.move_on:
        direction, how_sure = ("left_to_right" if vx > 0 else "right_to_left"), "medium"          # a camera that follows goes the way its subject goes
    elif abs(went) >= rules.travel and float(sig.subject[a:b].mean()) >= rules.subject_off:
        direction, how_sure = ("left_to_right" if went > 0 else "right_to_left"), "medium"
    else:
        direction, how_sure = "unknown", "low"
    labels["direction"] = _label(direction, how_sure)
    labels["position"] = _label([round(float(cx.mean()), 3), round(float(cy.mean()), 3)], "medium")
    if quality == "poor":                          # what is measured on a picture this bad is itself in doubt
        for key in ("camera", "direction", "position"):
            labels[key]["confidence"] = "low"
    return labels


def pick_frames(sig: Signals, t0: float, t1: float, zones: list[tuple[float, float]] = ()) -> list[float]:
    """The instants of a beat to look at: its beginning, its end, and where the subject moves most. A beat with more going
    on gets more of them (three to eight). No instant is taken inside a dissolve, where two pictures are mixed."""
    length = t1 - t0
    inset = min(0.25, length / 4)
    a, b = int(round(t0 * sig.fps)), max(int(round(t0 * sig.fps)) + 1, min(int(round(t1 * sig.fps)), sig.frames))
    activity = float(sig.subject[a:b].mean()) if b > a else 0.0
    wanted = int(min(8, max(3, 3 + round(length / 4) + round(activity * 10))))
    times = [t0 + inset, t1 - inset]
    level = _smooth(sig.subject[a:b], max(1, round(sig.fps * 0.4)))
    spacing = max(0.5, length / (wanted + 1))
    for i in np.argsort(level)[::-1]:
        t = (a + int(i)) / sig.fps
        if len(times) >= wanted:
            break
        if t0 + inset < t < t1 - inset and all(abs(t - other) >= spacing for other in times):
            times.append(t)
    k = 1
    while len(times) < wanted and k <= wanted:              # nothing stands out: spread the rest evenly
        t = t0 + length * k / (wanted + 1)
        if all(abs(t - other) >= min(spacing, length / (wanted + 2)) for other in times):
            times.append(t)
        k += 1

    def clear(t: float) -> float:
        for za, zb in zones:
            if za <= t <= zb:
                return min(max(zb + 0.05 if t1 - zb > za - t0 else za - 0.05, t0), t1)
        return t

    return sorted({round(clear(t), 2) for t in times})


def _chunks(t0: float, t1: float, longest: float) -> list[float]:
    """Boundaries that cut a stretch with nothing to go by into even pieces, the last taking what is left over."""
    out, t = [], t0 + longest
    while t1 - t >= 0.5:
        out.append(t)
        t += longest
    return out


def _beats_of_shot(sig: Signals, s0: float, s1: float, *, words, pins_add: list[float], pins_remove: list[float], rules: Rules) -> list[tuple[float, bool]]:
    """The boundaries between the beats of one shot, each with whether the operator placed it."""
    least, most = min(rules.min_beat_seconds, rules.max_beat_seconds), rules.max_beat_seconds
    found: list[tuple[float, int]] = []
    if most >= 2 * least and s1 - s0 >= 2 * least:           # otherwise there is no room for a boundary the content chose
        a, b = int(round(s0 * sig.fps)), min(int(round(s1 * sig.fps)), sig.frames)
        hold = max(1, round(rules.settle_seconds * sig.fps))
        found += [(t, 0) for t in _drift(sig, s0, s1, rules)]
        if b - a > hold:
            speed = _smooth(np.maximum(np.hypot(sig.pan_x[a:b], sig.pan_y[a:b]), np.abs(sig.zoom[a:b]) * rules.move_on / rules.zoom_on), hold, np.median)
            found += [((a + i) / sig.fps, 1) for i in _switches(speed, rules.move_on, rules.move_off, hold)]
            found += [((a + i) / sig.fps, 2) for i in _switches(_smooth(sig.subject[a:b], hold), rules.subject_on, rules.subject_off, hold)]
    found = sorted((t, rank) for t, rank in found if s0 < t < s1)
    kept: list[tuple[float, int]] = []
    for t, rank in found:                                   # boundaries close together are one boundary: the better reason wins
        if kept and t - kept[-1][0] < rules.join_seconds:
            if rank < kept[-1][1]:
                kept[-1] = (t, rank)
            continue
        kept.append((t, rank))
    times = [_between_words(t, words, rules.speech_reach) if words else t for t, _ in kept]
    times = [t for t in times if s0 < t < s1 and not any(abs(t - r) <= 0.3 for r in pins_remove)]
    marks = sorted({round(t, 3): False for t in times}.items())
    marks = [(t, False) for t, _ in marks if not any(abs(t - p) < rules.join_seconds for p in pins_add)] + [(p, True) for p in pins_add if s0 < p < s1]
    marks.sort()

    def too_short(i: int, edges: list[float]) -> bool:
        return edges[i + 1] - edges[i] < least

    while True:                                             # a beat too short joins the neighbour it looks more like
        edges = [s0, *[t for t, _ in marks], s1]
        short = [i for i in range(len(edges) - 1) if too_short(i, edges)]
        short = [i for i in short if (i > 0 and not marks[i - 1][1]) or (i < len(marks) and not marks[i][1])]
        if not short or not marks:
            break
        i = min(short, key=lambda k: edges[k + 1] - edges[k])
        left = i > 0 and not marks[i - 1][1]
        right = i < len(marks) and not marks[i][1]
        if left and right:
            mine = _mean_signature(sig, edges[i], edges[i + 1])
            before, after = _mean_signature(sig, edges[i - 1], edges[i]), _mean_signature(sig, edges[i + 1], edges[i + 2])
            left = float(difference(*before, *mine)) <= float(difference(*mine, *after))
        marks.pop(i - 1 if left else i)
    edges = [s0, *[t for t, _ in marks], s1]
    for i in range(len(edges) - 1):                         # a beat too long with nothing to divide it is cut evenly
        if edges[i + 1] - edges[i] > most + 1e-6:
            even = [_between_words(t, words, rules.speech_reach) if words else t for t in _chunks(edges[i], edges[i + 1], most)]
            marks += [(t, False) for t in even if edges[i] < t < edges[i + 1]]
    return sorted(marks)


def build(sig: Signals, *, usable: list[list[float]], words: list[tuple[float, float]] = (), pinned: list[dict] = (), source_rate: float | None = None,
          rules: Rules = Rules()) -> dict:
    """The shots and beats of a recording. `usable` are the parts that are not black, in seconds; `words` are the spoken words
    as (start, end); `pinned` are the boundaries the operator placed or took away, which every later division keeps."""
    words = sorted((float(a), float(b)) for a, b in words)
    cut_frames = detect_cuts(sig.diff, sig.fps, rules)
    faint, blends = detect_changes(sig, cut_frames, rules)
    shortest = max(1, round(rules.min_shot_seconds * sig.fps))
    for frame in faint:                                        # a faint cut too close to a plain one is that cut seen twice
        if all(abs(frame - c) >= shortest for c in cut_frames):
            cut_frames = sorted([*cut_frames, frame])
    zones = [(a / sig.fps, b / sig.fps) for a, b in blends]
    removed = [float(p["t"]) for p in pinned if p.get("op") == "remove"]
    marks = {round(c / sig.fps, 3): "cut" for c in cut_frames}
    marks.update({round((a + b) / 2, 3): "dissolve" for a, b in zones})
    marks = {t: how for t, how in marks.items() if not any(abs(t - r) <= 0.3 for r in removed)}
    zones = [z for z in zones if not any(abs((z[0] + z[1]) / 2 - r) <= 0.3 for r in removed)]
    shot_pins = sorted(float(p["t"]) for p in pinned if p.get("op") == "add" and p.get("kind") == "shot")
    for p in shot_pins:
        marks = {t: how for t, how in marks.items() if abs(t - p) >= 0.3}
        marks[round(p, 3)] = "marked"
    beat_pins = sorted(float(p["t"]) for p in pinned if p.get("op") == "add" and p.get("kind") == "beat")

    shots, beats = [], []
    for n, (u0, u1) in enumerate(sorted(usable)):
        u0, u1 = float(u0), float(u1)
        if u1 - u0 <= 0 and not (u0 == 0 and u1 == 0):
            continue
        inside = sorted(t for t in marks if u0 + 0.1 < t < u1 - 0.1)
        edges = [u0, *inside, u1]
        for i in range(len(edges) - 1):
            s0, s1 = edges[i], edges[i + 1]
            how = marks[s0] if i else ("start" if n == 0 and u0 <= 0.05 else "black")
            shots.append({"start": to_ticks(s0), "end": to_ticks(s1), "transition_in": how, "pinned": how == "marked"})
            bounds = _beats_of_shot(sig, s0, s1, words=words, pins_add=beat_pins, pins_remove=removed, rules=rules) if s1 > s0 else []
            beat_edges = [(s0, how == "marked"), *bounds, (s1, False)]
            for j in range(len(beat_edges) - 1):
                b0, b1 = beat_edges[j][0], beat_edges[j + 1][0]
                beats.append({"start": to_ticks(b0), "end": to_ticks(b1), "shot": len(shots) - 1, "pinned": bool(beat_edges[j][1]),
                              "labels": measure_beat(sig, b0, b1, words=words, source_rate=source_rate, rules=rules) if sig.frames else {},
                              "frames": pick_frames(sig, b0, b1, zones) if sig.frames and b1 > b0 else [round(b0, 2)]})
    top, bottom, left, right = sig.bars
    bars = "top_bottom" if top + bottom >= 0.04 and top + bottom >= left + right else "sides" if left + right >= 0.04 else "none"
    return {"version": VERSION, "fps": round(sig.fps, 3), "shots": shots, "beats": beats,
            "transitions": [[to_ticks(a), to_ticks(b)] for a, b in zones],
            "bars": {"value": bars, "source": "measured", "confidence": "high", "shares": [top, bottom, left, right]},
            "rules": asdict(rules)}


def boundaries(structure: dict) -> dict[str, list[float]]:
    """Where a recording is divided, in seconds: between shots, and between beats (which includes between shots). The start
    of the footage and the far side of a stretch of black are edges, not divisions, and are left out."""
    shots = structure.get("shots", [])
    between_shots = sorted(to_seconds(s["start"], 2) for s in shots if s["transition_in"] in ("cut", "dissolve", "marked"))
    edges = {s["start"] for s in shots if s["transition_in"] in ("start", "black")}
    return {"shot": between_shots, "beat": sorted(to_seconds(b["start"], 2) for b in structure.get("beats", []) if b["start"] not in edges)}


def beat_seconds(structure: dict) -> list[tuple[float, float]]:
    return [(to_seconds(b["start"]), to_seconds(b["end"])) for b in structure.get("beats", [])]


def coverage_faults(structure: dict, usable: list[list[float]]) -> list[str]:
    """What breaks the rule that every usable second belongs to exactly one beat: gaps, overlaps, a beat that runs across two
    shots. An empty list means the rule holds."""
    faults = []
    beats = sorted(structure.get("beats", []), key=lambda b: b["start"])
    shots = structure.get("shots", [])
    for a, b in zip(beats, beats[1:]):
        if b["start"] < a["end"]:
            faults.append(f"beats overlap at {to_seconds(b['start'])}s")
    for beat in beats:
        shot = shots[beat["shot"]]
        if beat["start"] < shot["start"] or beat["end"] > shot["end"]:
            faults.append(f"the beat at {to_seconds(beat['start'])}s runs outside its shot")
    for u0, u1 in usable:
        inside = [b for b in beats if b["start"] >= to_ticks(u0) and b["end"] <= to_ticks(u1)]
        cursor = to_ticks(u0)
        for beat in inside:
            if beat["start"] != cursor:
                faults.append(f"a gap from {to_seconds(cursor)}s to {to_seconds(beat['start'])}s")
            cursor = beat["end"]
        if cursor != to_ticks(u1):
            faults.append(f"a gap from {to_seconds(cursor)}s to {u1}s")
    return faults
