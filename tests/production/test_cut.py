"""The Edit step on FilmCraft: the storyboard made into FilmCraft commands, the cut kept in versions, and a saved cut rendered
(by a stand-in for FilmCraft's engine) into a render that waits for review like any other."""
import json
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from nexora.api.app import create_app
from nexora.app import build
from nexora.core.adapter import Adapter, Capability, Request, Result
from nexora.modules.edit.cut import TICKS

from tests.fakes import FakeModel
from tests.library.test_analysis import film, taken_in
from tests.visual_quality.test_vq import drain


class FakeFilmCraft(Adapter):
    """Renders a test card as long as the cut, and keeps the document it was given."""
    def __init__(self):
        self.documents = []

    def describe(self):
        return Capability(name="filmcraft", operations=("export", "inspect", "build"), runs="local")

    def submit(self, request: Request) -> Result:
        if request.operation == "build":                               # a headless build: a project naming each medium given
            self.built = request.inputs
            return Result(outputs={"document": document([m["name"].split(".")[0] for m in request.inputs["media"] if m["name"].startswith("ver_")]),
                                   "commands": len(request.inputs["commands"])})
        self.documents.append(request.inputs["document"])
        out = Path(request.params["out"])
        out.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=30000/1001:duration=2",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-af", "volume=0.3", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-c:a", "aac", "-shortest", str(out)], check=True)
        return Result(outputs={"result": {"frames": 60, "seconds": 1.0, "render_fps": 60}}, files=(str(out),))


def document(versions: list[str]) -> str:
    """A FilmCraft project naming these media the way the browser editor does."""
    items = {str(k): {"id": k, "name": f"{v}.mp4", "kind": {"Media": {"media": {"File": {"path": f"/files/{v}.mp4"}}}}} for k, v in enumerate(versions, 1)}
    items["99"] = {"id": 99, "name": "Cut", "kind": {"Sequence": {"video_tracks": [{"items": [{}, {}]}], "caption_tracks": [{"captions": [{}]}]}}}
    return json.dumps({"format": "filmcraft-project", "schema_version": 15, "generator": "test", "project": {"name": "t", "items": items}})


