"""Two cameras, one event: the library finds how far apart they started."""
import random
import struct
import subprocess
import wave

import pytest

from nexora.app import build


def camera(path, sound, *, skip=0.0, seconds=14):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size=320x180:rate=25:duration={seconds}",
                    "-ss", str(skip), "-i", str(sound), "-shortest", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path)], check=True)
    return path


def room_sound(path, seed, seconds=20):
    """Irregular bursts of noise, like claps and speech: what two microphones in one room would both hear."""
    rng, frames, level = random.Random(seed), [], 0.0
    for i in range(8000 * seconds):
        if i % 800 == 0:
            level = rng.choice([0.0, 0.0, 0.2, 0.9])
        frames.append(struct.pack("<h", int(rng.uniform(-1, 1) * level * 20000)))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000); w.writeframes(b"".join(frames))
    return path


def test_two_recordings_of_one_event_are_lined_up_and_unrelated_ones_are_refused(tmp_path):
    system = build(tmp_path / "data")
    sound = room_sound(tmp_path / "room.wav", 1)
    ids = [system.library.ingest(p)[0] for p in (camera(tmp_path / "a.mp4", sound), camera(tmp_path / "b.mp4", sound, skip=3.2),
                                                 camera(tmp_path / "c.mp4", room_sound(tmp_path / "other.wav", 2)))]
    while system.worker.run_once():
        pass
    a, b, c = ids
    found = system.library.sync(a, b)
    assert found["offset"] == pytest.approx(-3.2, abs=0.08) and found["confidence"] > 0.6     # what A shows at 5.0 s, B shows at 1.8 s
    assert system.assets.original(b).metadata["angles"][a] == pytest.approx(3.2, abs=0.08)
    with pytest.raises(ValueError, match="not_alike"):
        system.library.sync(a, c)
    silent = system.library.ingest(subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25:duration=3",
                                                   "-pix_fmt", "yuv420p", str(tmp_path / "mute.mp4")], check=True) and None or tmp_path / "mute.mp4")[0]
    while system.worker.run_once():
        pass
    with pytest.raises(ValueError, match="no_audio"):
        system.library.sync(a, silent)
