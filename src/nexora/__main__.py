"""Command line: python -m nexora [--data DIR] <command>."""
import argparse
import json
from dataclasses import replace
from pathlib import Path

from nexora.adapters.media import ffmpeg_capabilities
from nexora.app import build_from_config, doctor
from nexora.config import TEMPLATE, Config
from nexora.core import backup as backups

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".mts", ".webm", ".ogv"}


def main() -> None:
    parser = argparse.ArgumentParser(prog="nexora")
    parser.add_argument("--config", default="nexora.toml", help="settings file (optional)")
    parser.add_argument("--data", default=None, help="data directory; overrides the settings file")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("ingest", help="register files or folders and start their ingest runs")
    p.add_argument("paths", nargs="+")
    p = sub.add_parser("worker", help="run stages")
    p.add_argument("--drain", action="store_true", help="run until nothing is left, then exit")
    p = sub.add_parser("understand", help="describe and index every ingested video")
    p.add_argument("--force", action="store_true")
    sub.add_parser("runs", help="list runs and their stages")
    sub.add_parser("assets", help="list assets")
    sub.add_parser("env", help="check the environment")
    p = sub.add_parser("serve", help="start the API on the loopback address")
    p.add_argument("--port", type=int, default=None)
    sub.add_parser("doctor", help="check everything this installation needs")
    sub.add_parser("backup", help="copy the database into the backups folder")
    p = sub.add_parser("restore", help="put a backup in place of the database (stop the server first)")
    p.add_argument("file")
    sub.add_parser("init-config", help="write a nexora.toml with every setting and its default")
    p = sub.add_parser("vq", help="Visual Quality on any file: profile, recipe, preview, and with --out the result")
    p.add_argument("file")
    p.add_argument("--out", help="write the result here (approves the recipe)")
    p.add_argument("--preview", type=float, default=None, metavar="T", help="preview at T seconds, with temporal QA")
    p.add_argument("--seconds", type=float, default=3.0, help="length of the preview")
    p.add_argument("--target-height", type=int, default=None, help="upscale to this height")
    p.add_argument("--target-fps", type=int, default=None, help="interpolate to this frame rate")
    p.add_argument("--no-denoise", action="store_true")
    p.add_argument("--no-sharpen", action="store_true")
    p.add_argument("--no-stabilise", action="store_true")
    p.add_argument("--no-exposure", action="store_true")
    p.add_argument("--allow-cloud", action="store_true", help="let this recording go to the restoration endpoint on RunPod (VRT deblur); never in privacy mode")
    p.add_argument("--master", action="store_true", help="ProRes 422 HQ instead of HEVC 10-bit")
    p.add_argument("--json", action="store_true", help="print the whole profile and recipe as JSON")
    p.add_argument("--bench", action="store_true", help="also measure the engine on a clean frame of this file, damaged on purpose")
    args = parser.parse_args()
    if args.command == "init-config":
        target = Path(args.config)
        if target.exists():
            raise SystemExit(f"{target} already exists")
        target.write_text(TEMPLATE, encoding="utf-8")
        print(f"wrote {target}")
        return
    config = Config.load(args.config)
    if args.data:
        config = replace(config, data_dir=args.data)
    if args.command == "restore":                 # before anything opens the database
        kept = backups.restore(args.file, Path(config.data_dir).resolve() / "nexora.db")
        print(f"restored {args.file}; the database it replaced is kept as {kept.name}")
        return
    system = build_from_config(config)
    if args.command == "doctor":
        problems = 0
        for check in doctor(system, config):
            print(f"{'ok  ' if check['ok'] else 'opt ' if check['optional'] else 'MISS'}  {check['name']}: {check['detail']}" + (f"\n      {check['fix']}" if check["fix"] else ""))
            problems += not check["ok"] and not check["optional"]
        raise SystemExit(1 if problems else 0)
    if args.command == "backup":
        print(backups.backup(system.data_dir / "nexora.db", system.data_dir / "backups", keep=config.backups_kept))
        return

    if args.command == "vq":
        _vq(system, args)
        return

    if args.command == "ingest":
        for given in args.paths:
            root = Path(given).expanduser()
            files = sorted(f for f in root.rglob("*") if f.suffix.lower() in VIDEO_EXT) if root.is_dir() else [root]
            for f in files:
                asset_id, run_id = system.library.ingest(f)
                print(f"{asset_id}  {run_id}  {f.name}")
    elif args.command == "worker":
        if args.drain:
            system.worker.recover()
            import time
            while True:
                if system.worker.run_once():
                    continue
                waiting = any(s.status.value == "retry_wait" for r in system.orch.runs() for s in system.orch.stages(r))
                if not waiting:
                    break
                time.sleep(5)                # a stage is backing off before its retry
        else:
            system.worker.run_forever()
    elif args.command == "understand":
        for asset in system.assets.assets():
            print(asset["asset_id"], system.intelligence.understand(asset["asset_id"], force=args.force))
    elif args.command == "runs":
        for run_id in system.orch.runs():
            info = system.orch.run_info(run_id)
            print(f"{run_id}  {system.orch.run_status(run_id).value:14s} {info['pipeline_id']}  {info['subject_ref'] or ''}")
            for s in system.orch.stages(run_id):
                reason = f"  ({s.blocked_reason})" if s.blocked_reason else ""
                print(f"    {s.stage_key:12s} {s.status.value}{reason}")
    elif args.command == "assets":
        for asset in system.assets.assets():
            versions = system.assets.versions(asset["asset_id"])
            original = next(v for v in versions if v.role == "original")
            meta = original.metadata
            print(f"{asset['asset_id']}  {system.assets.path_of(original).name}  roles={[v.role for v in versions]}")
            if "probe" in meta:
                print(f"    {meta['probe']['width']}x{meta['probe']['height']}  {meta['probe']['duration']:.1f}s  usable={meta.get('usable_ranges')}")
            if "duplicate_of" in meta:
                print(f"    duplicate of {meta['duplicate_of']}")
    elif args.command == "env":
        print(json.dumps(ffmpeg_capabilities(), indent=2))
    elif args.command == "serve":
        import threading

        import uvicorn

        from nexora.api.app import create_app
        # One command runs everything: the worker on its own thread, the API and Web UI on the loopback address.
        # A backup at every start: cheap, and the moment before new work is the moment a copy is worth most.
        backups.backup(system.data_dir / "nexora.db", system.data_dir / "backups", keep=config.backups_kept)
        system.worker.recover()
        for worker in system.workers:
            threading.Thread(target=worker.run_forever, kwargs={"recover": False}, name=f"nexora-{worker.worker_id}", daemon=True).start()

        def produce():
            import time
            while True:
                try:
                    system.producer.tick()
                    system.autonomy.tick()
                    system.publishing.collect()
                except Exception as err:           # the agent must never take the server down
                    print(f"producer: {err!r}")
                time.sleep(3)
        threading.Thread(target=produce, name="nexora-producer", daemon=True).start()

        def watch():
            import time
            from nexora.app import scan_watch_folders, watch_health
            while True:
                try:
                    scan_watch_folders(system)
                    watch_health(system)
                except Exception as err:
                    print(f"watch folders: {err!r}")
                time.sleep(20)
        threading.Thread(target=watch, name="nexora-watch", daemon=True).start()

        def announcer():
            import time
            from nexora.app import announce
            seen = max((n["notification_id"] for n in system.orch.notifications(limit=1)), default=0)     # nothing from before this start
            while True:
                seen = announce(system, seen)
                time.sleep(3)
        threading.Thread(target=announcer, name="nexora-announcer", daemon=True).start()
        web = Path(__file__).resolve().parents[2] / "web" / "dist"
        port = args.port or config.port
        print(f"NEXORA: http://127.0.0.1:{port}" + ("" if web.is_dir() else "  (Web UI not built: run `npm run build` in web/)"))
        system.library.measure_unmeasured_music()        # tracks taken in by an older version are listened to once more
        system.library.find_missing_cuts()               # and footage taken in by an older version is looked through for scene cuts
        system.intelligence.find_unmeasured()                 # and measured, so that it is divided into shots and beats like the rest
        from nexora.app import TRASH_DAYS, purge_trash
        purge_trash(system, older_than_days=TRASH_DAYS)  # what has been in the Trash a month is deleted for good
        uvicorn.run(create_app(system, web_dir=web, config=config), host="127.0.0.1", port=port, log_level="warning", timeout_graceful_shutdown=2)




