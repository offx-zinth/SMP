from __future__ import annotations

import sys

try:
    import pysqlite3

    sys.modules["sqlite3"] = sys.modules.pop("pysqlite3")
except ImportError:
    pass

from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

import argparse
import asyncio
import time

from smp.logging import configure_logging, get_logger

log = get_logger(__name__)

DEFAULT_EXTENSIONS = (".py", ".ts", ".tsx", ".js", ".jsx")
DEFAULT_MAX_FILE_SIZE = 1_000_000


async def ingest_directory(
    directory: str,
    *,
    neo4j_uri: str = "bolt://localhost:7687",
    neo4j_user: str = "neo4j",
    neo4j_password: str = "123456789$Do",
    extensions: tuple[str, ...] = DEFAULT_EXTENSIONS,
    max_file_size: int = DEFAULT_MAX_FILE_SIZE,
    clear: bool = False,
) -> dict[str, int]:
    """Walk *directory*, parse all matching files, and build the graph."""
    from smp.engine.enricher import StaticSemanticEnricher
    from smp.engine.graph_builder import DefaultGraphBuilder
    from smp.parser.registry import ParserRegistry
    from smp.store.graph.neo4j_store import Neo4jGraphStore

    registry = ParserRegistry()
    graph_store = Neo4jGraphStore(uri=neo4j_uri, user=neo4j_user, password=neo4j_password)
    builder = DefaultGraphBuilder(graph_store)
    enricher = StaticSemanticEnricher()

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

        rel_path = str(file_path.relative_to(root))
        doc = registry.parse_file(str(file_path))
        doc = type(doc)(
            file_path=rel_path,
            language=doc.language,
            nodes=[
                type(n)(
                    id=n.id.replace(str(file_path), rel_path),
                    type=n.type,
                    file_path=rel_path,
                    structural=n.structural,
                    semantic=n.semantic,
                )
                for n in doc.nodes
            ],
            edges=[
                type(e)(
                    source_id=e.source_id.replace(str(file_path), rel_path),
                    target_id=e.target_id.replace(str(file_path), rel_path),
                    type=e.type,
                    metadata=e.metadata,
                )
                for e in doc.edges
            ],
            errors=doc.errors,
        )

        if doc.nodes or doc.edges:
            await builder.ingest_document(doc)

        if doc.nodes:
            enriched = await enricher.enrich_batch(doc.nodes)
            for en in enriched:
                if en.semantic.status == "enriched":
                    await graph_store.upsert_node(en)

        stats["files"] += 1
        stats["nodes"] += len(doc.nodes)
        stats["edges"] += len(doc.edges)
        stats["errors"] += len(doc.errors)

    resolved = await builder.resolve_pending_edges()
    if resolved:
        log.info("post_ingest_edges_resolved", count=resolved)

    elapsed = time.monotonic() - t0
    log.info(
        "ingest_complete",
        directory=str(root),
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
    ingest_cmd.add_argument("--neo4j-uri", default="bolt://localhost:7687")
    ingest_cmd.add_argument("--neo4j-user", default="neo4j")
    ingest_cmd.add_argument("--neo4j-password", default="123456789$Do")
    ingest_cmd.add_argument("--clear", action="store_true", help="Clear graph before ingesting")
    ingest_cmd.add_argument("--json-log", action="store_true", help="JSON structured logging")
    ingest_cmd.add_argument("--max-size", type=int, default=DEFAULT_MAX_FILE_SIZE, help="Max file size in bytes")

    serve_cmd = sub.add_parser("serve", help="Start the SMP JSON-RPC server")
    serve_cmd.add_argument("--host", default="0.0.0.0", help="Bind host")
    serve_cmd.add_argument("--port", type=int, default=8420, help="Bind port")
    serve_cmd.add_argument("--neo4j-uri", default="bolt://localhost:7687")
    serve_cmd.add_argument("--neo4j-user", default="neo4j")
    serve_cmd.add_argument("--neo4j-password", default="123456789$Do")
    serve_cmd.add_argument("--safety", action="store_true", help="Enable agent safety protocol")
    serve_cmd.add_argument("--json-log", action="store_true", help="JSON structured logging")

    run_cmd = sub.add_parser("run", help="Run a command in the background")
    run_cmd.add_argument("name", help="Name for this background process")
    run_cmd.add_argument("command", nargs="+", help="Command and arguments to run")
    run_cmd.add_argument("--cwd", type=str, help="Working directory")
    run_cmd.add_argument("--env", nargs="+", help="Environment variables as KEY=VALUE")
    run_cmd.add_argument("--restart", action="store_true", help="Restart if already running")

    list_cmd = sub.add_parser("ps", help="List running background processes")
    list_cmd.add_argument("--name", help="Show specific process details")

    stop_cmd = sub.add_parser("stop", help="Stop a background process")
    stop_cmd.add_argument("name", help="Name of the process to stop")

    logs_cmd = sub.add_parser("logs", help="View logs for a background process")
    logs_cmd.add_argument("name", help="Name of the process")
    logs_cmd.add_argument("--stream", action="store_true", help="Stream new output")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    configure_logging(json=getattr(args, "json_log", False))

    if args.command == "ingest":
        stats = asyncio.run(
            ingest_directory(
                args.directory,
                neo4j_uri=args.neo4j_uri,
                neo4j_user=args.neo4j_user,
                neo4j_password=args.neo4j_password,
                clear=args.clear,
                max_file_size=args.max_size,
            )
        )
        print(
            f"\nIngested {stats['files']} files: {stats['nodes']} nodes, "
            f"{stats['edges']} edges, {stats['errors']} errors"
        )

    elif args.command == "serve":
        import os

        import uvicorn

        os.environ["SMP_NEO4J_URI"] = args.neo4j_uri
        os.environ["SMP_NEO4J_USER"] = args.neo4j_user
        os.environ["SMP_NEO4J_PASSWORD"] = args.neo4j_password

        from smp.protocol.server import create_app

        application = create_app(
            neo4j_uri=args.neo4j_uri,
            neo4j_user=args.neo4j_user,
            neo4j_password=args.neo4j_password,
            safety_enabled=getattr(args, "safety", False),
        )
        uvicorn.run(application, host=args.host, port=args.port)

    elif args.command == "run":
        from smp.core.background import BackgroundRunner

        env = {}
        if args.env:
            for e in args.env:
                if "=" in e:
                    key, val = e.split("=", 1)
                    env[key] = val

        runner = BackgroundRunner()
        cwd = Path(args.cwd) if args.cwd else None

        try:
            bg_proc = runner.start(args.name, args.command, cwd=cwd, env=env or None)
            print(f"Started {args.name}: pid={bg_proc.pid}")
        except ValueError as e:
            if args.restart:
                bg_proc = runner.restart(args.name)
                print(f"Restarted {args.name}: pid={bg_proc.pid}")
            else:
                print(f"Error: {e}")
                sys.exit(1)

    elif args.command == "ps":
        from smp.core.background import BackgroundRunner

        runner = BackgroundRunner()
        if args.name:
            proc = runner.get(args.name)
            if proc:
                print(f"{args.name}: pid={proc['pid']}, running={proc['running']}")
                print(f"  command: {' '.join(proc['command'])}")
            else:
                print(f"Process not found: {args.name}")
        else:
            all_procs = runner.list()
            if all_procs:
                for name, info in all_procs.items():
                    print(f"{name}: pid={info['pid']}, running={info['running']}")
            else:
                print("No background processes running")

    elif args.command == "stop":
        from smp.core.background import BackgroundRunner

        runner = BackgroundRunner()
        if runner.stop(args.name):
            print(f"Stopped {args.name}")
        else:
            print(f"Process not found: {args.name}")
            sys.exit(1)

    elif args.command == "logs":
        from smp.core.background import BackgroundRunner

        runner = BackgroundRunner()
        try:
            logs = runner.logs(args.name)
            if logs["stdout"]:
                print(f"=== stdout ===\n{logs['stdout']}")
            if logs["stderr"]:
                print(f"=== stderr ===\n{logs['stderr']}")
        except ValueError as e:
            print(f"Error: {e}")
            sys.exit(1)


if __name__ == "__main__":
    main()
