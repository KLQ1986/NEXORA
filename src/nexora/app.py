"""Composition root: builds the system from its parts. The only place that knows every layer."""
import json
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from nexora.adapters.graphics import CaptionAdapter
from nexora.adapters.media import FFmpegAdapter, FFprobeAdapter
from nexora.core.adapter import AdapterRegistry
from nexora.core.adapter import Adapter, AdapterError, PrivacyClass, Request
from nexora.core.assets import AssetStore
from nexora.core.index import MomentIndex
from nexora.core.orchestrator import Orchestrator
from nexora.agents.autonomy import Autonomy
from nexora.agents.commands import Commands
from nexora.agents.producer import Producer
from nexora.core.pipeline import PipelineRegistry
from nexora.core.schedule import in_window
from nexora.core.projects import ProjectStore
from nexora.core.states import RunStatus, StageStatus
from nexora.core.worker import Worker
from nexora.modules.library.ingest import Library
from nexora.core.intelligence import VideoIntelligence
from nexora.core.intelligence_store import IntelligenceStore
from nexora.modules.intelligence.service import Intelligence
from nexora.modules.intelligence.analysis import Analysis
from nexora.modules.intelligence.profiler import Profiler
from nexora.modules.intelligence.structure import Rules, boundaries
from nexora.modules.distribution.package import Distribution
from nexora.modules.distribution.publish import Publishing
from nexora.modules.edit.render import Edit
from nexora.modules.edit.roughcut import RoughCut
from nexora.modules.intelligence.transcribe import Transcription
from nexora.modules.intelligence.understand import Understanding
from nexora.modules.planning.scripts import Planning
from nexora.modules.quality.evaluation import Evaluation
from nexora.modules.quality.fields import Fields
from nexora.modules.quality.qc import caption_findings, package_checks, picture_and_sound
from nexora.modules.quality.review import review_cut
from nexora.modules.quality.rights import rights_report
from nexora.modules.quality.watch import Viewer
from nexora.modules.sourcing.generate import Generation
from nexora.modules.sourcing.match import Sourcing


@dataclass
class System:
    data_dir: Path
    orch: Orchestrator
    assets: AssetStore
    adapters: AdapterRegistry
    registry: PipelineRegistry
    worker: Worker
    library: Library
    index: MomentIndex
    projects: ProjectStore
    planning: Planning
    sourcing: Sourcing
    edit: Edit
    distribution: Distribution
    generation: Generation
    workers: list = None            # one worker per lane, for a long-running server
    producer: Producer = None
    productions: "ProductionStore" = None        # what the interface calls a project: several videos and what they share
    roughcut: RoughCut = None
    commands: Commands = None
    viewer: Viewer = None
    evaluation: Evaluation = None
    fields: "Fields" = None
    intelligence: "Intelligence" = None          # the analysis domain: the only writer of the canonical model
    vi: "VideoIntelligence" = None               # the canonical model, read by every other module
    extractor: "Extractor" = None                # pieces of a recording taken out to be used elsewhere
    vq: "VisualQualityService" = None            # Visual Quality: profiles, recipes, previews (the only writer of vq_*)
    vq_reader: "VisualQuality" = None            # what every other module reads of Visual Quality
    publishing: Publishing = None
    autonomy: Autonomy = None
    storyboard: "Storyboard" = None              # a project's storyboard: scenes, shot specs and their versions, the conversation
    storyboard_planner: "StoryboardPlanner" = None
    director: "Director" = None                  # carries the storyboard's shots to acceptance, and holds the conversation
    missions: "Missions" = None                  # Mission Control: the operator's missions, planned, checked and carried out
    stock_scout: "StockScout" = None             # stock judged on its previews before anything is downloaded


def _stock_reason(c: dict) -> str:
    seen = f" Mô hình chấm ảnh xem trước {c['look']}/10: {c.get('why') or ''}".rstrip() if c.get("look") is not None else ""
    return f"Clip stock từ {c.get('source')}. Giấy phép: {c.get('license')}. Nguồn: {c.get('source_url')}.{seen}"


def use_stock_candidate(system: "System", cid: str, *, shot_id: str) -> dict:
    """A stock candidate chosen for a shot (a storyboard shot or a script line): only now is it downloaded, taken into the
    Library as licensed footage with where it came from, and given to the shot."""
    c = system.stock_scout.candidate(cid)
    if c is None:
        raise LookupError(cid)
    if system.orch.kill_switch():
        raise ValueError("Đang dừng khẩn cấp: không tải clip stock")
    path = system.stock_scout.fetch(cid, system.data_dir / "media" / "stock")
    rights = {"source": c.get("source"), "source_url": c.get("source_url"), "license": c.get("license"), "creator": c.get("creator"), "query": c.get("query"),
              "project_id": c.get("project_id"), "stock_id": f"{c['source']}:{c['source_id']}", "score": c.get("look"), "why": c.get("why")}
    asset_id, run_id = system.library.ingest(path, origin="licensed", rights=rights)
    if system.storyboard is not None and system.storyboard.shot(shot_id) is not None:
        system.director.use_asset(shot_id, asset_id, reason=_stock_reason(c))
    else:
        # Proposed at once; placed on the part that shows the line once the clip has been described (see build()).
        system.sourcing.use_asset(shot_id, asset_id, pending=system.intelligence.understands, reason=_stock_reason(c))
        if system.orch.run_status(run_id) is RunStatus.SUCCEEDED and system.index.moments(asset_id, level="segment"):
            system.sourcing.refine_from_asset(shot_id, asset_id)     # the same clip was fetched before and has already been described
    return {"asset_id": asset_id, "run_id": run_id, "rights": rights}


def _stock_sources(system: "System") -> list[str] | None:
    return json.loads(system.orch.setting("stock_sources", "[]")) or None      # the operator's choice of libraries; empty means all


def storyboard_stock(system: "System", shot_id: str, query: str | None = None) -> dict:
    """Stock candidates for a storyboard shot, judged on their previews and shown to the operator; nothing is downloaded until
    one is chosen. `query`: the operator's own words for what to look for, else the shot's line."""
    if system.orch.kill_switch():
        raise ValueError("Đang dừng khẩn cấp: không tìm clip stock")
    s = system.storyboard.shot(shot_id)
    line = (query or "").strip() or s.spec.get("line") or s.spec.get("intent") or ""
    found = system.stock_scout.find(s.project_id, shot_id, line, seconds=float(s.spec["duration"]["target"]), sources=_stock_sources(system))
    return {"found": bool(found), "options": len(found), "passed": sum(1 for c in found if c.get("look") is not None and c["look"] >= 5)}


def fill_gap_from_stock(system: "System", shot_id: str, line: str, *, take: bool | None = None) -> dict:
    """A script line the footage does not show: stock candidates judged on their previews and kept for the operator to choose
    from. Only when the operator lets the best one be taken (Tự duyệt → stock) is the best that passes downloaded, and never
    the clip already chosen for the line before or after it. `take`: the operator asked for this very line, so the best is
    taken whatever the switch says."""
    if system.orch.kill_switch():
        return {"found": False, "options": 0, "stopped": True}
    shot = system.projects.shot(shot_id)
    script = system.projects.script(shot.script_id)
    from nexora.modules.sourcing.match import needed_seconds
    found = system.stock_scout.find(script["project_id"], shot_id, line, seconds=needed_seconds(line), sources=_stock_sources(system))
    if not (take if take is not None else system.autonomy.switches().get("stock")):
        return {"found": False, "options": len(found)}
    lines = [x.shot_id for x in script["shots"]]
    at = lines.index(shot_id)
    avoid = set()
    for near in lines[max(0, at - 1):at] + lines[at + 1:at + 2]:
        sel = system.projects.selection(near)
        if sel is not None and sel.asset_id and system.assets.asset(sel.asset_id):
            stock_id = (system.assets.original(sel.asset_id).metadata.get("rights") or {}).get("stock_id")
            if stock_id:
                avoid.add(stock_id)
    best = system.stock_scout.best(script["project_id"], shot_id, avoid=avoid)
    if best is None:
        return {"found": False, "options": len(found)}
    return {"found": True, "options": len(found), "query": best.get("query"), **use_stock_candidate(system, best["cid"], shot_id=shot_id)}


def after_storyboard_approved(system: "System", project_id: str) -> dict:
    """Once a storyboard is approved: the stock candidates of the project and their previews are gone (none was downloaded),
    and stock downloaded for it that the approved storyboard does not use goes to the Trash (30 days to take it back). A clip
    another project uses, or one the operator rated 4 stars or more, stays."""
    previews = system.stock_scout.forget(project_id) if system.stock_scout is not None else 0
    used = {r[0] for r in system.projects._conn.execute("SELECT DISTINCT asset_id FROM selections WHERE asset_id IS NOT NULL")}
    for row in system.storyboard._conn.execute("SELECT assignment FROM sb_shots WHERE assignment IS NOT NULL"):
        a = json.loads(row[0] or "null") or {}
        used.add(a.get("asset_id"))
    unused = []
    for asset in system.assets.assets():
        if asset.get("origin") != "licensed" or asset.get("trashed_at") or asset["asset_id"] in used or (asset.get("rating") or 0) >= 4:
            continue
        if (system.assets.original(asset["asset_id"]).metadata.get("rights") or {}).get("project_id") == project_id:
            unused.append(asset["asset_id"])
    if unused:
        trash_items(system, assets=unused)
    return {"previews": previews, "trashed": len(unused)}


_FACES: dict = {}


