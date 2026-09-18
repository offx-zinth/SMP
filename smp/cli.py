from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv

from smp.core.config import Settings
from smp.logging import configure_logging, get_logger

load_dotenv(Path(__file__).parent.parent / ".env")

log = get_logger(__name__)

DEFAULT_EXTENSIONS = (
    ".py",
    ".pyw",
    ".pyi",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".ts",
    ".mts",
    ".cts",
    ".tsx",
    ".java",
    ".c",
    ".h",
    ".cpp",
    ".cc",
    ".cxx",
    ".hpp",
    ".hh",
    ".cs",
    ".go",
    ".rs",
    ".php",
    ".rb",
    ".swift",
    ".kt",
    ".kts",
    ".m",
)
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

    Uses a ThreadPoolExecutor to parallelize CPU-bound parsing, then
     applies results to the store sequentially.
    """
    from smp.store.graph.mmap_store import MMapGraphStore
    from smp.store.graph.parser import CodeParser, ParsedFile

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

    # 1. Collect files to parse
    files_to_parse: list[Path] = []
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
        files_to_parse.append(file_path)

    # 2. Parallel Parse
    parser = CodeParser()
    loop = asyncio.get_running_loop()

    def parse_sync(path: Path) -> tuple[str, ParsedFile | Exception]:
        try:
            return (str(path), parser.parse_file(str(path)))
        except Exception as e:
            return (str(path), e)

    with ThreadPoolExecutor() as executor:
        tasks = [loop.run_in_executor(executor, parse_sync, f) for f in files_to_parse]
        results = await asyncio.gather(*tasks)

    # 3. Sequential Apply
    for file_path_str, result in results:
        if isinstance(result, Exception):
            log.warning("parse_failed", file=file_path_str, error=str(result))
            stats["errors"] += 1
            continue

        try:
            await graph_store._apply_parsed_file(file_path_str, result)
            stats["files"] += 1
            stats["nodes"] += len(result.nodes)
        except Exception as exc:
            log.warning("apply_failed", file=file_path_str, error=str(exc))
            stats["errors"] += 1

    stats["edges"] = await graph_store.count_edges()

    try:
        stats["linked"] = await graph_store.resolve_placeholders()
    except Exception as exc:
        log.warning("placeholder_linking_failed", error=str(exc))
        stats["linked"] = 0

    elapsed = time.monotonic() - t0
    log.info(
        "ingest_complete",
        directory=str(root),
        graph_path=resolved_path,
        files=stats["files"],
        nodes=stats["nodes"],
        edges=stats["edges"],
        linked=stats["linked"],
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

    mcp_cmd = sub.add_parser("mcp", help="Start the SMP MCP server over stdio (for AI agents)")
    mcp_cmd.add_argument(
        "--graph-path",
        type=str,
        help="Path to the .smpg graph file (defaults to SMP_GRAPH_PATH or .smp/graph.smpg)",
    )
    mcp_cmd.add_argument("--json-log", action="store_true", help="JSON structured logging")

    backup_cmd = sub.add_parser("backup", help="Snapshot the graph file consistently")
    backup_cmd.add_argument("--graph-path", type=str, help="Live graph file (defaults to env)")
    backup_cmd.add_argument("--output", required=True, help="Where to write the snapshot")
    backup_cmd.add_argument(
        "--incremental",
        action="store_true",
        help="Incremental backup (not yet supported; exits non-zero)",
    )
    backup_cmd.add_argument("--json-log", action="store_true")

    restore_cmd = sub.add_parser("restore", help="Restore a graph file from a backup")
    restore_cmd.add_argument("--graph-path", type=str, help="Live graph file (defaults to env)")
    restore_cmd.add_argument("--input", required=True, help="Backup file to restore from")
    restore_cmd.add_argument("--json-log", action="store_true")

    compact_cmd = sub.add_parser("compact", help="Rewrite the journal to drop obsolete records")
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

        from smp.protocol.server import create_app, setup_graceful_shutdown

        settings = Settings.from_env()
        host = args.host or settings.host
        port = args.port or settings.port

        application = create_app(graph_path=args.graph_path)

        # Setup graceful shutdown handlers
        server = uvicorn.Server(uvicorn.Config(application, host=host, port=port))
        setup_graceful_shutdown(server, application)

        # Run server
        try:
            asyncio.run(server.serve())
        except KeyboardInterrupt:
            log.info("server_shutdown_keyboard_interrupt")
        except Exception as exc:  # noqa: BLE001
            log.exception("server_error", error=str(exc))

    elif args.command == "mcp":
        if args.graph_path:
            os.environ["SMP_GRAPH_PATH"] = args.graph_path

        from smp.protocol.mcp import main as mcp_main

        try:
            mcp_main()
        except KeyboardInterrupt:
            log.info("mcp_shutdown_keyboard_interrupt")
        except Exception as exc:  # noqa: BLE001
            log.exception("mcp_server_error", error=str(exc))
            sys.exit(1)

    elif args.command == "backup":
        if getattr(args, "incremental", False):
            print("error: incremental backups are not supported yet (take a full backup)", file=sys.stderr)
            sys.exit(1)
        from smp.observability.backup import backup as backup_store
        from smp.store.graph.mmap_store import MMapGraphStore

        settings = Settings.from_env()
        path = args.graph_path or settings.graph_path

        async def _do_backup() -> None:
            store = MMapGraphStore(path=path)
            try:
                await store.connect()
            except (FileNotFoundError, ValueError, OSError) as exc:
                print(f"backup failed: cannot open graph file: {exc}", file=sys.stderr)
                sys.exit(1)
            try:
                target = await backup_store(store, args.output)
                print(f"Backup written: {target} ({store.file.size} bytes)")
            except OSError as exc:
                print(f"backup failed: {exc}", file=sys.stderr)
                sys.exit(1)
            finally:
                await store.close()

        asyncio.run(_do_backup())

    elif args.command == "restore":
        from smp.observability.backup import restore as restore_store

        settings = Settings.from_env()
        path = args.graph_path or settings.graph_path

        async def _do_restore() -> None:
            try:
                target = await restore_store(path, args.input)
            except FileNotFoundError as exc:
                print(f"restore failed: backup file not found: {exc}", file=sys.stderr)
                sys.exit(1)
            except (ValueError, OSError) as exc:
                print(f"restore failed: {exc}", file=sys.stderr)
                sys.exit(1)
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
                print(f"Compacted: {stats['before_bytes']} -> {stats['after_bytes']} bytes (saved {saved})")
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
