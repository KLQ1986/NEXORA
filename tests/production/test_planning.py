"""Planning: sources read from the web, fact checks, critique and revision, the opportunity radar, the editorial calendar."""
import http.server
import threading

import pytest
from fastapi.testclient import TestClient

from nexora.adapters.web import WebReader, read_html
from nexora.api.app import create_app
from nexora.app import build
from nexora.core.adapter import AdapterError, PrivacyClass, Request
from nexora.modules.quality.review import review_cut

from tests.conftest import make_video
from tests.fakes import FakeModel, FakeVoice, FakeWeb
from tests.production.test_agent import settle

PAGE = {"title": "Chợ Bến Thành", "publisher": "Báo Thử", "date": "2024-03-01",
        "text": "Chợ Bến Thành được xây dựng xong vào năm 1914. Chợ có bốn cửa chính nhìn ra bốn hướng."}
URL = "https://example.test/cho-ben-thanh"


def make(tmp_path, **more):
    model = FakeModel()
    system = build(tmp_path / "data", model=model, voice=FakeVoice(), segment_seconds=2.0, web=FakeWeb({URL: PAGE}), **more)
    return system, model


def test_a_page_is_read_into_plain_text_with_who_published_it_and_when():
    page = read_html("""<html><head><title>Tiêu đề trang</title><meta property="og:site_name" content="Báo Thử">
        <meta property="article:published_time" content="2024-03-01T08:00:00+07:00"><style>p{color:red}</style></head>
        <body><nav>Trang chủ Thời sự Thể thao và một dãy liên kết dài để điều hướng</nav>
        <p>Chợ Bến Thành được xây dựng xong vào năm 1914, theo tài liệu lưu trữ.</p><script>var x = "không phải nội dung của bài viết này";</script></body></html>""")
    assert (page["title"], page["publisher"], page["date"]) == ("Tiêu đề trang", "Báo Thử", "2024-03-01")
    assert page["text"] == "Chợ Bến Thành được xây dựng xong vào năm 1914, theo tài liệu lưu trữ."


def test_the_web_reader_fetches_a_real_page_and_refuses_what_is_not_a_web_address(tmp_path):
    (tmp_path / "bai.html").write_text("<title>Bài</title><p>Một đoạn văn đủ dài để được coi là nội dung của trang này.</p>", encoding="utf-8")
    handler = lambda *a: http.server.SimpleHTTPRequestHandler(*a, directory=str(tmp_path))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        local = f"http://127.0.0.1:{server.server_port}/bai.html"
        out = WebReader(public_only=False).submit(Request("read", inputs={"url": local})).outputs
        assert out["title"] == "Bài" and "đoạn văn đủ dài" in out["text"] and out["publisher"].startswith("127.0.0.1")
        with pytest.raises(AdapterError):
            WebReader(public_only=False).submit(Request("read", inputs={"url": f"http://127.0.0.1:{server.server_port}/missing.html"}))
        # As installed, the reader keeps to the public web: this machine, the local network and addresses carrying a password are refused.
        for inside in (local, "http://localhost/", "http://192.168.1.1/", "http://169.254.169.254/latest/meta-data/", "http://[::1]/", "http://user:pw@example.com/"):
            with pytest.raises(AdapterError) as refused:
                WebReader().submit(Request("read", inputs={"url": inside}))
            assert refused.value.code.value == "invalid_request"
    finally:
        server.shutdown()
    with pytest.raises(AdapterError):
        WebReader().submit(Request("read", inputs={"url": "file:///etc/passwd"}))


