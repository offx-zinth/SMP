"""SMP CLI — ingest directories, start the JSON-RPC server.

Usage:
    python3.11 -m smp.cli ingest <directory> [--neo4j-uri bolt://localhost:7687]
    python3.11 -m smp.cli serve [--host 0.0.0.0] [--port 8420]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

from smp.logging import configure_logging, get_logger

log = get_logger(__name__)

DEFAULT_EXTENSIONS = (".py", ".ts", ".tsx", ".js", ".jsx")
DEFAULT_MAX_FILE_SIZE = 1_000_000  # 1MB


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
    """Walk *directory*, parse all matching files, and build the graph.

    Returns a stats dict with counts of files, nodes, edges, and errors.
    """
    from smp.engine.graph_builder import DefaultGraphBuilder
    from smp.parser.registry import ParserRegistry
    from smp.store.graph.neo4j_store import Neo4jGraphStore

    registry = ParserRegistry()
    graph_store = Neo4jGraphStore(uri=neo4j_uri, user=neo4j_user, password=neo4j_password)
    builder = DefaultGraphBuilder(graph_store)

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

        # Skip large files
        try:
            size = file_path.stat().st_size
        except OSError:
            continue
        if size > max_file_size:
            log.warning("file_too_large", file=str(file_path), size=size)
            stats["skipped"] += 1
            continue

        # Skip hidden / vendored dirs
        parts = file_path.relative_to(root).parts
        if any(p.startswith(".") or p in ("node_modules", "__pycache__", "venv", ".venv", "dist", "build") for p in parts):
            continue

        rel_path = str(file_path.relative_to(root))
        doc = registry.parse_file(str(file_path))
        # Rewrite file_path to be relative
        doc = type(doc)(
            file_path=rel_path,
            language=doc.language,
            nodes=[type(n)(id=n.id.replace(str(file_path), rel_path), type=n.type, name=n.name, file_path=rel_path, start_line=n.start_line, end_line=n.end_line, signature=n.signature, docstring=n.docstring, semantic=n.semantic, metadata=n.metadata) for n in doc.nodes],
            edges=[type(e)(source_id=e.source_id.replace(str(file_path), rel_path), target_id=e.target_id.replace(str(file_path), rel_path), type=e.type, metadata=e.metadata) for e in doc.edges],
            errors=doc.errors,
        )

        if doc.nodes or doc.edges:
            await builder.ingest_document(doc)

        stats["files"] += 1
        stats["nodes"] += len(doc.nodes)
        stats["edges"] += len(doc.edges)
        stats["errors"] += len(doc.errors)

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
    serve_cmd.add_argument("--gemini-api-key", default=None, help="Gemini API key for LLM enrichment")
    serve_cmd.add_argument("--json-log", action="store_true", help="JSON structured logging")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    configure_logging(json=getattr(args, "json_log", False))

    if args.command == "ingest":
        stats = asyncio.run(ingest_directory(
            args.directory,
            neo4j_uri=args.neo4j_uri,
            neo4j_user=args.neo4j_user,
            neo4j_password=args.neo4j_password,
            clear=args.clear,
            max_file_size=args.max_size,
        ))
        print(f"\nIngested {stats['files']} files: {stats['nodes']} nodes, {stats['edges']} edges, {stats['errors']} errors")

    elif args.command == "serve":
        import uvicorn
        import os
        # Set env vars so server.py create_app() can read them
        os.environ["SMP_NEO4J_URI"] = args.neo4j_uri
        os.environ["SMP_NEO4J_USER"] = args.neo4j_user
        os.environ["SMP_NEO4J_PASSWORD"] = args.neo4j_password
        if args.gemini_api_key:
            os.environ["GEMINI_API_KEY"] = args.gemini_api_key

        # Use the factory to create a fresh app with correct config
        from smp.protocol.server import create_app
        application = create_app(
            neo4j_uri=args.neo4j_uri,
            neo4j_user=args.neo4j_user,
            neo4j_password=args.neo4j_password,
            gemini_api_key=args.gemini_api_key,
        )
        uvicorn.run(application, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
