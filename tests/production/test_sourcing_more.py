"""Sourcing: providers and routing, consistency from a project bible, the quality check with its bounded repair loop,
variations, the local still-to-clip provider, and the plan for lines that have no picture."""
import subprocess

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from nexora.adapters.motion import StillMotion, camera_filter
from nexora.api.app import create_app
from nexora.app import build, capabilities
from nexora.core.adapter import Adapter, AdapterError, Capability, ErrorCode, Request, Result
from nexora.core.states import RunStatus
from nexora.modules.sourcing.generate import MAX_REPAIRS, PromptSpec, compile_prompt

from tests.conftest import make_video
from tests.fakes import FakeImageGen, FakeModel, FakeVideoGen, FakeVoice


def drain(system):
    while system.worker.run_once():
        pass


class Named(FakeImageGen):
    """An image provider with its own name, which can be told to fail."""

    def __init__(self, name, *, runs="cloud", fail=None):
        super().__init__()
        self.name, self.runs, self.fail = name, runs, fail

    def describe(self) -> Capability:
        return Capability(name=f"image_gen.{self.name}", operations=("generate",), runs=self.runs)

    def submit(self, request):
        if self.fail:
            self.requests.append(request)
            raise AdapterError(self.fail, f"{self.name} is down")
        result = super().submit(request)
        return Result(outputs={"provider": self.name, "model": "m"}, files=result.files, usage=result.usage)


class Critic(FakeModel):
    """Marks stills by a list of scores, in the order they are shown."""

    def __init__(self, scores):
        super().__init__()
        self.scores, self.seen = list(scores), []

    def submit(self, request):
        if request.operation == "describe" and request.params.get("task") == "quality":
            self.seen.append(request.inputs["images"][0])
            return Result(outputs={"json": {"diem": self.scores.pop(0) if self.scores else 9, "loi": ["tay méo"]}})
        return super().submit(request)


def story(system, lines=("Một chú mèo cam ngồi bên cửa sổ.",)):
    pid = system.planning.create_project("Mèo cam")
    return pid, system.planning.save_script(pid, list(lines))


def test_a_shot_goes_to_the_chosen_provider_and_a_provider_that_is_down_is_passed_over(tmp_path):
    a, b, down = Named("a"), Named("b"), Named("down", fail=ErrorCode.UNAVAILABLE)
    system = build(tmp_path / "data", voice=FakeVoice(), generators=[down, a, b, FakeVideoGen()])
    assert [p["label"] for p in system.generation.available()["image_providers"]] == ["down", "a", "b"]
    assert next(c for c in capabilities(system) if c["pipeline"] == "sourcing.generate")["available"]          # image_gen.<name> answers for image_gen
    pid, script = story(system, ["Mèo ngồi bên cửa sổ.", "Mèo nhìn mưa rơi."])
    shots = system.projects.script(script)["shots"]
    system.projects.annotate_shot(shots[1].shot_id, gen={"provider_image": "image_gen.b"})
    run = system.generation.start(script)
    drain(system)
    assert system.orch.run_status(run) is RunStatus.WAITING_REVIEW
    assert (len(down.requests), len(a.requests), len(b.requests)) == (1, 1, 1)                 # shot 1 fell through to a; shot 2 went straight to b
    assert [system.projects.generations(s.shot_id, kind="keyframe")[-1]["provider"] for s in shots] == ["a", "b"]

    system.orch.set_setting("providers:image_gen", '["image_gen.b", "image_gen.a"]')           # the operator's order of preference
    assert [p["label"] for p in system.generation.providers("image_gen")] == ["b", "a", "down"]


def test_privacy_mode_sends_generation_to_a_local_provider_or_makes_it_wait(tmp_path):
    cloud, local = Named("cloud"), Named("local", runs="local")
    system = build(tmp_path / "data", voice=FakeVoice(), generators=[cloud, local])
    system.orch.set_setting("privacy_local_only", "1")
    pid, script = story(system)
    system.generation.start(script)
    drain(system)
    assert (len(cloud.requests), len(local.requests)) == (0, 1)

    only_cloud = build(tmp_path / "other", voice=FakeVoice(), generators=[Named("cloud")])
    only_cloud.orch.set_setting("privacy_local_only", "1")
    pid, script = story(only_cloud)
    run = only_cloud.generation.start(script)
    drain(only_cloud)
    assert only_cloud.orch.stages(run)[0].blocked_reason == "auth"