def test_a_factual_line_is_checked_against_the_sources_and_a_quote_not_in_the_source_counts_for_nothing(tmp_path):
    system, model = make(tmp_path)
    project = system.planning.create_project("Chợ Bến Thành")
    system.planning.save_script(project, ["Chợ Bến Thành xây xong năm 1914.", "Chợ có sáu cửa chính.", "Chợ mở từ năm 1800.", "Buổi sáng ở chợ thật đông vui."])
    assert system.planning.read_source(project, URL)["publisher"] == "Báo Thử"
    assert system.planning.read_source(project, URL) and len(system.planning.research(project)) == 1      # reading it again replaces it

    model.answers["facts"] = {"du_kien": [1, 2, 3, 99, "x"]}
    assert len(system.planning.find_facts(project)) == 3
    def check(request):
        line = request.params["prompt"].split('"')[1]
        if "1914" in line:
            return {"ket_luan": "dung", "nguon": 1, "trich": "xây dựng xong vào năm 1914", "giai_thich": "Nguồn nêu đúng năm."}
        if "sáu cửa" in line:
            return {"ket_luan": "sai", "nguon": 1, "trich": "Chợ có bốn cửa chính", "giai_thich": "Nguồn nói bốn cửa."}
        return {"ket_luan": "dung", "nguon": 1, "trich": "chợ mở từ năm 1800", "giai_thich": "Tự tin nhưng không có trong nguồn."}
    model.answers["check"] = check
    results = system.planning.check_facts(project)
    assert [r["verdict"] for r in results] == ["supported", "contradicted", "not_found"]
    shots = system.projects.current_script(project)["shots"]
    assert shots[0].source == "Chợ Bến Thành" and shots[1].source is None and shots[2].fact_check["quote"] == "" and shots[3].fact_check is None

    # The verdicts follow the lines into the next version of the script, and reach the review of a cut.
    system.planning.save_script(project, [s.text for s in shots])
    carried = system.projects.current_script(project)["shots"]
    assert carried[1].fact_check["verdict"] == "contradicted"
    cut = [{"text": s.text, "duration": 3.0, "gap": False, "asset_id": f"a{i}", "t_in": 0.0, "is_fact": s.is_fact, "source": s.source, "fact_check": s.fact_check} for i, s in enumerate(carried)]
    found = [(f["shot"], f["text"]) for f in review_cut(cut) if f["check"] == "Dữ kiện"]
    assert [n for n, _ in found] == [2, 3] and "trái với nguồn" in found[0][1] and "chưa gắn nguồn" in found[1][1]


def test_privacy_mode_keeps_the_researcher_off_the_web(tmp_path):
    system, _ = make(tmp_path)
    project = system.planning.create_project("Riêng tư")
    system.orch.set_setting("privacy_local_only", "1")
    with pytest.raises(AdapterError):
        system.planning.read_source(project, URL)
    assert system.planning.research(project) == []


def test_a_critique_is_kept_with_its_version_and_the_revision_is_the_next_version(tmp_path):
    system, model = make(tmp_path)
    project = system.planning.create_project("Buổi sáng ở chợ")
    system.planning.save_script(project, ["# Mở đầu", "Hôm nay chúng ta sẽ cùng nhau đi thăm một khu chợ.", "# Trong chợ", "Cá tươi nằm trên sạp."])
    model.answers["critique"] = {"nhan_xet": [{"cau": 1, "van_de": "Mở đầu chậm.", "de_xuat": "Vào thẳng hình ảnh."}, {"cau": 9, "van_de": "Kết chưa rõ.", "de_xuat": "Thêm một câu kết."}, {"cau": 2}, {"cau": 0, "van_de": "Cá tươi nằm trên sạp.", "de_xuat": "Cá nằm trên sạp."}]}
    notes = system.planning.critique(project)
    assert notes == [{"line": 1, "issue": "Mở đầu chậm.", "fix": "Vào thẳng hình ảnh."}, {"line": 0, "issue": "Kết chưa rõ.", "fix": "Thêm một câu kết."}]
    first = system.projects.current_script(project)
    assert first["critique"] == notes
    model.answers["revise"] = {"cau": ["Năm giờ sáng, chợ đã sáng đèn.", "Cá tươi nằm trên sạp."]}
    system.planning.revise(project)
    second = system.projects.current_script(project)
    assert second["version"] == first["version"] + 1 and second["critique"] is None
    assert [(s.scene, s.text) for s in second["shots"]] == [("Mở đầu", "Năm giờ sáng, chợ đã sáng đèn."), ("Trong chợ", "Cá tươi nằm trên sạp.")]
    assert system.planning.revise(project) is None                # nothing to answer on a version nobody has criticised


