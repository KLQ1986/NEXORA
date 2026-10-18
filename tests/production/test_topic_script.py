"""A script from a topic (design 2026-10-18, Claude Code as NEXORA's writer): a writer that reads the web returns its sources and the
lines it wrote on them; NEXORA checks the package before anything is written, and writes it into the production and the video."""
import pytest
from fastapi.testclient import TestClient

from nexora.api.app import create_app
from nexora.app import apply_topic, build, merge_sources
from nexora.modules.planning.topic import UNSOURCED_NOTE, check_package, script_lines, topic_prompt

from tests.fakes import FakeClaudeCode, FakeModel, FakeVoice
from tests.library.test_analysis import drain


def test_a_line_carries_its_fact_its_source_and_its_screen_words(tmp_path):
    system = build(tmp_path / "data", model=FakeModel(), voice=FakeVoice())
    project = system.planning.create_project("Rừng")
    unsourced = {"verdict": "not_found", "source": None, "quote": "", "note": "Người viết không dẫn nguồn cho câu này.", "checked_at": 1.0}
    system.projects.keep_draft(project, [{"text": "Năm 1950 Israel trồng rừng.", "is_fact": True, "source": "Haaretz", "screen_text": "1950"},
                                         {"text": "Không ai nhớ nổi.", "is_fact": True, "fact_check": unsourced}])
    system.planning.save_script(project, ["Năm 1950 Israel trồng rừng.", "Không ai nhớ nổi."])
    first, second = system.projects.current_script(project)["shots"]
    assert (first.is_fact, first.source, first.screen_text) == (True, "Haaretz", "1950")
    assert second.is_fact and second.fact_check["note"] == "Người viết không dẫn nguồn cho câu này."


PACKAGE = {"title": "Rừng bạch đàn", "angle": "Vì sao một cây ngoại lai thành bài toán",
           "sources": [{"id": "S1", "url": "https://example.org/a", "title": "Bài A", "publisher": "Haaretz", "date": "2021-05-03", "passage": "Năm 1950 KKL trồng bạch đàn."},
                       {"id": "S1", "url": "https://example.org/dup", "title": "Trùng", "publisher": "", "date": "", "passage": "x"},
                       {"id": "S2", "url": "ftp://x", "title": "Sai", "publisher": "", "date": "", "passage": "y"},
                       {"id": "S3", "url": "https://example.org/b", "title": "Bài B", "publisher": "", "date": "", "passage": ""}],
           "lines": [{"part": "Mở đầu", "text": "Năm 1950 người ta trồng bạch đàn khắp nơi.", "fact": True, "sources": ["S1"], "brief": "rừng bạch đàn",
                      "illustration": {"mode": "direct"}, "screen_text": "1950"},
                     {"part": "Mở đầu", "text": "> Có người bảo đó là sai lầm.", "fact": False, "sources": [], "brief": "", "illustration": {"mode": "associative", "evokes": "hối tiếc"}},
                     {"part": "Thân bài", "text": "Mỗi cây uống hai mươi lít nước một ngày.", "fact": True, "sources": ["S9"], "brief": "lá cây"},
                     {"part": "Thân bài", "text": "   ", "fact": False, "sources": []}],
           "unverified": ["con số chính xác diện tích"]}


def test_a_package_is_checked_before_anything_is_written():
    p = check_package(PACKAGE)
    assert [s["id"] for s in p["sources"]] == ["S1"]                        # a duplicate id, a non-web url, an empty passage: dropped
    assert [l["text"] for l in p["lines"]] == ["Năm 1950 người ta trồng bạch đàn khắp nơi.", "Có người bảo đó là sai lầm.", "Mỗi cây uống hai mươi lít nước một ngày."]
    assert p["lines"][0]["source"] == "Bài A" and p["lines"][2]["unsourced"] and p["unverified"] == ["con số chính xác diện tích"]
    lines = script_lines(p)
    assert lines[0] == "# Mở đầu" and lines[3] == "# Thân bài"
    assert lines[1]["is_fact"] and lines[1]["source"] == "Bài A" and lines[1]["screen_text"] == "1950" and "fact_check" not in lines[1]
    assert lines[4]["is_fact"] and lines[4]["fact_check"]["note"] == UNSOURCED_NOTE and "source" not in lines[4]
    assert lines[2]["illustration"] == {"mode": "associative", "evokes": "hối tiếc"}