def test_the_bible_describes_named_characters_the_same_way_in_every_shot_and_passes_their_pictures(tmp_path):
    image = FakeImageGen()
    system = build(tmp_path / "data", voice=FakeVoice(), generators=[image, FakeVideoGen()])
    Image.new("RGB", (64, 64), "orange").save(tmp_path / "mit.png")
    ref, _ = system.library.ingest(tmp_path / "mit.png")
    drain(system)
    client = TestClient(create_app(system))
    pid = client.post("/api/v1/projects", json={"title": "Mít", "lines": ["Mít ngồi bên cửa sổ.", "Trời mưa ngoài hiên.", "Mít ngủ trên ghế."]}).json()["project_id"]
    view = client.patch(f"/api/v1/projects/{pid}", json={"bible": [
        {"name": "Mít", "kind": "character", "description": "an orange tabby cat with a white chest", "asset_id": ref},
        {"name": "Nét vẽ", "kind": "style", "description": "soft watercolour, muted palette", "asset_id": "ast_missing"}, {"name": " "}]}).json()
    assert [(e["name"], e["asset_id"]) for e in view["bible"]] == [("Mít", ref), ("Nét vẽ", None)]
    client.post(f"/api/v1/projects/{pid}/generate")
    drain(system)
    prompts = [r.inputs["prompt"] for r in image.requests]
    assert ["orange tabby cat" in p for p in prompts] == [True, False, True] and all("soft watercolour" in p for p in prompts)
    assert [len(r.inputs["references"]) for r in image.requests] == [1, 0, 1] and image.requests[0].inputs["references"][0].endswith("mit.png")


def test_a_poor_still_is_made_again_a_bounded_number_of_times_and_the_best_one_is_proposed(tmp_path):
    image, critic = FakeImageGen(), Critic([3, 5, 4])                  # never good enough
    system = build(tmp_path / "data", model=critic, voice=FakeVoice(), generators=[image, FakeVideoGen()])
    pid, script = story(system)
    shot = system.projects.script(script)["shots"][0]
    run = system.generation.start(script)
    drain(system)
    assert len(image.requests) == 1 + MAX_REPAIRS and len({r.params["seed"] for r in image.requests}) == 3
    chosen = system.projects.generations(shot.shot_id, kind="keyframe")
    assert len(chosen) == 1 and chosen[0]["quality"] == {"score": 5, "issues": ["tay méo"], "tries": 3} and chosen[0]["seed"] == image.requests[1].params["seed"]
    assert len(system.projects.generations(shot.shot_id, kind="keyframe_try")) == 2             # the rejected attempts are kept on record
    assert system.orch.run_cost(run) == pytest.approx(0.06) and system.orch.stages(run)[0].outputs == {"keyframes": 1, "repairs": 2}

    good = build(tmp_path / "good", model=Critic([8]), voice=FakeVoice(), generators=[FakeImageGen(), FakeVideoGen()])
    pid, script = story(good)
    good.generation.start(script)
    drain(good)
    assert good.projects.generations(good.projects.script(script)["shots"][0].shot_id)[0]["quality"]["tries"] == 1


def test_a_variation_or_a_changed_brief_remakes_one_still_and_leaves_the_others_alone(tmp_path):
    image, video = FakeImageGen(), FakeVideoGen()
    system = build(tmp_path / "data", voice=FakeVoice(), generators=[image, video])
    client = TestClient(create_app(system))
    pid = client.post("/api/v1/projects", json={"title": "Mèo", "lines": ["Mèo ngồi bên cửa sổ.", "Mèo nhìn mưa rơi."]}).json()["project_id"]
    client.post(f"/api/v1/projects/{pid}/generate")
    drain(system)
    shots = client.get(f"/api/v1/projects/{pid}").json()["shots"]
    first_seed = shots[0]["generation"]["seed"]
    client.post(f"/api/v1/projects/{pid}/generate")
    drain(system)
    assert len(image.requests) == 2                                                             # nothing changed: nothing is made again

    assert client.post(f"/api/v1/shots/{shots[0]['shot_id']}/variation").json() == {"attempt": 1}
    client.patch(f"/api/v1/shots/{shots[1]['shot_id']}", json={"gen": {"subject": "a cat watching rain through a window", "shot_size": "close-up", "camera": "pan left", "bogus": "x"}})
    client.post(f"/api/v1/projects/{pid}/generate")
    drain(system)
    after = client.get(f"/api/v1/projects/{pid}").json()["shots"]
    assert len(image.requests) == 4 and after[0]["generation"]["seed"] != first_seed and after[0]["generation"]["prompt"] == shots[0]["generation"]["prompt"]
    assert "a cat watching rain through a window. close-up" in after[1]["generation"]["prompt"] and after[1]["gen"] == {"subject": "a cat watching rain through a window", "shot_size": "close-up", "camera": "pan left"}

    client.post(f"/api/v1/projects/{pid}/generate/approve")
    drain(system)
    assert len(video.requests) == 2 and video.requests[1].params["camera"] == "pan left"
    client.post(f"/api/v1/projects/{pid}/generate")                                              # run again with nothing changed
    drain(system)
    client.post(f"/api/v1/projects/{pid}/generate/approve")
    drain(system)
    assert len(video.requests) == 2                                                             # clips already made from these stills are kept