def test_the_producer_hears_the_critic_once_reads_the_named_pages_and_checks_the_facts(tmp_path):
    system, model = make(tmp_path)
    model.script = ["cá tươi trên sạp", "chợ rau củ xây năm 1914"]
    system.library.ingest(make_video(tmp_path / "footage.mp4", picture=20))
    while system.worker.run_once():
        pass
    model.answers["critique"] = {"nhan_xet": [{"cau": 2, "van_de": "Câu hai khó đọc.", "de_xuat": "Viết ngắn lại."}]}       # the critic never runs out of things to say
    model.answers["revise"] = {"cau": ["cá tươi trên sạp", "chợ rau củ xây xong năm 1914"]}
    model.answers["facts"] = {"du_kien": [2]}
    model.answers["check"] = {"ket_luan": "dung", "nguon": 1, "trich": "xây dựng xong vào năm 1914", "giai_thich": ""}
    task_id = system.producer.start("một buổi sáng ở chợ", urls=[URL, "https://example.test/khong-co"], use_stock=False)
    settle(system)
    task = system.producer.task(task_id)
    roles = [e["role"] for e in task["log"]]
    assert roles[:8] == ["Điều phối", "Nghiên cứu", "Nghiên cứu", "Nghiên cứu", "Biên kịch", "Phản biện", "Biên kịch", "Kiểm chứng"]
    assert "Không đọc được" in task["log"][2]["text"] and task["options"]["revisions"] == 1 and roles.count("Phản biện") == 1
    script = system.projects.current_script(task["project_id"])
    assert script["version"] == 2 and script["shots"][1].source == "Chợ Bến Thành" and task["step"] == "review"


def test_a_task_that_keeps_moving_without_finishing_is_stopped(tmp_path, monkeypatch):
    system, model = make(tmp_path)
    task_id = system.producer.start("việc không bao giờ xong")
    monkeypatch.setattr(system.producer, "advance", lambda task_id: True)
    for _ in range(60):
        system.producer.tick()
    task = system.producer.task(task_id)
    assert task["status"] == "failed" and "quá 40 bước" in task["log"][-1]["text"]


def test_the_radar_measures_unused_footage_and_how_well_the_library_answers_a_topic(tmp_path):
    system, model = make(tmp_path)
    used, _ = system.library.ingest(make_video(tmp_path / "a.mp4", picture=12))
    spare, _ = system.library.ingest(make_video(tmp_path / "b.mp4", picture=8, size="322x180"))
    while system.worker.run_once():
        pass
    project = system.planning.create_project("Chợ")
    script = system.planning.save_script(project, ["cá tươi trên sạp"])
    shot = system.projects.script(script)["shots"][0]
    system.projects.set_selection(shot.shot_id, status="accepted", asset_id=used, t_in=0.0, t_out=2.0)
    radar = system.planning.radar(["cá tươi trên sạp", "tên lửa phóng lên quỹ đạo"])
    # The fake model's topic ("thử nghiệm") appears in no described beat, so a grounded summary drops it.
    assert [(s["subject"], s["videos"], s["unused_videos"]) for s in radar["subjects"]] == [("chưa rõ chủ đề", 2, 1)]
    assert radar["unused"][0]["examples"][0]["asset_id"] == spare and radar["unused"][0]["unused_seconds"] == pytest.approx(8, abs=1)
    fish, rocket = radar["watched"]
    assert fish["moments"] >= 1 and fish["verdict"] != "chưa có hình" and (rocket["moments"], rocket["verdict"]) == (0, "chưa có hình")


def test_sources_facts_critique_radar_and_the_calendar_are_reachable_through_the_api(tmp_path):
    system, model = make(tmp_path)
    client = TestClient(create_app(system))
    project = client.post("/api/v1/projects", json={"title": "Chợ Bến Thành", "lines": ["Chợ Bến Thành xây xong năm 1914.", "Chợ rất đông."]}).json()["project_id"]
    assert client.post(f"/api/v1/projects/{project}/sources/read", json={"url": "javascript:alert(1)"}).status_code == 422
    assert client.post(f"/api/v1/projects/{project}/sources/read", json={"url": "https://example.test/khong-co"}).status_code == 422
    view = client.post(f"/api/v1/projects/{project}/sources/read", json={"url": URL}).json()
    assert view["research"][0]["title"] == "Chợ Bến Thành" and "1914" in view["research"][0]["passage"]
    model.answers["facts"] = {"du_kien": [1]}
    model.answers["check"] = {"ket_luan": "dung", "nguon": 1, "trich": "xây dựng xong vào năm 1914", "giai_thich": "Khớp."}
    assert client.post(f"/api/v1/projects/{project}/facts/find").json()["found"] == 1
    view = client.post(f"/api/v1/projects/{project}/facts/check").json()
    assert view["shots"][0]["fact_check"]["verdict"] == "supported" and view["shots"][0]["source"] == "Chợ Bến Thành"
    model.answers["critique"] = {"nhan_xet": [{"cau": 2, "van_de": "Câu hai mơ hồ.", "de_xuat": "Nói rõ đông lúc nào."}]}
    assert client.post(f"/api/v1/projects/{project}/critique").json()["script"]["critique"][0]["line"] == 2
    model.answers["revise"] = {"cau": ["Chợ Bến Thành xây xong năm 1914.", "Sáu giờ sáng chợ đã kín người."]}
    revised = client.post(f"/api/v1/projects/{project}/revise").json()
    assert revised["revised"] and revised["script"]["version"] == 2 and revised["shots"][0]["fact_check"]["verdict"] == "supported"

    system.orch.set_setting("privacy_local_only", "1")
    assert client.post(f"/api/v1/projects/{project}/sources/read", json={"url": URL}).status_code == 409
    system.orch.set_setting("privacy_local_only", "0")

    assert client.patch(f"/api/v1/projects/{project}", json={"due_date": "20/10/2026"}).status_code == 422
    client.patch(f"/api/v1/projects/{project}", json={"due_date": "2026-10-20"})
    row = client.get("/api/v1/calendar").json()["projects"][0]
    assert (row["due_date"], row["stage"], row["ready"]) == ("2026-10-20", "Có kịch bản", False)
    radar = client.post("/api/v1/radar/topics", json={"topics": ["chợ", "chợ", " "]}).json()
    assert radar["topics"] == ["chợ"] and radar["watched"][0]["verdict"] == "chưa có hình" and client.get("/api/v1/radar").json()["topics"] == ["chợ"]