def face_likeness(system: "System", asset_id: str, t: float, reference: str) -> float | None:
    """How alike the largest face in a picture (an asset at `t`) and the largest in a reference asset are: SigLIP 2 on the two
    faces, cut out with a margin by Apple Vision. None when either has no face, or the tools are not set up. Lives here because
    it joins the library, Apple's frames and the picture model."""
    names = {c.name for c in system.adapters.describe()}
    if "restore_faces" not in names or "picture_text" not in names:
        return None

    def picture(aid: str, at: float | None) -> Path | None:
        asset = system.assets.asset(aid)
        if not asset:
            return None
        path = system.assets.path_of(system.assets.original(aid))
        if asset.get("kind") == "image" or path.suffix.lower() in (".jpg", ".jpeg", ".png", ".heic", ".tif", ".tiff"):
            return path if path.is_file() else None
        versions = {v.role: v for v in system.assets.versions(aid)}
        if not path.is_file() and "proxy" in versions:
            path = system.assets.path_of(versions["proxy"])
        if not path.is_file():
            return None
        out = system.data_dir / "tmp" / "likeness" / f"{aid}_{(at or 0):.2f}.jpg"
        if not out.is_file():
            out.parent.mkdir(parents=True, exist_ok=True)
            system.adapters.submit("ffmpeg", Request("thumbnail", inputs={"path": str(path)}, params={"out": str(out), "at": float(at or 1.0)}))
        return out

    def face(path: Path | None):
        if path is None:
            return None
        if str(path) in _FACES:
            return _FACES[str(path)]
        from PIL import Image
        found = system.adapters.submit("restore_faces", Request("find", inputs={"path": str(path)})).outputs.get("faces", [])
        vector = None
        if found:
            x, y, w, h = max(found, key=lambda f: f["box"][2] * f["box"][3])["box"]
            crop = system.data_dir / "tmp" / "likeness" / f"face_{abs(hash(str(path)))}.png"
            crop.parent.mkdir(parents=True, exist_ok=True)
            with Image.open(path) as im:
                m = 0.25 * max(w, h)
                im.convert("RGB").crop((max(0, x - m), max(0, y - m), min(im.width, x + w + m), min(im.height, y + h + m))).save(crop)
            vector = system.adapters.submit("picture_text", Request("images", inputs={"images": [str(crop)]})).outputs["vectors"][0]
        _FACES[str(path)] = vector
        return vector

    a, b = face(picture(asset_id, t)), face(picture(reference, None))
    if a is None or b is None:
        return None
    return round(float(sum(x * y for x, y in zip(a, b))), 3)


def remove_asset(system: "System", asset_id: str, *, discard_file: bool = False, trash: str | Path | None = None) -> dict:
    """Take an asset out of the library for good. Work still running on it is stopped; the lines that showed it are without a
    picture again; what was said about it, measured in it and kept as an answer for it is forgotten; and everything made
    from it (proxy, thumbnail, frames, measures) is deleted, since all of that can be made again. The file itself stays
    where it is unless `discard_file`, in which case it is moved to the Trash, not erased."""
    import shutil
    from nexora.core.states import RunStatus
    if system.assets.asset(asset_id) is None:
        raise LookupError(asset_id)
    for run_id in system.orch.runs_for_subject(asset_id):
        if system.orch.run_status(run_id) in (RunStatus.QUEUED, RunStatus.RUNNING, RunStatus.WAITING_REVIEW, RunStatus.BLOCKED):
            system.orch.cancel_run(run_id)
    original = system.assets.original(asset_id)
    source, name = system.assets.path_of(original), system.assets.path_of(original).name
    media = (system.data_dir / "media").resolve()
    derived = [system.assets.path_of(v) for v in system.assets.versions(asset_id) if v.role != "original"]
    gaps = system.projects.forget_asset(asset_id, reason=f"Footage của câu này ({name}) đã bị xoá khỏi thư viện.")
    cases = system.evaluation.forget_asset(asset_id)
    system.fields.forget_asset(asset_id)
    moments = system.index.remove_asset(asset_id)
    system.intelligence.forget(asset_id)
    system.assets.remove(asset_id)
    shared = bool(original.checksum and system.assets.find_original_by_checksum(original.checksum))      # a second copy of the same file still uses what was made from it
    if original.checksum and not shared:
        folder = media / original.checksum[:2]
        derived += [p for p in folder.glob(f"{original.checksum}_*")] if folder.is_dir() else []
    for path in derived:
        if media in path.resolve().parents:
            shutil.rmtree(path, ignore_errors=True) if path.is_dir() else path.unlink(missing_ok=True)
    trashed = _to_trash(source, trash) if discard_file and source.is_file() else None
    return {"name": name, "gaps": gaps, "cases": cases, "moments": moments, "trashed": trashed}


def _to_trash(path: Path, trash: str | Path | None = None) -> str:
    """Move a file to the Trash under a name that does not overwrite one already there. Returns where it went."""
    import shutil
    bin_ = Path(trash).expanduser() if trash else Path.home() / ".Trash"
    bin_.mkdir(parents=True, exist_ok=True)
    target, n = bin_ / path.name, 1
    while target.exists():
        target, n = bin_ / f"{path.stem} ({n}){path.suffix}", n + 1
    shutil.move(str(path), str(target))
    return str(target)


def remove_project(system: "System", project_id: str, *, trash: str | Path | None = None) -> dict:
    """Delete a project. Work still running for it is stopped, its scripts, lines, choices, storyboard, cut versions and cuts are forgotten, and the
    cut files are moved to the Trash, not erased. A project with a video already published is refused: the record of what
    went out, and the figures gathered for it, must not vanish with it. The footage it used stays in the library."""
    if system.projects.project(project_id) is None:
        raise LookupError(project_id)
    _refuse_if_published(system, project_id)
    _stop_project_work(system, project_id)
    title = system.projects.project(project_id)["title"]
    tasks = system.producer.forget_project(project_id)
    removed = system.projects.remove(project_id)
    boards = system.storyboard.forget_project(project_id) if system.storyboard is not None else 0
    cuts = system.cuts.forget_project(project_id) if getattr(system, "cuts", None) is not None else 0
    media = (system.data_dir / "media").resolve()
    trashed = []
    for render in removed["renders"]:
        path = Path(render["path"])
        if path.is_file() and media in path.resolve().parents:            # only cuts NEXORA made itself; an imported finished file stays where the operator keeps it
            trashed.append(_to_trash(path, trash))
    return {"title": title, "scripts": len(removed["scripts"]), "lines": len(removed["shots"]), "renders": len(removed["renders"]), "tasks": tasks,
            "storyboard_shots": boards, "cut_versions": cuts, "trashed": trashed}


def remove_render(system: "System", render_id: str, *, trash: str | Path | None = None) -> dict:
    """Delete one cut. Its file goes to the computer's Trash when NEXORA made it; its publishing package is deleted, since it
    can be made again. A cut that has been published is refused."""
    render = system.projects.render(render_id)
    if render is None:
        raise LookupError(render_id)
    if any(p["render_id"] == render_id for p in system.publishing.publications(project_id=render["project_id"])):
        raise ValueError("Bản dựng này đã được đăng. Không xoá được để giữ lại hồ sơ đăng của nó.")
    _stop(system, render_id)
    system.projects.remove_render(render_id)
    path, data = Path(render["path"]), system.data_dir.resolve()
    trashed = _to_trash(path, trash) if path.is_file() and (data / "media") in path.resolve().parents else None
    exports = data / "exports" / render_id
    if exports.is_dir():
        shutil.rmtree(exports, ignore_errors=True)
    return {"render_id": render_id, "trashed": trashed}


# ---------------------------------------------------------------------------------------------- NEXORA's own Trash
TRASH_DAYS = 30                  # what is in the Trash this long is deleted for good when the server starts


def _stop(system: "System", subject: str) -> None:
    from nexora.core.states import RunStatus
    for run_id in system.orch.runs_for_subject(subject):
        if system.orch.run_status(run_id) in (RunStatus.QUEUED, RunStatus.RUNNING, RunStatus.WAITING_REVIEW, RunStatus.BLOCKED):
            system.orch.cancel_run(run_id)


def _stop_project_work(system: "System", project_id: str) -> None:
    scripts = system.projects.script_ids(project_id)
    renders = [r["render_id"] for r in system.projects.renders(project_id) + system.projects.renders(project_id, previews=True)]
    shots = [s.shot_id for sid in scripts for s in (system.projects.script(sid) or {}).get("shots", [])]
    for subject in [project_id, *scripts, *shots, *renders]:
        _stop(system, subject)


def _refuse_if_published(system: "System", project_id: str) -> None:
    if system.publishing.publications(project_id=project_id):
        raise ValueError("Dự án này đã có video được đăng. Không xoá được để giữ lại hồ sơ đăng và số liệu của nó.")


def asset_name(system: "System", asset: dict) -> str:
    """What an asset is called on screen: the operator's name for it, else its file name."""
    return asset.get("title") or system.assets.path_of(system.assets.original(asset["asset_id"])).name


