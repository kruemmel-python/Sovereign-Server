from __future__ import annotations
import argparse, dataclasses
from pathlib import Path
from .config import DEFAULT_CONFIG
from .server import SovereignServer

def main(router=None) -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--host", default=DEFAULT_CONFIG.host)
    p.add_argument("--port", type=int, default=DEFAULT_CONFIG.port)
    p.add_argument("--workers", type=int, default=DEFAULT_CONFIG.workers)
    p.add_argument("--static-dir", type=Path, default=DEFAULT_CONFIG.static_dir)
    p.add_argument("--upload-dir", type=Path, default=DEFAULT_CONFIG.upload_dir)
    p.add_argument("--task-db", type=Path, default=DEFAULT_CONFIG.task_db)
    p.add_argument("--json-logs", action="store_true")
    args = p.parse_args()
    if router is None:
        from examples.app import router
    config = dataclasses.replace(DEFAULT_CONFIG, host=args.host, port=args.port, workers=args.workers,
                                 static_dir=args.static_dir, upload_dir=args.upload_dir,
                                 task_db=args.task_db, json_logs=args.json_logs)
    SovereignServer(router, config).serve_forever()

if __name__ == "__main__":
    main()