def test_sources_are_found_by_subject_read_in_and_a_page_that_cannot_be_read_is_passed_over(tmp_path):
    system, model = make(tmp_path)
    client = TestClient(create_app(system))
    project = client.post("/api/v1/projects", json={"title": "Chợ Bến Thành", "lines": ["Chợ Bến Thành xây xong năm 1914."]}).json()["project_id"]
    view = client.post(f"/api/v1/projects/{project}/sources/find", json={}).json()
    assert view["found"] == 1 and [s["title"] for s in view["research"]] == ["Chợ Bến Thành"]         # the broken page in the results was skipped
    assert client.post(f"/api/v1/projects/{project}/sources/find", json={"query": "không liên quan gì"}).json()["found"] == 0
    system.orch.set_setting("privacy_local_only", "1")
    assert client.post(f"/api/v1/projects/{project}/sources/find", json={}).status_code == 409
    system.orch.set_setting("privacy_local_only", "0")

    model.script = ["cá tươi trên sạp"]
    system.library.ingest(make_video(tmp_path / "footage.mp4", picture=8))
    while system.worker.run_once():
        pass
    task_id = system.producer.start("Chợ Bến Thành buổi sáng", find_sources=True, use_stock=False)
    settle(system)
    log = system.producer.task(task_id)["log"]
    assert "Tự tìm và đọc “Chợ Bến Thành”" in log[1]["text"] and log[2]["text"] == "Có 1 nguồn để đối chiếu dữ kiện."


def test_the_encyclopedia_search_asks_in_vietnamese_first_and_builds_addresses_that_can_be_read(tmp_path):
    import json as js
    asked = []

    class Wiki(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            asked.append(self.path)
            body = {"query": {"search": [{"title": "Chợ Bến Thành", "snippet": "Một <span class=\"searchmatch\">ngôi chợ</span> ở Sài Gòn"}]}}
            self.send_response(200); self.send_header("content-type", "application/json"); self.end_headers(); self.wfile.write(js.dumps(body).encode())
        def log_message(self, *a): pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Wiki)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        reader = WebReader(public_only=False, wiki=f"http://127.0.0.1:{server.server_port}/{{language}}")
        results = reader.submit(Request("search", inputs={"query": "chợ Bến Thành"}, params={"limit": 2})).outputs["results"]
        assert [r["language"] for r in results] == ["vi", "en"] and results[0]["snippet"] == "Một ngôi chợ ở Sài Gòn"
        assert results[0]["url"].endswith("/vi/wiki/Ch%E1%BB%A3_B%E1%BA%BFn_Th%C3%A0nh") and "srsearch=ch" in asked[0] and asked[0].startswith("/vi/w/api.php")
        with pytest.raises(AdapterError):
            reader.submit(Request("search", inputs={"query": " "}))
    finally:
        server.shutdown()


