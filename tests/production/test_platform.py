"""Platform core: the model router and privacy, the Claude text adapter, the audit log, autonomy levels."""
import http.server
import json
import threading

import pytest
from fastapi.testclient import TestClient

from nexora.adapters.claude import ClaudeText
from nexora.adapters.outbox import FolderPublisher
from nexora.api.app import create_app
from nexora.app import build
from nexora.core.adapter import Adapter, AdapterError, Capability, ErrorCode, PrivacyClass, Request, Result, Usage
from nexora.core.states import RunStatus

from tests.conftest import make_video
from tests.fakes import FakeModel, FakeVoice


def drain(system):
    while system.worker.run_once():
        pass


class Cloud(Adapter):
    """A cloud text model that remembers what it was asked."""
    def __init__(self): self.asked = []
    def describe(self): return Capability(name="model.cloud", operations=("chat",), runs="cloud")
    def submit(self, request):
        self.asked.append(request)
        return Result(outputs={"json": {"nhan_xet": [{"cau": 1, "van_de": "Từ mô hình cloud.", "de_xuat": ""}], "cau": ["câu từ cloud"]}}, usage=Usage(units=100, cost=0.01))


def test_text_goes_to_the_model_chosen_for_the_task_and_footage_and_privacy_mode_keep_everything_local(tmp_path):
    local, cloud = FakeModel(), Cloud()
    system = build(tmp_path / "data", model=local, voice=FakeVoice(), segment_seconds=2.0, cloud_models=[cloud])
    client = TestClient(create_app(system))
    system.library.ingest(make_video(tmp_path / "a.mp4", picture=6)); drain(system)
    assert cloud.asked == []                                                    # describing footage never left this machine, routes or no routes
    pid = client.post("/api/v1/projects", json={"title": "Chợ", "lines": ["chợ rau củ", "cá tươi"]}).json()["project_id"]
    local.answers["critique"] = {"nhan_xet": []}
    assert client.post(f"/api/v1/projects/{pid}/critique").json()["script"]["critique"] == []         # no route chosen: the local model answers

    routes = client.post("/api/v1/models/routes", json={"routes": {"critique": "model.cloud", "bogus": "model.cloud", "check": "model.nowhere"}}).json()
    assert routes["routes"] == {"critique": "model.cloud"} and sorted(m["name"] for m in routes["models"]) == ["model", "model.cloud"]
    assert client.post(f"/api/v1/projects/{pid}/critique").json()["script"]["critique"][0]["issue"] == "Từ mô hình cloud."
    assert len(cloud.asked) == 1 and system.orch.usage()[0]["adapter"] in ("model.cloud", "model", "ffmpeg", "ffprobe")
    assert any(u["adapter"] == "model.cloud" and u["cost"] == pytest.approx(0.01) for u in system.orch.usage())      # the call is on record under the model that served it

    system.orch.set_setting("privacy_local_only", "1")
    assert client.post(f"/api/v1/projects/{pid}/critique").json()["script"]["critique"] == [] and len(cloud.asked) == 1     # privacy mode: back to the local model, nothing refused
    system.orch.set_setting("privacy_local_only", "0")
    system.orch.set_setting("model_routes", json.dumps({"*": "model.cloud"}))
    # A request with pictures, or one marked local-only, stays where it was addressed even with every task routed to the cloud.
    system.adapters.submit("model", Request("chat", params={"prompt": "x", "json": True}))
    system.adapters.submit("model", Request("chat", inputs={"images": ["/tmp/frame.jpg"]}, params={"prompt": "x", "json": True}, privacy_class=PrivacyClass.CLOUD_ALLOWED))
    system.adapters.submit("model", Request("describe", inputs={"images": []}, params={"prompt": "x"}, privacy_class=PrivacyClass.CLOUD_ALLOWED))
    assert len(cloud.asked) == 1
    system.adapters.submit("model", Request("chat", params={"prompt": "x", "json": True}, privacy_class=PrivacyClass.CLOUD_ALLOWED))
    assert len(cloud.asked) == 2

    # Writing tasks with names of their own follow the route chosen for writing ("write"), the others theirs.
    system.orch.set_setting("model_routes", json.dumps({"write": "model.cloud"}))
    for task in ("draft", "draft_speech", "rewrite", "variant", "idea_angle", "mission_plan"):
        system.adapters.submit("model", Request("chat", params={"prompt": "x", "json": True, "task": task}, privacy_class=PrivacyClass.CLOUD_ALLOWED))
    assert len(cloud.asked) == 8
    system.adapters.submit("model", Request("chat", params={"prompt": "x", "json": True, "task": "critique"}, privacy_class=PrivacyClass.CLOUD_ALLOWED))
    assert len(cloud.asked) == 8


