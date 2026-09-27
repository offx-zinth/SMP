from __future__ import annotations

import argparse
import asyncio
import contextlib
import gc
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from smp.core.config import Settings
from smp.logging import configure_logging, get_logger

load_dotenv(Path(__file__).parent.parent / ".env")

# Use the "smp.cli" logger name explicitly: under `python -m smp.cli`,
# __name__ is "__main__" which is outside the "smp" logger hierarchy and
# would fall back to the root logger (WARNING level — INFO events dropped).
log = get_logger("smp.cli")

_WORKER_PARSER: Any = None


def _init_parse_worker(worker_cpus: frozenset[int] | None = None) -> None:
    """Create a per-process parser once (tree-sitter is CPU/GIL bound).

    Best-effort CPU isolation: the parent pins itself to one logical CPU for
    the apply loop; workers take the remaining CPUs so apply doesn't get
    timesliced against parse (measured ~2x apply slowdown under contention).
    """
    if worker_cpus:
        with contextlib.suppress(OSError, AttributeError):
            os.sched_setaffinity(0, set(worker_cpus))
    global _WORKER_PARSER
    from smp.store.graph.parser import CodeParser

    _WORKER_PARSER = CodeParser()


def _parse_in_worker(file_path_str: str) -> tuple[str, Any]:
    """Parse one file inside a worker process; never raise."""
    global _WORKER_PARSER
    if _WORKER_PARSER is None:
        _init_parse_worker()
    try:
        return (file_path_str, _WORKER_PARSER.parse_file(file_path_str))
    except Exception as e:  # noqa: BLE001
        return (file_path_str, e)


def _parse_chunk_in_worker(file_paths: list[str]) -> list[tuple[str, Any]]:
    """Parse a chunk of files inside a worker; never raise per file.

    Chunking amortizes pickle + future overhead over N files — at 65k files
    per-file round-trips cost ~100s of pure event-loop/pickle time.
    """
    global _WORKER_PARSER
    if _WORKER_PARSER is None:
        _init_parse_worker()
    results: list[tuple[str, Any]] = []
    for file_path_str in file_paths:
        try:
            results.append((file_path_str, _WORKER_PARSER.parse_file(file_path_str)))
        except Exception as e:  # noqa: BLE001
            results.append((file_path_str, e))
    return results


_PARSE_CHUNK_SIZE = 32
_PROGRESS_EVERY = 1000


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


async def _embed_parsed_file(
    vector_store: Any,
    embedding_service: Any,
    parsed: Any,
) -> None:
    """Embed all nodes from a parsed file into the vector store."""
    from smp.embedding.service import build_code_text

    ids: list[str] = []
    embeddings: list[list[float]] = []
    metadatas: list[dict[str, Any]] = []
    documents: list[str] = []

    for node in parsed.nodes:
        node_data = {
            "name": node.name,
            "signature": node.signature,
            "docstring": node.docstring,
            "file_path": parsed.file_path,
            "type": node.type,
        }
        document = build_code_text(node_data)
        embedding = await embedding_service.embed_document(document)
        ids.append(node.node_id)
        embeddings.append(embedding)
        metadatas.append(
            {
                "file_path": parsed.file_path,
                "type": node.type,
                "name": node.name,
                "start_line": node.start_line,
            }
        )
        documents.append(document)

    if ids:
        await vector_store.upsert(
            ids=ids,
            embeddings=embeddings,
            metadatas=metadatas,
            documents=documents,
        )