def test_a_date_the_writer_could_not_give_is_no_date():
    p = check_package({**PACKAGE, "sources": [{**PACKAGE["sources"][0], "date": "không rõ"}, {**PACKAGE["sources"][0], "id": "S4", "url": "https://example.org/c", "date": "2019"}]})
    assert [s["date"] for s in p["sources"]] == [None, "2019"]


def test_a_package_with_nothing_usable_is_refused():
    with pytest.raises(ValueError):
        check_package({"title": "x", "sources": [], "lines": [{"text": " "}]})
    with pytest.raises(ValueError):
        check_package({"oops": True})


def test_the_prompt_carries_the_voice_the_structure_and_the_siblings():
    system, prompt = topic_prompt("rừng bạch đàn Israel", goal="vì sao", seconds=300, form="science", structure=[{"name": "Mở đầu", "min": 5, "max": 10}],
                                  voice="Giọng miền Nam.", style="mixed", siblings=["Bạch đàn và nước ngầm"])
    assert "Giọng miền Nam." in system and "nguồn" in system and "WebSearch" in system
    assert "Diễn giải khoa học" in system and "so sánh đời thường" in system                  # the kind of video, and how it tells its story
    assert "rừng bạch đàn Israel" in prompt and "Mở đầu" in prompt and "Bạch đàn và nước ngầm" in prompt
    assert "khoảng 5 phút (300 giây)" in prompt and "780 chữ" in prompt


def test_a_draft_much_shorter_or_longer_than_asked_is_said_to_be():
    p = check_package(PACKAGE, seconds=600)
    assert p["seconds"] == 10 and any("ngắn hơn nhiều so với 10 phút 00 giây" in w for w in p["warnings"])
    assert not any("phút" in w for w in check_package(PACKAGE, seconds=11)["warnings"])


def _topic_system(tmp_path, answer=PACKAGE):
    system = build(tmp_path / "data", model=FakeModel(), voice=FakeVoice(), cloud_models=[FakeClaudeCode(answer)])
    return system, TestClient(create_app(system))


def test_a_topic_is_written_by_the_researching_writer_and_applied_with_its_sources(tmp_path):
    system, client = _topic_system(tmp_path)
    project = system.planning.create_project("Rừng")
    sibling = system.planning.create_project("Bạch đàn và nước ngầm", production_id=system.projects.project(project)["production_id"])
    run_id = system.topics.start(project, "rừng bạch đàn Israel", goal="vì sao", seconds=240, form="history")
    assert system.orch.lane_load()["claude_code"]["ready"] == 1                  # on a lane of its own
    drain(system)
    got = system.topics.get(run_id)
    assert got["state"] == "written" and got["package"]["title"] == "Rừng bạch đàn" and got["package"]["unverified"] == ["con số chính xác diện tích"]
    asked = system.adapters._adapters["model.claude_code"].asked[-1]
    assert asked.operation == "research" and "rừng bạch đàn Israel" in asked.params["prompt"] and asked.params["schema"]
    assert "Bạch đàn và nước ngầm" in asked.params["prompt"] and "miền Nam" in asked.params["system"]       # the other videos, the house voice
    assert "240 giây" in asked.params["prompt"] and "Tài liệu lịch sử" in asked.params["system"] and asked.deadline_seconds == 1080
    script_id = apply_topic(system, project, run_id)
    shots = system.projects.script(script_id)["shots"]
    assert shots[0].text == "Năm 1950 người ta trồng bạch đàn khắp nơi." and shots[0].scene == "Mở đầu" and shots[0].source == "Bài A"
    research = system.planning.research(project)
    assert [s["url"] for s in research] == ["https://example.org/a"] and research[0]["passage"].startswith("Năm 1950")
    production = system.productions.get(system.projects.project(project)["production_id"])
    assert "https://example.org/a" in production["research"] and "https://example.org/a" in (system.projects.project(sibling)["research"] or "")
    assert system.topics.get(run_id)["state"] == "applied"
    assert merge_sources(system, project, got["package"]["sources"]) == 0          # merged by address: nothing twice


def test_a_package_that_fails_its_checks_fails_the_run_and_writes_nothing(tmp_path):
    system, client = _topic_system(tmp_path, answer={"title": "x", "sources": [], "lines": []})
    project = system.planning.create_project("Rừng")
    run_id = system.topics.start(project, "x")
    drain(system)
    assert system.orch.run_status(run_id).value == "failed" and system.projects.current_script(project) is None
    assert system.topics.get(run_id)["state"] == "asked"


