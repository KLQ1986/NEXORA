"""Stock in the storyboard and the producer: candidates shown to choose from and watched from their source, only the chosen
one downloaded, the best taken only when the operator allows it, and what was only for choosing cleaned up once the
storyboard is approved (design 2026-10-19)."""
from fastapi.testclient import TestClient

from nexora.api.app import create_app
from nexora.app import after_storyboard_approved, build, fill_gap_from_stock

from tests.fakes import FakeModel, FakeStock, fake_preview
from tests.library.test_analysis import drain, film, taken_in


def _system(tmp_path):
    stock = FakeStock()
    system = build(tmp_path / "data", model=FakeModel(), segment_seconds=15.0, stock=stock, stock_preview=fake_preview)
    return system, stock, TestClient(create_app(system))


def test_a_storyboard_shot_shows_judged_stock_to_watch_and_downloads_only_the_one_chosen(tmp_path):
    system, stock, client = _system(tmp_path)
    taken_in(system, film(tmp_path / "bars.mp4", [("smptebars", 4)]))
    project = system.projects.create_project("Miền Tây")
    system.projects.save_script(project, ["Chợ nổi Cái Răng buổi sáng.", "Ghe về bến."])
    url = f"/api/v1/projects/{project}/storyboard"
    client.post(f"{url}/from-script")
    shot = client.get(url).json()["shots"][0]["shot_id"]
    # Searching shows candidates; nothing is downloaded.
    v = client.post(f"{url}/shots/{shot}/stock", json={}).json()
    opts = next(s for s in v["shots"] if s["shot_id"] == shot)["stock_options"]
    assert v["stock"]["options"] == 1 and stock.downloads == 0
    c = opts[0]
    assert c["preview_url"] == "https://example.org/clip.mp4" and c["source_url"] == "https://example.org/clip" and c["look"] == 9
    thumb = client.get(c["thumb_url"])
    assert thumb.status_code == 200 and thumb.headers["content-type"] == "image/jpeg"
    # The emergency stop: nothing is looked for, nothing fetched.
    system.orch.set_kill_switch(True)
    assert client.post(f"{url}/shots/{shot}/stock", json={}).status_code == 422
    assert client.post(f"{url}/shots/{shot}/use-stock", json={"candidate": c["cid"]}).status_code == 422 and stock.downloads == 0
    system.orch.set_kill_switch(False)
    # Chosen: downloaded now, taken in as licensed stock with where it came from, given to the shot.
    v = client.post(f"{url}/shots/{shot}/use-stock", json={"candidate": c["cid"]}).json()
    a = next(s for s in v["shots"] if s["shot_id"] == shot)["assignment"]
    assert stock.downloads == 1 and a["asset_id"] and "Public Domain" in a["text"]
    asset = system.assets.asset(a["asset_id"])
    rights = system.assets.original(a["asset_id"]).metadata["rights"]
    assert asset["origin"] == "licensed" and rights["project_id"] == project and rights["stock_id"] == "archive_org:clip" and rights["score"] == 9
    assert client.post(f"{url}/shots/{shot}/use-stock", json={"candidate": "stk_nope"}).status_code == 409


def test_the_best_candidate_is_taken_only_when_the_operator_allows_it_and_never_twice_in_a_row(tmp_path):
    system, stock, _ = _system(tmp_path)
    project = system.projects.create_project("Miền Tây")
    script = system.projects.save_script(project, ["ghe chở trái cây trên sông", "ghe chở trái cây ngoài chợ"])
    first, second = (s.shot_id for s in system.projects.script(script)["shots"])
    out = fill_gap_from_stock(system, first, "ghe chở trái cây trên sông")
    assert out == {"found": False, "options": 1} and stock.downloads == 0                     # the switch is off: kept to choose from
    system.autonomy.set_switches({"stock": True})
    assert fill_gap_from_stock(system, first, "ghe chở trái cây trên sông")["found"] and stock.downloads == 1
    # The same clip is the best for the next line too, but it is the picture of the line before: not taken again.
    assert fill_gap_from_stock(system, second, "ghe chở trái cây ngoài chợ")["found"] is False and stock.downloads == 1


def test_approving_the_storyboard_cleans_up_candidates_and_puts_unused_stock_of_the_project_in_the_trash(tmp_path):
    system, stock, client = _system(tmp_path)
    project = system.projects.create_project("Miền Tây")
    system.projects.save_script(project, ["Chợ nổi Cái Răng buổi sáng."])
    url = f"/api/v1/projects/{project}/storyboard"
    client.post(f"{url}/from-script")
    shot = client.get(url).json()["shots"][0]["shot_id"]
    v = client.post(f"{url}/shots/{shot}/stock", json={}).json()
    cid = v["shots"][0]["stock_options"][0]["cid"]
    client.post(f"{url}/shots/{shot}/use-stock", json={"candidate": cid})
    used = client.get(url).json()["shots"][0]["assignment"]["asset_id"]
    # Two more clips fetched for this project but not in the storyboard; one kept with 5 stars; one of another project.
    def stray(name, source, project_id, rating=0):
        aid, _ = system.library.ingest(film(tmp_path / name, [(source, 2)]), origin="licensed", rights={"project_id": project_id})
        if rating:
            system.assets.annotate(aid, rating=rating)
        return aid
    unused, starred, other = stray("a.mp4", "testsrc", project), stray("b.mp4", "rgbtestsrc", project, rating=5), stray("c.mp4", "testsrc2", "prj_other")
    drain(system)
    done = client.post(f"{url}/approve").json()
    assert done["cleaned"] == {"previews": 1, "trashed": 1}
    trashed = {a["asset_id"] for a in system.assets.trashed()}
    assert trashed == {unused} and used not in trashed and starred not in trashed and other not in trashed
    assert system.stock_scout.options(project, shot) == [] and not (system.data_dir / "tmp" / "stock" / project).exists()
    assert after_storyboard_approved(system, project) == {"previews": 0, "trashed": 0}      # once is enough


def test_one_line_whose_stock_search_breaks_does_not_stop_the_producer_step_nor_make_it_start_over(tmp_path):
    from tests.fakes import FakeVoice
    from tests.conftest import make_video
    system, stock, _ = _system(tmp_path)
    system.library.ingest(make_video(tmp_path / "footage.mp4", picture=20)); drain(system)
    asked = []
    def flaky(shot_id, line):
        asked.append(line)
        if len(asked) == 1:
            raise TypeError("a library answered something unexpected")
        return {"found": False, "options": 2}
    system.producer._fill_gap = flaky
    system.adapters._adapters["model"].script = ["cá tươi trên sạp", "tàu vũ trụ bay lên", "tên lửa rời bệ"]
    task_id = system.producer.start("một buổi sáng ở chợ", critique=False)
    for _ in range(12):
        system.producer.advance(task_id); drain(system)
    task = system.producer.task(task_id)
    stock_lines = [e["text"] for e in task["log"] if e["role"] == "Tìm stock"]
    assert task["step"] != "gaps" and len(asked) == len(stock_lines) and "bỏ qua câu này" in stock_lines[0]
