"""Composition root: builds the system from its parts. The only place that knows every layer."""
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from nexora.adapters.graphics import CaptionAdapter
from nexora.adapters.media import FFmpegAdapter, FFprobeAdapter
from nexora.core.adapter import AdapterRegistry
from nexora.core.adapter import Adapter, PrivacyClass, Request
from nexora.core.assets import AssetStore
from nexora.core.index import MomentIndex
from nexora.core.orchestrator import Orchestrator
from nexora.agents.producer import Producer
from nexora.core.pipeline import PipelineRegistry
from nexora.core.schedule import in_window
from nexora.core.projects import ProjectStore
from nexora.core.states import RunStatus
from nexora.core.worker import Worker
from nexora.modules.library.ingest import Library
from nexora.modules.distribution.package import Distribution
from nexora.modules.edit.render import Edit
from nexora.modules.edit.roughcut import RoughCut
from nexora.modules.library.transcribe import Transcription
from nexora.modules.library.understand import Understanding
from nexora.modules.planning.scripts import Planning
from nexora.modules.quality.review import review_cut
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
    roughcut: RoughCut = None


def fill_gap_from_stock(system: "System", shot_id: str, query: str) -> dict:
    """Resolve a gap with licensed stock: search, bring the clip into the Library like any footage, and propose it for the shot.
    Only the query text leaves the machine. Lives here because it joins two modules that may not import each other."""
    out_dir = system.data_dir / "media" / "stock"
    sources = json.loads(system.orch.setting("stock_sources", "[]"))          # the operator's choice of stock libraries; empty means the adapter's own
    result = system.adapters.submit("stock", Request("search", inputs={"queries": [query]}, params={"out_dir": str(out_dir), "clips_per_query": 1, **({"sources": sources} if sources else {})},
                                                    privacy_class=PrivacyClass.CLOUD_ALLOWED))
    if not result.files:
        return {"found": False}
    clip = result.outputs["clips"][0]
    rights = {"source": clip.get("source"), "source_url": clip.get("source_url"), "license": clip.get("license"), "creator": clip.get("creator"), "query": query}
    asset_id, run_id = system.library.ingest(result.files[0], origin="licensed", rights=rights)
    # Proposed at once so the operator sees something; placed properly, or withdrawn, once the clip has been watched (see build()).
    system.sourcing.use_asset(shot_id, asset_id, pending=system.library.understands,
                              reason=f"Clip stock từ {clip.get('source')}. Giấy phép: {clip.get('license')}. Nguồn: {clip.get('source_url')}")
    if system.orch.run_status(run_id) is RunStatus.SUCCEEDED and system.index.moments(asset_id, level="segment"):
        system.sourcing.refine_from_asset(shot_id, asset_id)     # the same clip was fetched before and has already been watched
    return {"found": True, "asset_id": asset_id, "run_id": run_id, "rights": rights}


PIPELINE_NAMES = {"library.ingest": "Nhập footage", "library.ingest_image": "Nhập ảnh", "library.ingest_audio": "Nhập nhạc", "library.understand": "Hiểu nội dung footage", "library.transcribe": "Nghe lời nói trong footage",
                  "sourcing.match": "Chọn clip", "sourcing.generate": "Sinh hình bằng AI", "edit.render": "Dựng video", "edit.preview": "Dựng bản xem thử"}
ANNOUNCE = {"disk_low": "ổ đĩa sắp đầy", "volume_offline": "không tìm thấy nơi chứa footage", "gaps": "còn câu chưa có hình", "waiting_review": "đang chờ bạn duyệt", "blocked": "đang dừng và cần bạn xử lý", "failed": "thất bại", "succeeded": "đã xong"}
QUIET = frozenset({"library.ingest", "library.ingest_image", "library.ingest_audio", "library.understand", "library.transcribe", "edit.preview"})   # finishing these needs nobody's attention


def announce(system: "System", after: int) -> int:
    """Send every notification newer than `after` to the desktop, when the operator has turned that on. Returns the newest id seen."""
    for n in system.orch.notifications_after(after):
        after = n["notification_id"]
        pipeline = (system.orch.run_info(n["run_id"]) or {}).get("pipeline_id")
        muted = json.loads(system.orch.setting("notify_off", "[]"))
        quiet = system.orch.setting("quiet_hours", "")
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


DEFAULT_TEMPLATES = [
    {"name": "Video ngang có lời dẫn", "format": "landscape", "voice": "", "music_gain": 0.35, "auto_accept": False, "caption_scale": 1.0, "caption_position": "bottom", "pronounce": {}},
    {"name": "Video dọc ngắn", "format": "portrait", "voice": "", "music_gain": 0.3, "auto_accept": True, "caption_scale": 1.15, "caption_position": "middle", "pronounce": {}},
]
MEDIA_EXT = frozenset({".mp4", ".mov", ".m4v", ".mkv", ".avi", ".mts", ".webm", ".jpg", ".jpeg", ".png", ".webp", ".mp3", ".wav", ".m4a", ".aiff", ".flac"})


