"""Ideas from the library (design 2026-10-18): the footage grouped and measured first, the model asked only for an angle and
the shots it needs, every shot looked for in the index; a risk blocks; an accepted idea becomes a project. Channels speak in
the prompts and their banned phrases are measured; a template's structure shapes the draft and checks the script; an opening
or an ending is written again several ways and one is chosen as the next version."""
import json

from fastapi.testclient import TestClient

from nexora.api.app import create_app
from nexora.app import build

from tests.fakes import FakeModel
from tests.library.test_analysis import film, taken_in


def _angle(request):
    prompt = request.params["prompt"]
    if "Chợ sáng" in prompt:
        return {"tieu_de": "Một sáng ở chợ quê", "goc_ke": "Đi chợ từ lúc mở hàng", "mau": "Video ngang có lời dẫn",
                "canh": ["cá tươi trên sạp", "chợ rau củ", "tên lửa rời bệ phóng"], "hop_khan_gia": 4, "hop_kenh": 5, "rui_ro": "Thiếu cảnh tên lửa.", "muc_rui_ro": "luu_y"}
    if "Biển" in prompt:
        return {"tieu_de": "Cà phê sáng", "goc_ke": "Một ly cà phê trước khi đi làm", "mau": "Video dọc ngắn",
                "canh": ["pha cà phê", "con đường mòn"], "hop_khan_gia": 3, "rui_ro": "Người trong hình chưa đồng ý xuất hiện.", "muc_rui_ro": "chan"}
    return {"tieu_de": "", "canh": []}


def _setup(tmp_path):
    model = FakeModel()
    model.answers["idea_angle"] = _angle
    system = build(tmp_path / "data", model=model, segment_seconds=15.0)
    client = TestClient(create_app(system))
    market = taken_in(system, film(tmp_path / "market.mp4", [("testsrc2", 12)]))
    cafe = taken_in(system, film(tmp_path / "cafe.mp4", [("smptebars", 12)]))
    system.assets.annotate(market, session="Chợ sáng")
    system.assets.annotate(cafe, session="Biển")
    for asset_id, texts in ((market, ["cá tươi trên sạp", "chợ rau củ đông người"]), (cafe, ["pha cà phê bằng phin", "con đường mòn ven biển"])):
        for k, text in enumerate(texts):
            system.index.upsert(asset_id, "segment", k * 6.0, k * 6.0 + 6.0, text, data={"detail": {"boi_canh": "chợ" if asset_id == market else "quán"}})
    return system, model, client, market, cafe


def test_ideas_are_measured_from_the_library_and_a_risk_blocks_until_a_reason_is_given(tmp_path):
    system, model, client, market, cafe = _setup(tmp_path)
    groups = system.planning.clusters()
    assert {g["name"] for g in groups} >= {"Chợ sáng", "Biển"} and all(g["seconds"] > 0 for g in groups)
    assert "chợ" in next(g for g in groups if g["name"] == "Chợ sáng")["places"]

    asked = []
    model.answers["idea_angle"] = lambda r: asked.append(r.params["prompt"]) or _angle(r)
    client.post("/api/v1/channels", json={"channels": [{"name": "Quê nhà", "platform": "YouTube", "tone": "mộc, chậm", "banned": ["siêu đỉnh"]}]})
    ideas = client.post("/api/v1/ideas", json={"channel": "Quê nhà", "wait": True}).json()["ideas"]
    by = {i["title"]: i for i in ideas}
    market_idea, cafe_idea = by["Một sáng ở chợ quê"], by["Cà phê sáng"]
    # Two of three shots are in the library; the rocket is a gap. The model's opinion about footage is never asked.
    assert [s["covered"] for s in market_idea["shots"]] == [True, True, False] and market_idea["gaps"] == ["tên lửa rời bệ phóng"]
    assert market_idea["shots"][0]["asset_id"] == market and abs(market_idea["coverage"] - 2 / 3) < 0.01
    assert market_idea["scores"]["co_hinh"] == 4 and market_idea["scores"]["moi"] == 5 and market_idea["scores"]["hop_kenh"] == 5
    assert market_idea["status"] == "new" and market_idea["risk"] == "Thiếu cảnh tên lửa." and cafe_idea["status"] == "blocked"                       # a risk blocks, it does not just lower a score
    assert ideas.index(market_idea) < ideas.index(cafe_idea)
    assert all("giọng văn: mộc, chậm" in a and "\"siêu đỉnh\"" in a for a in asked)                 # the channel speaks in every prompt
    assert client.post(f"/api/v1/ideas/{cafe_idea['idea_id']}/accept", json={}).status_code == 409
    taken = client.post(f"/api/v1/ideas/{cafe_idea['idea_id']}/accept", json={"reason": "đã xin phép chủ quán"}).json()
    assert taken["format"] == "portrait" and taken["template"] == "Video dọc ngắn" and taken["channel"] == "Quê nhà"
    assert taken["idea"]["reason"] == "đã xin phép chủ quán" and taken["idea"]["shots"][0]["need"] == "pha cà phê"
    board = client.get(f"/api/v1/projects/{taken['project_id']}/storyboard").json()["shared"]
    assert board["idea"].startswith("Cà phê sáng. Một ly cà phê") and "pha cà phê; con đường mòn" in board["idea"]      # the Storyboard starts from it
    assert client.post(f"/api/v1/ideas/{cafe_idea['idea_id']}/accept", json={"reason": "x"}).status_code == 404     # taken once

    # Proposing again replaces the undecided idea of the same group; the accepted one stays as history.
    again = client.post("/api/v1/ideas", json={"channel": "Quê nhà", "wait": True}).json()["ideas"]
    assert [i["status"] for i in again if i["title"] == "Cà phê sáng"] == ["blocked", "accepted"]
    assert len([i for i in again if i["title"] == "Một sáng ở chợ quê"]) == 1
    fresh = next(i for i in again if i["title"] == "Một sáng ở chợ quê")
    assert client.post(f"/api/v1/ideas/{fresh['idea_id']}/drop").json()["status"] == "dropped"
    assert all(i["status"] != "new" or i["title"] != "Một sáng ở chợ quê" for i in client.get("/api/v1/ideas").json()["ideas"])