def test_the_storyboard_becomes_a_sequence_and_a_saved_cut_is_rendered_for_review(tmp_path):
    system = build(tmp_path / "data", model=FakeModel(), segment_seconds=15.0)
    fake = FakeFilmCraft()
    system.adapters.register(fake)
    client = TestClient(create_app(system))
    for name, src in (("market.mp4", "testsrc2"), ("bars.mp4", "smptebars")):
        taken_in(system, film(tmp_path / name, [(src, 4)]))
    project = system.projects.create_project("Vườn dừa")
    system.projects.save_script(project, ["Chợ rau củ buổi sáng.", "Một con tàu vũ trụ rời bệ phóng."])
    assert client.get(f"/api/v1/projects/{project}/cut/plan").status_code == 409            # no storyboard yet
    client.post(f"/api/v1/projects/{project}/storyboard/from-script")
    client.post(f"/api/v1/projects/{project}/storyboard/run", json={})
    plan = client.get(f"/api/v1/projects/{project}/cut/plan").json()
    ids = [c["id"] for c in plan["commands"]]
    assert ids[0] == "file.newSequence" and plan["commands"][0]["params"]["width"] == 1920 and ids.count("markers.add") == 2
    placed = [c["params"] for c in plan["commands"] if c["id"] == "timeline.place"]
    shots = client.get(f"/api/v1/projects/{project}/storyboard").json()["shots"]
    pictured = [s for s in shots if s["assignment"] and s["assignment"].get("asset_id")]
    assert len(placed) == len(pictured) and placed[0]["sourceIn"] == round(pictured[0]["assignment"]["t_in"] * TICKS)
    assert placed[0]["item"].startswith("$item:ver_") and plan["media"][0]["url"].startswith("/media/ver_")
    assert {m["code"] for m in plan["missing"]} | {f"SC{k}" for k, s in enumerate(shots, 1) if s in pictured} == {f"SC{k}" for k in range(1, len(shots) + 1)}
    assert ids[-1] == "captions.setTrack" and plan["commands"][-1]["params"]["syncLock"]          # captions follow ripples
    caps = [c["params"] for c in plan["commands"] if c["id"] == "captions.add"]
    assert all(b["time"] > a["time"] + a["durationSeconds"] * TICKS for a, b in zip(caps, caps[1:]))   # never touching
    # Saved by the editor: versions, the document handed back, a refused non-project, a restore that adds a version.
    versions = [m["version"] for m in plan["media"]]
    saved = client.post(f"/api/v1/projects/{project}/cut", json={"document": document(versions), "note": "lắp từ storyboard", "source": "storyboard"}).json()
    assert saved["saved"]["version"] == 1 and saved["saved"]["stats"]["sequences"][0]["video_clips"] == 2
    assert client.post(f"/api/v1/projects/{project}/cut", json={"document": "{\"x\":1}"}).status_code == 422
    cut_id = saved["saved"]["cut_id"]
    assert json.loads(client.get(f"/api/v1/projects/{project}/cut/{cut_id}/document").text)["schema_version"] == 15
    client.post(f"/api/v1/projects/{project}/cut", json={"document": document(versions[:1])})
    again = client.post(f"/api/v1/projects/{project}/cut/1/restore").json()
    assert [v["version"] for v in again["versions"]] == [3, 2, 1] and again["versions"][0]["note"] == "quay lại v1"
    # Rendered on "this Mac": the media pointed at the files a final cut reads, the render waits for review.
    newest = again["versions"][0]["cut_id"]
    assert client.post(f"/api/v1/projects/{project}/cut/{newest}/export").status_code == 202
    drain(system)
    sent = fake.documents[-1]
    assert "/files/" not in sent and all(Path(p).is_file() for p in json.loads(sent)["project"]["items"]["1"]["kind"]["Media"]["media"]["File"].values())
    view = client.get(f"/api/v1/projects/{project}").json()
    assert view["render"]["status"] == "waiting_review" and view["renders"][0]["qc"]["source"] == "filmcraft" and view["renders"][0]["qc"]["cut_version"] == 3
    assert client.get(f"/api/v1/projects/{project}/cut").json()["versions"][0]["export"]["status"] == "waiting_review"
    decided = client.post(f"/api/v1/projects/{project}/render/decision", json={"approve": True}).json()
    assert decided["renders"][0]["review"]["approved"] is True


def test_the_sequence_carries_the_narration_the_music_and_its_ducking(tmp_path):
    """A1 says each line (here the operator's own takes), from the start of its shot; A2 holds the project's music under the
    whole cut at its gain, ducked while a line is said; the clip's own sound only where the shot asks for it."""
    system = build(tmp_path / "data", model=FakeModel(), segment_seconds=15.0)
    system.adapters.register(FakeFilmCraft())
    client = TestClient(create_app(system))
    for name, src in (("market.mp4", "testsrc2"), ("bars.mp4", "smptebars")):
        taken_in(system, film(tmp_path / name, [(src, 4)]))
    takes, music = tmp_path / "takes", tmp_path / "bed.wav"
    takes.mkdir()
    for n in (1, 2):
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=300:duration=1.5", str(takes / f"{n}.wav")], check=True)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=500:duration=20", str(music)], check=True)
    project = system.projects.create_project("Vườn dừa")
    system.projects.update_project(project, narration_dir=str(takes), music_path=str(music), music_gain=0.35)
    system.projects.save_script(project, ["Chợ rau củ buổi sáng.", "Người ta pha cà phê."])
    client.post(f"/api/v1/projects/{project}/storyboard/from-script")
    client.post(f"/api/v1/projects/{project}/storyboard/run", json={})
    plan = client.get(f"/api/v1/projects/{project}/cut/plan").json()
    places = [c for c in plan["commands"] if c["id"] == "timeline.place"]
    assert all(p["params"]["audio"] is False for p in places if p["params"]["track"] == "V1")          # the line speaks, not the clip
    voice = [p for p in places if p.get("tag") == "voice"]
    assert len(voice) == 2 and voice[0]["params"]["track"] == "A1" and voice[1]["params"]["seconds"] >= 1.5    # never over the line before
    bed = next(p for p in places if p.get("tag") == "music")
    assert bed["params"]["track"] == "A2" and bed["params"]["seconds"] == 0 and plan["sound"] == {"voice": 2, "music": True, "sfx": 0}
    gain = next(c for c in plan["commands"] if c["id"] == "clip.audioGain")
    assert gain["params"]["clips"] == "$tag:music" and abs(gain["params"]["db"] - 20 * __import__("math").log10(0.35)) < 0.01
    ids = [c["id"] for c in plan["commands"]]
    assert ids.index("essentialSound.generateDucking") > ids.index("essentialSound.setType")
    # The sounds are handed out under the names the cut gives them, and nothing else is.
    names = {m["name"]: m["url"] for m in plan["media"] if m["version"] is None}
    music_name = next(n for n in names if n.startswith("music_"))
    assert client.get(names[music_name]).content == music.read_bytes()
    assert client.get(f"/api/v1/projects/{project}/cut/sound/..%2Fnexora.db").status_code == 404
    # Rendered: every name pointed at its real file.
    doc = json.loads(document([m["version"] for m in plan["media"] if m["version"]]))
    doc["project"]["items"]["50"] = {"id": 50, "name": music_name, "kind": {"Media": {"media": {"File": {"path": f"/files/{music_name}"}}}}}
    relinked, unread = system.cut.relinked(json.dumps(doc), project)
    assert not unread and str(music) in relinked and "/files/" not in relinked


