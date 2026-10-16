"""Every item gets a code KIND-YYMMDD-NNN once, keeps it, and is shown by a name the operator may change."""
from types import SimpleNamespace as NS

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nexora.api.catalog import add_catalog


class Fake:
    def __init__(self, data_dir):
        self.data_dir = data_dir
        self.titles = {}
        self.items = [{"asset_id": "a1", "kind": "video", "created_at": 1_780_000_000, "title": None},
                      {"asset_id": "a2", "kind": "video", "created_at": 1_780_000_000, "title": None},
                      {"asset_id": "a3", "kind": "image", "created_at": 1_780_000_000, "title": None}]
        probe = {"a1": {"created": "2026-06-05T10:33:10"}, "a2": {"created": "2026-06-05T11:00:00"}, "a3": {"still": True, "created": "2026-06-05T09:00:00"}}
        self.assets = NS(assets=lambda include_trashed=False: self.items, asset=lambda i: next((a for a in self.items if a["asset_id"] == i), None),
                         versions=lambda i: [NS(role="original", metadata={"probe": probe[i]})], path_of=lambda v: f"/x/{id(v)}.mp4")
        self.index = NS(moments=lambda i: [NS(level="video", text="tóm tắt", data={"detail": {"tieu_de": f"Cảnh {i}"}})])
        cuts = [{"render_id": "r1", "project_id": "p1", "created_at": 1_790_000_000, "qc": {}, "review": None}]
        self.projects = NS(projects=lambda include_trashed=False: [{"project_id": "p1", "title": "Dừa"}], renders=lambda pid, previews=False: [] if previews else cuts,
                           render=lambda i: cuts[0] if i == "r1" else None, project=lambda i: {"project_id": "p1", "title": "Dừa"}, used_assets=lambda: {"a1": ["p1"]})
        self.publishing = NS(publications=lambda project_id=None: [{"publication_id": "x", "render_id": "r1", "target": "youtube", "status": "published", "url": None, "title": "Dừa", "published_at": 1}])
        self.library = NS(annotate=lambda i, title=None: self.titles.__setitem__(i, title))


def test_codes_follow_the_convention_and_never_change(tmp_path):
    system = Fake(tmp_path)
    app = FastAPI(); add_catalog(app, system); c = TestClient(app)
    codes = {i["subject"]: i for i in c.get("/api/v1/catalog").json()["items"]}
    assert codes["a1"]["code"] == "FT-260605-001" and codes["a2"]["code"] == "FT-260605-002" and codes["a3"]["code"] == "AN-260605-001"
    assert codes["a1"]["title"] == "Cảnh a1" and codes["r1"]["code"].startswith("BD-") and codes["r1"]["title"] == "Dừa v1"
    system.items.insert(0, {"asset_id": "a0", "kind": "video", "created_at": 1_780_000_000, "title": None})
    system.assets.versions = (lambda old: lambda i: [NS(role="original", metadata={"probe": {"created": "2026-06-05T08:00:00"}})] if i == "a0" else old(i))(system.assets.versions)
    again = {i["subject"]: i["code"] for i in c.get("/api/v1/catalog").json()["items"]}
    assert again["a1"] == "FT-260605-001" and again["a0"] == "FT-260605-003"         # a newcomer takes the next number; nobody is renumbered


def test_a_name_can_be_changed_and_a_code_leads_to_everything(tmp_path):
    system = Fake(tmp_path)
    app = FastAPI(); add_catalog(app, system); c = TestClient(app)
    code = next(i["code"] for i in c.get("/api/v1/catalog").json()["items"] if i["subject"] == "a1")
    assert c.patch(f"/api/v1/catalog/{code}", json={"title": "Cây dừa Bến Tre"}).json()["title"] == "Cây dừa Bến Tre" and system.titles["a1"] == "Cây dừa Bến Tre"
    assert c.patch(f"/api/v1/catalog/{code}", json={"title": " "}).status_code == 422
    cut = next(i["code"] for i in c.get("/api/v1/catalog").json()["items"] if i["subject"] == "r1")
    found = c.get(f"/api/v1/catalog/{cut.lower()}").json()
    assert found["projects"][0]["title"] == "Dừa" and found["publications"][0]["target"] == "youtube"
    assert c.get("/api/v1/catalog/FT-990101-001").status_code == 404