def test_the_claude_adapter_speaks_the_messages_api_counts_cost_and_names_its_errors():
    seen, answers, headers_seen = [], [], []

    class Api(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            ok = self.headers.get("x-api-key") == "sk-test"
            self.send_response(200 if ok else 401); self.send_header("content-type", "application/json"); self.end_headers()
            self.wfile.write(json.dumps({"data": [{"id": "claude-haiku-5-5"}]} if ok else {"error": {"message": "invalid x-api-key"}}).encode())

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["content-length"])))
            seen.append((self.path, self.headers.get("x-api-key"), self.headers.get("anthropic-version"), body))
            headers_seen.append(self.headers.get("anthropic-workspace-id") or "")
            status, payload = answers.pop(0)
            self.send_response(status); self.send_header("content-type", "application/json"); self.end_headers()
            self.wfile.write(json.dumps(payload).encode())
        def log_message(self, *a): pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Api)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        adapter = ClaudeText("sk-test", host=f"http://127.0.0.1:{server.server_port}", input_price=1.0, output_price=5.0)
        assert adapter.describe() == Capability(name="model.claude", operations=("chat",), runs="cloud") and adapter.environment()["key_present"]
        assert adapter.check() == {"ok": True, "detail": "khoá được chấp nhận; model claude-haiku-5-5 có trong danh sách"} and seen == []          # asked without sending a message
        assert ClaudeText("wrong", host=f"http://127.0.0.1:{server.server_port}").check() == {"ok": False, "detail": "API trả lời 401"}
        answers.append((200, {"content": [{"type": "text", "text": "```json\n{\"cau\": [\"một\", \"hai\"]}\n```"}], "usage": {"input_tokens": 1000, "output_tokens": 200}, "stop_reason": "end_turn"}))
        result = adapter.submit(Request("chat", params={"prompt": "Viết hai câu.", "json": True, "max_tokens": 300}))
        assert result.outputs["json"] == {"cau": ["một", "hai"]} and result.usage.cost == pytest.approx(0.002) and result.usage.units == 1200
        path, key, version, body = seen[0]
        assert (path, key, version) == ("/v1/messages", "sk-test", "2023-06-01") and body["model"] == "claude-haiku-5-5" and body["max_tokens"] == 300 and "Viết hai câu." in body["messages"][0]["content"]
        answers.append((200, {"content": [{"type": "text", "text": "Xin chào."}], "usage": {"input_tokens": 5, "output_tokens": 3}}))
        assert adapter.submit(Request("chat", params={"prompt": "Chào"})).outputs["text"] == "Xin chào."
        for status, code in ((401, ErrorCode.AUTH), (429, ErrorCode.RATE_LIMITED), (529, ErrorCode.UNAVAILABLE), (400, ErrorCode.INVALID_REQUEST)):
            answers.append((status, {"error": {"message": "x"}}))
            with pytest.raises(AdapterError) as failed:
                adapter.submit(Request("chat", params={"prompt": "x"}))
            assert failed.value.code is code
        # Two refusals that come back as a plain bad request but that only the operator can fix.
        for detail, code, word in (("This API key is not scoped to a workspace, so this request must include the anthropic-workspace-id header", ErrorCode.AUTH, "anthropic_workspace_id"),
                                   ("Your credit balance is too low to access the Anthropic API.", ErrorCode.QUOTA_EXHAUSTED, "credit")):
            answers.append((400, {"type": "error", "error": {"type": "invalid_request_error", "message": detail}}))
            with pytest.raises(AdapterError) as refused:
                adapter.submit(Request("chat", params={"prompt": "x"}))
            assert refused.value.code is code and word in refused.value.message and not refused.value.retryable
        scoped = ClaudeText("sk-test", host=f"http://127.0.0.1:{server.server_port}", workspace_id="wrkspc_1")
        answers.append((200, {"content": [{"type": "text", "text": "ok"}], "usage": {}}))
        scoped.submit(Request("chat", params={"prompt": "x"}))
        assert seen[-1][3]["messages"] and "wrkspc_1" in headers_seen[-1]
        answers.append((200, {"content": [{"type": "text", "text": "không phải JSON"}], "usage": {}}))
        with pytest.raises(AdapterError) as bad:
            adapter.submit(Request("chat", params={"prompt": "x", "json": True}))
        assert bad.value.code is ErrorCode.OUTPUT_INVALID
    finally:
        server.shutdown()