def trash_items(system: "System", *, assets: list[str] = (), projects: list[str] = ()) -> dict:
    """Put assets and projects in NEXORA's Trash. Nothing is lost: an asset leaves the library, the search and the matching,
    and the lines that showed it are without a picture until it comes back; a project leaves every list. Work running on
    either is stopped. A project with a published video is refused, as it would be when deleted for good."""
    for project_id in projects:
        if system.projects.project(project_id) is None:
            raise LookupError(project_id)
        _refuse_if_published(system, project_id)
    for asset_id in assets:
        if system.assets.asset(asset_id) is None:
            raise LookupError(asset_id)
    lines = 0
    for asset_id in assets:
        asset = system.assets.asset(asset_id)
        if asset["trashed_at"]:
            continue
        _stop(system, asset_id)
        lines += system.projects.set_aside_asset(asset_id, reason=f"Footage của câu này ({asset_name(system, asset)}) đang ở Thùng rác.")
        system.assets.trash(asset_id)
    for project_id in projects:
        if system.projects.project(project_id)["trashed_at"]:
            continue
        _stop_project_work(system, project_id)
        system.projects.trash(project_id)
    return {"assets": len(assets), "projects": len(projects), "lines": lines}


def restore_items(system: "System", *, assets: list[str] = (), projects: list[str] = ()) -> dict:
    """Take assets and projects back out of the Trash, as they were. Lines that lost an asset get it back unless they were
    given another picture in the meantime."""
    lines = 0
    for asset_id in assets:
        if system.assets.asset(asset_id) is None:
            raise LookupError(asset_id)
        system.assets.restore(asset_id)
        lines += system.projects.bring_back_asset(asset_id)
    for project_id in projects:
        if system.projects.project(project_id) is None:
            raise LookupError(project_id)
        system.projects.restore(project_id)
    return {"assets": len(assets), "projects": len(projects), "lines": lines}


def trash_view(system: "System", *, now: float | None = None) -> dict:
    """What is in the Trash, newest first, with the day each will be deleted for good."""
    now = now or time.time()
    left = lambda at: max(0, -int(-(at + TRASH_DAYS * 86400 - now) // 86400))      # whole days, rounded up
    assets = [{"asset_id": a["asset_id"], "name": asset_name(system, a), "kind": a["kind"], "trashed_at": a["trashed_at"], "days_left": left(a["trashed_at"])}
              for a in system.assets.trashed()]
    projects = [{"project_id": p["project_id"], "title": p["title"], "trashed_at": p["trashed_at"], "days_left": left(p["trashed_at"]),
                 "published": bool(system.publishing.publications(project_id=p["project_id"]))} for p in system.projects.trashed()]
    return {"assets": assets, "projects": projects, "days": TRASH_DAYS}


def purge_trash(system: "System", *, assets: list[str] | None = None, projects: list[str] | None = None, older_than_days: float | None = None,
                discard_files: bool = False, trash: str | Path | None = None, now: float | None = None) -> dict:
    """Delete for good what is in the Trash: the items named, or else everything that has been there `older_than_days` (all
    of it when 0). An asset's own file stays where it is unless `discard_files`; cuts NEXORA made go to the computer's Trash.
    An item that cannot go (a project with a published video) stays in the Trash and is reported."""
    now = now or time.time()
    old = lambda at: older_than_days is None or at <= now - older_than_days * 86400
    in_trash_assets = {a["asset_id"]: a for a in system.assets.trashed()}
    in_trash_projects = {p["project_id"]: p for p in system.projects.trashed()}
    pick_assets = [a for a in (assets if assets is not None else in_trash_assets) if a in in_trash_assets and (assets is not None or old(in_trash_assets[a]["trashed_at"]))]
    pick_projects = [p for p in (projects if projects is not None else in_trash_projects) if p in in_trash_projects and (projects is not None or old(in_trash_projects[p]["trashed_at"]))]
    done, kept = {"assets": 0, "projects": 0}, []
    for project_id in pick_projects:
        try:
            remove_project(system, project_id, trash=trash)
            done["projects"] += 1
        except ValueError as e:
            kept.append({"project_id": project_id, "title": in_trash_projects[project_id]["title"], "reason": str(e)})
    for asset_id in pick_assets:
        remove_asset(system, asset_id, discard_file=discard_files, trash=trash)
        done["assets"] += 1
    return {**done, "kept": kept}


def footage_insights(system: "System") -> dict:
    """What the channel's own figures say about the footage used: for each published video, the share of it watched on average
    and the measured traits of the stretches it was cut from (design 2026-10-14, group 12). Lives here because it joins three
    modules: what went out, the cut, and the profile of the footage."""
    from nexora.modules.intelligence.profile import what_works
    rows = system.publishing._conn.execute("SELECT p.publication_id, p.render_id, (SELECT figures FROM metric_snapshots m WHERE m.publication_id = p.publication_id "
                                           "ORDER BY at DESC LIMIT 1) AS figures FROM publications p WHERE p.status = 'published'").fetchall()
    videos = []
    for row in rows:
        figures = json.loads(row["figures"] or "{}")
        render = system.projects.render(row["render_id"])
        shots = (render or {}).get("qc", {}).get("shots") or []
        length = sum((s.get("t_out") or 0) - (s.get("t_in") or 0) for s in shots) or (render or {}).get("qc", {}).get("duration") or 0
        if not figures.get("views") or not figures.get("watch_seconds") or not length:
            continue
        sizes, faces, words = [], 0, 0
        for s in shots:
            if not s.get("asset_id"):
                continue
            span = (s.get("t_in") or 0.0, s.get("t_out") or 0.0)
            sizes += [o.value for o in system.vi.observations(s["asset_id"], "shot_size", span) if o.source != "model"]
            faces += any((o.evidence.get("faces") or 0) > 0 for o in system.vi.observations(s["asset_id"], "people", span))
            words += bool(system.vi.observations(s["asset_id"], "speaker", span))
        sizes = [x for x in sizes if x]
        traits = {"cỡ cảnh chính": max(set(sizes), key=sizes.count) if sizes else "không rõ", "có mặt người": faces > 0, "có người nói": words > 0,
                  "số cảnh mỗi phút": "nhiều" if len(shots) / max(length / 60, 1e-3) >= 12 else "ít"}
        videos.append({"retention": min(1.0, figures["watch_seconds"] / figures["views"] / length), "traits": traits, "publication_id": row["publication_id"]})
    return what_works(videos)


def render_rights(system: "System", render_id: str) -> dict:
    """The rights report of a render. Lives here because it reads what three modules own: the cut, the assets and the project."""
    render = system.projects.render(render_id)
    project = system.projects.project(render["project_id"])
    by_id = {}
    for shot in render["qc"].get("shots") or []:
        asset = system.assets.asset(shot.get("asset_id") or "")
        if asset:
            original = system.assets.original(asset["asset_id"])
            used = [s for s in render["qc"].get("shots") or [] if s.get("asset_id") == asset["asset_id"]]
            # Faces seen in the stretches the cut uses: people who can be recognised need to have agreed to appear.
            with_people = sum(1 for u in used for o in system.vi.observations(asset["asset_id"], "people", (u.get("t_in") or 0.0, u.get("t_out") or 1e9))
                              if o.source != "model" and (o.evidence.get("faces") or 0) > 0)
            by_id[asset["asset_id"]] = {"origin": asset["origin"], "name": system.assets.path_of(original).name, "rights": original.metadata.get("rights"),
                                        "people": with_people, "consent": asset.get("consent")}
    options = json.loads(project.get("options") or "{}")
    music = project["music_path"] if render["qc"].get("music") and project.get("music_path") else None
    return rights_report(render["qc"].get("shots") or [], by_id, music=music, music_cleared=bool(options.get("music_cleared")))


def evaluation_config(system: "System") -> dict:
    """What describes the installation for a benchmark run: the models in use and the versions of the prompts."""
    from nexora.modules.intelligence.understand import PROMPT_VERSION
    env = (system.adapters.environment().get("model") or {}).get("models") or {}
    return {"models": ", ".join(sorted(env)) or "không có mô hình", "describe_prompt": PROMPT_VERSION, "segment_seconds": system.intelligence.segment_seconds,
            "moments": system.index.count()}


def structure_config(system: "System") -> dict:
    """What describes how footage is divided, for a benchmark run: the version of the rules and every level they decide against."""
    from dataclasses import asdict
    from nexora.modules.intelligence import signals, structure
    return {"signals": signals.VERSION, "structure": structure.VERSION, **asdict(system.intelligence.analysis.rules)}


PIPELINE_NAMES = {"edit.cut": "Xuất bản dựng", "library.ingest": "Nhập footage", "library.ingest_image": "Nhập ảnh", "library.ingest_audio": "Nhập nhạc", "library.understand": "Hiểu nội dung footage", "library.transcribe": "Nghe lời nói trong footage", "library.profile": "Đo và nhận diện footage",
                  "sourcing.match": "Chọn clip", "sourcing.generate": "Sinh hình bằng AI", "edit.render": "Dựng video", "edit.preview": "Dựng bản xem thử", "library.enhance": "Nâng chất lượng clip", "sourcing.train": "Huấn luyện mô hình nhân vật", "library.cuts": "Tìm chỗ chuyển cảnh", "library.structure": "Đo và chia footage thành cú máy, nhịp",
                  "planning.topic_script": "Viết kịch bản theo chủ đề", "vq.analyse": "Đo chất lượng hình", "vq.preview": "Xem thử chỉnh hình", "vq.apply": "Chỉnh chất lượng hình"}
ANNOUNCE = {"model_fallback": "không dùng được mô hình cloud đã chọn, mô hình trên máy làm thay", "autonomy_lowered": "mức tự chủ vừa bị hạ", "metrics_due": "đã tới mốc ghi số liệu", "disk_low": "ổ đĩa sắp đầy", "volume_offline": "không tìm thấy nơi chứa footage", "gaps": "còn câu chưa có hình", "waiting_review": "đang chờ bạn duyệt", "blocked": "đang dừng và cần bạn xử lý", "failed": "thất bại", "succeeded": "đã xong"}
QUIET = frozenset({"library.ingest", "library.ingest_image", "library.ingest_audio", "library.understand", "library.transcribe", "library.profile", "edit.preview", "library.cuts", "library.enhance", "library.structure"})   # finishing these needs nobody's attention


def announce(system: "System", after: int) -> int:
    """Send every notification newer than `after` to the desktop, when the operator has turned that on. Returns the newest id seen."""
    for n in system.orch.notifications_after(after):
        after = n["notification_id"]
        pipeline = (system.orch.run_info(n["run_id"]) or {}).get("pipeline_id")
        muted = json.loads(system.orch.setting("notify_off", "[]"))
        quiet = system.orch.setting("quiet_hours", "")
        if n["kind"] == "metrics_due":
            pipeline = f"Video {n['reason']}"
        if n["kind"] in ("autonomy_lowered", "model_fallback"):
            pipeline = "Hệ thống:"
        if not pipeline and n["kind"] in ("disk_low", "volume_offline"):
            pipeline = "Máy"
        if (system.orch.setting("desktop_notifications", "1") != "1" or n["kind"] not in ANNOUNCE or n["kind"] in muted
                or (n["kind"] == "succeeded" and pipeline in QUIET) or (quiet and in_window(quiet))):         # the inbox keeps everything; only the desktop stays silent
            continue
        try:
            system.adapters.submit("desktop", Request("notify", inputs={"title": "NEXORA", "text": f"{PIPELINE_NAMES.get(pipeline, pipeline)} {ANNOUNCE[n['kind']]}."}))
        except Exception:                # a notification that cannot be shown must never disturb the work
            pass
    return after


# The shape of a video (design v4.0, 16.4): segments in order, each with a duration range and what it must achieve.
DEFAULT_STRUCTURE = [
    {"role": "hook", "label": "Mở bài", "min": 3, "max": 8, "goal": "giữ người xem ngay từ câu đầu"},
    {"role": "body", "label": "Thân bài", "min": 15, "max": 90, "goal": "kể nội dung chính"},
    {"role": "close", "label": "Kết", "min": 3, "max": 10, "goal": "đọng lại một ý, mời xem tiếp"},
]
SHORT_STRUCTURE = [
    {"role": "hook", "label": "Mở bài", "min": 1, "max": 3, "goal": "một hình và một câu khiến người xem dừng lại"},
    {"role": "body", "label": "Thân bài", "min": 10, "max": 45, "goal": "một ý, nhịp nhanh"},
    {"role": "close", "label": "Kết", "min": 2, "max": 6, "goal": "chốt ý hoặc mời theo dõi"},
]
DEFAULT_TEMPLATES = [
    {"name": "Video ngang có lời dẫn", "format": "landscape", "voice": "", "music_gain": 0.35, "auto_accept": False, "caption_scale": 1.0, "caption_position": "bottom", "pronounce": {},
     "structure": DEFAULT_STRUCTURE},
    {"name": "Video dọc ngắn", "format": "portrait", "voice": "", "music_gain": 0.3, "auto_accept": True, "caption_scale": 1.15, "caption_position": "middle", "pronounce": {},
     "structure": SHORT_STRUCTURE},
]
ROLES = ("hook", "body", "close")


def clean_structure(raw) -> list[dict]:
    """A template's segments as the operator gave them, kept only where they make sense: a role, a label, min ≤ max."""
    out = []
    for seg in raw if isinstance(raw, list) else []:
        if not isinstance(seg, dict) or not str(seg.get("label", "")).strip():
            continue
        try:
            lo, hi = max(0.0, float(seg.get("min") or 0)), max(0.0, float(seg.get("max") or 0))
        except (TypeError, ValueError):
            continue
        out.append({"role": seg.get("role") if seg.get("role") in ROLES else "body", "label": str(seg["label"]).strip(), "min": min(lo, hi), "max": max(lo, hi),
                    "goal": str(seg.get("goal") or "").strip()})
    return out
MEDIA_EXT = frozenset({".mp4", ".mov", ".m4v", ".mkv", ".avi", ".mts", ".webm", ".jpg", ".jpeg", ".png", ".webp", ".mp3", ".wav", ".m4a", ".aiff", ".flac"})


def templates(system: "System") -> list[dict]:
    """Format templates: the settings a kind of video always starts from."""
    stored = system.orch.setting("templates")
    out = json.loads(stored) if stored else [dict(t) for t in DEFAULT_TEMPLATES]
    for t in out:                                    # a template kept before templates had a structure takes the default one
        if "structure" not in t:
            t["structure"] = SHORT_STRUCTURE if t.get("format") == "portrait" else DEFAULT_STRUCTURE
        t.setdefault("illustration", "mixed")        # how its pictures illustrate the words: mixed lets the writer choose per line
    return out


def channel_named(system: "System", name: str | None) -> dict | None:
    return next((c for c in json.loads(system.orch.setting("channels", "[]")) if c["name"] == name), None) if name else None


def template_named(system: "System", name: str | None) -> dict | None:
    return next((t for t in templates(system) if t["name"] == name), None) if name else None


def illustration_style(system: "System", project: dict | None) -> str:
    """How a project's pictures illustrate its words: its channel's choice when the channel makes one, else its template's, else
    mixed (the writer chooses per line)."""
    project = project or {}
    channel = channel_named(system, project.get("channel")) or {}
    if channel.get("illustration") in ("direct", "associative", "mixed"):
        return channel["illustration"]
    template = template_named(system, project.get("template")) or {}
    return template.get("illustration") if template.get("illustration") in ("direct", "associative", "mixed") else "mixed"


def apply_template(system: "System", project_id: str, chosen: dict) -> None:
    """A project starts from a template: its format, voice, music level, captions and logo."""
    system.projects.update_project(project_id, template=chosen["name"], format=chosen["format"], voice=chosen["voice"] or None, music_gain=chosen["music_gain"], auto_accept=int(chosen["auto_accept"]),
                                   profile=json.dumps({"caption_scale": chosen.get("caption_scale", 1.0), "caption_position": chosen.get("caption_position", "bottom"),
                                                       "typeface": chosen.get("typeface", "sans"), "caption_colour": chosen.get("caption_colour"), "logo_path": chosen.get("logo_path") or None,
                                                       "pronounce": chosen.get("pronounce", {})}, ensure_ascii=False))


def budget_left(system: "System", *, now: float | None = None) -> float | None:
    """What is left of the day's and the month's budgets, the smaller; None when no budget is set."""
    t = time.localtime(now)
    day, month = time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1)), time.mktime((t.tm_year, t.tm_mon, 1, 0, 0, 0, 0, 0, -1))
    left = []
    for key, since in (("budget_day", day), ("budget_month", month)):
        value = system.orch.setting(key, "")
        if value not in (None, ""):
            left.append(max(0.0, float(value) - system.orch.spent_since(since)))
    return round(min(left), 4) if left else None