def test_the_prompt_carries_the_cast_and_old_records_without_it_still_compile():
    spec = PromptSpec(subject="A cat by a window", cast="Mít: an orange tabby")
    assert compile_prompt(spec, kind="image") == "A cat by a window. medium shot. Mít: an orange tabby. aspect ratio 16:9. Avoid: text, watermark, logo, distorted hands."
    assert "Mít" not in compile_prompt(PromptSpec(subject="A cat"), kind="video")


def test_a_still_becomes_a_moving_clip_on_this_machine(tmp_path):
    Image.new("RGB", (800, 450), "teal").save(tmp_path / "key.png")
    adapter = StillMotion()
    assert adapter.describe().runs == "local" and "zoompan=z='1.12'" in camera_filter("pan left", 50, 1280, 720)
    out = adapter.submit(Request("generate", inputs={"first_frame": str(tmp_path / "key.png")}, params={"out": str(tmp_path / "clip.mp4"), "duration": 2.0, "aspect": "9:16", "camera": "slow pull out"}))
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,nb_frames", "-of", "csv=p=0", out.files[0]], capture_output=True, text=True).stdout.strip()
    assert probe == "720,1280,50"
    with pytest.raises(AdapterError):
        adapter.submit(Request("generate", inputs={"first_frame": str(tmp_path / "missing.png")}, params={"out": str(tmp_path / "x.mp4"), "duration": 1}))


def test_a_generated_story_runs_end_to_end_with_the_local_clip_provider(tmp_path):
    system = build(tmp_path / "data", voice=FakeVoice(), generators=[FakeImageGen(), StillMotion()])
    pid, script = story(system, ["Một chú mèo cam ngồi bên cửa sổ.", "Chú mèo nhìn mưa rơi ngoài hiên."])
    run = system.generation.start(script)
    drain(system)
    system.generation.approve(run)
    drain(system)
    system.generation.approve(run)
    assert system.orch.run_cost(run) == pytest.approx(0.04)                    # the stills cost; the clips, made here, do not
    system.edit.start_render(script)
    drain(system)
    assert system.projects.renders(pid)[0]["qc"]["passed"]


def test_every_line_without_a_picture_gets_the_ways_out_this_machine_has_and_a_list_to_shoot(tmp_path):
    system = build(tmp_path / "data", model=FakeModel(), voice=FakeVoice(), segment_seconds=2.0, judge=False)
    client = TestClient(create_app(system))
    system.library.ingest(make_video(tmp_path / "a.mp4", picture=6))
    drain(system)
    pid = client.post("/api/v1/projects", json={"title": "Chợ sáng", "lines": ["# Ngoài chợ", "chợ rau củ", "tên lửa phóng lên quỹ đạo", "# Về nhà", "con mèo ngủ trên mái nhà"]}).json()["project_id"]
    shots = client.get(f"/api/v1/projects/{pid}").json()["shots"]
    client.patch(f"/api/v1/shots/{shots[2]['shot_id']}", json={"brief": "mèo vàng nằm trên mái ngói", "target_seconds": 6})
    client.post(f"/api/v1/projects/{pid}/match")
    drain(system)
    gaps = client.get(f"/api/v1/projects/{pid}/gaps").json()["gaps"]
    assert [(g["line"], g["scene"], g["seconds"]) for g in gaps] == [(2, "Ngoài chợ", pytest.approx(2.5, abs=1.5)), (3, "Về nhà", 6.0)]
    assert [w["way"] for w in gaps[0]["ways"]][-2:] == ["reword", "shoot"] and not any(w["way"] in ("stock", "generate") for w in gaps[0]["ways"])
    assert "mèo vàng nằm trên mái ngói" in gaps[1]["ways"][-1]["text"] and "6 giây" in gaps[1]["ways"][-1]["text"]
    listing = client.get(f"/api/v1/projects/{pid}/shotlist")
    assert listing.headers["content-type"].startswith("text/markdown") and "attachment" in listing.headers["content-disposition"]
    text = listing.text
    assert "# Danh sách cần quay thêm: Chợ sáng" in text and "## Ngoài chợ" in text and "## Về nhà" in text
    assert "- [ ] Câu 3: mèo vàng nằm trên mái ngói" in text and "Tổng cộng 2 cảnh" in text and "chợ rau củ" not in text

    with_tools = build(tmp_path / "tools", model=FakeModel(), voice=FakeVoice(), judge=False, generators=[FakeImageGen(), FakeVideoGen()])
    pid2, script2 = story(with_tools, ["một câu không có hình"])
    with_tools.sourcing.start_match(script2)
    drain(with_tools)
    assert "generate" in [w["way"] for w in with_tools.sourcing.gap_plan(script2, generate=True)[0]["ways"]]