def test_the_editor_gets_the_topic_draft_unsaved_and_its_sources_on_save_only(tmp_path):
    system, client = _topic_system(tmp_path)
    project = system.planning.create_project("Rừng")
    assert client.post(f"/api/v1/projects/{project}/draft-from-topic", json={"topic": " "}).status_code == 422
    assert client.get(f"/api/v1/projects/{project}/draft-from-topic").json() == {"state": None}
    assert client.post(f"/api/v1/projects/{project}/draft-from-topic", json={"topic": "rừng", "form": "không có"}).status_code == 422
    forms = client.get("/api/v1/topic/forms").json()
    assert {f["key"] for f in forms["forms"]} >= {"reportage", "science", "history"} and forms["seconds"]["max"] == 900
    client.post(f"/api/v1/projects/{project}/draft-from-topic", json={"topic": "rừng bạch đàn Israel", "minutes": 5, "form": "science"})
    assert client.get(f"/api/v1/projects/{project}/draft-from-topic").json()["state"] == "asked"
    drain(system)
    got = client.get(f"/api/v1/projects/{project}/draft-from-topic").json()
    assert got["state"] == "offered" and got["lines"][0] == "# Mở đầu" and got["sources"][0]["url"] == "https://example.org/a"
    assert got["unverified"] == ["con số chính xác diện tích"] and got["warnings"] and got["target_seconds"] == 300 and got["form"] == "science" and got["seconds"] == 10
    assert system.projects.current_script(project) is None and system.planning.research(project) == []       # nothing saved yet
    client.put(f"/api/v1/projects/{project}/script", json={"lines": got["lines"]})
    first = system.projects.current_script(project)["shots"][0]
    assert first.is_fact and first.source == "Bài A" and len(system.planning.research(project)) == 1
    client.put(f"/api/v1/projects/{project}/script", json={"lines": got["lines"]})
    assert len(system.planning.research(project)) == 1                                                      # applied once
    other = system.planning.create_project("Khác")
    client.put(f"/api/v1/projects/{other}/script", json={"lines": ["Một câu."]})
    assert system.planning.research(other) == []


def test_the_editor_is_told_when_claude_code_is_missing_or_the_writing_failed(tmp_path):
    system = build(tmp_path / "data", model=FakeModel(), voice=FakeVoice())
    client = TestClient(create_app(system))
    project = system.planning.create_project("Rừng")
    assert client.post(f"/api/v1/projects/{project}/draft-from-topic", json={"topic": "rừng"}).status_code == 503
    system, client = _topic_system(tmp_path / "b", answer={"title": "x", "sources": [], "lines": []})
    project = system.planning.create_project("Rừng")
    client.post(f"/api/v1/projects/{project}/draft-from-topic", json={"topic": "rừng"})
    drain(system)
    got = client.get(f"/api/v1/projects/{project}/draft-from-topic").json()
    assert got["status"] == "failed" and "not usable" in got["reason"]


def test_a_topic_mission_researches_then_carries_on_like_any_video(tmp_path):
    system, client = _topic_system(tmp_path)
    plan = {"loai": "topic", "muc_tieu": "khủng hoảng rừng bạch đàn Israel", "tieu_de": "Rừng bạch đàn", "so_video": 1, "dinh_dang": "landscape",
            "thoi_luong_phut": 5, "the_loai": "analysis"}
    system.adapters._adapters["model"].answers["mission_plan"] = plan
    m = client.post("/api/v1/missions", json={"text": "sản xuất video về khủng hoảng rừng bạch đàn của Israel"}).json()
    assert m["plan"]["kind"] == "topic" and m["plan"]["critique"] is False and m["state"] == "planned"
    assert m["plan"]["seconds"] == 300 and m["plan"]["form"] == "analysis"
    done = client.post(f"/api/v1/missions/{m['mission_id']}/confirm").json()
    task_id, project = done["links"]["tasks"][0], done["links"]["projects"][0]
    assert system.producer.task(task_id)["step"] == "topic"
    for _ in range(12):                                          # the producer steps; the worker runs what they start
        system.producer.advance(task_id)
        drain(system)
    task = system.producer.task(task_id)
    said = " ".join(e["text"] for e in task["log"])
    assert system.projects.current_script(project)["shots"][0].text == "Năm 1950 người ta trồng bạch đàn khắp nơi."
    assert "Claude Code viết 3 câu dựa trên 1 nguồn; 1 câu nêu dữ kiện chưa có nguồn." in said and "câu nêu dữ kiện" in said      # written, then checked
    asked = system.adapters._adapters["model.claude_code"].asked[-1]
    assert "300 giây" in asked.params["prompt"] and "Phân tích / bình luận" in asked.params["system"]
    assert task["step"] in ("review", "cut", "cutting") and len(system.planning.research(project)) == 1