async def ingest_directory(
    directory: str,
    *,
    graph_path: str | None = None,
    extensions: tuple[str, ...] = DEFAULT_EXTENSIONS,
    max_file_size: int = DEFAULT_MAX_FILE_SIZE,
    clear: bool = False,
    semantic_search: bool = False,
) -> dict[str, int]:
    """Walk *directory*, parse all matching files, and build the graph.

    Uses a ProcessPoolExecutor (parsing is GIL-bound Python work) with a
    bounded in-flight window so parse results stream into the sequential
    apply phase as they complete, keeping peak memory flat.
    """
    from smp.store.graph.mmap_store import MMapGraphStore

    settings = Settings.from_env()
    resolved_path = graph_path or settings.graph_path
    Path(resolved_path).parent.mkdir(parents=True, exist_ok=True)

    graph_store = MMapGraphStore(path=resolved_path)
    await graph_store.connect()

    # Vector store + embedding model load only when embeddings are requested —
    # llama_cpp model load costs ~15s startup and ~1GB RSS for nothing otherwise.
    vector_store: MMapVectorStore | None = None
    embedding_service: Any = None
    if semantic_search:
        from smp.embedding.service import get_embedding_service
        from smp.vector.mmap_vector import MMapVectorStore

        vector_store = MMapVectorStore(path=settings.vector_path, dimension=1024)
        await vector_store.connect()
        embedding_service = await get_embedding_service()
        vector_store.set_embedding_service(embedding_service)

    if clear:
        await graph_store.clear()
        log.warning("graph_cleared")

    root = Path(directory).resolve()
    if not root.is_dir():
        raise ValueError(f"Not a directory: {root}")

    stats = {"files": 0, "nodes": 0, "edges": 0, "errors": 0, "skipped": 0}
    t0 = time.monotonic()

    # 1. Collect files to parse (os.walk + string paths; pathlib rglob on
    #    ~100k entries costs ~60s of Path object churn, this costs ~5s).
    #    Check order matches the previous sorted(rglob) loop exactly:
    #    extension -> size (skipped++) -> dot/skip path parts.
    skip_dir_names = frozenset({"node_modules", "__pycache__", "venv", ".venv", "dist", "build"})
    files_to_parse: list[Path] = []
    for dirpath, _dirnames, filenames in os.walk(root, followlinks=False):
        # Prune nothing: oversized files inside skipped dirs must still be
        # counted in `skipped` exactly like the previous implementation.
        for name in filenames:
            suffix = os.path.splitext(name)[1].lower()
            if suffix not in extensions:
                continue
            full = os.path.join(dirpath, name)
            try:
                size = os.stat(full).st_size
            except OSError:
                continue
            if size > max_file_size:
                log.warning("file_too_large", file=full, size=size)
                stats["skipped"] += 1
                continue
            rel_parts = os.path.relpath(full, root).split(os.sep)
            if any(p.startswith(".") or p in skip_dir_names for p in rel_parts):
                continue
            files_to_parse.append(Path(full))
    files_to_parse.sort()
    t_collect = time.monotonic() - t0
    log.info("collect_complete", files=len(files_to_parse), skipped=stats["skipped"], elapsed_s=round(t_collect, 2))

    # 2. Parallel parse in worker processes + streaming apply.
    #    A bounded window of in-flight *chunks* keeps memory flat while the
    #    main thread applies completed parses without idling the workers.
    loop = asyncio.get_running_loop()

    # CPU isolation: apply thread owns one logical CPU; workers get the rest.
    try:
        all_cpus = frozenset(os.sched_getaffinity(0))
    except (OSError, AttributeError):
        all_cpus = frozenset(range(os.cpu_count() or 4))
    parent_cpu = min(all_cpus)
    worker_cpus = frozenset(all_cpus - {parent_cpu})
    with contextlib.suppress(OSError, AttributeError):
        os.sched_setaffinity(0, {parent_cpu})

    max_workers = len(worker_cpus) or 4
    max_inflight = max_workers * 4
    file_iter = iter(files_to_parse)
    inflight: dict[Any, list[str]] = {}
    t_apply_total = 0.0
    files_done = 0
    next_progress = _PROGRESS_EVERY
    t_parse_apply0 = time.monotonic()
    gc.disable()  # measured 0.23ms/file at real heap; structures are acyclic

    with ProcessPoolExecutor(
        max_workers=max_workers, initializer=_init_parse_worker, initargs=(worker_cpus,)
    ) as executor:

        def _submit_next() -> bool:
            chunk: list[str] = []
            for _ in range(_PARSE_CHUNK_SIZE):
                fp = next(file_iter, None)
                if fp is None:
                    break
                chunk.append(str(fp))
            if not chunk:
                return False
            fut = loop.run_in_executor(executor, _parse_chunk_in_worker, chunk)
            inflight[fut] = chunk
            return True

        for _ in range(max_inflight):
            if not _submit_next():
                break

        while inflight:
            done, _ = await asyncio.wait(inflight.keys(), return_when=asyncio.FIRST_COMPLETED)
            for fut in done:
                chunk = inflight.pop(fut)
                try:
                    results = fut.result()
                except Exception as exc:  # noqa: BLE001
                    for file_path_str in chunk:
                        log.warning("parse_failed", file=file_path_str, error=str(exc))
                        stats["errors"] += 1
                    continue

                for file_path_str, result in results:
                    if isinstance(result, Exception):
                        log.warning("parse_failed", file=file_path_str, error=str(result))
                        stats["errors"] += 1
                        continue

                    t_a0 = time.monotonic()
                    try:
                        await graph_store._apply_parsed_file(file_path_str, result)
                        stats["files"] += 1
                        stats["nodes"] += len(result.nodes)
                        if semantic_search and vector_store is not None and embedding_service is not None:
                            await _embed_parsed_file(vector_store, embedding_service, result)
                    except Exception as exc:  # noqa: BLE001
                        log.warning("apply_failed", file=file_path_str, error=str(exc))
                        stats["errors"] += 1
                    finally:
                        t_apply_total += time.monotonic() - t_a0

                    files_done = stats["files"]
                    if files_done >= next_progress:
                        next_progress = ((files_done // _PROGRESS_EVERY) + 1) * _PROGRESS_EVERY
                        elapsed = time.monotonic() - t0
                        log.info(
                            "ingest_progress",
                            files=files_done,
                            nodes=stats["nodes"],
                            elapsed_s=round(elapsed, 1),
                            apply_s=round(t_apply_total, 1),
                            rate=round(files_done / elapsed, 1),
                        )

            while len(inflight) < max_inflight:
                if not _submit_next():
                    break

    t_parse_apply = time.monotonic() - t_parse_apply0
    log.info(
        "parse_apply_complete",
        files=stats["files"],
        errors=stats["errors"],
        parse_apply_s=round(t_parse_apply, 2),
        apply_s=round(t_apply_total, 2),
    )

    t_count0 = time.monotonic()
    stats["edges"] = await graph_store.count_edges()
    t_count = time.monotonic() - t_count0

    t_res0 = time.monotonic()
    try:
        stats["linked"] = await graph_store.resolve_placeholders()
    except Exception as exc:
        log.warning("placeholder_linking_failed", error=str(exc))
        stats["linked"] = 0
    t_resolve = time.monotonic() - t_res0
    gc.enable()
    gc.collect()

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
        phases={
            "collect": round(t_collect, 2),
            "parse_apply": round(t_parse_apply, 2),
            "apply": round(t_apply_total, 2),
            "count_edges": round(t_count, 2),
            "resolve": round(t_resolve, 2),
        },
    )

    t_close0 = time.monotonic()
    await graph_store.close()
    if vector_store is not None:
        await vector_store.close()
    if embedding_service is not None:
        await embedding_service.close()
    log.info("ingest_closed", close_s=round(time.monotonic() - t_close0, 2))
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
    ingest_cmd.add_argument("--semantic-search", action="store_true", help="Embed code nodes for semantic search")
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
                semantic_search=getattr(args, "semantic_search", False),
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
