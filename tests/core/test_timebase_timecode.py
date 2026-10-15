"""SMPTE timecode, as an EDL writes it: drop-frame at 29.97 and 59.94, so that the clock keeps to real time."""
from nexora.core.timebase import frames_timecode, is_drop, timecode_frames

NTSC = 30000 / 1001


def test_drop_frame_skips_two_frame_numbers_a_minute_except_every_tenth():
    assert frames_timecode(timecode_frames("00:00:59;29", NTSC) + 1, NTSC) == "00:01:00;02"
    assert frames_timecode(timecode_frames("00:09:59;29", NTSC) + 1, NTSC) == "00:10:00;00"
    assert frames_timecode(timecode_frames("01:59:53;21", NTSC), NTSC) == "01:59:53;21"       # 0059's first frame


def test_whole_rates_count_every_frame():
    assert not is_drop(25) and not is_drop(30) and not is_drop(24000 / 1001) and is_drop(60000 / 1001)
    assert frames_timecode(timecode_frames("00:00:10:00", 25) + 13, 25) == "00:00:10:13"
