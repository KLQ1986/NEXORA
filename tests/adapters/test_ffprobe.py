"""The FFprobe adapter against real files."""
import subprocess

import pytest

from nexora.adapters.media import FFprobeAdapter
from nexora.core.adapter import AdapterError, ErrorCode, Request


@pytest.fixture(scope="module")
def video(tmp_path_factory):
    path = tmp_path_factory.mktemp("media") / "clip.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25:duration=2",
                    "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


def test_probe_reads_the_properties_of_a_video(video):
    result = FFprobeAdapter().submit(Request("probe", inputs={"path": str(video)}))
    out = result.outputs
    assert out["width"] == 320 and out["height"] == 180
    assert out["duration"] == pytest.approx(2.0, abs=0.1)
    assert out["frame_rate"] == pytest.approx(25.0, abs=0.1)
    assert out["has_audio"] is False


def test_probe_reports_a_missing_file_as_missing_input(tmp_path):
    with pytest.raises(AdapterError) as err:
        FFprobeAdapter().submit(Request("probe", inputs={"path": str(tmp_path / "nope.mp4")}))
    assert err.value.code is ErrorCode.MISSING_INPUT


def test_probe_reports_a_file_that_is_not_media_as_invalid(tmp_path):
    junk = tmp_path / "junk.mp4"
    junk.write_text("this is not a video")
    with pytest.raises(AdapterError) as err:
        FFprobeAdapter().submit(Request("probe", inputs={"path": str(junk)}))
    assert err.value.code is ErrorCode.INVALID_REQUEST


def test_the_adapter_declares_itself_local():
    cap = FFprobeAdapter().describe()
    assert cap.runs == "local" and "probe" in cap.operations


def _make(path, *args):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args, str(path)], check=True)
    return path


def test_probe_reports_container_colour_streams_and_device(tmp_path):
    clip = _make(tmp_path / "talk.mov", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30:duration=1", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                 "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ac", "2", "-metadata:s:a:0", "language=vie",
                 "-movflags", "use_metadata_tags", "-metadata", "com.apple.quicktime.make=DJI", "-metadata", "com.apple.quicktime.model=OsmoAction6", "-shortest")
    out = FFprobeAdapter().submit(Request("probe", inputs={"path": str(clip)})).outputs
    assert out["container"].startswith("mov") and out["bit_rate"] > 0 and out["size"] == clip.stat().st_size
    assert out["pixel_format"] == "yuv420p" and out["bit_depth"] == 8 and out["hdr"] is False
    assert out["orientation"] == "ngang" and out["display_aspect"] == pytest.approx(16 / 9, abs=0.01)
    assert out["audio_streams"] == [{"codec": "aac", "channels": 2, "layout": "stereo", "sample_rate": 44100, "bit_rate": out["audio_streams"][0]["bit_rate"], "language": "vie"}]
    assert out["variable_frame_rate"] is False and out["rotation"] == 0
    assert out["device"] == "DJI OsmoAction6" and out["encoder"]


def test_probe_turns_a_phone_clip_recorded_on_its_side_upright(tmp_path):
    flat = _make(tmp_path / "flat.mp4", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25:duration=1", "-pix_fmt", "yuv420p")
    turned = _make(tmp_path / "turned.mp4", "-display_rotation", "90", "-i", str(flat), "-c", "copy")
    out = FFprobeAdapter().submit(Request("probe", inputs={"path": str(turned)})).outputs
    assert out["rotation"] in (90, 270)
    assert (out["display_width"], out["display_height"]) == (180, 320) and out["orientation"] == "dọc"


def test_bit_depth_is_read_from_the_pixel_format_when_the_stream_does_not_say():
    from nexora.adapters.media import _bit_depth
    assert _bit_depth({"pix_fmt": "yuv420p10le"}) == 10
    assert _bit_depth({"pix_fmt": "yuv420p"}) == 8
    assert _bit_depth({"bits_per_raw_sample": "12", "pix_fmt": "yuv420p"}) == 12


def test_variable_frame_rate_is_named_when_nominal_and_average_rates_disagree():
    from nexora.adapters.media import technical
    out = technical({"format": {}, "streams": []}, {"width": 1920, "height": 1080, "r_frame_rate": "60/1", "avg_frame_rate": "2997/100"})
    assert out["variable_frame_rate"] is True and out["nominal_frame_rate"] == 60.0