def test_channels_have_a_cadence_and_the_calendar_says_which_weeks_fall_short(tmp_path):
    import datetime
    system, _ = make(tmp_path)
    client = TestClient(create_app(system))
    saved = client.post("/api/v1/channels", json={"channels": [{"name": "Bếp nhà", "platform": "YouTube", "audience": "người thích nấu ăn", "per_week": 2, "template": "Video dọc ngắn"},
                                                               {"name": "Bếp nhà", "per_week": 5}, {"name": " "}, {"name": "Du lịch", "per_week": "nhiều", "template": "không có"}]}).json()["channels"]
    assert [(c["name"], c["per_week"], c["template"]) for c in saved] == [("Bếp nhà", 2, "Video dọc ngắn"), ("Du lịch", 0, None)]
    monday = datetime.date.today() - datetime.timedelta(days=datetime.date.today().weekday())
    ids = [client.post("/api/v1/projects", json={"title": t}).json()["project_id"] for t in ("Phở", "Bún chả", "Cao lầu")]
    client.patch(f"/api/v1/projects/{ids[0]}", json={"channel": "Bếp nhà", "due_date": (monday + datetime.timedelta(days=1)).isoformat()})
    client.patch(f"/api/v1/projects/{ids[1]}", json={"channel": "Bếp nhà", "due_date": (monday + datetime.timedelta(days=3)).isoformat()})
    client.patch(f"/api/v1/projects/{ids[2]}", json={"channel": "Bếp nhà", "due_date": (monday + datetime.timedelta(days=8)).isoformat()})
    assert client.patch(f"/api/v1/projects/{ids[2]}", json={"channel": "Kênh lạ"}).json()["channel"] is None and client.patch(f"/api/v1/projects/{ids[2]}", json={"channel": "Bếp nhà"}).json()["channel"] == "Bếp nhà"
    calendar = client.get("/api/v1/calendar").json()
    kitchen = calendar["cadence"][0]
    assert len(calendar["cadence"]) == 1 and kitchen["channel"] == "Bếp nhà"                    # a channel without a cadence promises nothing
    assert [(w["planned"], w["short"]) for w in kitchen["weeks"]] == [(2, 0), (1, 1), (0, 2), (0, 2)] and kitchen["short"] == 5
    assert {p["title"]: p["channel"] for p in calendar["projects"]} == {"Phở": "Bếp nhà", "Bún chả": "Bếp nhà", "Cao lầu": "Bếp nhà"}


def test_pieces_of_one_recording_heard_with_their_own_sound_are_not_one_picture_twice():
    talk = [{"text": "Đây là khu vui chơi,", "duration": 1.9, "gap": False, "asset_id": "a", "t_in": 0.9, "live_sound": True},
            {"text": "có tàu lượn Wonder Hill.", "duration": 2.9, "gap": False, "asset_id": "a", "t_in": 2.7, "live_sound": True}]
    assert not any(f["check"] == "Lặp hình" for f in review_cut(talk))
    pictures = [{**s, "live_sound": False} for s in talk]
    assert any(f["check"] == "Lặp hình" for f in review_cut(pictures))          # narrated over, the same stretch twice is still flagged


def test_a_line_the_checker_could_not_read_is_left_unchecked_and_the_others_are_checked(tmp_path):
    from nexora.app import build
    from nexora.core.adapter import AdapterError, ErrorCode
    from tests.fakes import FakeModel, FakeVoice
    system = build(tmp_path / "data", model=FakeModel(), voice=FakeVoice())
    pid = system.planning.create_project("Miền Tây")
    system.projects.update_project(pid, research=__import__("json").dumps([{"title": "Bài A", "url": "https://a", "passage": "Chợ nổi Cái Răng họp từ ba giờ sáng."}]))
    system.projects.keep_draft(pid, [{"text": "Chợ nổi họp từ ba giờ sáng.", "is_fact": True}, {"text": "Vùng này nuôi 65% thuỷ sản.", "is_fact": True}])
    system.planning.save_script(pid, ["Chợ nổi họp từ ba giờ sáng.", "Vùng này nuôi 65% thuỷ sản."])
    send = system.adapters.submit
    def broken(name, request):
        if request.params.get("task") == "check" and "65%" in request.params["prompt"]:
            raise AdapterError(ErrorCode.OUTPUT_INVALID, 'the model did not return JSON: {"ket_luan": "sai", "trich": "chừng 65%')
        return send(name, request)
    system.adapters.submit = broken
    results = system.planning.check_facts(pid)
    assert len(results) == 2 and results[1]["verdict"] == "not_found" and "Chưa kiểm được" in results[1]["note"]
