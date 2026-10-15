"""The report on how well the footage serves a script: each line, each recording, and how much of the script has a picture."""
from fastapi.testclient import TestClient

from nexora.api.app import create_app
from nexora.app import build
from nexora.modules.sourcing.report import line_grade, why_chosen

from tests.conftest import make_video
from tests.fakes import FakeModel, FakeVoice


def drain(system):
    while system.worker.run_once():
        pass


def test_a_line_is_good_when_its_frames_show_it_and_short_of_that_when_they_show_it_less_well_or_are_faulty():
    assert line_grade("gap", None, None) == "thiếu"
    assert line_grade("proposed", 9, "dùng được") == "tốt"
    assert line_grade("proposed", 6, "dùng được") == "tạm"
    assert line_grade("proposed", 9, "lỗi") == "tạm"                 # shown well, but the picture is shaky or burnt
    assert line_grade("accepted", 6, "dùng được") == "tốt"           # the operator's word
    assert why_chosen("Thấy rõ thuyền thúng. (9/10). Khớp place ngoài trời (measured). Một bãi biển... Thấy: cát.") == \
        "Thấy rõ thuyền thúng. (9/10). Khớp place ngoài trời (measured)."
    assert why_chosen("Một bãi biển với cát. Thấy: cát.") == "Một bãi biển với cát. Thấy: cát."


def test_the_report_tells_what_each_line_got_what_each_recording_serves_and_how_much_has_a_picture(tmp_path):
    system = build(tmp_path / "data", model=FakeModel(), voice=FakeVoice(), segment_seconds=2.0, judge=True)
    client = TestClient(create_app(system))
    system.library.ingest(make_video(tmp_path / "a.mp4", picture=6))
    drain(system)
    words = system.index.moments(system.assets.assets()[0]["asset_id"], level="segment")[0].text.lower().replace(".", "").replace(":", "")
    found_line = " ".join(words.split()[:4])                        # a line the footage shows, in its own words
    pid = client.post("/api/v1/projects", json={"title": "Thử", "lines": [found_line, "tên lửa phóng lên quỹ đạo"]}).json()["project_id"]
    client.post(f"/api/v1/projects/{pid}/match")
    drain(system)

    made = client.get(f"/api/v1/projects/{pid}/match/report").json()
    first, second = made["lines"]
    assert first["found"]["name"] == "a.mp4" and first["judge"] == 9 and first["grade"] == "tốt"
    assert second["grade"] == "thiếu" and second["found"] is None
    assert made["totals"]["lines"] == 2 and made["totals"]["tốt"] == 1 and made["totals"]["thiếu"] == 1
    assert 0 < made["totals"]["coverage"] < 1 and made["totals"]["judge_mean"] == 9
    assert made["clips"][0]["name"] == "a.mp4" and made["clips"][0]["lines"] == [1] and made["unused"] == []

    page = client.get(f"/api/v1/projects/{pid}/match/report", params={"format": "md"}).text
    assert page.startswith("# Báo cáo ghép nguyên liệu: Thử") and "1 tốt, 0 tạm, 1 thiếu" in page and "## Theo clip" in page
    assert "Chưa có hình trong kho cho câu này." in page