def test_what_the_operator_does_through_the_interface_is_written_down(tmp_path):
    system = build(tmp_path / "data", model=FakeModel(), voice=FakeVoice())
    client = TestClient(create_app(system))
    client.get("/api/v1/projects")
    pid = client.post("/api/v1/projects", json={"title": "Chợ"}).json()["project_id"]
    client.patch(f"/api/v1/projects/{pid}", json={"due_date": "sai"})
    client.post("/api/v1/control/kill-switch", json={"on": True})
    entries = client.get("/api/v1/audit").json()["entries"]
    assert [(e["method"], e["path"], e["status"]) for e in entries] == [("POST", "/api/v1/control/kill-switch", 200), ("PATCH", f"/api/v1/projects/{pid}", 422), ("POST", "/api/v1/projects", 201)]


def cut(system, client, tmp_path, title, *, approve_clips=True):
    pid = client.post("/api/v1/projects", json={"title": title, "lines": ["chợ rau củ", "cá tươi trên sạp"]}).json()["project_id"]
    client.post(f"/api/v1/projects/{pid}/match"); drain(system)
    if approve_clips and client.get(f"/api/v1/projects/{pid}").json()["match"]["status"] == "waiting_review":
        client.post(f"/api/v1/projects/{pid}/match/approve")
    client.post(f"/api/v1/projects/{pid}/render"); drain(system)
    return pid


