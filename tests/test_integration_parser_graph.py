"""Integration tests for ParserRegistry and DefaultGraphBuilder using sample_project."""

from __future__ import annotations

from pathlib import Path

import pytest

from smp.core.models import Document, EdgeType, Language, NodeType
from smp.engine.graph_builder import DefaultGraphBuilder
from smp.parser.registry import ParserRegistry
from smp.store.graph.neo4j_store import Neo4jGraphStore


FIXTURE_PATH = Path("/home/bhagyarekhab/SMP/tests/fixtures/sample_project/src")


class TestParserRegistryIntegration:
    """Test ParserRegistry parsing all files in sample_project/src."""

    @pytest.fixture()
    def registry(self) -> ParserRegistry:
        return ParserRegistry()

    def _get_python_files(self) -> list[Path]:
        """Get all Python files from the fixture directory."""
        return list(FIXTURE_PATH.rglob("*.py"))

    def test_finds_python_files(self, registry: ParserRegistry) -> None:
        """Verify fixture directory has Python files."""
        files = self._get_python_files()
        assert len(files) > 0, "No Python files found in fixture directory"

    @pytest.mark.asyncio
    async def test_parse_auth_service(self, registry: ParserRegistry) -> None:
        """Parse auth_service.py and verify nodes extracted."""
        doc = registry.parse_file(str(FIXTURE_PATH / "auth/auth_service.py"))

        assert doc.language == Language.PYTHON
        assert len(doc.errors) == 0, f"Parse errors: {doc.errors}"

        functions = [n for n in doc.nodes if n.type == NodeType.FUNCTION]
        classes = [n for n in doc.nodes if n.type == NodeType.CLASS]
        imports = [n for n in doc.nodes if n.type == NodeType.FILE and "import" in n.structural.signature]

        assert len(functions) >= 4, f"Expected 4+ functions, got {len(functions)}: {[f.structural.name for f in functions]}"
        assert len(classes) >= 1, f"Expected 1+ classes, got {len(classes)}"
        assert len(imports) >= 3, f"Expected 3+ imports, got {len(imports)}"

    @pytest.mark.asyncio
    async def test_parse_db_models(self, registry: ParserRegistry) -> None:
        """Parse db/models.py and verify nodes extracted."""
        doc = registry.parse_file(str(FIXTURE_PATH / "db/models.py"))

        assert doc.language == Language.PYTHON
        assert len(doc.errors) == 0, f"Parse errors: {doc.errors}"

        classes = [n for n in doc.nodes if n.type == NodeType.CLASS]
        functions = [n for n in doc.nodes if n.type == NodeType.FUNCTION]

        assert len(classes) >= 1, f"Expected 1+ classes, got {len(classes)}"
        assert len(functions) >= 0, f"Expected 0+ functions, got {len(functions)}"

    @pytest.mark.asyncio
    async def test_parse_api_routes(self, registry: ParserRegistry) -> None:
        """Parse api/routes.py and verify nodes extracted."""
        doc = registry.parse_file(str(FIXTURE_PATH / "api/routes.py"))

        assert doc.language == Language.PYTHON
        assert len(doc.errors) == 0, f"Parse errors: {doc.errors}"

        functions = [n for n in doc.nodes if n.type == NodeType.FUNCTION]
        imports = [n for n in doc.nodes if n.type == NodeType.FILE and "import" in n.structural.signature]

        assert len(functions) >= 3, f"Expected 3+ functions, got {len(functions)}: {[f.structural.name for f in functions]}"
        assert len(imports) >= 2, f"Expected 2+ imports, got {len(imports)}"

    @pytest.mark.asyncio
    async def test_parse_all_files(self, registry: ParserRegistry) -> None:
        """Parse all Python files in fixture directory."""
        files = self._get_python_files()
        results: list[tuple[str, Document]] = []

        for f in files:
            doc = registry.parse_file(str(f))
            results.append((str(f), doc))

        total_nodes = sum(len(doc.nodes) for _, doc in results)
        total_errors = sum(len(doc.errors) for _, doc in results)

        assert len(results) == len(files), f"Not all files were parsed"
        assert total_nodes > 0, "No nodes extracted from any file"
        assert total_errors == 0, f"Parse errors in files: {[(f, doc.errors) for f, doc in results if doc.errors]}"


