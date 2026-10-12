"""HDR footage is brought to SDR wherever it is read: the proxy, the frames the model sees, the thumbnail and the cut."""
import subprocess

import pytest
from PIL import Image, ImageStat

from nexora.adapters.media import FULL_BUILDS, FFmpegAdapter, FFprobeAdapter, find_ffmpeg
from nexora.app import build
from nexora.core.adapter import AdapterError, ErrorCode, Request

from tests.fakes import FakeModel, FakeVoice

FULL = find_ffmpeg()
needs_full = pytest.mark.skipif(FULL not in FULL_BUILDS, reason="needs an FFmpeg build with zscale (brew install ffmpeg-full)")


PATTERN = "testsrc2=size=640x360:rate=25"


def hdr_clip(path, seconds=4):
    """A test pattern truly converted to HDR10 (ten bits, BT.2020 primaries, PQ curve), as a camera would record it."""
    to_hdr = "zscale=tin=bt709:min=bt709:pin=bt709:rin=tv:t=smpte2084:m=bt2020nc:p=bt2020:r=tv:npl=100,format=yuv420p10le"
    subprocess.run([FULL, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"{PATTERN}:duration={seconds}", "-vf", to_hdr,
                    "-c:v", "libx265", "-x265-params", "colorprim=bt2020:transfer=smpte2084:colormatrix=bt2020nc:log-level=error", "-tag:v", "hvc1", str(path)], check=True)
    return path


def distance(a, b) -> float:
    """How far two pictures are apart: the mean difference per channel, 0 to 255."""
    from PIL import ImageChops
    one, two = Image.open(a).convert("RGB"), Image.open(b).convert("RGB").resize(Image.open(a).size)
    return sum(ImageStat.Stat(ImageChops.difference(one, two)).mean) / 3


@needs_full
def test_an_hdr_clip_is_recognised_and_its_frames_come_out_in_sdr_with_their_colour(tmp_path):
    clip = hdr_clip(tmp_path / "hdr.mov")
    probe = FFprobeAdapter().submit(Request("probe", inputs={"path": str(clip)})).outputs
    assert probe["color_transfer"] == "smpte2084"
    adapter = FFmpegAdapter()
    subprocess.run([FULL, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"{PATTERN}:duration=2", "-ss", "1", "-frames:v", "1", str(tmp_path / "truth.jpg")], check=True)
    adapter.submit(Request("thumbnail", inputs={"path": str(clip)}, params={"out": str(tmp_path / "plain.jpg"), "at": 1.0}))
    adapter.submit(Request("thumbnail", inputs={"path": str(clip)}, params={"out": str(tmp_path / "sdr.jpg"), "at": 1.0, "color_transfer": "smpte2084"}))
    converted, unconverted = distance(tmp_path / "truth.jpg", tmp_path / "sdr.jpg"), distance(tmp_path / "truth.jpg", tmp_path / "plain.jpg")
    assert converted < unconverted * 0.7        # converted, the picture is close to what was shot; read as if it were SDR, it is far from it
    adapter.submit(Request("proxy", inputs={"path": str(clip)}, params={"out": str(tmp_path / "proxy.mp4"), "color_transfer": "smpte2084"}))
    made = FFprobeAdapter().submit(Request("probe", inputs={"path": str(tmp_path / "proxy.mp4")})).outputs
    assert made["color_transfer"] != "smpte2084" and made["height"] == 360


@needs_full
def test_hdr_footage_goes_through_ingest_and_into_a_cut(tmp_path):
    system = build(tmp_path / "data", model=FakeModel(), voice=FakeVoice(), segment_seconds=2.0, judge=False)
    asset, _ = system.library.ingest(hdr_clip(tmp_path / "hdr.mov", seconds=8))
    while system.worker.run_once():
        pass
    assert system.assets.original(asset).metadata["probe"]["color_transfer"] == "smpte2084" and system.index.moments(asset, level="segment")
    project = system.planning.create_project("HDR")
    script = system.planning.save_script(project, ["chợ rau củ"])
    run = system.sourcing.start_match(script)
    while system.worker.run_once():
        pass
    system.sourcing.approve(run)
    system.edit.start_render(script)
    while system.worker.run_once():
        pass
    render = system.projects.renders(project)[0]
    assert render["qc"]["passed"] and FFprobeAdapter().submit(Request("probe", inputs={"path": render["path"]})).outputs["color_transfer"] != "smpte2084"


def test_a_build_without_the_filters_says_it_cannot_convert_hdr_instead_of_making_a_grey_picture(tmp_path, plain_clip):
    adapter = FFmpegAdapter("ffmpeg")
    adapter._can_tonemap = False                     # as on a machine with only the ordinary build
    with pytest.raises(AdapterError) as refused:
        adapter.submit(Request("thumbnail", inputs={"path": str(plain_clip)}, params={"out": str(tmp_path / "t.jpg"), "color_transfer": "arib-std-b67"}))
    assert refused.value.code is ErrorCode.UNAVAILABLE and not refused.value.retryable and "ffmpeg-full" in refused.value.message
    adapter.submit(Request("thumbnail", inputs={"path": str(plain_clip)}, params={"out": str(tmp_path / "t.jpg"), "color_transfer": "bt709"}))      # SDR footage is untouched
