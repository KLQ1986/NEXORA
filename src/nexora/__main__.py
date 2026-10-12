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
            print(asset["asset_id"], system.library.understand(asset["asset_id"], force=args.force))
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
        uvicorn.run(create_app(system, web_dir=web, config=config), host="127.0.0.1", port=port, log_level="warning", timeout_graceful_shutdown=2)


if __name__ == "__main__":
    main()
