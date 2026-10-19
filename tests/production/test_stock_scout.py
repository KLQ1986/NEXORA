"""The stock scout judges candidates on their previews and downloads nothing until one is chosen (design 2026-10-19)."""
from pathlib import Path

from nexora.core.adapter import Adapter, AdapterError, AdapterRegistry, Capability, ErrorCode, Request, Result
from nexora.modules.sourcing.stock import LOOK_PASS, StockScout


def cand(source, sid, *, thumb=True, duration=10.0, tags=""):
    return {"source": source, "source_id": sid, "source_url": f"https://{source}/{sid}", "download_url": f"https://{source}/{sid}.mp4",
            "preview_url": f"https://{source}/{sid}-sd.mp4", "thumbnail_url": f"https://{source}/{sid}.jpg" if thumb else "", "width": 1920, "height": 1080,
            "duration": duration, "creator": "", "license": "Public domain", "tags": tags, "query": ""}


class Stock(Adapter):
    """OpenMontage's keyless libraries: answers per query; a query in `fail` fails."""
    def __init__(self, by_query, name="stock"):
        self.by_query, self.name, self.asked, self.downloads = by_query, name, [], []

    def describe(self):
        return Capability(name=self.name, operations=("candidates", "download"), runs="cloud")

    def submit(self, request):
        if request.operation == "download":
            c = request.inputs["candidate"]
            path = Path(request.params["out_dir"]) / f"{c['source']}_{c['source_id']}.mp4"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"video")
            self.downloads.append(c["source_id"])
            return Result(outputs={"path": str(path)}, files=(str(path),))
        self.asked.append((tuple(request.inputs["queries"]), request.params.get("lang")))
        out = []
        for q in request.inputs["queries"]:
            got = self.by_query.get(q, [])
            if isinstance(got, Exception):
                raise got
            out += got
        return Result(outputs={"candidates": out, "errors": {}})


class Pictures(Adapter):
    """SigLIP: a picture's vector says which candidate it is; the words' vector favours `liked`."""
    def __init__(self, liked):
        self.liked = liked

    def describe(self):
        return Capability(name="picture_text", operations=("images", "texts"), runs="local")

    def submit(self, request):
        if request.operation == "images":
            return Result(outputs={"vectors": [[1.0, 0.0] if any(l in Path(p).read_text() for l in self.liked) else [0.2, 1.0] for p in request.inputs["images"]]})
        return Result(outputs={"vectors": [[1.0, 0.0]]})


class Model(Adapter):
    """Keywords for the line; the look gives `marks` by preview file (by default 2); `down` makes every look fail."""
    def __init__(self, marks=None, down=False):
        self.marks, self.down, self.looked = marks or {}, down, []

    def describe(self):
        return Capability(name="model", operations=("chat", "describe"), runs="local")

    def submit(self, request):
        if request.operation == "chat":
            return Result(outputs={"json": {"en": ["floating market boats", "river boats"], "vi": ["chợ nổi"], "names": ["Cái Răng"]}})
        if self.down:
            raise AdapterError(ErrorCode.UNAVAILABLE, "ollama is down")
        image = Path(request.inputs["images"][0]).read_text()          # the preview's file holds its address (see fetch)
        self.looked.append(image)
        mark = next((m for k, m in self.marks.items() if k in image), 2)
        return Result(outputs={"json": {"phu_hop": mark, "ly_do": "giả lập"}})


def fetch(url, path):
    if "broken" in url:
        raise AdapterError(ErrorCode.UNAVAILABLE, "404")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(url.encode())             # the preview's file carries its address, so the fakes can tell them apart
    return Path(path)


