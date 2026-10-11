"""The FFmpeg adapter against real files."""
import pytest

from nexora.adapters.media import FFmpegAdapter, FFprobeAdapter, ffmpeg_capabilities
from nexora.core.adapter import AdapterError, ErrorCode, Request


def test_blackdetect_finds_the_black_tail(clip_with_black_tail):
    out = FFmpegAdapter().submit(Request("blackdetect", inputs={"path": str(clip_with_black_tail)})).outputs
    assert len(out["black_ranges"]) == 1
    start, end = out["black_ranges"][0]
    assert start == pytest.approx(2.0, abs=0.2) and end == pytest.approx(4.0, abs=0.2)


def test_blackdetect_finds_nothing_in_a_normal_clip(plain_clip):
    assert FFmpegAdapter().submit(Request("blackdetect", inputs={"path": str(plain_clip)})).outputs["black_ranges"] == []


def test_proxy_is_written_atomically_at_the_requested_height(plain_clip, tmp_path):
    out = tmp_path / "proxy.mp4"
    result = FFmpegAdapter().submit(Request("proxy", inputs={"path": str(plain_clip)}, params={"out": str(out), "max_height": 90}))
    assert result.files == (str(out),) and out.is_file()
    assert not list(tmp_path.glob("*.partial*"))
    probe = FFprobeAdapter().submit(Request("probe", inputs={"path": str(out)})).outputs
    assert probe["height"] == 90 and probe["duration"] == pytest.approx(2.0, abs=0.2)


def test_thumbnail_is_taken_at_the_requested_time(plain_clip, tmp_path):
    out = tmp_path / "t.jpg"
    FFmpegAdapter().submit(Request("thumbnail", inputs={"path": str(plain_clip)}, params={"out": str(out), "at": 1.0}))
    assert out.stat().st_size > 500


def test_a_missing_input_is_reported(tmp_path):
    with pytest.raises(AdapterError) as err:
        FFmpegAdapter().submit(Request("blackdetect", inputs={"path": str(tmp_path / "no.mp4")}))
    assert err.value.code is ErrorCode.MISSING_INPUT


def test_capabilities_report_which_filters_this_build_has():
    caps = ffmpeg_capabilities()
    assert caps["filters"]["blackdetect"] is True and caps["filters"]["scale"] is True
    assert isinstance(caps["filters"]["zscale"], bool)


def test_freezedetect_reports_a_frozen_stretch(tmp_path):
    import subprocess
    src = tmp_path / "frozen.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25:duration=2",
                    "-vf", "tpad=stop_mode=clone:stop_duration=3", "-pix_fmt", "yuv420p", str(src)], check=True)
    out = FFmpegAdapter().submit(Request("freezedetect", inputs={"path": str(src)})).outputs
    assert len(out["frozen_ranges"]) == 1 and out["frozen_ranges"][0][0] == pytest.approx(2.0, abs=0.3)


def test_proxy_bitrate_is_modest(plain_clip, tmp_path):
    out = tmp_path / "p.mp4"
    FFmpegAdapter().submit(Request("proxy", inputs={"path": str(plain_clip)}, params={"out": str(out)}))
    assert out.stat().st_size < 2 * 1_500_000 / 8 * 1.5          # two seconds at well under 1.5 Mbit/s plus overhead


def test_concat_works_when_segments_are_given_as_relative_paths(plain_clip, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for name in ("a.mp4", "b.mp4"):
        FFmpegAdapter().submit(Request("segment", inputs={"path": str(plain_clip)}, params={"out": name, "duration": 2.0}))
    out = FFmpegAdapter().submit(Request("concat", inputs={"paths": ["a.mp4", "b.mp4"]}, params={"out": "final.mp4"}))
    probe = FFprobeAdapter().submit(Request("probe", inputs={"path": "final.mp4"})).outputs
    assert probe["duration"] == pytest.approx(4.0, abs=0.3) and probe["has_audio"]
