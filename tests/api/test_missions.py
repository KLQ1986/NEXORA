"""Mission Control (design 2026-10-18): a mission is planned from the operator's words but checked in code, runs only once
confirmed, and reads its status from the work it started; the approvals, the fleet and the quality verdicts are read from
what each service keeps."""
from fastapi.testclient import TestClient

from nexora.agents.missions import Missions
from nexora.api.app import create_app
from nexora.api.missions import verdict
from nexora.app import build

from tests.fakes import FakeModel, FakeVoice
from tests.library.test_analysis import film, taken_in

PLAN = {"loai": "video", "muc_tieu": "Một buổi sáng ở chợ quê", "so_video": 2, "dinh_dang": "portrait", "so_cau": 4, "kenh": "", "mau": "Video dọc ngắn",
        "ngan_sach_usd": None, "dung_dich_vu_tra_tien": False, "tim_stock": True, "tu_phan_bien": False,
        "rang_buoc": ["dưới 60 giây"], "nghiem_thu": ["có lời dẫn và phụ đề", "dừng ở bước duyệt clip"]}


def _setup(tmp_path, plan=PLAN, voice=True):
    model = FakeModel()
    model.answers["mission_plan"] = plan
    system = build(tmp_path / "data", model=model, voice=FakeVoice() if voice else None, segment_seconds=15.0)
    return system, model, TestClient(create_app(system))


def test_a_mission_is_planned_checked_and_runs_only_once_confirmed(tmp_path):
    system, model, client = _setup(tmp_path)
    m = client.post("/api/v1/missions", json={"text": "làm 2 video dọc về chợ sáng, không tốn tiền"}).json()
    plan = m["plan"]
    assert m["status"] == "planned" and m["problems"] == []
    assert plan["kind"] == "video" and plan["count"] == 2 and plan["format"] == "portrait" and plan["lines"] == 4 and plan["paid"] is False
    assert plan["acceptance"] == ["có lời dẫn và phụ đề", "dừng ở bước duyệt clip"] and plan["constraints"] == ["dưới 60 giây"]
    assert system.producer.tasks() == []                                    # nothing runs before the operator's go
    assert any(a["kind"] == "mission" and a["id"] == m["mission_id"] for a in client.get("/api/v1/approvals").json()["approvals"])

    # The operator edits the plan: a channel that does not exist makes it a draft, with the reason.
    bad = client.patch(f"/api/v1/missions/{m['mission_id']}", json={"plan": {"channel": "Không có"}}).json()
    assert bad["status"] == "draft" and "Không có kênh “Không có”." in bad["problems"]
    assert client.post(f"/api/v1/missions/{m['mission_id']}/confirm").status_code == 409
    good = client.patch(f"/api/v1/missions/{m['mission_id']}", json={"plan": {"channel": None, "count": 2}}).json()
    assert good["status"] == "planned"

    done = client.post(f"/api/v1/missions/{m['mission_id']}/confirm").json()
    assert len(done["links"]["tasks"]) == 2 and len(done["links"]["projects"]) == 2 and done["status"] == "running"
    for pid in done["links"]["projects"]:
        p = system.projects.project(pid)
        assert p["budget_cap"] == 0.0 and p["format"] == "portrait" and p["template"] == "Video dọc ngắn"    # no paid service without the permission
    assert client.patch(f"/api/v1/missions/{m['mission_id']}", json={"plan": {"count": 3}}).status_code == 409

    # Pause stops the producer taking steps; resume brings back where it was; cancel stops everything it started.
    paused = client.post(f"/api/v1/missions/{m['mission_id']}/pause").json()
    assert paused["status"] == "paused" and all(system.producer.task(t)["status"] == "paused" for t in done["links"]["tasks"])
    assert system.producer.tick() == 0
    resumed = client.post(f"/api/v1/missions/{m['mission_id']}/resume").json()
    assert resumed["status"] == "running" and all(system.producer.task(t)["status"] == "working" for t in done["links"]["tasks"])
    cancelled = client.post(f"/api/v1/missions/{m['mission_id']}/cancel").json()
    assert cancelled["status"] == "cancelled" and all(system.producer.task(t)["status"] == "cancelled" for t in done["links"]["tasks"])
    events = [e["kind"] for e in cancelled["events"]]
    assert events[:2] == ["created", "planned"] and {"confirmed", "paused", "cancelled"} <= set(events)
    assert any(e["kind"] == "mission" for e in client.get("/api/v1/logs").json()["entries"])