def scout(tmp_path, *, stock, api=None, model=None, liked=("wikimedia/1",), frame=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    reg = AdapterRegistry()
    for a in (stock, api, model or Model(), Pictures(liked)):
        if a is not None:
            reg.register(a)
    frames = []

    def grab(url, out):
        frames.append(url)
        if frame is None:
            return None
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_bytes(url.encode())
        return Path(out)
    return StockScout(tmp_path / "db.sqlite", reg, tmp_path / "tmp", fetch=fetch, frame=grab), frames


def test_candidates_are_found_in_each_librarys_words_judged_on_their_previews_and_none_is_downloaded(tmp_path):
    stock = Stock({"floating market boats": [cand("wikimedia", "1"), cand("archive_org", "2")], "Cái Răng": [cand("wikimedia", "1")]})
    api = Stock({"chợ nổi": [cand("pexels", "3")], "floating market boats": [cand("pixabay", "4")]}, name="stock_api")
    model = Model(marks={"wikimedia": 8})
    s, _ = scout(tmp_path, stock=stock, api=api, model=model)
    found = s.find("prj_1", "shot_1", "Chợ nổi Cái Răng lúc rạng sáng.", seconds=6)
    assert stock.asked == [(("floating market boats", "Cái Răng"), None)]                   # keyless libraries: English and the names
    assert sorted(api.asked) == [(("chợ nổi",), "vi"), (("floating market boats",), "en")]    # Pexels/Pixabay: Vietnamese and English
    assert [c["source"] for c in found][0] == "wikimedia" and len(found) == 4               # deduplicated; the one the model passed first
    assert found[0]["look"] == 8 and found[0]["why"] == "giả lập" and len(model.looked) == 3  # only the first three are looked at
    assert not stock.downloads and not api.downloads and not list((tmp_path / "tmp").rglob("*.mp4"))
    assert s.best("prj_1", "shot_1")["source_id"] == "1" and s.options("prj_1", "shot_1")[0]["cid"] == found[0]["cid"]
    # The one chosen is downloaded, from the library that found it.
    path = s.fetch(found[0]["cid"], tmp_path / "media")
    assert path.is_file() and stock.downloads == ["1"]
    assert s.best("prj_1", "shot_1", avoid={"wikimedia:1"}) is None                        # the next shot does not take it again


def test_broader_words_are_tried_only_while_nothing_passes_and_a_short_clip_is_left_out(tmp_path):
    stock = Stock({"floating market boats": [cand("archive_org", "2")], "river boats": [cand("wikimedia", "1"), cand("nasa", "9", duration=1.0)]})
    s, _ = scout(tmp_path, stock=stock, model=Model(marks={"wikimedia": 7}))
    found = s.find("prj_1", "shot_1", "Thuyền trên sông.", seconds=6)
    assert [q for q, _ in stock.asked] == [("floating market boats", "Cái Răng"), ("river boats",)]
    assert {c["source"] for c in found} == {"archive_org", "wikimedia"}                     # the 1 s clip is too short for a 6 s shot
    stock.asked.clear()
    passing = Stock({"floating market boats": [cand("wikimedia", "1")]})
    s2, _ = scout(tmp_path / "b", stock=passing, model=Model(marks={"wikimedia": LOOK_PASS}))
    s2.find("prj_1", "shot_1", "Thuyền trên sông.", seconds=6)
    assert len(passing.asked) == 1                                                          # it passed: no broader search


def test_a_library_that_fails_leaves_the_others_and_a_clip_without_a_preview_is_judged_on_a_frame_read_from_its_source(tmp_path):
    stock = Stock({"floating market boats": [cand("wikimedia", "1", thumb=False)], "Cái Răng": AdapterError(ErrorCode.UNAVAILABLE, "timeout")})
    api = Stock({"chợ nổi": AdapterError(ErrorCode.UNAVAILABLE, "429"), "floating market boats": [cand("pexels", "3")]}, name="stock_api")
    s, frames = scout(tmp_path, stock=stock, api=api, frame=True, model=Model(marks={"wikimedia": 9}))
    found = s.find("prj_1", "shot_1", "Chợ nổi.", seconds=4)
    # The keyless call failed as a whole on the names; Pexels in English still answered.
    assert {c["source"] for c in found} == {"pexels"}
    stock2 = Stock({"floating market boats": [cand("wikimedia", "1", thumb=False)]})
    s2, frames2 = scout(tmp_path / "b", stock=stock2, frame=True, model=Model(marks={"wikimedia": 9}))
    got = s2.find("prj_1", "shot_1", "Chợ nổi.", seconds=4)
    assert frames2 == ["https://wikimedia/1-sd.mp4"] and got[0]["look"] == 9 and got[0]["thumb"]


def test_without_the_vision_model_nothing_is_chosen_and_forgetting_a_project_removes_its_candidates_and_previews(tmp_path):
    stock = Stock({"floating market boats": [cand("wikimedia", "1"), cand("archive_org", "broken")]})
    s, _ = scout(tmp_path, stock=stock, model=Model(down=True))
    found = s.find("prj_1", "shot_1", "Chợ nổi.", seconds=4)
    assert found and all(c["look"] is None for c in found) and s.best("prj_1", "shot_1") is None
    assert any(c["thumb"] is None for c in found)                       # a preview that could not be fetched: no picture, still offered
    s.find("prj_2", "shot_9", "Chợ nổi.", seconds=4)
    assert s.forget("prj_1") == 2 and s.options("prj_1", "shot_1") == [] and not (tmp_path / "tmp" / "prj_1").exists()
    assert s.options("prj_2", "shot_9")                                  # another project's candidates stay