def test_a_level_must_be_earned_by_the_operators_own_record_and_is_given_back_when_a_cut_is_turned_down(tmp_path):
    system = build(tmp_path / "data", model=FakeModel(), voice=FakeVoice(), segment_seconds=2.0, publishers=[FolderPublisher(tmp_path / "outbox")])
    client = TestClient(create_app(system))
    system.library.ingest(make_video(tmp_path / "a.mp4", picture=20)); drain(system)
    status = client.get("/api/v1/autonomy").json()
    assert status["level"] == 1 and [l["earned"] for l in status["levels"]] == [True, True, False, False, False]
    refused = client.post("/api/v1/autonomy", json={"level": 3})
    assert refused.status_code == 409 and "Hiện có 0 lần" in refused.json()["detail"]

    for i in range(8):                                             # the operator approves clips and cuts, eight videos running
        pid = cut(system, client, tmp_path, f"Video {i}")
        client.post(f"/api/v1/projects/{pid}/render/decision", json={"approve": True})
    status = client.get("/api/v1/autonomy").json()
    assert [l["earned"] for l in status["levels"]] == [True] * 5 and status["levels"][3]["progress"]["have"] == 8
    assert client.post("/api/v1/autonomy", json={"level": 4}).json()["level"] == 4 and client.post("/api/v1/autonomy", json={"level": 9}).status_code == 422

    pid = cut(system, client, tmp_path, "Tự chạy", approve_clips=False)
    view = client.get(f"/api/v1/projects/{pid}").json()
    assert view["script"]["match_approved"] and view["render"]["status"] == "waiting_review"          # level 2 and up: confident clips needed no review
    assert system.autonomy.tick() == [f"approved:{view['renders'][0]['render_id']}", f"published:{view['renders'][0]['render_id']}"]
    after = client.get(f"/api/v1/projects/{pid}").json()
    assert after["render"]["status"] == "succeeded" and "Tự duyệt" in after["renders"][0]["review"]["comment"] and after["renders"][0]["package"]["rights"]["clear"]
    assert [p["status"] for p in client.get("/api/v1/publishing", params={"project_id": pid}).json()["publications"]] == ["published"]
    assert system.autonomy.tick() == [] and len(list((tmp_path / "outbox").iterdir())) == 1            # nothing is done twice
    assert next(d for d in system.orch.decisions("edit.render") if d["run_id"])["actor"] == "policy"   # and the record says who pressed approve

    system.orch.set_setting("kill_switch", "1") if False else None
    pid = cut(system, client, tmp_path, "Bị từ chối", approve_clips=False)
    client.post(f"/api/v1/projects/{pid}/render/decision", json={"approve": False, "comment": "Cảnh hai bị tối."})
    assert system.autonomy.tick() == ["demoted"] and client.get("/api/v1/autonomy").json()["level"] == 2
    assert any(n["kind"] == "autonomy_lowered" for n in system.orch.notifications())
    assert client.post("/api/v1/autonomy", json={"level": 3}).status_code == 409                      # the last five are no longer all approvals

    assert client.post("/api/v1/autonomy", json={"level": 0}).json()["level"] == 0                    # down is always allowed
    client.patch(f"/api/v1/projects/{pid}", json={"auto_accept": 1})
    client.post(f"/api/v1/projects/{pid}/match"); drain(system)
    assert not client.get(f"/api/v1/projects/{pid}").json()["script"]["match_approved"]               # level 0: nothing is accepted on its own, whatever the project says


def test_a_cut_with_a_serious_finding_or_a_gap_is_left_for_the_operator_at_every_level(tmp_path):
    system = build(tmp_path / "data", model=FakeModel(), voice=FakeVoice(), segment_seconds=2.0)
    client = TestClient(create_app(system))
    system.library.ingest(make_video(tmp_path / "a.mp4", picture=20)); drain(system)
    system.orch.set_setting("autonomy_level", "3")
    pid = client.post("/api/v1/projects", json={"title": "Thiếu hình", "lines": ["chợ rau củ", "tên lửa phóng lên quỹ đạo"]}).json()["project_id"]
    client.post(f"/api/v1/projects/{pid}/match"); drain(system)
    client.post(f"/api/v1/projects/{pid}/match/approve")
    client.post(f"/api/v1/projects/{pid}/render"); drain(system)
    assert system.autonomy.tick() == [] and client.get(f"/api/v1/projects/{pid}").json()["render"]["status"] == "waiting_review"


