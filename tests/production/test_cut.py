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
        return Capability(name="filmcraft", operations=("export", "inspect"), runs="local")

    def submit(self, request: Request) -> Result:
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
