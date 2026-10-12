from pathlib import Path
import subprocess

import pytest


def make_video(path, *, picture=2, black=0, size="320x180", rate=25):
    """A test clip: `picture` seconds of moving test pattern followed by `black` seconds of black."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    inputs = ["-f", "lavfi", "-i", f"testsrc2=size={size}:rate={rate}:duration={picture}"]
    graph = "[0:v]null[v]"
    if black:
        inputs += ["-f", "lavfi", "-i", f"color=c=black:size={size}:rate={rate}:duration={black}"]
        graph = "[0:v][1:v]concat=n=2:v=1[v]"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *inputs, "-filter_complex", graph, "-map", "[v]",
                    "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


@pytest.fixture(scope="session")
def clip_with_black_tail(tmp_path_factory):
    return make_video(tmp_path_factory.mktemp("footage") / "tail.mp4", picture=2, black=2)


@pytest.fixture(scope="session")
def plain_clip(tmp_path_factory):
    return make_video(tmp_path_factory.mktemp("footage2") / "plain.mp4", picture=2)
