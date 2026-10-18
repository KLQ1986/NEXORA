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


def test_a_package_with_nothing_usable_is_refused():
    with pytest.raises(ValueError):
        check_package({"title": "x", "sources": [], "lines": [{"text": " "}]})
    with pytest.raises(ValueError):
        check_package({"oops": True})


def test_the_prompt_carries_the_voice_the_structure_and_the_siblings():
    system, prompt = topic_prompt("rừng bạch đàn Israel", goal="vì sao", lines=8, structure=[{"name": "Mở đầu", "min": 5, "max": 10}],
                                  voice="Giọng miền Nam.", style="mixed", siblings=["Bạch đàn và nước ngầm"])
    assert "Giọng miền Nam." in system and "nguồn" in system and "WebSearch" in system
    assert "rừng bạch đàn Israel" in prompt and "Mở đầu" in prompt and "Bạch đàn và nước ngầm" in prompt and "8" in prompt


def _topic_system(tmp_path, answer=PACKAGE):
    system = build(tmp_path / "data", model=FakeModel(), voice=FakeVoice(), cloud_models=[FakeClaudeCode(answer)])
    return system, TestClient(create_app(system))


def test_a_topic_is_written_by_the_researching_writer_and_applied_with_its_sources(tmp_path):
    system, client = _topic_system(tmp_path)
    project = system.planning.create_project("Rừng")
    sibling = system.planning.create_project("Bạch đàn và nước ngầm", production_id=system.projects.project(project)["production_id"])
    run_id = system.topics.start(project, "rừng bạch đàn Israel", goal="vì sao", lines=6)
    assert system.orch.lane_load()["claude_code"]["ready"] == 1                  # on a lane of its own
    drain(system)
    got = system.topics.get(run_id)
    assert got["state"] == "written" and got["package"]["title"] == "Rừng bạch đàn" and got["package"]["unverified"] == ["con số chính xác diện tích"]
    asked = system.adapters._adapters["model.claude_code"].asked[-1]
    assert asked.operation == "research" and "rừng bạch đàn Israel" in asked.params["prompt"] and asked.params["schema"]
    assert "Bạch đàn và nước ngầm" in asked.params["prompt"] and "miền Nam" in asked.params["system"]       # the other videos, the house voice
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