def test_a_cloud_model_that_cannot_serve_hands_the_work_back_to_the_local_one_and_says_so_once(tmp_path):
    class Broke(Cloud):
        def submit(self, request):
            self.asked.append(request)
            raise AdapterError(ErrorCode.QUOTA_EXHAUSTED, "the Anthropic account has no credit left", retryable=False)
    local, cloud = FakeModel(), Broke()
    system = build(tmp_path / "data", model=local, voice=FakeVoice(), cloud_models=[cloud])
    client = TestClient(create_app(system))
    pid = client.post("/api/v1/projects", json={"title": "Chợ", "lines": ["chợ rau củ", "cá tươi"]}).json()["project_id"]
    client.post("/api/v1/models/routes", json={"routes": {"critique": "model.cloud"}})
    local.answers["critique"] = {"nhan_xet": [{"cau": 1, "van_de": "Từ mô hình trên máy.", "de_xuat": ""}]}
    for _ in range(3):
        assert client.post(f"/api/v1/projects/{pid}/critique").json()["script"]["critique"][0]["issue"] == "Từ mô hình trên máy."       # the work is done all the same
    assert len(cloud.asked) == 3
    notices = [n for n in client.get("/api/v1/notifications").json()["items"] if n["kind"] == "model_fallback"]
    assert len(notices) == 1 and "no credit left" in notices[0]["reason"] and notices[0]["link"] == "/he-thong"                             # told once, not three times

    class Wrong(Cloud):
        def submit(self, request):
            raise AdapterError(ErrorCode.OUTPUT_INVALID, "the model did not return JSON")
    strict = build(tmp_path / "strict", model=FakeModel(), voice=FakeVoice(), cloud_models=[Wrong()])
    strict.orch.set_setting("model_routes", json.dumps({"*": "model.cloud"}))
    with pytest.raises(AdapterError):                                          # a bad answer is the model's fault, not a reason to ask another one silently
        strict.adapters.submit("model", Request("chat", params={"prompt": "x", "json": True}, privacy_class=PrivacyClass.CLOUD_ALLOWED))


def test_the_operator_turns_approving_on_their_own_and_off_gate_by_gate(tmp_path):
    from tests.fakes import FakeImageGen, FakeVideoGen
    system = build(tmp_path / "data", model=FakeModel(), voice=FakeVoice(), segment_seconds=2.0, generators=[FakeImageGen(), FakeVideoGen()])
    client = TestClient(create_app(system))
    system.library.ingest(make_video(tmp_path / "a.mp4", picture=20)); drain(system)
    system.orch.set_setting("autonomy_level", "0")                                   # whatever the level: the switches are the operator's own
    assert client.get("/api/v1/autonomy").json()["switches"] == {"clips": False, "renders": False, "pictures": False, "stock": False}

    off = cut(system, client, tmp_path, "Chưa bật", approve_clips=False)
    assert system.autonomy.tick() == [] and client.get(f"/api/v1/projects/{off}").json()["match"]["status"] == "waiting_review"

    switched = client.post("/api/v1/autonomy/switches", json={"clips": True, "renders": True}).json()["switches"]
    assert switched == {"clips": True, "renders": True, "pictures": False, "stock": False}             # no record needs earning first
    assert system.autonomy.tick() == [f"clips:{off}"]
    client.post(f"/api/v1/projects/{off}/render"); drain(system)
    view = client.get(f"/api/v1/projects/{off}").json()
    assert system.autonomy.tick() == [f"approved:{view['renders'][0]['render_id']}"]
    assert client.get(f"/api/v1/projects/{off}").json()["render"]["status"] == "succeeded"
    assert {d["actor"] for d in system.orch.decisions("sourcing.match") + system.orch.decisions("edit.render")} == {"policy"}       # the operator's record is untouched

    pid = system.planning.create_project("Mèo")
    run = system.generation.start(system.planning.save_script(pid, ["Một chú mèo cam ngồi bên cửa sổ."]))
    drain(system)
    assert system.autonomy.tick() == [] and system.orch.run_status(run) is RunStatus.WAITING_REVIEW        # paid pictures wait while their switch is off
    client.post("/api/v1/autonomy/switches", json={"pictures": True})
    assert system.autonomy.tick() == [f"pictures:{run}"]; drain(system)
    assert system.autonomy.tick() == [f"pictures:{run}"] and system.orch.run_status(run) is RunStatus.SUCCEEDED

    client.post("/api/v1/autonomy/switches", json={"clips": False, "renders": False, "pictures": False})
    later = cut(system, client, tmp_path, "Đã tắt", approve_clips=False)
    assert system.autonomy.tick() == [] and client.get(f"/api/v1/projects/{later}").json()["match"]["status"] == "waiting_review"
    system.orch.set_kill_switch(True)
    client.post("/api/v1/autonomy/switches", json={"clips": True})
    assert system.autonomy.tick() == []                                                # the kill switch first, always