def _vq(system, args) -> None:
    """Visual Quality on one file, outside the library, run to the end before returning."""
    import time

    def wait(run_id: str) -> None:
        system.worker.recover()
        while system.orch.run_status(run_id).value not in ("succeeded", "failed", "cancelled", "blocked", "waiting_review"):
            if not system.worker.run_once():
                time.sleep(0.5)
        if system.orch.run_status(run_id).value != "succeeded":
            raise SystemExit(f"{run_id}: {system.orch.run_status(run_id).value}")

    try:
        subject = system.vq.subject_for_file(args.file)
    except FileNotFoundError:
        raise SystemExit(f"no such file: {args.file}")
    options = {"target_height": args.target_height, "target_fps": args.target_fps, "denoise": not args.no_denoise, "sharpen": not args.no_sharpen,
               "stabilise": not args.no_stabilise, "exposure": not args.no_exposure, "approve": bool(args.out),
               "allow_cloud": bool(args.allow_cloud)}
    wait(system.vq.analyse(subject, **{k: v for k, v in options.items() if v is not None}))
    profile = system.vq_reader.profile(subject)
    recipe = system.vq_reader.recipe(subject)
    if args.json:
        print(json.dumps({"subject": subject, "profile": profile, "recipe": recipe.data}, ensure_ascii=False, indent=2))
    else:
        t = profile["technical"]
        print(f"{subject}  {Path(args.file).name}")
        print(f"  nguồn: {t.get('codec') or t.get('container')} {t.get('display_width')}x{t.get('display_height')} {t.get('bit_depth')}-bit"
              f" {t.get('frame_rate') or ''} · {profile['content']} · màu: {profile.get('encoding_name') or 'không nhận ra'} ({profile['encoding_confidence']})")
        for w in profile.get("warnings", []):
            print(f"  ! {w}")
        for k, shot in enumerate(recipe.shots):
            print(f"  shot {k + 1} {shot['t_start']:.2f}-{shot['t_end']:.2f}s: " + (", ".join(f"{s['op']}[{s.get('tier', 'ffmpeg')}]" for s in shot["steps"]) or "không cần xử lý"))
            for s in shot["steps"]:
                print(f"      {s['op']}: {s.get('why', '')}")
    if args.preview is not None:
        wait(system.vq.preview(subject, t=args.preview, seconds=args.seconds))
        shown = system.vq_reader.previews(recipe.recipe_id)[0]
        print(f"  xem trước: {shown['qa']['verdict']}" + (f" ({'; '.join(shown['qa']['reasons'])})" if shown["qa"]["reasons"] else ""))
        for name, path in shown["files"].items():
            print(f"      {name}: {path}")
    if args.bench:
        from nexora.modules.visual_quality.benchmark import table
        print("  " + table(system.vq.benchmark(subject)).replace("\n", "\n  "))
    if args.out:
        wait(system.vq.apply(subject, out=args.out, master=args.master))
        print(f"  đã ghi: {args.out}")


if __name__ == "__main__":
    main()
