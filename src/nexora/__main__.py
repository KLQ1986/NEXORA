"""Command line: python -m nexora [--data DIR] <command>."""
import argparse
import json
from pathlib import Path

from nexora.adapters.media import ffmpeg_capabilities
from nexora.app import build

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".mts", ".webm", ".ogv"}


def main() -> None:
    parser = argparse.ArgumentParser(prog="nexora")
    parser.add_argument("--data", default="data", help="data directory (database and managed media)")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("ingest", help="register files or folders and start their ingest runs")
    p.add_argument("paths", nargs="+")
    p = sub.add_parser("worker", help="run stages")
    p.add_argument("--drain", action="store_true", help="run until nothing is left, then exit")
    sub.add_parser("runs", help="list runs and their stages")
    sub.add_parser("assets", help="list assets")
    sub.add_parser("env", help="check the environment")
    p = sub.add_parser("serve", help="start the API on the loopback address")
    p.add_argument("--port", type=int, default=8600)
    args = parser.parse_args()
    system = build(args.data)

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
            while system.worker.run_once():
                pass
        else:
            system.worker.run_forever()
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
        import uvicorn

        from nexora.api.app import create_app
        uvicorn.run(create_app(system), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
