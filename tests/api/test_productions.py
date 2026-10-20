"""Projects of videos (design 2026-10-18): a production holds several videos (one video = one script = one storyboard) and
what they share; a change reaches the videos still on the production's value; a total budget; a mission's videos in one
production; projects made before productions existed become productions of one video."""
import json
import sqlite3

from fastapi.testclient import TestClient

from nexora.api.app import create_app
from nexora.app import build, production_budget_left

from tests.fakes import FakeModel, FakeVoice


def _setup(tmp_path):
    system = build(tmp_path / "data", model=FakeModel(), voice=FakeVoice())
    system.orch.set_setting("channels", json.dumps([{"name": "Biển", "version": 2}, {"name": "Phố", "version": 1}]))
    return system, TestClient(create_app(system))


def test_videos_made_before_productions_become_productions_of_one_video(tmp_path):
    system, client = _setup(tmp_path)
    first = system.projects.create_project("Chợ sáng")
    with sqlite3.connect(tmp_path / "data" / "nexora.db") as c:                         # as a database from before productions
        c.execute("UPDATE projects SET production_id = NULL, channel = 'Biển', voice = 'Linh'")
        c.execute("DELETE FROM productions")
    assert system.productions.adopt_loose() == 1 and system.productions.adopt_loose() == 0          # once
    video = system.projects.project(first)
    d = system.productions.get(video["production_id"])
    assert d["title"] == "Chợ sáng" and d["channel"] == "Biển" and d["voice"] == "Linh"


def test_a_production_shares_its_values_with_its_videos_until_one_is_set_on_its_own(tmp_path):
    system, client = _setup(tmp_path)
    d = client.post("/api/v1/productions", json={"title": "Series biển"}).json()
    pid = d["production_id"]
    assert pid.startswith("prd_") and client.post("/api/v1/productions", json={"title": " "}).status_code == 422
    client.patch(f"/api/v1/productions/{pid}", json={"channel": "Biển", "template": "Video dọc ngắn", "voice": "Linh"})
    a = client.post("/api/v1/projects", json={"title": "Sáng", "production_id": pid}).json()
    b = client.post("/api/v1/projects", json={"title": "Chiều", "production_id": pid}).json()
    va = system.projects.project(a["project_id"])
    assert va["production_id"] == pid and va["channel"] == "Biển" and va["channel_version"] == 2 and va["template"] == "Video dọc ngắn" and va["voice"] == "Linh"
    assert a["production"] == {"production_id": pid, "title": "Series biển"}

    # Video B is given its own voice; the production's change reaches A, not B.
    client.patch(f"/api/v1/projects/{b['project_id']}", json={"voice": "Nam"})
    client.patch(f"/api/v1/productions/{pid}", json={"voice": "Mai", "channel": "Phố"})
    assert system.projects.project(a["project_id"])["voice"] == "Mai" and system.projects.project(b["project_id"])["voice"] == "Nam"
    assert {system.projects.project(x["project_id"])["channel"] for x in (a, b)} == {"Phố"}
    assert client.patch(f"/api/v1/productions/{pid}", json={"channel": "Không có"}).status_code == 422

    view = client.get(f"/api/v1/productions/{pid}").json()
    assert view["videos"] == [b["project_id"], a["project_id"]] and [p["title"] for p in view["projects"]] == ["Chiều", "Sáng"]
    assert any(x["production_id"] == pid for x in client.get("/api/v1/productions").json()["productions"])

    # A video without a production named has one of its own; a video moves to another production; an empty one is removed.
    lone = client.post("/api/v1/projects", json={"title": "Một mình"}).json()
    other = system.projects.project(lone["project_id"])["production_id"]
    assert other != pid and system.productions.get(other)["title"] == "Một mình"
    assert client.delete(f"/api/v1/productions/{other}").status_code == 409                      # it still has a video
    client.patch(f"/api/v1/projects/{lone['project_id']}", json={"production_id": pid})
    assert system.projects.project(lone["project_id"])["production_id"] == pid
    assert client.delete(f"/api/v1/productions/{other}").status_code == 200 and system.productions.get(other) is None


def test_a_production_total_budget_counts_every_video(tmp_path):
    system, client = _setup(tmp_path)
    pid = client.post("/api/v1/productions", json={"title": "Có ngân sách"}).json()["production_id"]
    a = client.post("/api/v1/projects", json={"title": "A", "production_id": pid}).json()["project_id"]
    b = client.post("/api/v1/projects", json={"title": "B", "production_id": pid}).json()["project_id"]
    assert production_budget_left(system.projects, system.productions, system.generation, a) is None    # no total set
    client.patch(f"/api/v1/productions/{pid}", json={"budget_cap": 1.0})
    system.generation.spent = lambda project_id: {a: 0.3, b: 0.5}.get(project_id, 0.0)
    assert round(production_budget_left(system.projects, system.productions, system.generation, a), 2) == 0.2
    assert client.patch(f"/api/v1/productions/{pid}", json={"budget_cap": -1}).status_code == 422


