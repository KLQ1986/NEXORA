"""FilmCraft's web build served for the Edit step: refused until it is set up, handed out isolated as its authors ask, and
refused again when a file of code is not the one that was pinned."""
from fastapi.testclient import TestClient

from nexora.adapters import pinned
from nexora.api.app import create_app
from nexora.app import build
from tests.fakes import FakeModel


def test_filmcraft_is_served_only_as_pinned(tmp_path, monkeypatch):
    system = build(tmp_path / "data", model=FakeModel())
    client = TestClient(create_app(system))
    assert client.get("/filmcraft/").status_code == 404                   # not set up: says how
    root = tmp_path / "data" / "tools" / "filmcraft-web" / pinned.FILMCRAFT_VERSION
    root.mkdir(parents=True)
    page, code = b"<!doctype html><title>FilmCraft</title>", b"export default 1;"
    (root / "index.html").write_bytes(page)
    (root / "filmcraft_web.js").write_bytes(code)
    import hashlib
    monkeypatch.setattr(pinned, "FILMCRAFT_INDEX", hashlib.sha256(page).hexdigest())
    monkeypatch.setitem(pinned.PINS, "filmcraft_web.js", hashlib.sha256(code).hexdigest())
    r = client.get("/filmcraft/")
    assert r.status_code == 200 and r.headers["cross-origin-embedder-policy"] == "require-corp" and r.headers["cross-origin-opener-policy"] == "same-origin"
    assert client.get("/filmcraft/filmcraft_web.js").headers["content-type"].startswith("text/javascript")
    (root / "filmcraft_web.js").write_bytes(b"export default 2;")             # swapped after it was pinned
    assert client.get("/filmcraft/filmcraft_web.js").status_code == 409
    (root / "index.html").write_bytes(page + b"<script>fetch('//elsewhere')</script>")
    assert client.get("/filmcraft/").status_code == 409
    assert client.get("/filmcraft/../../nexora.db").status_code == 404     # nothing outside the build