def start_library_work(system: "System", kind: str) -> list[str]:
    """A mission's library work: every recording not yet described (or not yet listened to) is given to its pipeline."""
    runs = []
    for asset in system.assets.assets():
        if asset["kind"] != "video" or asset.get("rejected") or asset.get("trashed_at"):
            continue
        aid = asset["asset_id"]
        if kind != "understand" and asset.get("origin") == "licensed":
            continue                                   # stock is described, never listened to
        if kind == "understand":
            if system.index.moments(aid, level="video"):
                continue
            earlier = [r for r in system.orch.runs_for_subject(aid) if system.orch.pipeline_of(r) == "library.understand"]
            if earlier and system.orch.run_status(earlier[0]).value in ("queued", "running"):
                runs.append(earlier[0])
                continue
            run = system.intelligence.understand(aid, force=bool(earlier))
        else:
            run = system.intelligence.transcribe(aid)
            if run and system.orch.run_status(run).value == "succeeded":
                continue                               # heard already: the same request answers with the run that did it
        if run:
            runs.append(run)
    return runs


def production_budget_left(projects, productions, generation, project_id: str) -> float | None:
    """What a production's total budget leaves for one of its videos: the total less what all its videos have spent; None when
    the production sets no total."""
    video = projects.project(project_id) or {}
    production = productions.get(video.get("production_id"))
    if not production or production.get("budget_cap") is None:
        return None
    spent = sum(generation.spent(p["project_id"]) for p in projects.projects(include_trashed=True) if p.get("production_id") == production["production_id"])
    return max(0.0, float(production["budget_cap"]) - spent)


def take_shared(system: "System", project_id: str, values: dict) -> None:
    """Shared values set on a video: its channel (with the profile's version), its template (applied, as a template is), and
    the rest as they are."""
    if values.get("template"):
        chosen = template_named(system, values["template"])
        if chosen:
            apply_template(system, project_id, {**chosen, "format": (system.projects.project(project_id) or {}).get("format") or chosen["format"]})
    if "channel" in values:
        channel = channel_named(system, values["channel"])
        system.projects.update_project(project_id, channel=values["channel"] or None, channel_version=(channel or {}).get("version"))
    system.projects.update_project(project_id, **{k: values[k] for k in ("voice", "music_path", "bible", "research") if k in values})


def new_video(system: "System", title: str, *, production_id: str | None = None, format: str = "landscape") -> str:
    """A video in a production (a new one of its title when none is named), taking the production's shared values."""
    project_id = system.projects.create_project(title, format=format, production_id=production_id)
    production = system.productions.get((system.projects.project(project_id) or {}).get("production_id"))
    if production:
        take_shared(system, project_id, {k: production[k] for k in ("channel", "template", "voice", "music_path", "bible", "research") if production.get(k)})
    return project_id


