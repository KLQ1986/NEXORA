"""The YouTube publisher against a stand-in for the Data API: upload, the key that prevents a second upload, figures."""
import http.server
import json
import threading
import time
import urllib.parse

import pytest
from fastapi.testclient import TestClient

from nexora.adapters.youtube import YouTubePublisher
from nexora.api.app import create_app
from nexora.app import build
from nexora.core.adapter import AdapterError, ErrorCode

from tests.conftest import make_video
from tests.fakes import FakeModel, FakeVoice


class Tube:
    def __init__(self):
        self.videos, self.tokens, self.lose_answer, self.views = {}, 0, False, 1000
        tube = self

        class Api(http.server.BaseHTTPRequestHandler):
            def _send(self, status, body, headers=()):
                self.send_response(status)
                for k, v in headers: self.send_header(k, v)
                self.send_header("content-type", "application/json"); self.end_headers(); self.wfile.write(json.dumps(body).encode())
            def _body(self): return self.rfile.read(int(self.headers.get("content-length") or 0))
            def _authed(self): return self.headers.get("authorization") == "Bearer access-1"
            def do_POST(self):
                body = self._body()
                if self.path == "/token":
                    form = urllib.parse.parse_qs(body.decode())
                    if form.get("refresh_token") != ["good"]:
                        return self._send(400, {"error": "invalid_grant"})
                    tube.tokens += 1
                    return self._send(200, {"access_token": "access-1", "expires_in": 3600})
                if not self._authed(): return self._send(401, {"error": "unauthorized"})
                tube.pending = json.loads(body)
                self._send(200, {}, [("location", f"http://127.0.0.1:{self.server.server_port}/session/1")])
            def do_PUT(self):
                data = self._body()
                video_id = f"vid{len(tube.videos) + 1}"
                tube.videos[video_id] = {**tube.pending, "bytes": len(data)}
                if tube.lose_answer:
                    tube.lose_answer = False
                    return self._send(503, {"error": "backend error"})
                self._send(200, {"id": video_id})
            def do_GET(self):
                if not self._authed(): return self._send(401, {"error": "unauthorized"})
                url = urllib.parse.urlparse(self.path); q = urllib.parse.parse_qs(url.query)
                if url.path.endswith("/search"):
                    key = q["q"][0].strip('"')
                    return self._send(200, {"items": [{"id": {"videoId": v}} for v, d in tube.videos.items() if key in d["snippet"]["tags"]]})
                video = tube.videos.get(q["id"][0])
                if video is None: return self._send(200, {"items": []})
                self._send(200, {"items": [{"snippet": video["snippet"], "statistics": {"viewCount": str(tube.views), "likeCount": "40", "commentCount": "3"}}]})
            def log_message(self, *a): pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Api)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def adapter(self, refresh="good", **more):
        base = f"http://127.0.0.1:{self.server.server_port}"
        return YouTubePublisher("client", "secret", refresh, api=base, token_url=base + "/token", **more)


@pytest.fixture
def tube():
    tube = Tube()
    yield tube
    tube.server.shutdown()


def packaged(tmp_path, tube):
    system = build(tmp_path / "data", model=FakeModel(), voice=FakeVoice(), segment_seconds=2.0, judge=False, publishers=[tube.adapter()])
    client = TestClient(create_app(system))
    system.library.ingest(make_video(tmp_path / "a.mp4", picture=20))
    while system.worker.run_once(): pass
    pid = client.post("/api/v1/projects", json={"title": "Chợ sáng Hội An", "lines": ["chợ rau củ", "cá tươi trên sạp"]}).json()["project_id"]
    client.post(f"/api/v1/projects/{pid}/match")
    while system.worker.run_once(): pass
    client.post(f"/api/v1/projects/{pid}/match/approve")
    client.post(f"/api/v1/projects/{pid}/render")
    while system.worker.run_once(): pass
    client.post(f"/api/v1/projects/{pid}/render/decision", json={"approve": True})
    render = client.get(f"/api/v1/projects/{pid}").json()["renders"][0]["render_id"]
    client.post(f"/api/v1/renders/{render}/package", json={})
    return system, client, render


def test_a_cut_is_uploaded_private_once_and_an_upload_whose_answer_was_lost_is_found_on_the_channel(tube, tmp_path):
    system, client, render = packaged(tmp_path, tube)
    targets = client.get("/api/v1/publishing").json()["targets"]
    assert {"target": "publish.youtube", "label": "YouTube", "manual": False} in targets and not any(t["target"] == "youtube" for t in targets)
    tube.lose_answer = True                                    # the file arrives, the answer does not
    row = client.post(f"/api/v1/renders/{render}/publish", json={"target": "publish.youtube"}).json()
    assert row["status"] == "unknown" and len(tube.videos) == 1
    row = client.post(f"/api/v1/renders/{render}/publish", json={"target": "publish.youtube"}).json()
    assert row["status"] == "published" and row["url"] == "https://youtu.be/vid1" and len(tube.videos) == 1         # found by its key: not uploaded twice
    sent = tube.videos["vid1"]
    assert sent["status"]["privacyStatus"] == "private" and sent["snippet"]["title"] == "Chợ sáng Hội An" and sent["snippet"]["tags"] == [row["idempotency_key"]] and sent["bytes"] > 10000
    assert tube.tokens == 1                                    # one access token served every call


def test_figures_are_fetched_from_the_platform_when_a_mark_is_reached(tube, tmp_path):
    system, client, render = packaged(tmp_path, tube)
    pub = client.post(f"/api/v1/renders/{render}/publish", json={"target": "publish.youtube"}).json()["publication_id"]
    assert system.publishing.collect() == []                   # just published: no mark reached yet
    system.publishing._set(pub, published_at=time.time() - 26 * 3600)
    assert system.publishing.collect() == [pub]
    snapshot = system.publishing.publication(pub)["snapshots"][0]
    assert snapshot["figures"] == {"views": 1000.0, "likes": 40.0, "comments": 3.0} and 25 < snapshot["hours"] < 27
    assert system.publishing.collect() == [] and client.get("/api/v1/publishing").json()["due"] == []       # taken once for this mark
    tube.videos.clear()                                        # the video is removed from the channel
    system.publishing._set(pub, published_at=time.time() - 80 * 3600)
    assert system.publishing.collect() == [] and len(system.publishing.publication(pub)["snapshots"]) == 1


def test_a_revoked_token_and_a_missing_video_file_are_named(tube, tmp_path):
    from nexora.core.adapter import PrivacyClass, Request
    (tmp_path / "pkg").mkdir()
    request = Request("publish", inputs={"folder": str(tmp_path / "pkg"), "files": ["video.mp4"], "title": "x"}, idempotency_key="k", privacy_class=PrivacyClass.CLOUD_ALLOWED)
    with pytest.raises(AdapterError) as missing:
        tube.adapter().submit(request)
    assert missing.value.code is ErrorCode.MISSING_INPUT
    make_video(tmp_path / "pkg" / "video.mp4", picture=1)
    with pytest.raises(AdapterError) as revoked:
        tube.adapter(refresh="revoked").submit(request)
    assert revoked.value.code is ErrorCode.INVALID_REQUEST and tube.videos == {}
    assert tube.adapter(privacy="everyone").environment() == {"configured": True, "privacy": "private"}       # an unknown setting falls back to private