def test_a_mission_makes_one_production_of_its_videos_or_adds_to_the_one_named(tmp_path):
    system, client = _setup(tmp_path)
    plan = {"loai": "video", "muc_tieu": "buổi sáng ở chợ", "tieu_de": "Chợ sáng", "so_video": 2, "dinh_dang": "portrait", "so_cau": 3}
    system.adapters._adapters["model"].answers["mission_plan"] = plan
    m = client.post("/api/v1/missions", json={"text": "làm 2 video về chợ"}).json()
    done = client.post(f"/api/v1/missions/{m['mission_id']}/confirm").json()
    owners = {system.projects.project(p)["production_id"] for p in done["links"]["projects"]}
    assert len(owners) == 1 and system.productions.get(owners.pop())["title"] == "Chợ sáng"
    pid = client.post("/api/v1/productions", json={"title": "Của tôi"}).json()["production_id"]
    client.patch(f"/api/v1/productions/{pid}", json={"voice": "Linh"})
    m2 = client.post("/api/v1/missions", json={"text": "làm 2 video nữa", "production_id": pid}).json()
    assert m2["plan"]["production_id"] == pid
    done2 = client.post(f"/api/v1/missions/{m2['mission_id']}/confirm").json()
    assert all(system.projects.project(p)["production_id"] == pid and system.projects.project(p)["voice"] == "Linh" for p in done2["links"]["projects"])


def test_a_production_lists_the_missions_given_for_it_and_mission_control_filters_by_it(tmp_path):
    system, client = _setup(tmp_path)
    plan = {"loai": "video", "muc_tieu": "buổi sáng ở chợ", "tieu_de": "Chợ sáng", "so_video": 1, "dinh_dang": "portrait", "so_cau": 3}
    system.adapters._adapters["model"].answers["mission_plan"] = plan
    pid = client.post("/api/v1/productions", json={"title": "Chợ"}).json()["production_id"]
    given = client.post("/api/v1/missions", json={"text": "làm video chợ", "production_id": pid}).json()
    assert given["production_id"] == pid                                                          # kept as soon as it is planned
    loose = client.post("/api/v1/missions", json={"text": "làm video biển"}).json()
    assert loose["production_id"] is None
    client.post(f"/api/v1/missions/{loose['mission_id']}/confirm")
    made = system.missions.store.get(loose["mission_id"])["production_id"]                         # the production its videos went into
    assert made and made != pid and system.productions.get(made)["title"] == "Chợ sáng"

    view = client.get(f"/api/v1/productions/{pid}").json()
    assert [m["mission_id"] for m in view["missions"]] == [given["mission_id"]] and view["missions"][0]["status"] == "planned"
    listed = client.get("/api/v1/missions", params={"production": pid}).json()
    assert [m["mission_id"] for m in listed["missions"]] == [given["mission_id"]] and listed["missions"][0]["production"] == {"production_id": pid, "title": "Chợ"}
    every = client.get("/api/v1/missions").json()
    assert {d["production_id"] for d in every["productions"]} == {pid, made}
    assert client.get(f"/api/v1/missions/{given['mission_id']}").json()["production"]["title"] == "Chợ"

    # An empty production removed: the mission planned for it keeps its record and, carried out, makes a production of its own.
    assert client.delete(f"/api/v1/productions/{pid}").status_code == 200
    assert system.missions.store.get(given["mission_id"])["production_id"] is None
    from nexora.core.missions import MissionStore
    assert MissionStore(tmp_path / "data" / "nexora.db").get(given["mission_id"])["production_id"] is None     # not brought back at start-up
    done = client.post(f"/api/v1/missions/{given['mission_id']}/confirm").json()
    assert system.productions.get(system.projects.project(done["links"]["projects"][0])["production_id"]) is not None


def test_missions_made_before_take_the_production_of_their_first_video(tmp_path):
    system, client = _setup(tmp_path)
    plan = {"loai": "video", "muc_tieu": "chợ", "tieu_de": "Chợ", "so_video": 1, "dinh_dang": "portrait", "so_cau": 3}
    system.adapters._adapters["model"].answers["mission_plan"] = plan
    m = client.post("/api/v1/missions", json={"text": "làm video chợ"}).json()
    done = client.post(f"/api/v1/missions/{m['mission_id']}/confirm").json()
    owner = system.projects.project(done["links"]["projects"][0])["production_id"]
    with sqlite3.connect(tmp_path / "data" / "nexora.db") as c:                         # as a database from before missions kept it
        c.execute("UPDATE missions SET production_id = NULL")
    from nexora.core.missions import MissionStore
    assert MissionStore(tmp_path / "data" / "nexora.db").get(m["mission_id"])["production_id"] == owner
