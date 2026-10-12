"""What a music track is like, measured from its sound: tempo, liveliness, how soon it starts (design v4.0, section 19.6).

All of it comes from the loudness envelope the library already takes for syncing cameras. Tempo is the lag at which the
track's bursts of sound best repeat; it is an estimate, good to within a few beats for music with a clear pulse and
meaningless for music without one, which is why it comes with how sure the measurement is.
"""
import math

ENERGIES = ("êm", "vừa", "sôi động")


def analyse(envelope: list[float], rate: int) -> dict:
    """`envelope`: loudness `rate` times a second. Returns tempo (beats a minute, or None), pulse (0 to 1: how clearly it repeats),
    energy (one of ENERGIES), lead_in (seconds before the track is properly under way) and dynamics (0 to 1: how much it rises and falls)."""
    if len(envelope) < rate * 4:
        return {"tempo": None, "pulse": 0.0, "energy": ENERGIES[1], "lead_in": 0.0, "dynamics": 0.0}
    peak = max(envelope) or 1.0
    level = [v / peak for v in envelope]
    mean = sum(level) / len(level)
    # Onsets: moments where the sound gets louder. A pulse shows as onsets that repeat at one interval.
    onsets = [max(0.0, b - a) for a, b in zip(level, level[1:])]
    strength = sum(o * o for o in onsets) or 1e-9
    best, best_lag = 0.0, 0
    steady = max(onsets) < 0.15                       # a drone or a held chord never jumps in loudness: it has no beats, and any "tempo" would be noise
    for lag in [] if steady else range(int(rate * 60 / 180), int(rate * 60 / 60) + 1):              # 60 to 180 beats a minute
        score = sum(a * b for a, b in zip(onsets, onsets[lag:])) / strength
        if score > best:
            best, best_lag = score, lag
    # Liveliness is how often the sound jumps, not how loud it is: every track is brought to the same loudness in the mix anyway.
    busy = sum(1 for o in onsets if o > 0.15) / (len(onsets) / rate)                 # clear onsets a second
    energy = ENERGIES[0] if busy < 0.5 else ENERGIES[2] if busy > 2.5 else ENERGIES[1]
    start = next((i for i, v in enumerate(level) if v > 0.25 * mean + 0.05), 0)
    spread = math.sqrt(sum((v - mean) ** 2 for v in level) / len(level))
    return {"tempo": round(60 * rate / best_lag) if best_lag and best > 0.12 else None, "pulse": round(min(1.0, best), 2), "energy": energy,
            "lead_in": round(start / rate, 1), "dynamics": round(min(1.0, spread * 2), 2)}


def rank(tracks: list[dict], *, seconds: float, energy: str | None = None) -> list[dict]:
    """Order tracks for a cut `seconds` long. A track at least as long as the cut needs no loop; the operator's own rating counts;
    the liveliness asked for counts most when it is asked for."""
    out = []
    for track in tracks:
        long_enough = track["duration"] >= seconds
        points = (2 if long_enough else 0) + track.get("rating", 0) * 0.5 + (3 if energy and track.get("energy") == energy else 0) - (1 if track.get("lead_in", 0) > 3 else 0)
        why = [("dài hơn video nên không phải lặp" if long_enough else f"ngắn hơn video, sẽ lặp {math.ceil(seconds / max(track['duration'], 1))} lần"), f"nhịp {track['energy']}"]
        if track.get("tempo"):
            why.append(f"khoảng {track['tempo']} nhịp mỗi phút")
        if track.get("lead_in", 0) > 3:
            why.append(f"vào chậm, {track['lead_in']:.0f} giây đầu gần như im")
        if track.get("rating"):
            why.append(f"bạn chấm {track['rating']} sao")
        out.append({**track, "points": points, "why": ", ".join(why)})
    return sorted(out, key=lambda t: -t["points"])
