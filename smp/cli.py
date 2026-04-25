from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from smp.core.config import Settings
from smp.logging import configure_logging, get_logger

load_dotenv(Path(__file__).parent.parent / ".env")

log = get_logger(__name__)

DEFAULT_EXTENSIONS = (".py",)
DEFAULT_MAX_FILE_SIZE = 1_000_000


async def ingest_directory(
    directory: str,
    *,
    graph_path: str | None = None,
    extensions: tuple[str, ...] = DEFAULT_EXTENSIONS,
    max_file_size: int = DEFAULT_MAX_FILE_SIZE,
    clear: bool = False,
) -> dict[str, int]:
    """Walk *directory*, parse all matching files, and build the graph.

    Files are parsed on-demand via :class:`MMapGraphStore.parse_file`,
    which extracts nodes and edge candidates and writes them through the
    memory-mapped store directly.
    """
    from smp.store.graph.mmap_store import MMapGraphStore

    settings = Settings.from_env()
    resolved_path = graph_path or settings.graph_path
    Path(resolved_path).parent.mkdir(parents=True, exist_ok=True)

    graph_store = MMapGraphStore(path=resolved_path)
    await graph_store.connect()
    if clear:
        await graph_store.clear()
        log.warning("graph_cleared")

    root = Path(directory).resolve()
    if not root.is_dir():
        raise ValueError(f"Not a directory: {root}")

    stats = {"files": 0, "nodes": 0, "edges": 0, "errors": 0, "skipped": 0}
    t0 = time.monotonic()

    for file_path in sorted(root.rglob("*")):
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() not in extensions:
            continue

        try:
            size = file_path.stat().st_size
        except OSError:
            continue
        if size > max_file_size:
            log.warning("file_too_large", file=str(file_path), size=size)
            stats["skipped"] += 1
            continue

        parts = file_path.relative_to(root).parts
        if any(
            p.startswith(".") or p in ("node_modules", "__pycache__", "venv", ".venv", "dist", "build") for p in parts
        ):
            continue

        try:
            graph_nodes = await graph_store.parse_file(str(file_path))
        except Exception as exc:  # noqa: BLE001
            log.warning("parse_failed", file=str(file_path), error=str(exc))
            stats["errors"] += 1
            continue

        stats["files"] += 1
        stats["nodes"] += len(graph_nodes)

    stats["edges"] = await graph_store.count_edges()

    elapsed = time.monotonic() - t0
    log.info(
        "ingest_complete",
        directory=str(root),
        graph_path=resolved_path,
        files=stats["files"],
        nodes=stats["nodes"],
        edges=stats["edges"],
        errors=stats["errors"],
        skipped=stats["skipped"],
        elapsed_s=round(elapsed, 2),
    )

    await graph_store.close()
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(prog="smp", description="Structural Memory Protocol CLI")
    sub = parser.add_subparsers(dest="command")

    ingest_cmd = sub.add_parser("ingest", help="Parse a directory and build the graph")
    ingest_cmd.add_argument("directory", help="Root directory to ingest")
    ingest_cmd.add_argument(
        "--graph-path",
        type=str,
        help="Path to the .smpg graph file (defaults to SMP_GRAPH_PATH or .smp/graph.smpg)",
    )
    ingest_cmd.add_argument("--clear", action="store_true", help="Clear graph before ingesting")
    ingest_cmd.add_argument("--json-log", action="store_true", help="JSON structured logging")
    ingest_cmd.add_argument("--max-size", type=int, default=DEFAULT_MAX_FILE_SIZE, help="Max file size in bytes")

    serve_cmd = sub.add_parser("serve", help="Start the SMP JSON-RPC server")
    serve_cmd.add_argument("--host", default=None, help="Bind host")
    serve_cmd.add_argument("--port", type=int, default=None, help="Bind port")
    serve_cmd.add_argument(
        "--graph-path",
        type=str,
        help="Path to the .smpg graph file (defaults to SMP_GRAPH_PATH or .smp/graph.smpg)",
    )
    serve_cmd.add_argument("--json-log", action="store_true", help="JSON structured logging")

    backup_cmd = sub.add_parser("backup", help="Snapshot the graph file consistently")
    backup_cmd.add_argument("--graph-path", type=str, help="Live graph file (defaults to env)")
    backup_cmd.add_argument("--output", required=True, help="Where to write the snapshot")
    backup_cmd.add_argument("--json-log", action="store_true")

    restore_cmd = sub.add_parser("restore", help="Restore a graph file from a backup")
    restore_cmd.add_argument("--graph-path", type=str, help="Live graph file (defaults to env)")
    restore_cmd.add_argument("--input", required=True, help="Backup file to restore from")
    restore_cmd.add_argument("--json-log", action="store_true")

    compact_cmd = sub.add_parser(
        "compact", help="Rewrite the journal to drop obsolete records"
    )
    compact_cmd.add_argument("--graph-path", type=str, help="Live graph file (defaults to env)")
    compact_cmd.add_argument("--json-log", action="store_true")

    integrity_cmd = sub.add_parser("integrity", help="Run a full on-disk integrity check")
    integrity_cmd.add_argument("--graph-path", type=str, help="Live graph file (defaults to env)")
    integrity_cmd.add_argument("--json-log", action="store_true")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    configure_logging(json=getattr(args, "json_log", False))

    if args.command == "ingest":
        stats = asyncio.run(
            ingest_directory(
                args.directory,
                graph_path=getattr(args, "graph_path", None),
                clear=args.clear,
                max_file_size=args.max_size,
            )
        )
        print(
            f"\nIngested {stats['files']} files: {stats['nodes']} nodes, "
            f"{stats['edges']} edges, {stats['errors']} errors"
        )

    elif args.command == "serve":
        import uvicorn

        if args.graph_path:
            os.environ["SMP_GRAPH_PATH"] = args.graph_path

        from smp.protocol.server import create_app

        settings = Settings.from_env()
        host = args.host or settings.host
        port = args.port or settings.port

        application = create_app(graph_path=args.graph_path)
        uvicorn.run(application, host=host, port=port)

    elif args.command == "backup":
        from smp.observability.backup import backup as backup_store
        from smp.store.graph.mmap_store import MMapGraphStore

        settings = Settings.from_env()
        path = args.graph_path or settings.graph_path

        async def _do_backup() -> None:
            store = MMapGraphStore(path=path)
            await store.connect()
            try:
                target = await backup_store(store, args.output)
                print(f"Backup written: {target} ({store.file.size} bytes)")
            finally:
                await store.close()

        asyncio.run(_do_backup())

    elif args.command == "restore":
        from smp.observability.backup import restore as restore_store

        settings = Settings.from_env()
        path = args.graph_path or settings.graph_path

        async def _do_restore() -> None:
            target = await restore_store(path, args.input)
            print(f"Restored to: {target}")

        asyncio.run(_do_restore())

    elif args.command == "compact":
        from smp.observability.backup import compact as compact_store
        from smp.store.graph.mmap_store import MMapGraphStore

        settings = Settings.from_env()
        path = args.graph_path or settings.graph_path

        async def _do_compact() -> None:
            store = MMapGraphStore(path=path)
            await store.connect()
            try:
                stats = await compact_store(store)
                saved = stats["before_bytes"] - stats["after_bytes"]
                print(
                    f"Compacted: {stats['before_bytes']} -> {stats['after_bytes']} bytes "
                    f"(saved {saved})"
                )
            finally:
                await store.close()

        asyncio.run(_do_compact())

    elif args.command == "integrity":
        import json as _json

        from smp.store.graph.mmap_store import MMapGraphStore

        settings = Settings.from_env()
        path = args.graph_path or settings.graph_path

        async def _do_integrity() -> None:
            store = MMapGraphStore(path=path)
            await store.connect()
            try:
                report = await store.integrity_report()
                print(_json.dumps(report, indent=2, default=str))
                if not report["ok"]:
                    sys.exit(2)
            finally:
                await store.close()

        asyncio.run(_do_integrity())


if __name__ == "__main__":
    main()