def update_production(system: "System", production_id: str, changes: dict) -> dict:
    """A production's record changed. A shared value reaches each of its videos still on the production's previous value (or on
    none); a video given its own keeps it. Returns the production as it now is."""
    from nexora.core.productions import FIELDS, SHARED
    changes = {k: v for k, v in changes.items() if k in FIELDS}
    before = system.productions.update(production_id, **changes)
    reach = {k: v for k, v in changes.items() if k in SHARED and v != before.get(k)}
    if reach:
        for video in system.projects.projects(include_trashed=True):
            if video.get("production_id") != production_id:
                continue
            values = {k: v for k, v in reach.items() if video.get(k) in (before.get(k), None, "")}
            if values:
                take_shared(system, video["project_id"], values)
    return system.productions.get(production_id)


def topic_context(system: "System", project_id: str) -> dict:
    """What a writer of a script from a topic is told about the video: the voice to write in, the template's parts, the way of
    illustrating, and the titles of the other videos of its production, so that this one takes another angle."""
    from nexora.modules.planning.scripts import HOUSE_VOICE
    project = system.projects.project(project_id) or {}
    def told(p: dict) -> str:                    # a sibling's title, and the angle its own writer took, when one wrote it
        angle = ((system.topics.latest(p["project_id"]) or {}).get("package") or {}).get("angle") if system.topics else None
        return f"{p['title']} (góc: {angle})" if angle else p["title"]
    siblings = [told(p) for p in system.projects.projects() if project.get("production_id") and p.get("production_id") == project["production_id"] and p["project_id"] != project_id]
    return {"voice": system.orch.setting("writing_voice", "") or HOUSE_VOICE, "structure": (template_named(system, project.get("template")) or {}).get("structure"),
            "style": illustration_style(system, project), "siblings": siblings}


def merge_sources(system: "System", project_id: str, sources: list[dict]) -> int:
    """Sources a writer read, kept as the operator's own are (who published it, when, the passage), merged by address into the
    video's production, where its other videos find them, and into the video itself. Returns how many were new to the video."""
    import time
    def merged(raw: str | None) -> tuple[str, int]:
        kept = json.loads(raw or "[]")
        known = {s.get("url") for s in kept}
        new = [{"title": s["title"], "publisher": s.get("publisher"), "date": s.get("date"), "url": s["url"], "passage": s["passage"], "retrieved_at": time.time()}
               for s in sources if s.get("url") and s["url"] not in known]
        return json.dumps(kept + new, ensure_ascii=False), len(new)
    project = system.projects.project(project_id) or {}
    production = system.productions.get(project.get("production_id")) if system.productions else None
    if production:
        value, added = merged(production.get("research"))
        if added:
            update_production(system, production["production_id"], {"research": value})       # reaches the videos still on its sources
    value, added = merged((system.projects.project(project_id) or {}).get("research"))
    if added:
        system.projects.update_project(project_id, research=value)
    return added


def apply_topic(system: "System", project_id: str, run_id: str) -> str:
    """A script from a topic, written and checked, saved into the video with what the writer said about each line, and its
    sources into the production and the video. Returns the script saved."""
    from nexora.modules.planning.topic import script_lines
    got = system.topics.get(run_id)
    if not got or not got["package"]:
        raise ValueError("nothing was written for this run")
    lines = script_lines(got["package"])
    system.projects.keep_draft(project_id, [l for l in lines if isinstance(l, dict)])
    script_id = system.planning.save_script(project_id, lines)
    merge_sources(system, project_id, got["package"]["sources"])
    system.topics.mark(run_id, "applied")
    return script_id


def cut_gate(system: "System", project_id: str) -> str | None:
    """The stage of the project's cut waiting for review, if one is: the newer of a render from its script and an export of
    its newest saved cut (the Edit step), as the review screen shows it."""
    script = system.projects.current_script(project_id)
    runs = [r for r in system.orch.runs_for_subject(script["script_id"]) if system.orch.pipeline_of(r) == "edit.render"] if script else []
    cut = system.cuts.latest(project_id) if getattr(system, "cuts", None) is not None else None
    if cut:
        runs += [r for r in system.orch.runs_for_subject(cut["cut_id"]) if system.orch.pipeline_of(r) == "edit.cut"]
    if not runs:
        return None
    newest = max(runs, key=lambda r: system.orch.run_info(r).get("created_at") or 0)
    return next((s.stage_id for s in system.orch.stages(newest) if s.status is StageStatus.WAITING_REVIEW), None)


def approve_clips_by_policy(system: "System", project_id: str, run_id: str) -> None:
    """A clip match approved by the operator's switch, as the storyboard approves it: a storyboard laid out for the video is
    written back to the script with its pictures first; with none, the selections are taken as they stand."""
    if system.storyboard is not None and system.storyboard.shots(project_id) and system.director is not None:
        try:
            system.director.approve(project_id)
        except (ValueError, LookupError, AdapterError):
            pass                                                    # the storyboard could not be written back; the clips still stand
        for script_id in system.projects.script_ids(project_id):
            for waiting, stage_id in system.orch.waiting_review("sourcing.match"):
                if system.orch.run_info(waiting)["subject_ref"] == script_id:
                    system.orch.decide_review(stage_id, approve=True, actor="policy")
        return
    system.sourcing.approve(run_id, actor="policy")


def lay_out_storyboard(system: "System", project_id: str) -> int:
    """The clips chosen for a script laid out on the project's storyboard, where the operator looks at them and approves. A
    storyboard the project already has is never replaced. Returns how many shots were laid out."""
    if system.storyboard is None or system.storyboard_planner is None or system.storyboard.shots(project_id):
        return 0
    return system.storyboard_planner.from_script(project_id)


def prepare_mission_project(system: "System", project_id: str, plan: dict) -> None:
    """A project a mission started: its production's shared values, then the template and channel the plan names, and the
    share of the mission's budget it may spend."""
    production = system.productions.get((system.projects.project(project_id) or {}).get("production_id")) if system.productions else None
    if production:
        take_shared(system, project_id, {k: production[k] for k in ("channel", "template", "voice", "music_path", "bible", "research") if production.get(k)})
    chosen = template_named(system, plan.get("template"))
    if chosen:
        apply_template(system, project_id, {**chosen, "format": plan.get("format") or chosen["format"]})
    channel = channel_named(system, plan.get("channel"))
    if channel:
        system.projects.update_project(project_id, channel=channel["name"], channel_version=channel.get("version", 1))
    system.projects.update_project(project_id, budget_cap=plan.get("budget_cap", 0.0))


IDEAS_SETTLE = 3600.0          # proposed again when the understood library changed and an hour has passed
IDEAS_WEEK = 7 * 86400.0       # or a week has passed whatever happened


def refresh_ideas(system: "System", *, now: float | None = None) -> int:
    """Ideas proposed in the background (design v4.0, 16.6): after new footage is understood, or once a week. The operator can
    turn it off (`ideas_auto`). Returns how many ideas are open afterwards, or -1 when nothing was run."""
    import time
    now = time.time() if now is None else now
    if system.orch.setting("ideas_auto", "1") != "1":
        return -1
    footprint = json.dumps(system.index.assets_with("video"))
    last = float(system.orch.setting("ideas_last_at", "0") or 0)
    changed = footprint != system.orch.setting("ideas_last_footprint", "")
    if not ((changed and now - last >= IDEAS_SETTLE) or now - last >= IDEAS_WEEK):
        return -1
    system.orch.set_setting("ideas_last_at", str(now))
    system.orch.set_setting("ideas_last_footprint", footprint)
    channels = json.loads(system.orch.setting("channels", "[]"))
    open_before = {i["idea_id"] for i in system.planning.ideas.ideas(status=("new", "blocked"))}
    ideas = system.planning.find_ideas(channel=channels[0] if channels else None, templates=[t["name"] for t in templates(system)])
    fresh = [i for i in ideas if i["idea_id"] not in open_before]
    if fresh:
        system.orch.notify("ideas", "", reason=str(len(fresh)))
    return len(ideas)


def scan_watch_folders(system: "System", *, now: float | None = None, settle_seconds: float = 15.0) -> list[str]:
    """Ingest media that appeared in a watched folder. A file is taken only once it has stopped changing, so a copy in progress is never read."""
    import time
    now = time.time() if now is None else now
    known = {str(system.assets.path_of(system.assets.original(a["asset_id"]))) for a in system.assets.assets(include_trashed=True)}      # a file in the Trash is still known
    taken = []
    for folder in json.loads(system.orch.setting("watch_folders", "[]")):
        root = Path(folder)
        if not root.is_dir():
            continue
        for f in sorted(root.rglob("*")):
            if f.is_file() and f.suffix.lower() in MEDIA_EXT and not f.name.startswith(".") and str(f.resolve()) not in known and now - f.stat().st_mtime >= settle_seconds:
                system.library.ingest(f)
                taken.append(str(f))
    return taken


def watch_health(system: "System", *, min_free_bytes: int = 5 * 1024**3) -> list[str]:
    """Tell the operator once when the disk runs low or a footage location disappears, and stay quiet until that changes."""
    now = {"disk_low": shutil.disk_usage(system.data_dir).free < min_free_bytes,
           **{f"volume_offline:{v['volume_id']}": not v["online"] for v in system.assets.volumes()}}
    before = json.loads(system.orch.setting("health_state", "{}"))
    raised = [key for key, bad in now.items() if bad and not before.get(key)]
    for key in raised:
        kind, _, volume = key.partition(":")
        mount = next((v["mount_path"] for v in system.assets.volumes() if v["volume_id"] == volume), None)
        system.orch.notify(kind, "", reason=mount)
    if now != before:
        system.orch.set_setting("health_state", json.dumps(now))
    return raised