def test_the_keyless_image_service_reports_a_spent_allowance_as_something_only_the_operator_can_fix(tmp_path):
    import http.server, threading
    from nexora.adapters.pollinations import PollinationsImage
    from nexora.core.adapter import NEEDS_OPERATOR
    import io
    png = io.BytesIO(); Image.new("RGB", (720, 1280), "navy").save(png, "JPEG")
    seen = []

    class Service(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append((self.path, self.headers.get("authorization")))
            if len(seen) > 1:
                self.send_response(402); self.end_headers(); self.wfile.write(b"{}"); return
            self.send_response(200); self.send_header("content-type", "image/jpeg"); self.end_headers(); self.wfile.write(png.getvalue())
        def log_message(self, *a): pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Service)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        adapter = PollinationsImage(host=f"http://127.0.0.1:{server.server_port}", token="abc")
        request = Request("generate", inputs={"prompt": "một chú mèo / bên cửa sổ?"}, params={"out": str(tmp_path / "a.png"), "seed": 2**40 + 5, "aspect": "9:16"})
        result = adapter.submit(request)
        assert Image.open(tmp_path / "a.png").format == "PNG" and result.usage.cost == 0 and adapter.describe().runs == "cloud"
        path, token = seen[0]
        assert "width=720&height=1280" in path and "seed=5" in path and "%2F" in path and "%3F" in path and token == "Bearer abc"     # the prompt cannot break out of its place in the address
        with pytest.raises(AdapterError) as refused:
            adapter.submit(request)
        assert refused.value.code in NEEDS_OPERATOR
    finally:
        server.shutdown()


def test_the_operator_chooses_which_stock_libraries_are_searched(tmp_path):
    from tests.fakes import FakeStock, fake_preview
    class Asked(FakeStock):
        def __init__(self): super().__init__(); self.params = []
        def submit(self, request):
            self.params.append(request.params)
            return super().submit(request)
    stock = Asked()
    system = build(tmp_path / "data", model=FakeModel(), voice=FakeVoice(), segment_seconds=2.0, judge=False, stock=stock, stock_preview=fake_preview)
    client = TestClient(create_app(system))
    assert [s["on"] for s in client.get("/api/v1/generators").json()["stock"]["sources"]] == [True, True, True]
    assert client.post("/api/v1/control/stock-sources", json={"sources": ["bogus"]}).status_code == 422
    chosen = client.post("/api/v1/control/stock-sources", json={"sources": ["nasa", "bogus"]}).json()["stock"]["sources"]
    assert [(s["key"], s["on"]) for s in chosen] == [("archive_org", False), ("nasa", True), ("wikimedia", False)]
    pid = client.post("/api/v1/projects", json={"title": "Vũ trụ", "lines": ["tên lửa phóng lên quỹ đạo"]}).json()["project_id"]
    client.post(f"/api/v1/projects/{pid}/match"); drain(system)
    shot = client.get(f"/api/v1/projects/{pid}").json()["shots"][0]["shot_id"]
    assert client.post(f"/api/v1/shots/{shot}/stock", json={"query": "rocket launch"}).status_code == 200
    assert stock.params[-1]["sources"] == ["nasa"]
