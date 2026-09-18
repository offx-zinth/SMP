from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from smp.cli import ingest_directory
from smp.store.graph.mmap_store import MMapGraphStore

# Skip if tree-sitter is not available
tree_sitter = pytest.importorskip("tree_sitter_languages", reason="tree-sitter required for ingestion")


@pytest.mark.asyncio
async def test_multilang_ingestion():
    """Verify that the ingestion process handles multiple languages without crashing."""
    with tempfile.TemporaryDirectory() as tmp:
        # Create a directory with various file types
        codebase = Path(tmp) / "multilang_code"
        codebase.mkdir()

        (codebase / "main.py").write_text("def hello():\n    print('hello python')\n\nhello()")
        (codebase / "app.js").write_text("console.log('hello js')")
        (codebase / "main.go").write_text('package main\nfunc main() { println("hello go") }')

        graph_path = Path(tmp) / "multilang.smpg"

        # Ingest with multiple extensions
        stats = await ingest_directory(
            str(codebase),
            graph_path=str(graph_path),
            extensions=(".py", ".js", ".go"),
            clear=True,
        )

        # Verify that all 3 files were processed (even if JS and Go have no nodes)
        assert stats["files"] == 3

        # Verify nodes for Python file
        store = MMapGraphStore(graph_path)
        await store.connect()
        try:
            # Python file should have at least one node (the file itself)
            py_nodes = await store.find_nodes(file_path=str((codebase / "main.py").resolve()))
            assert len(py_nodes) > 0

            # JS file should be recorded (though likely as 0 nodes if parser doesn't support it)
            js_nodes = await store.find_nodes(file_path=str((codebase / "app.js").resolve()))
            # If parser is empty, it might have 0 nodes or just 1 (the file node)
            # Based on CodeParser._empty_parsed_file, it returns a ParsedFile with nodes=field(default_factory=list)
            # So it should have 0 nodes.
            assert len(js_nodes) == 0

        finally:
            await store.close()