def test_a_channel_profile_is_versioned_and_its_banned_phrases_are_measured(tmp_path):
    system, model, client, *_ = _setup(tmp_path)
    save = lambda **c: client.post("/api/v1/channels", json={"channels": [{"name": "Quê nhà", **c}]}).json()["channels"][0]
    assert save(tone="mộc")["version"] == 1 and save(tone="mộc")["version"] == 1 and save(tone="vui", banned="siêu đỉnh\nđỉnh của chóp")["version"] == 2
    pid = client.post("/api/v1/projects", json={"title": "Chợ", "lines": ["Chợ sáng siêu đỉnh.", "Cá tươi trên sạp."]}).json()["project_id"]
    client.patch(f"/api/v1/projects/{pid}", json={"channel": "Quê nhà"})
    seen = []
    model.answers["critique"] = lambda r: seen.append(r.params["prompt"]) or {"nhan_xet": []}
    critique = client.post(f"/api/v1/projects/{pid}/critique").json()["script"]["critique"]
    assert critique[0]["line"] == 1 and "siêu đỉnh" in critique[0]["issue"] and critique[0]["measured"]
    assert "giọng văn: vui" in seen[0] and "đỉnh của chóp" in seen[0]


def test_the_template_shapes_the_draft_and_checks_the_script_and_an_opening_is_chosen_among_alternatives(tmp_path):
    system, model, client, *_ = _setup(tmp_path)
    pid = client.post("/api/v1/projects", json={"title": "Chợ quê"}).json()["project_id"]
    client.post(f"/api/v1/projects/{pid}/template", json={"name": "Video ngang có lời dẫn"})
    asked = []
    model.answers["draft"] = lambda r: asked.append(r.params["prompt"]) or {"phan": [{"ten": "Mở bài", "cau": ["Năm giờ sáng, chợ đã đông."]},
                                                                                   {"ten": "Thân bài", "cau": ["Cá tươi trên sạp.", "Rau củ từ vườn nhà."]},
                                                                                   {"ten": "Kết", "cau": ["Chợ tan, nắng lên."]}]}
    lines = client.post(f"/api/v1/projects/{pid}/draft", json={"topic": "chợ quê"}).json()["lines"]
    assert lines[0] == "# Mở bài" and "# Kết" in lines and "Mở bài (3–8 giây" in asked[0]
    view = client.put(f"/api/v1/projects/{pid}/script", json={"lines": lines}).json()
    rows = {r["label"]: r for r in view["structure"]["segments"]}
    assert rows["Mở bài"]["state"] == "ok" and rows["Thân bài"]["state"] == "short" and view["structure"]["findings"] == [
        "Phần “Thân bài” khoảng 6 giây, ngắn hơn 15–90 giây."]

    model.answers["variant"] = {"phuong_an": [{"ten": "bắt đầu bằng âm thanh", "cau": ["Tiếng rao vang từ đầu ngõ."]},
                                              {"ten": "bắt đầu bằng câu hỏi", "cau": ["Bạn dậy lúc mấy giờ?", "Chợ quê thì đã đông."]}]}
    made = client.post(f"/api/v1/projects/{pid}/variants", json={"part": "opening"}).json()
    assert made["made"] == 3 and [v["label"] for v in made["variants"]] == ["Mở bài A", "Mở bài B", "Mở bài C"]
    c = made["variants"][2]
    assert c["lines"][:3] == ["# Mở bài", "Bạn dậy lúc mấy giờ?", "Chợ quê thì đã đông."] and c["lines"][3:] == lines[2:]      # the rest untouched
    chosen = client.post(f"/api/v1/variants/{c['variant_id']}/choose").json()
    assert chosen["script"]["label"] == "Mở bài C" and chosen["script"]["version"] == 2 and chosen["shots"][0]["text"] == "Bạn dậy lúc mấy giờ?"
    left = client.get(f"/api/v1/projects/{pid}/variants").json()["variants"]
    assert [v["chosen"] is not None for v in left] == [False, False, True]                         # the others stay to choose later


def test_ideas_are_proposed_in_the_background_when_the_library_changes_or_a_week_passes(tmp_path):
    from nexora.app import refresh_ideas
    system, model, client, *_ = _setup(tmp_path)
    assert refresh_ideas(system, now=10_000.0) == 2                                                  # never run: run now
    assert client.get("/api/v1/notifications").json()["items"][0]["kind"] == "ideas"
    assert refresh_ideas(system, now=10_100.0) == -1                                                 # nothing changed
    assert refresh_ideas(system, now=10_000.0 + 8 * 86400) == 2                                      # a week later
    system.orch.set_setting("ideas_auto", "0")
    assert refresh_ideas(system, now=10_000.0 + 30 * 86400) == -1
