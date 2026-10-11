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