# Text tasks with names of their own, answered as the kind of work the operator routes on the System screen: writing a script
# in any form is "write" (before, a choice for "write" never reached the draft, which asked as "draft").
TASK_GROUPS = {"draft": "write", "draft_speech": "write", "rewrite": "write", "variant": "write", "idea_angle": "write", "mission_plan": "write",
               "storyboard_idea": "write", "storyboard_ops": "command", "copilot_read": "write"}


def capabilities(system: "System") -> list[dict]:
    """The capability matrix: for each pipeline, whether this installation can run every stage, and what is missing if not."""
    have = {c.name for c in system.adapters.describe()}
    have |= {name.partition(".")[0] for name in have}          # image_gen.<provider> answers for image_gen
    out = []
    for pipeline in system.registry.pipelines():
        missing = sorted({r for s in pipeline.stages for r in s.requires if r not in have})
        out.append({"pipeline": pipeline.pipeline_id, "available": not missing, "missing": missing,
                    "stages": [{"key": s.key, "requires": list(s.requires), "available": all(r in have for r in s.requires)} for s in pipeline.stages]})
    return out


def build(data_dir: str | Path, *, min_free_bytes: int = 2 * 1024**3, model: Adapter | None = None,
          segment_seconds: float = 12.0, voice: Adapter | None = None, match_threshold: float = 0.5, judge: bool = True,
          generators: list[Adapter] | None = None, stock: Adapter | None = None, desktop: Adapter | None = None, voice_name: str = "Linh",
          ffmpeg_binary: str = "", web: Adapter | None = None, speech: Adapter | None = None, publishers: list[Adapter] | None = None, shot_models: list[Adapter] | None = None, cloud_models: list[Adapter] | None = None,
          recognisers: list[Adapter] | None = None, pictures: Adapter | None = None, stock_api: Adapter | None = None, stock_preview=None) -> System:
    """`model` is the adapter for vision, reasoning and embeddings; without one, footage is ingested but not understood."""
    data_dir = Path(data_dir).resolve()          # tools resolve relative paths differently; keep every path absolute
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "nexora.db"
    orch, assets = Orchestrator(db_path), AssetStore(db_path)
    adapters = AdapterRegistry()
    adapters.register(FFprobeAdapter())
    adapters.register(FFmpegAdapter(ffmpeg_binary))
    adapters.register(CaptionAdapter())
    if voice is not None:
        adapters.register(voice)
    adapters.observer = orch.record_call
    adapters.local_only = lambda: orch.setting("privacy_local_only", "0") == "1"
    for cloud_model in [*(cloud_models or []), *(shot_models or [])]:
        adapters.register(cloud_model)

    def route(name: str, request: Request) -> str:
        """The model router: a text task goes to the model the operator chose for that kind of task, if any. The registry then
        refuses the choice whenever it would carry footage or break privacy mode, so this function decides preference only."""
        if name != "model" or request.operation != "chat":
            return name
        routes = json.loads(orch.setting("model_routes", "{}"))
        task = request.params.get("task") or "write"
        return routes.get(task) or routes.get(TASK_GROUPS.get(task, "")) or routes.get("*") or name
    adapters.router = route

    def routed_model_failed(chosen: str, err) -> None:
        """Say once, not at every call, that the model chosen for text work could not be used and the local one answered instead."""
        state = f"{chosen}:{err.code.value}"
        if orch.setting("model_fallback", "") != state:
            orch.set_setting("model_fallback", state)
            orch.notify("model_fallback", "", reason=f"{chosen.partition('.')[2] or chosen}: {err.message or err.code.value}")
    adapters.on_fallback = routed_model_failed
    index = MomentIndex(db_path)
    transcription = None
    if speech is not None:
        adapters.register(speech)
        transcription = Transcription(assets, index, adapters)
    # Footage is measured and divided into shots and beats with no model at all; the longest beat is the old length of a segment.
    analysis = Analysis(assets, adapters, data_dir / "media", rules=Rules(max_beat_seconds=segment_seconds),
                        words=(lambda asset_id: [(w["start"], w["end"]) for w in transcription.words(asset_id)]) if transcription else None)
    for recogniser in recognisers or []:            # Apple's picture and sound recognisers, where this machine has them
        adapters.register(recogniser)
    if pictures is not None:                        # the picture-and-words model (SigLIP 2), where it has been set up
        adapters.register(pictures)
    profiler = Profiler(assets, index, adapters, data_dir / "media", structure_of=analysis.structure, signals_of=analysis.signals,
                        words=transcription.words if transcription else (lambda asset_id: []))
    understanding = None
    if model is not None:
        adapters.register(model)
        index.embed = lambda texts: adapters.submit("model", Request("embed", inputs={"texts": texts})).outputs["vectors"]
        understanding = Understanding(assets, index, adapters, data_dir / "media", segment_seconds=segment_seconds, structure_of=analysis.structure,
                                      profile_of=profiler.beat_fields, signals_of=analysis.signals)
    registry = PipelineRegistry()
    library = Library(orch, assets, adapters, data_dir / "media", min_free_bytes=min_free_bytes)
    library.register(registry)
    # Video Intelligence: analyses every recording once and keeps what it learns; everything else reads it (design 2026-10-15).
    store = IntelligenceStore(db_path)
    intelligence = Intelligence(orch, assets, store, analysis, profiler=profiler, understanding=understanding, transcription=transcription)
    intelligence.register(registry)
    library.on_taken_in.append(intelligence.taken_in)
    library.on_note.append(intelligence.noted)
    vi = VideoIntelligence(db_path, released=lambda: system.fields.released(), exists=lambda asset_id: assets.asset(asset_id) is not None,
                           search=lambda query, limit, levels, min_score, exclude, exclude_assets: index.search(query, limit=limit, level=levels, min_score=min_score,
                                                                                                               exclude=exclude, exclude_assets=exclude_assets),
                           picture_text=(lambda query: adapters.submit("picture_text", Request("texts", inputs={"texts": [query]})).outputs["vectors"][0]) if pictures is not None else None,
                           alike=lambda asset_id, a, b, limit: profiler.alike(asset_id, a, b, among=[x["asset_id"] for x in assets.assets() if x["kind"] == "video"], limit=limit))
    # Visual Quality: how a picture looks and the recipes that put it right, for any source (design 2026-10-16).
    from nexora.adapters.color import ColorTransforms
    from nexora.core.visual_quality import VisualQuality
    from nexora.core.visual_quality_store import VisualQualityStore
    from nexora.modules.visual_quality.service import VisualQualityService
    adapters.register(ColorTransforms(data_dir / "luts"))
    from nexora.adapters.apple_frames import AppleFrames
    adapters.register(AppleFrames(data_dir / "tools" / "apple_frames" / "apple_frames"))
    from nexora.adapters.gyroflow import Gyroflow
    adapters.register(Gyroflow())
    from nexora.adapters.restore_local import RestoreLocal
    adapters.register(RestoreLocal(data_dir / "tools" / "realesrgan", ffmpeg_binary or "ffmpeg"))
    from nexora.adapters.faces import Faces
    adapters.register(Faces(data_dir / "tools" / "faces", data_dir / "tools" / "apple_frames" / "apple_frames"))
    from nexora.adapters.local_tone import LocalTone
    adapters.register(LocalTone(ffmpeg_binary or "ffmpeg"))
    from nexora.adapters.deblur import Deblur
    adapters.register(Deblur(data_dir / "tools" / "nafnet", ffmpeg_binary or "ffmpeg"))
    from nexora.adapters.propainter import ProPainter
    adapters.register(ProPainter(data_dir / "tools" / "propainter", ffmpeg_binary or "ffmpeg"))
    from nexora.adapters.stills import Stills
    adapters.register(Stills(ffmpeg_binary or "ffmpeg"))
    vq_reader = VisualQuality(db_path)
    vq = VisualQualityService(orch, assets, adapters, VisualQualityStore(db_path), vq_reader, data_dir / "vq", data_dir / "luts",
                              shots_of=lambda asset_id: [(s.t_start, s.t_end) for s in vi.segments(asset_id, "shot")])
    vq.register(registry)
    library.vq = vq_reader
    library.vq_render = lambda asset_id, out: vq.render_approved(asset_id, out)
    projects = ProjectStore(db_path)
    from nexora.core.productions import ProductionStore
    productions = ProductionStore(db_path)
    productions.adopt_loose()                     # videos made before productions existed: each a production of its own, once
    from nexora.core.ideas import IdeaStore
    from nexora.modules.planning.scripts import HOUSE_VOICE
    planning = Planning(projects, assets, index, adapters, ideas=IdeaStore(db_path), voice=lambda: orch.setting("writing_voice", "") or HOUSE_VOICE)
    sourcing = Sourcing(orch, projects, index, threshold=match_threshold, adapters=adapters, judge=judge and model is not None, rejected=assets.rejected,
                        may_accept=lambda project: system.autonomy.clips_may_be_accepted(project),
                        cuts=lambda asset_id: (assets.original(asset_id).metadata.get("scene_cuts") or [], assets.original(asset_id).metadata.get("probe", {}).get("duration")),
                        intel=vi)
    sourcing.register(registry)
    intelligence.on_understood.append(lambda asset_id: [sourcing.refine_from_asset(shot_id, asset_id) for shot_id in sourcing.pending_for(asset_id)])
    edit = Edit(orch, projects, assets, adapters, data_dir / "media", voice=voice is not None, voice_name=voice_name, reviewer=review_cut, model=model is not None,
                inspector={"file": picture_and_sound, "captions": caption_findings}, vq=vq_reader)
    edit.register(registry)
    if stock is not None:
        adapters.register(stock)
    if stock_api is not None and stock_api.describe() and getattr(stock_api, "sources", lambda: ["any"])():
        adapters.register(stock_api)
    if desktop is not None:
        adapters.register(desktop)
    if web is not None:
        adapters.register(web)
    for generator in generators or []:
        adapters.register(generator)
    generation = Generation(orch, projects, assets, adapters, data_dir / "media", judge=model is not None,
                            prefer=lambda kind: json.loads(orch.setting(f"providers:{kind}", "[]")),
                            also_left=lambda project_id: production_budget_left(projects, productions, generation, project_id), db_path=db_path)
    generation.register(registry)
    # The Edit step on FilmCraft: the storyboard built into a sequence in the browser, the cut kept in versions, rendered here.
    from nexora.adapters.filmcraft import FilmCraft
    from nexora.core.cuts import CutStore
    from nexora.core.storyboard import Storyboard as _Board
    from nexora.modules.edit.cut import Cut
    adapters.register(FilmCraft(data_dir))
    cuts = CutStore(db_path)
    cut = Cut(orch, projects, assets, _Board(db_path), cuts, adapters, data_dir / "media", source=edit.final_source,
              narrate=lambda project, text, position: edit.line_audio(project, text, position),
              words=lambda asset_id: [{**w, "speaker": ((m.data.get("speaker") or {}).get("value") if isinstance(m.data.get("speaker"), dict) else None)}
                                      for m in index.moments(asset_id, level="speech") for w in m.data.get("words", [])])
    cut.register(registry)
    distribution = Distribution(projects, assets, adapters, data_dir / "exports")
    (data_dir / "logs").mkdir(exist_ok=True)

    def log(entry: dict) -> None:
        """One line per stage that ran: what, how long, how it ended. Plain JSON so that any tool can read it."""
        with open(data_dir / "logs" / "stages.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    worker = Worker(orch, registry, worker_id=f"worker-{os.getpid()}", log=log)
    # Long footage analysis has its own worker, so that a render or a match the operator is waiting for never queues behind it.
    night_only = lambda: in_window(orch.setting("background_window", ""))          # the operator may keep heavy analysis to chosen hours
    workers = [Worker(orch, registry, worker_id=f"interactive-{os.getpid()}", lanes=frozenset({"interactive"}), log=log),
               Worker(orch, registry, worker_id=f"background-{os.getpid()}", lanes=frozenset({"background"}), log=log, allowed=night_only),
               # A writer that reads the web (Claude Code) takes minutes and runs one at a time on the operator's plan: a lane of its own.
               Worker(orch, registry, worker_id=f"claude-code-{os.getpid()}", lanes=frozenset({"claude_code"}), log=log),
               # What the producer starts on its own (a match, a render) runs here, so the operator's own never waits behind an hour of it.
               Worker(orch, registry, worker_id=f"agent-{os.getpid()}", lanes=frozenset({"agent"}), log=log)]
    system = System(data_dir, orch, assets, adapters, registry, worker, library, index, projects, planning, sourcing, edit, distribution, generation, workers)
    system.intelligence, system.vi = intelligence, vi
    system.vq, system.vq_reader = vq, vq_reader
    from nexora.modules.library.extract import Extractor
    system.extractor = Extractor(assets, adapters, vi, data_dir / "exports" / "assets", vq=vq_reader)
    system.roughcut = RoughCut(projects, assets, index)
    system.commands = Commands(adapters, projects, sourcing, edit)
    from nexora.agents.director import Director
    from nexora.core.storyboard import Storyboard
    from nexora.modules.planning.storyboard import StoryboardPlanner
    system.storyboard = Storyboard(db_path)
    system.cuts, system.cut = cuts, cut
    system.storyboard_planner = StoryboardPlanner(system.storyboard, projects, adapters, inventory=planning.inventory)
    from nexora.agents.copilot import Copilot
    system.copilot = Copilot(system.storyboard, system.storyboard_planner, index, assets, adapters)
    mid = lambda a: (float(a["t_in"]) + float(a["t_out"])) / 2
    system.director = Director(system.storyboard, system.storyboard_planner, index, vi, vq_reader, assets, projects,
                               colour_gap=lambda a, b: vq.colour_gap(a["asset_id"], mid(a), b["asset_id"], mid(b)),
                               likeness=lambda a, ref: face_likeness(system, a["asset_id"], mid(a), ref),
                               # the storyboard chooses pictures with the clip step's search and teaches it the operator's verdicts
                               find=lambda words, need, line, illustration=None: system.sourcing.find(words, need, line=line, illustration=illustration),
                               remember=lambda line, moment_id, verdict, **kw: system.sourcing.remember(line, moment_id, verdict, **kw),
                               look=(lambda line, asset_id, t_in, moment_id: system.sourcing.look(line, asset_id=asset_id, t_in=t_in, moment_id=moment_id)) if model is not None else None)
    system.viewer = Viewer(projects, adapters, data_dir / "media") if model is not None else None
    def measured_boundaries(asset_id: str):
        made = analysis.as_measured(asset_id) if assets.asset(asset_id) else None
        return boundaries(made) if made else None

    def coverage_faults_everywhere() -> dict:
        found = {a["asset_id"]: analysis.faults(a["asset_id"]) for a in assets.assets() if a["kind"] == "video"}
        return {asset_id: faults for asset_id, faults in found.items() if faults}
    system.evaluation = Evaluation(db_path, index, threshold=match_threshold, measured=measured_boundaries, faults=coverage_faults_everywhere)
    system.fields = Fields(db_path, vi)
    for publisher in publishers or []:
        adapters.register(publisher)
    system.publishing = Publishing(db_path, projects, adapters, distribution.package, notify=lambda kind, reason: orch.notify(kind, "", reason=reason))

    def package_for_policy(render_id: str, peek: bool = False):
        if peek:
            return distribution.package(render_id)
        package = distribution.build_package(render_id)
        return distribution.annotate_package(render_id, rights={**render_rights(system, render_id), "override_reason": None}, checks=package_checks(package))
    has_folder = any(c.name == "publish.folder" for c in adapters.describe())
    from nexora.modules.sourcing.stock import StockScout
    system.stock_scout = StockScout(db_path, adapters, data_dir / "tmp" / "stock", **({"fetch": stock_preview, "frame": stock_preview} if stock_preview else {}))
    system.autonomy = Autonomy(orch, projects, package=package_for_policy, rights=lambda render_id: render_rights(system, render_id),
                               publish=(lambda render_id: system.publishing.publish(render_id, "publish.folder")) if has_folder else None,
                               approve_clips=lambda project_id, run_id: approve_clips_by_policy(system, project_id, run_id),
                               cut_gate=lambda project_id: cut_gate(system, project_id),
                               approve_pictures=lambda run_id: system.generation.approve(run_id, actor="policy"))
    from nexora.modules.planning.topic import TopicWriter
    system.topics = TopicWriter(db_path, adapters, context=lambda project_id: topic_context(system, project_id), submit=orch.submit_run)
    system.topics.register(registry)
    system.producer = Producer(db_path, orch=orch, projects=projects, planning=planning, sourcing=sourcing, edit=edit, adapters=adapters,
                               fill_gap=lambda shot_id, line: fill_gap_from_stock(system, shot_id, line),
                               to_storyboard=lambda project_id: lay_out_storyboard(system, project_id),
                               style=lambda project_id: illustration_style(system, projects.project(project_id)),
                               write_topic=lambda project_id, topic, seconds, form: system.topics.start(project_id, topic, seconds=seconds, form=form),
                               topic_state=lambda run_id: (system.topics.get(run_id) or {}).get("state", "asked"),
                               apply_topic=lambda project_id, run_id: apply_topic(system, project_id, run_id),
                               generate=lambda script_id, shot_ids: system.generation.start(script_id, only=shot_ids))
    from nexora.agents.missions import Missions
    from nexora.core.missions import MissionStore

    def missing(pipeline_id: str) -> list[str] | None:
        found = next((c for c in capabilities(system) if c["pipeline"] == pipeline_id), None)
        return [f"quy trình {pipeline_id}"] if found is None else found["missing"]
    system.productions = productions
    system.missions = Missions(MissionStore(db_path), orch=orch, producer=system.producer, projects=projects, adapters=adapters, available=missing,
                               channels=lambda: [c["name"] for c in json.loads(orch.setting("channels", "[]"))], templates=lambda: [t["name"] for t in templates(system)],
                               budget_left=lambda: budget_left(system), prepare=lambda project_id, plan: prepare_mission_project(system, project_id, plan),
                               start_library=lambda kind: start_library_work(system, kind), autonomy=lambda: system.autonomy.level,
                               new_production=lambda title: productions.create(title))
    return system


def build_from_config(config, **overrides) -> System:
    """The system as one installation's settings describe it, with the real tools of this machine."""
    from nexora.adapters.desktop import DesktopNotifier
    from nexora.adapters.ollama import OllamaAdapter
    from nexora.adapters.openmontage import OpenMontageStock
    from nexora.adapters.stock_api import StockApi
    import os as _os
    from nexora.adapters.claude import ClaudeText
    from nexora.adapters.claude_code import ClaudeCode, find_claude
    claude_code = config.claude_code_binary or find_claude()          # Claude Code, when installed: the operator's plan
    from nexora.adapters.motion import StillMotion
    from nexora.adapters.outbox import FolderPublisher
    from nexora.adapters.pollinations import PollinationsImage
    from nexora.adapters.runpod import RunPodImage, RunPodLipSync, RunPodTrainer, RunPodUpscale, RunPodVideo
    from nexora.adapters.runpod_restore import RunPodRestore
    runpod_key = _os.environ.get("RUNPOD_API_KEY") or config.runpod_api_key
    rented_image = [RunPodImage(runpod_key, config.runpod_image_endpoint, price_per_second=config.runpod_price_per_second)] if runpod_key and config.runpod_image_endpoint else []
    rented = [RunPodVideo(runpod_key, config.runpod_video_endpoint, price_per_second=config.runpod_price_per_second)] if runpod_key and config.runpod_video_endpoint else []
    from nexora.adapters.fal import FalImage, FalVideo
    from nexora.adapters.comfy import Comfy, ComfyVideo
    comfy = [Comfy(runpod_key, config.runpod_comfy_endpoint, checkpoint=config.comfy_checkpoint, price_per_second=config.runpod_price_per_second),
             ComfyVideo(runpod_key, config.runpod_comfy_endpoint, checkpoint=config.comfy_video_checkpoint, price_per_second=config.runpod_price_per_second)] \
        if runpod_key and config.runpod_comfy_endpoint else []
    fal_key = _os.environ.get("FAL_KEY") or config.fal_api_key
    fal = ([FalImage(fal_key, config.fal_image_model, price=config.fal_image_price)] if config.fal_image_model else []) + \
          ([FalVideo(fal_key, config.fal_video_model, price=config.fal_video_price_per_second)] if config.fal_video_model else []) if fal_key else []
    from nexora.adapters.speech import WhisperCpp
    from nexora.adapters.apple import AppleSound, AppleTool, AppleVision
    from nexora.adapters.voice import SayVoice
    from nexora.adapters.web import WebReader
    from nexora.adapters.youtube import YouTubePublisher
    return build(config.data_dir, ffmpeg_binary=config.ffmpeg_binary, min_free_bytes=int(config.min_free_gb * 1024**3), segment_seconds=config.segment_seconds, judge=config.judge,
                 model=OllamaAdapter(host=config.ollama_host, vision_model=config.vision_model, embed_model=config.embed_model,
                                     judge_model=config.judge_model, writer_model=config.writer_model),
                 voice=SayVoice(), voice_name=config.voice, match_threshold=config.match_threshold,
                 stock=OpenMontageStock(config.openmontage_repo, keys={"pexels": _os.environ.get("PEXELS_API_KEY") or config.pexels_api_key, "pixabay_video": _os.environ.get("PIXABAY_API_KEY") or config.pixabay_api_key}), desktop=DesktopNotifier(), web=WebReader(),
                 stock_api=StockApi(pexels_key=_os.environ.get("PEXELS_API_KEY") or config.pexels_api_key, pixabay_key=_os.environ.get("PIXABAY_API_KEY") or config.pixabay_api_key),
                 pictures=_pictures(config),
                 recognisers=[AppleVision(AppleTool(Path(config.data_dir) / "tools")), AppleSound(AppleTool(Path(config.data_dir) / "tools"))] if AppleTool(Path(config.data_dir) / "tools").available() else [],
                 speech=WhisperCpp(config.speech_model, language=config.speech_language, vad_model=config.speech_vad_model or None) if config.speech_model else None,
                 generators=[*rented_image, *fal, *comfy[:1], *([PollinationsImage(token=config.pollinations_token)] if config.pollinations else []), *rented, *comfy[1:], StillMotion()],
                 shot_models=[cls(runpod_key, endpoint, price_per_second=config.runpod_price_per_second) for cls, endpoint in
                              ((RunPodLipSync, config.runpod_lipsync_endpoint), (RunPodUpscale, config.runpod_upscale_endpoint), (RunPodTrainer, config.runpod_train_endpoint))
                              if runpod_key and endpoint]
                             + ([RunPodRestore(runpod_key, config.runpod_restore_endpoint, price_per_second=config.runpod_price_per_second, tasks=tuple(config.runpod_restore_tasks),
                                               concurrency=config.runpod_restore_concurrency, ffmpeg=config.ffmpeg_binary or "ffmpeg")]
                                if runpod_key and config.runpod_restore_endpoint else []),
                 publishers=[*([FolderPublisher(config.publish_folder)] if config.publish_folder else []),
                             *([YouTubePublisher(config.youtube_client_id, config.youtube_client_secret, config.youtube_refresh_token, privacy=config.youtube_privacy)]
                               if config.youtube_client_id and config.youtube_client_secret and config.youtube_refresh_token else [])],
                 cloud_models=([ClaudeText(_os.environ.get("ANTHROPIC_API_KEY") or config.anthropic_api_key, model=config.claude_model, workspace_id=config.anthropic_workspace_id,
                                           input_price=config.claude_input_price, output_price=config.claude_output_price)]
                               if (_os.environ.get("ANTHROPIC_API_KEY") or config.anthropic_api_key) else [])
                              + ([ClaudeCode(claude_code, model=config.claude_code_model, effort=config.claude_code_effort, chat_seconds=config.claude_code_chat_seconds,
                                             research_seconds=config.claude_code_research_seconds, workdir=Path(config.data_dir) / "claude_code")] if claude_code else []),
                 **overrides)


def _pictures(config):
    """The picture-and-words model, when its environment has been set up (scripts/setup-pictures.sh) and it is not turned off."""
    from nexora.adapters.siglip import PictureText
    found = PictureText(Path(config.data_dir) / "tools" / "siglip" / "bin" / "python", config.picture_model) if config.picture_model else None
    return found if found is not None and found.available() else None


def doctor(system: System, config=None) -> list[dict]:
    """Everything this installation needs, checked one by one, with what to do about each thing that is missing."""
    import sqlite3
    checks = []
    add = lambda name, ok, detail, fix=None, optional=False: checks.append({"name": name, "ok": bool(ok), "detail": detail, "fix": None if ok else fix, "optional": optional})
    for tool in ("ffmpeg", "ffprobe", "say", "osascript"):
        add(f"Công cụ {tool}", shutil.which(tool), shutil.which(tool) or "không tìm thấy", f"Cài {tool} và bảo đảm nó nằm trong PATH." )
    env = system.adapters.environment()
    model = env.get("model") or {}
    add("Ollama đang chạy", model.get("running"), "có kết nối" if model.get("running") else "không kết nối được", "Mở ứng dụng Ollama hoặc chạy `ollama serve`.")
    for wanted, have in (model.get("models") or {}).items():
        add(f"Mô hình {wanted}", have, "đã tải" if have else "chưa tải", f"Chạy `ollama pull {wanted}`.")
    speech = env.get("speech")
    if speech is not None:
        add("Công cụ nhận dạng giọng nói", speech.get("binary"), speech.get("binary") or "không tìm thấy whisper-cli", "Chạy `brew install whisper-cpp`.", optional=True)
        add("Mô hình nhận dạng giọng nói", speech.get("model_present"), speech["model"] if speech.get("model_present") else "chưa có file mô hình",
            f"Tải một mô hình ggml của whisper.cpp về {speech['model']}, hoặc sửa speech_model trong nexora.toml.", optional=True)
    voices = (env.get("voice") or {}).get("vietnamese_voices", [])
    add("Giọng đọc tiếng Việt", voices, ", ".join(voices) or "không có", "Tải một giọng tiếng Việt trong Cài đặt > Trợ năng > Nội dung được đọc.")
    missing = [k for k, ok in (env.get("ffmpeg") or {}).get("filters", {}).items() if not ok]
    add("Bộ lọc FFmpeg", not missing, f"đủ ({(env.get('ffmpeg') or {}).get('binary')})" if not missing else f"thiếu {', '.join(missing)}", "Chạy `brew install ffmpeg-full` để có bộ lọc chuyển HDR về SDR; hệ thống tự dùng bản đó khi có.", optional=True)
    for name, state in system.adapters.checks().items():
        add(f"Kết nối {name}", state["ok"], state["detail"], "Xem khoá và mã endpoint trong nexora.toml.", optional=True)
    if config and config.runpod_api_key and not any(n.endswith(".runpod") for n in system.adapters.checks()):
        from nexora.adapters.runpod import RunPodVideo
        state = RunPodVideo(config.runpod_api_key, "").check()
        accepted = "khoá được chấp nhận" in state["detail"]
        add("Kết nối RunPod", accepted, "khoá được chấp nhận; chưa có mã endpoint nào trong nexora.toml" if accepted else state["detail"],
            "Xem runpod_api_key trong nexora.toml.", optional=True)
    free = shutil.disk_usage(system.data_dir).free
    add("Ổ đĩa", free > 5 * 1024**3, f"còn trống {free / 1024**3:.0f} GB", "Giải phóng dung lượng hoặc dọn bộ đệm ở mục Hệ thống.")
    conn = sqlite3.connect(system.data_dir / "nexora.db")
    try:
        state = conn.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        conn.close()
    add("Cơ sở dữ liệu", state == "ok", state, "Khôi phục từ một bản sao lưu: `python -m nexora restore <file>`.")
    if config:
        repo = __import__("pathlib").Path(config.openmontage_repo).expanduser()
        add("OpenMontage (tìm clip stock)", repo.is_dir(), str(repo) if repo.is_dir() else "không tìm thấy", f"Đặt OpenMontage ở {repo} hoặc sửa openmontage_repo trong nexora.toml.")
    return checks