def test_a_spoken_clip_carries_its_transcript_and_the_cut_can_be_built_without_a_browser(tmp_path):
    system = build(tmp_path / "data", model=FakeModel(), segment_seconds=15.0)
    fake = FakeFilmCraft()
    system.adapters.register(fake)
    client = TestClient(create_app(system))
    asset_id = taken_in(system, film(tmp_path / "talk.mp4", [("testsrc2", 6)]))
    system.index.upsert(asset_id, "speech", 0.5, 3.0, "Vườn dừa này đẹp lắm.", data={"words": [
        {"text": "Vườn", "start": 0.5, "end": 0.9, "p": 0.9}, {"text": "dừa", "start": 0.9, "end": 3.0, "p": 0.9}], "speaker": {"value": 0}})
    project = system.projects.create_project("Vườn dừa")
    system.projects.save_script(project, ["Vườn dừa lúc bình minh."])
    url = f"/api/v1/projects/{project}/storyboard"
    client.post(f"{url}/from-script")
    shot = client.post(f"{url}/run", json={}).json()["storyboard"]["shots"][0]
    if shot["assignment"] is None or shot["assignment"].get("asset_id") != asset_id:     # the one recording there is
        system.storyboard.set_state(shot["shot_id"], "needs", assignment={"kind": "footage", "asset_id": asset_id, "t_in": 0.0, "t_out": 3.0, "score": None, "text": ""})
    client.patch(f"{url}/shots/{shot['shot_id']}/treatment", json={"live_sound": True})
    plan = client.get(f"/api/v1/projects/{project}/cut/plan").json()
    sets = [c["params"] for c in plan["commands"] if c["id"] == "transcript.set"]
    assert len(sets) == 1 and sets[0]["item"].startswith("$item:ver_") and sets[0]["transcript"]["language"] == "vi"
    words = sets[0]["transcript"]["words"]
    assert words[0] == {"text": "Vườn", "start": round(0.5 * TICKS), "end": round(0.9 * TICKS), "speaker": 0}
    assert words[1]["end"] - words[1]["start"] == round(0.6 * TICKS)             # a word stretched over a silence keeps its end
    assert not any(c.get("tag") == "voice" for c in plan["commands"])            # the clip speaks: no narration over it
    built = client.post(f"/api/v1/projects/{project}/cut/build").json()
    assert built["saved"]["version"] == 1 and built["saved"]["note"].startswith("lắp từ storyboard")
    assert fake.built["commands"] == plan["commands"] and all(Path(m["path"]).is_file() for m in fake.built["media"])