class TestGraphBuilderIntegration:
    """Test DefaultGraphBuilder ingesting parsed nodes into Neo4j."""

    @pytest.fixture()
    async def store(self, clean_graph: Neo4jGraphStore) -> Neo4jGraphStore:
        await clean_graph.connect()
        return clean_graph

    @pytest.fixture()
    def builder(self, store: Neo4jGraphStore) -> DefaultGraphBuilder:
        return DefaultGraphBuilder(store)

    @pytest.fixture()
    def registry(self) -> ParserRegistry:
        return ParserRegistry()

    @pytest.mark.asyncio
    async def test_ingest_auth_service(
        self,
        store: Neo4jGraphStore,
        builder: DefaultGraphBuilder,
        registry: ParserRegistry,
    ) -> None:
        """Parse auth_service.py and ingest into graph, verify nodes and edges."""
        doc = registry.parse_file(str(FIXTURE_PATH / "auth/auth_service.py"))
        assert len(doc.errors) == 0, f"Parse errors: {doc.errors}"

        await builder.ingest_document(doc)

        stored_nodes = await store.find_nodes()
        node_names = {n.structural.name for n in stored_nodes}

        expected_functions = ["hash_password", "verify_password", "generate_token", "login", "logout", "verify_token", "get_current_user"]
        expected_classes = ["AuthService"]

        for func_name in expected_functions:
            assert func_name in node_names, f"Function {func_name} not found in graph. Available: {node_names}"

        for class_name in expected_classes:
            assert class_name in node_names, f"Class {class_name} not found in graph. Available: {node_names}"

        edges = await store.get_edges(limit=100)
        edge_types = {e.type for e in edges}

        assert EdgeType.DEFINES in edge_types, f"Missing DEFINES edges. Types found: {edge_types}"
        assert EdgeType.CALLS in edge_types or EdgeType.DEFINES in edge_types, f"Missing relationship edges. Types found: {edge_types}"

    @pytest.mark.asyncio
    async def test_ingest_db_models(
        self,
        store: Neo4jGraphStore,
        builder: DefaultGraphBuilder,
        registry: ParserRegistry,
    ) -> None:
        """Parse db/models.py and ingest into graph."""
        doc = registry.parse_file(str(FIXTURE_PATH / "db/models.py"))
        assert len(doc.errors) == 0, f"Parse errors: {doc.errors}"

        await builder.ingest_document(doc)

        stored_nodes = await store.find_nodes()
        classes = [n for n in stored_nodes if n.type == NodeType.CLASS]
        class_names = {c.structural.name for c in classes}

        assert len(classes) >= 1, f"Expected 1+ classes, got {len(classes)}: {class_names}"

    @pytest.mark.asyncio
    async def test_ingest_api_routes(
        self,
        store: Neo4jGraphStore,
        builder: DefaultGraphBuilder,
        registry: ParserRegistry,
    ) -> None:
        """Parse api/routes.py and ingest into graph."""
        doc = registry.parse_file(str(FIXTURE_PATH / "api/routes.py"))
        assert len(doc.errors) == 0, f"Parse errors: {doc.errors}"

        await builder.ingest_document(doc)

        stored_nodes = await store.find_nodes()
        functions = [n for n in stored_nodes if n.type == NodeType.FUNCTION]
        function_names = {f.structural.name for f in functions}

        assert len(functions) >= 2, f"Expected 2+ functions, got {len(functions)}: {function_names}"

    @pytest.mark.asyncio
    async def test_ingest_all_files(
        self,
        store: Neo4jGraphStore,
        builder: DefaultGraphBuilder,
        registry: ParserRegistry,
    ) -> None:
        """Parse and ingest all Python files, verify complete graph."""
        files = list(FIXTURE_PATH.rglob("*.py"))

        for f in files:
            doc = registry.parse_file(str(f))
            if doc.errors:
                pytest.fail(f"Parse errors in {f}: {doc.errors}")
            await builder.ingest_document(doc)

        stored_nodes = await store.find_nodes(limit=500)
        stored_edges = await store.get_edges(limit=500)

        assert len(stored_nodes) > 0, "No nodes stored in graph"
        assert len(stored_edges) > 0, "No edges stored in graph"

        node_types = {n.type for n in stored_nodes}
        edge_types = {e.type for e in stored_edges}

        assert NodeType.FUNCTION in node_types, f"No functions found. Types: {node_types}"
        assert NodeType.CLASS in node_types, f"No classes found. Types: {node_types}"

        assert EdgeType.DEFINES in edge_types, f"No DEFINES edges. Types: {edge_types}"
        assert EdgeType.CALLS in edge_types or EdgeType.IMPORTS in edge_types, f"No CALLS or IMPORTS edges. Types: {edge_types}"