def test_a_topic_mission_needs_claude_code(tmp_path):
    system = build(tmp_path / "data", model=FakeModel(), voice=FakeVoice())
    client = TestClient(create_app(system))
    system.adapters._adapters["model"].answers["mission_plan"] = {"loai": "topic", "muc_tieu": "rừng", "so_video": 1}
    m = client.post("/api/v1/missions", json={"text": "video về rừng"}).json()
    assert m["state"] == "draft" and any("model.claude_code" in p for p in m["problems"])


def test_pictures_are_made_for_the_lines_named_only(tmp_path):
    system, client = _topic_system(tmp_path)
    project = system.planning.create_project("Rừng")
    system.projects.save_script(project, ["Câu một.", "Câu hai."])
    script = system.projects.current_script(project)
    run_id = system.generation.start(script["script_id"], only=[script["shots"][1].shot_id])
    assert system.generation.targets(run_id) == {script["shots"][1].shot_id}
    assert system.generation.targets(system.generation.start(script["script_id"])) == set()      # every line


def test_a_topic_mission_allowed_to_pay_asks_pictures_for_the_lines_left_without_one(tmp_path):
    system, client = _topic_system(tmp_path)
    plan = {"loai": "topic", "muc_tieu": "rừng bạch đàn Israel", "tieu_de": "Rừng", "so_video": 1, "thoi_luong_phut": 2, "dung_dich_vu_tra_tien": True, "ngan_sach_usd": 2}
    system.adapters._adapters["model"].answers["mission_plan"] = plan
    m = client.post("/api/v1/missions", json={"text": "video về rừng bạch đàn, được dùng dịch vụ trả tiền tối đa 2 USD"}).json()
    done = client.post(f"/api/v1/missions/{m['mission_id']}/confirm").json()
    task_id, project = done["links"]["tasks"][0], done["links"]["projects"][0]
    for _ in range(12):
        system.producer.advance(task_id)
        drain(system)
    script = system.projects.current_script(project)
    gaps = {s.shot_id for s in system.projects.selections(script["script_id"]) if s.status == "gap"}
    run = system.orch.runs_for_subject(script["script_id"])
    made = [r for r in run if system.orch.pipeline_of(r) == "sourcing.generate"]
    assert gaps and made and system.generation.targets(made[-1]) == gaps
    assert "Tạo hình AI cho" in " ".join(e["text"] for e in system.producer.task(task_id)["log"])


def test_what_the_operator_chose_as_they_asked_is_taken_over_what_the_model_read(tmp_path):
    system, client = _topic_system(tmp_path)
    system.adapters._adapters["model"].answers["mission_plan"] = {"loai": "video", "muc_tieu": "rừng bạch đàn", "so_video": 1, "thoi_luong_phut": 2, "the_loai": "news"}
    m = client.post("/api/v1/missions", json={"text": "video về rừng bạch đàn", "kind": "topic", "form": "science", "seconds": 480}).json()
    assert (m["plan"]["kind"], m["plan"]["form"], m["plan"]["seconds"], m["plan"]["critique"]) == ("topic", "science", 480, False)
    auto = client.post("/api/v1/missions", json={"text": "video về rừng bạch đàn", "kind": "", "form": None}).json()
    assert auto["plan"]["kind"] == "video"                                   # nothing chosen: the model's reading stands


def _topic_mission(system, client):
    system.adapters._adapters["model"].answers["mission_plan"] = {"loai": "topic", "muc_tieu": "rừng bạch đàn Israel", "tieu_de": "Rừng", "so_video": 1}
    m = client.post("/api/v1/missions", json={"text": "video về rừng bạch đàn"}).json()
    return client.post(f"/api/v1/missions/{m['mission_id']}/confirm").json()


