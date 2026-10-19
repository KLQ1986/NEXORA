"""Stock candidates are found without downloading anything: OpenMontage's keyless libraries through its sources, Pexels and
Pixabay asked by NEXORA in the language of the words (design 2026-10-19, section 1)."""
import io
import json
import urllib.parse

import pytest

from nexora.adapters import openmontage, stock_api
from nexora.core.adapter import AdapterError, Request
from nexora.core.process import Completed


def test_openmontage_lists_candidates_without_downloading_and_fetches_only_the_one_asked_for(tmp_path, monkeypatch):
    (tmp_path / "om").mkdir()
    sent = []

    def fake(cmd, *, timeout, cwd=None, stdin=None, env=None):
        req = json.loads(stdin)
        sent.append(req)
        if req["op"] == "candidates":
            out = {"candidates": [{"source": "wikimedia", "source_id": "7", "source_url": "https://w/7", "download_url": "https://w/7.webm",
                                   "thumbnail_url": "https://w/7.jpg", "kind": "video", "duration": 12.0, "license": "CC-BY", "source_tags": "boats", "query": req["queries"][0]}],
                   "errors": {"nasa": "timed out"}}
        else:
            out = {"path": req["out_path"]}
        return Completed(0, "@@NEXORA@@" + json.dumps(out), "")
    monkeypatch.setattr(openmontage, "run_process", fake)
    stock = openmontage.OpenMontageStock(tmp_path / "om")
    found = stock.submit(Request("candidates", inputs={"queries": ["river market boats"]}))
    c = found.outputs["candidates"][0]
    assert sent[0]["sources"] == ["archive_org", "nasa", "wikimedia"] and "output_dir" not in json.dumps(sent[0])
    assert (c["source"], c["preview_url"], c["tags"], c["query"]) == ("wikimedia", "https://w/7.webm", "boats", "river market boats")
    assert found.outputs["errors"] == {"nasa": "timed out"} and not found.files                 # nothing was downloaded
    got = stock.submit(Request("download", inputs={"candidate": c}, params={"out_dir": str(tmp_path / "in")}))
    assert sent[1]["op"] == "download" and sent[1]["candidate"]["source_id"] == "7" and got.files == (str(tmp_path / "in" / "wikimedia_7.webm"),)


class Answers:
    def __init__(self, by_host):
        self.by_host, self.asked = by_host, []

    def __call__(self, req, timeout=None):
        url = req.full_url
        self.asked.append((url, dict(req.header_items())))
        host = urllib.parse.urlparse(url).hostname
        body = self.by_host[host]
        if isinstance(body, Exception):
            raise body
        return io.BytesIO(json.dumps(body).encode())


PEXELS = {"videos": [{"id": 11, "url": "https://www.pexels.com/video/11/", "image": "https://images.pexels.com/11.jpg", "duration": 9, "user": {"name": "An"},
                      "video_files": [{"link": "https://v.pexels.com/11-uhd.mp4", "width": 3840, "height": 2160, "file_type": "video/mp4"},
                                      {"link": "https://v.pexels.com/11-sd.mp4", "width": 640, "height": 360, "file_type": "video/mp4"},
                                      {"link": "https://v.pexels.com/11-tiny.mp4", "width": 320, "height": 180, "file_type": "video/mp4"}]}]}
PIXABAY = {"hits": [{"id": 22, "pageURL": "https://pixabay.com/videos/22/", "tags": "chợ nổi, thuyền", "duration": 14, "user": "Binh",
                     "videos": {"large": {"url": "https://cdn.pixabay.com/22-large.mp4", "width": 1920, "height": 1080, "thumbnail": "https://cdn.pixabay.com/22-l.jpg"},
                                "medium": {"url": "https://cdn.pixabay.com/22-medium.mp4", "width": 1280, "height": 720, "thumbnail": "https://cdn.pixabay.com/22-m.jpg"},
                                "tiny": {"url": "https://cdn.pixabay.com/22-tiny.mp4", "width": 640, "height": 360}}}]}


def test_pexels_and_pixabay_are_asked_in_the_language_of_the_words_and_give_a_small_file_to_watch_and_a_large_one_to_fetch(monkeypatch):
    answers = Answers({"api.pexels.com": PEXELS, "pixabay.com": PIXABAY})
    monkeypatch.setattr(stock_api.urllib.request, "urlopen", answers)
    api = stock_api.StockApi(pexels_key="pk", pixabay_key="xk")
    found = api.submit(Request("candidates", inputs={"queries": ["chợ nổi Cái Răng"]}, params={"lang": "vi", "per_query": 6})).outputs
    (pex_url, pex_headers), (pix_url, _) = answers.asked
    assert "locale=vi-VN" in pex_url and pex_headers.get("Authorization") == "pk"
    assert "lang=vi" in pix_url and "key=xk" in pix_url
    pex, pix = found["candidates"]
    assert (pex["preview_url"], pex["download_url"], pex["license"]) == ("https://v.pexels.com/11-sd.mp4", "https://v.pexels.com/11-uhd.mp4", "Pexels License")
    assert (pix["preview_url"], pix["download_url"], pix["thumbnail_url"]) == ("https://cdn.pixabay.com/22-tiny.mp4", "https://cdn.pixabay.com/22-large.mp4", "https://cdn.pixabay.com/22-m.jpg")
    assert pix["tags"] == "chợ nổi, thuyền" and pex["query"] == "chợ nổi Cái Răng"


def test_a_library_that_fails_leaves_the_other_and_one_without_a_key_is_not_asked(monkeypatch):
    answers = Answers({"api.pexels.com": OSError("429 too many requests"), "pixabay.com": PIXABAY})
    monkeypatch.setattr(stock_api.urllib.request, "urlopen", answers)
    found = stock_api.StockApi(pexels_key="pk", pixabay_key="xk").submit(Request("candidates", inputs={"queries": ["boats"]})).outputs
    assert [c["source"] for c in found["candidates"]] == ["pixabay"] and "pexels" in found["errors"]
    only = stock_api.StockApi(pixabay_key="xk")
    assert only.sources() == ["pixabay"]
    with pytest.raises(AdapterError):
        stock_api.StockApi().submit(Request("candidates", inputs={"queries": ["boats"]}))