class TestEdgeCreation:
    """Test that specific edge types (CALLS, IMPORTS, DEFINES) are created correctly."""

    @pytest.fixture()
    async def store(self, clean_graph: Neo4jGraphStore) -> Neo4jGraphStore:
        await clean_graph.connect()
        return clean_graph

    @pytest.fixture()
    def builder(self, store: Neo4jGraphStore) -> DefaultGraphBuilder:
        return DefaultGraphBuilder(store)

    @pytest.fixture()
    def registry(self) -> ParserRegistry:
        return ParserRegistry()

    @pytest.mark.asyncio
    async def test_defines_edges_exist(
        self,
        store: Neo4jGraphStore,
        builder: DefaultGraphBuilder,
        registry: ParserRegistry,
    ) -> None:
        """Verify DEFINES edges connect File/Class nodes to their children."""
        doc = registry.parse_file(str(FIXTURE_PATH / "auth/auth_service.py"))
        await builder.ingest_document(doc)

        edges = await store.get_edges(limit=200)
        defines_edges = [e for e in edges if e.type == EdgeType.DEFINES]

        assert len(defines_edges) > 0, "No DEFINES edges created"

    @pytest.mark.asyncio
    async def test_import_edges_exist(
        self,
        store: Neo4jGraphStore,
        builder: DefaultGraphBuilder,
        registry: ParserRegistry,
    ) -> None:
        """Verify IMPORTS edges are created for import statements."""
        doc = registry.parse_file(str(FIXTURE_PATH / "auth/auth_service.py"))
        await builder.ingest_document(doc)

        edges = await store.get_edges(limit=200)
        import_edges = [e for e in edges if e.type == EdgeType.IMPORTS]

        assert len(import_edges) >= 3, f"Expected 3+ IMPORTS edges, got {len(import_edges)}"

    @pytest.mark.asyncio
    async def test_calls_edges_exist(
        self,
        store: Neo4jGraphStore,
        builder: DefaultGraphBuilder,
        registry: ParserRegistry,
    ) -> None:
        """Verify CALLS edges exist for function invocations."""
        doc = registry.parse_file(str(FIXTURE_PATH / "auth/auth_service.py"))
        await builder.ingest_document(doc)

        edges = await store.get_edges(limit=200)
        calls_edges = [e for e in edges if e.type == EdgeType.CALLS]

        assert len(calls_edges) > 0, "No CALLS edges created"

    @pytest.mark.asyncio
    async def test_class_method_defines(
        self,
        store: Neo4jGraphStore,
        builder: DefaultGraphBuilder,
        registry: ParserRegistry,
    ) -> None:
        """Verify DEFINES edges from Class to its methods."""
        doc = registry.parse_file(str(FIXTURE_PATH / "auth/auth_service.py"))
        await builder.ingest_document(doc)

        edges = await store.get_edges(limit=200)
        defines_edges = [e for e in edges if e.type == EdgeType.DEFINES]

        auth_service_defines = [e for e in defines_edges if "AuthService" in e.source_id]
        assert len(auth_service_defines) >= 3, f"Expected 3+ AuthService method defines, got {len(auth_service_defines)}"