def test_a_topic_mission_whose_writing_failed_writes_again_when_retried(tmp_path):
    answers = [{"title": "x", "sources": [], "lines": []}, PACKAGE]
    system, client = _topic_system(tmp_path, answer=lambda request: answers.pop(0) if len(answers) > 1 else answers[0])
    m = _topic_mission(system, client)
    task_id, project = m["links"]["tasks"][0], m["links"]["projects"][0]
    for _ in range(3):
        system.producer.advance(task_id)
        drain(system)
    assert system.producer.task(task_id)["status"] == "failed"
    assert "not usable" in system.producer.task(task_id)["log"][-1]["text"]
    assert any(system.orch.pipeline_of(r) == "planning.topic_script" for r in client.get(f"/api/v1/missions/{m['mission_id']}").json()["run_ids"])
    client.post(f"/api/v1/missions/{m['mission_id']}/retry")
    for _ in range(4):
        system.producer.advance(task_id)
        drain(system)
    assert system.projects.current_script(project)["shots"][0].text == "Năm 1950 người ta trồng bạch đàn khắp nơi."
    assert system.producer.task(task_id)["status"] != "failed"


def test_a_failed_wait_retried_on_its_own_starts_its_work_again(tmp_path):
    answers = [{"title": "x", "sources": [], "lines": []}, PACKAGE]
    system, client = _topic_system(tmp_path, answer=lambda request: answers.pop(0) if len(answers) > 1 else answers[0])
    task_id = system.producer.start("rừng bạch đàn", topic=True, critique=False)
    for _ in range(3):
        system.producer.advance(task_id)
        drain(system)
    assert system.producer.task(task_id)["status"] == "failed"
    assert system.producer.retry(task_id)                      # the producer alone: its failed run is asked for again
    for _ in range(4):
        system.producer.advance(task_id)
        drain(system)
    assert system.projects.current_script(system.producer.task(task_id)["project_id"]) is not None


def test_cancelling_a_topic_mission_stops_its_writer(tmp_path):
    system, client = _topic_system(tmp_path)
    m = _topic_mission(system, client)
    task_id = m["links"]["tasks"][0]
    system.producer.advance(task_id)                           # the writer is asked, not yet run
    run_id = system.producer.task(task_id)["options"]["topic_run"]
    client.post(f"/api/v1/missions/{m['mission_id']}/cancel")
    assert system.orch.run_status(run_id).value == "cancelled"


def test_a_templates_parts_share_out_the_length_asked(tmp_path):
    from nexora.app import DEFAULT_STRUCTURE
    system, prompt = topic_prompt("miền Tây sông nước", seconds=300, structure=DEFAULT_STRUCTURE)
    assert "Mở bài" in prompt and "Thân bài" in prompt and "giữ người xem ngay từ câu đầu" in prompt
    assert "15–90 giây" not in prompt                                  # a template's short-video timings are not the length asked
    shares = [int(s) for s in __import__("re").findall(r"khoảng (\d+) giây\)", prompt)]
    assert len(shares) == 3 and abs(sum(shares) - 300) <= 3 and shares[1] > shares[0] + shares[2]
    topic_prompt("x", structure=[{"role": "hook"}, {}])                 # a part with nothing but its role, or nothing at all


def test_a_topic_mission_on_a_template_writes(tmp_path):
    system, client = _topic_system(tmp_path)
    m = _topic_mission(system, client)
    task_id, project = m["links"]["tasks"][0], m["links"]["projects"][0]
    system.projects.update_project(project, template="Video ngang có lời dẫn")      # as its production gives it, on this machine
    for _ in range(3):
        system.producer.advance(task_id)
        drain(system)
    assert system.projects.current_script(project) is not None, system.producer.task(task_id)["log"]


def test_the_editor_says_what_went_wrong_not_that_it_gave_up(tmp_path):
    system, client = _topic_system(tmp_path, answer=lambda request: (_ for _ in ()).throw(KeyError("name")))
    project = system.planning.create_project("Rừng")
    client.post(f"/api/v1/projects/{project}/draft-from-topic", json={"topic": "rừng"})
    drain(system)
    with system.orch._conn:                                                     # the wait before the second try, gone by
        system.orch._conn.execute("UPDATE stages SET next_retry_at = 0 WHERE status = 'retry_wait'")
    drain(system)
    got = client.get(f"/api/v1/projects/{project}/draft-from-topic").json()
    assert got["status"] == "blocked" and "name" in got["reason"] and got["reason"] != "retry_limit"


def test_a_writer_is_told_the_angles_its_productions_other_videos_took(tmp_path):
    from nexora.app import topic_context
    system, client = _topic_system(tmp_path)
    production = client.post("/api/v1/productions", json={"title": "Rừng"}).json()["production_id"]
    first, second = (system.planning.create_project(t, production_id=production) for t in ("Video một", "Video hai"))
    system.topics.start(first, "rừng")
    drain(system)
    assert topic_context(system, second)["siblings"] == ["Video một (góc: Vì sao một cây ngoại lai thành bài toán)"]