def test_the_code_not_the_model_decides_what_can_run(tmp_path):
    # Without a voice the machine cannot render: a video mission is a draft that says so.
    system, model, client = _setup(tmp_path, voice=False)
    m = client.post("/api/v1/missions", json={"text": "làm video"}).json()
    assert m["status"] == "draft" and any("thiếu voice" in p for p in m["problems"])

    # A kind outside the catalogue, a paid service without a budget, a budget over what is left today.
    model.answers["mission_plan"] = {**PLAN, "loai": "dang_len_tiktok"}
    assert "NEXORA chưa làm được" in client.post("/api/v1/missions", json={"text": "đăng tiktok"}).json()["problems"][0]
    system2, model2, client2 = _setup(tmp_path / "b", plan={**PLAN, "dung_dich_vu_tra_tien": True})
    assert "cần một ngân sách" in " ".join(client2.post("/api/v1/missions", json={"text": "x"}).json()["problems"])
    client2.post("/api/v1/control/settings", json={"budget_day": 1.0})
    model2.answers["mission_plan"] = {**PLAN, "dung_dich_vu_tra_tien": True, "ngan_sach_usd": 5}
    over = client2.post("/api/v1/missions", json={"text": "x"}).json()
    assert over["status"] == "draft" and "vượt phần còn lại" in " ".join(over["problems"])
    fine = client2.patch(f"/api/v1/missions/{over['mission_id']}", json={"plan": {"budget": 0.8}}).json()
    assert fine["status"] == "planned"
    started = client2.post(f"/api/v1/missions/{over['mission_id']}/confirm").json()
    assert {system2.projects.project(p)["budget_cap"] for p in started["links"]["projects"]} == {0.4}       # the budget shared between the videos

    # A model that does not answer leaves a draft the operator can finish by hand.
    model.answers["mission_plan"] = lambda r: (_ for _ in ()).throw(KeyError("json"))
    stuck = client.post("/api/v1/missions", json={"text": "mô tả kho"}).json()
    assert stuck["status"] == "draft" and stuck["plan"]["goal"] == "mô tả kho"


def test_status_is_read_from_the_children():
    derive = Missions.derive
    assert derive("planned", []) == "planned" and derive("paused", [{"state": "running"}]) == "paused"
    assert derive("confirmed", []) == "completed"
    assert derive("confirmed", [{"state": "running"}, {"state": "waiting"}]) == "awaiting_approval"
    assert derive("confirmed", [{"state": "done"}, {"state": "blocked"}]) == "blocked"
    assert derive("confirmed", [{"state": "queued"}]) == "queued"
    assert derive("confirmed", [{"state": "done"}, {"state": "done"}]) == "completed"
    assert derive("confirmed", [{"state": "done"}, {"state": "failed"}]) == "partially_completed"
    assert derive("confirmed", [{"state": "failed"}]) == "failed" and derive("confirmed", [{"state": "cancelled"}]) == "cancelled"


def test_library_missions_run_the_footage_pipelines_and_the_overview_reads_everything(tmp_path):
    system, model, client = _setup(tmp_path, plan={**PLAN, "loai": "understand"})
    clip = taken_in(system, film(tmp_path / "market.mp4", [("testsrc2", 4)]))
    system.index.remove(clip, "video")                                      # as if the recording had never been described
    m = client.post("/api/v1/missions", json={"text": "mô tả hết footage chưa hiểu"}).json()
    assert m["status"] == "planned"
    started = client.post(f"/api/v1/missions/{m['mission_id']}/confirm").json()
    assert started["links"]["runs"] and started["status"] in ("queued", "running")
    detail = client.get(f"/api/v1/missions/{m['mission_id']}").json()
    assert detail["runs"][0]["pipeline"] == "library.understand" and detail["runs"][0]["stages"]

    view = client.get("/api/v1/mission-control").json()
    assert view["kpis"]["active"] == 1 and view["kpis"]["awaiting"] == len(client.get("/api/v1/approvals").json()["approvals"])
    assert set(view["kpis"]["health"]) == {"healthy", "busy", "degraded", "offline", "disabled"}
    fleet = client.get("/api/v1/fleet").json()
    assert {a["key"] for a in fleet["agents"]} >= {"producer", "director", "copilot", "ideas", "autonomy"}
    assert {w["key"] for w in fleet["workers"]} == {"interactive", "background"}
    client.post("/api/v1/control/kill-switch", json={"on": True})
    assert all(a["state"] == "disabled" for a in client.get("/api/v1/fleet").json()["agents"])
    res = client.get("/api/v1/resources").json()
    assert res["machine"]["disk_free"] > 0 and isinstance(res["lanes"], dict)
    assert client.get("/api/v1/quality").json()["counts"] == {"pass": 0, "pass_with_warnings": 0, "fail": 0, "manual_review": 0}


def test_quality_verdicts_come_from_the_measured_checks():
    assert verdict({"passed": True, "checks": {"duration": True}, "findings": []}) == "pass"
    assert verdict({"passed": True, "checks": {"duration": True}, "findings": [{"check": "Phụ đề"}]}) == "pass_with_warnings"
    assert verdict({"passed": False, "checks": {"duration": False}, "findings": []}) == "fail"
    assert verdict({"external": True, "passed": True, "checks": {}}) == "manual_review"