def templates(system: "System") -> list[dict]:
    """Format templates: the settings a kind of video always starts from."""
    stored = system.orch.setting("templates")
    return json.loads(stored) if stored else DEFAULT_TEMPLATES


def scan_watch_folders(system: "System", *, now: float | None = None, settle_seconds: float = 15.0) -> list[str]:
    """Ingest media that appeared in a watched folder. A file is taken only once it has stopped changing, so a copy in progress is never read."""
    import time
    now = time.time() if now is None else now
    known = {str(system.assets.path_of(system.assets.original(a["asset_id"]))) for a in system.assets.assets()}
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
          web: Adapter | None = None, speech: Adapter | None = None) -> System:
    """`model` is the adapter for vision, reasoning and embeddings; without one, footage is ingested but not understood."""
    data_dir = Path(data_dir).resolve()          # tools resolve relative paths differently; keep every path absolute
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "nexora.db"
    orch, assets = Orchestrator(db_path), AssetStore(db_path)
    adapters = AdapterRegistry()
    adapters.register(FFprobeAdapter())
    adapters.register(FFmpegAdapter())
    adapters.register(CaptionAdapter())
    if voice is not None:
        adapters.register(voice)
    adapters.observer = orch.record_call
    adapters.local_only = lambda: orch.setting("privacy_local_only", "0") == "1"
    index = MomentIndex(db_path)
    understanding = None
    if model is not None:
        adapters.register(model)
        index.embed = lambda texts: adapters.submit("model", Request("embed", inputs={"texts": texts})).outputs["vectors"]
        understanding = Understanding(assets, index, adapters, data_dir / "media", segment_seconds=segment_seconds)
    registry = PipelineRegistry()
    transcription = None
    if speech is not None:
        adapters.register(speech)
        transcription = Transcription(assets, index, adapters)
    library = Library(orch, assets, adapters, data_dir / "media", min_free_bytes=min_free_bytes, understanding=understanding, transcription=transcription)
    library.register(registry)
    projects = ProjectStore(db_path)
    planning = Planning(projects, assets, index, adapters)
    sourcing = Sourcing(orch, projects, index, threshold=match_threshold, adapters=adapters, judge=judge and model is not None, rejected=assets.rejected)
    sourcing.register(registry)
    library.on_understood.append(lambda asset_id: [sourcing.refine_from_asset(shot_id, asset_id) for shot_id in sourcing.pending_for(asset_id)])
    edit = Edit(orch, projects, assets, adapters, data_dir / "media", voice=voice is not None, voice_name=voice_name, reviewer=review_cut, model=model is not None)
    edit.register(registry)
    if stock is not None:
        adapters.register(stock)
    if desktop is not None:
        adapters.register(desktop)
    if web is not None:
        adapters.register(web)
    for generator in generators or []:
        adapters.register(generator)
    generation = Generation(orch, projects, assets, adapters, data_dir / "media", judge=model is not None,
                            prefer=lambda kind: json.loads(orch.setting(f"providers:{kind}", "[]")))
    generation.register(registry)
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
               Worker(orch, registry, worker_id=f"background-{os.getpid()}", lanes=frozenset({"background"}), log=log, allowed=night_only)]
    system = System(data_dir, orch, assets, adapters, registry, worker, library, index, projects, planning, sourcing, edit, distribution, generation, workers)
    system.roughcut = RoughCut(projects, assets, index)
    system.producer = Producer(db_path, orch=orch, projects=projects, planning=planning, sourcing=sourcing, edit=edit, adapters=adapters,
                               fill_gap=lambda shot_id, query: fill_gap_from_stock(system, shot_id, query))
    return system


def build_from_config(config, **overrides) -> System:
    """The system as one installation's settings describe it, with the real tools of this machine."""
    from nexora.adapters.desktop import DesktopNotifier
    from nexora.adapters.ollama import OllamaAdapter
    from nexora.adapters.openmontage import OpenMontageStock
    from nexora.adapters.motion import StillMotion
    from nexora.adapters.pollinations import PollinationsImage
    from nexora.adapters.speech import WhisperCpp
    from nexora.adapters.voice import SayVoice
    from nexora.adapters.web import WebReader
    return build(config.data_dir, min_free_bytes=int(config.min_free_gb * 1024**3), segment_seconds=config.segment_seconds, judge=config.judge,
                 model=OllamaAdapter(host=config.ollama_host, vision_model=config.vision_model, embed_model=config.embed_model,
                                     judge_model=config.judge_model, writer_model=config.writer_model),
                 voice=SayVoice(), voice_name=config.voice, match_threshold=config.match_threshold,
                 stock=OpenMontageStock(config.openmontage_repo), desktop=DesktopNotifier(), web=WebReader(),
                 speech=WhisperCpp(config.speech_model, language=config.speech_language) if config.speech_model else None,
                 generators=[*([PollinationsImage(token=config.pollinations_token)] if config.pollinations else []), StillMotion()], **overrides)


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
    add("Bộ lọc FFmpeg", not missing, "đủ" if not missing else f"thiếu {', '.join(missing)}", "Cài bản FFmpeg đầy đủ hơn nếu cần chuyển HDR hoặc vẽ chữ bằng FFmpeg.", optional=True)
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
