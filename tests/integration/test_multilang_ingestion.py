from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from smp.core.models import (
    EdgeType,
    GraphEdge,
    GraphNode,
    Language,
    NodeType,
    SemanticProperties,
    StructuralProperties,
)
from smp.store.graph.mmap_store import MMapGraphStore
from smp.vector.mmap_vector import MMapVectorStore


@dataclass
class MultilangTestProject:
    root: Path
    languages: dict[str, Path] = field(default_factory=dict)

    def add_language(self, ext: str, content: str) -> Path:
        suffix = ext.lstrip(".")
        lang_path = self.root / f"src.{suffix}"
        lang_path.parent.mkdir(parents=True, exist_ok=True)
        lang_path.write_text(content)
        self.languages[ext] = lang_path
        return lang_path


@pytest.fixture
async def multilang_project(tmp_path: Path) -> MultilangTestProject:
    project = MultilangTestProject(root=tmp_path / "multilang_project")
    return project


@pytest.fixture
async def python_source() -> str:
    return """\
\"\"\"Python module with class and functions.\"\"\"

class DataProcessor:
    \"\"\"Process data with transformations.\"\"\"

    def __init__(self, config: dict):
        self.config = config

    def process(self, items: list) -> list:
        \"\"\"Process items through pipeline.\"\"\"
        return [self.transform(i) for i in items]

    def transform(self, item):
        return item.upper()


def main():
    processor = DataProcessor({"mode": "test"})
    return processor.process(["a", "b"])


def utility(x: int) -> int:
    return x * 2
"""


@pytest.fixture
async def javascript_source() -> str:
    return """\
/**
 * JavaScript module with class and functions.
 */

class DataProcessor {
  constructor(config) {
    this.config = config;
  }

  process(items) {
    return items.map(i => this.transform(i));
  }

  transform(item) {
    return item.toUpperCase();
  }
}

function main() {
  const processor = new DataProcessor({ mode: 'test' });
  return processor.process(['a', 'b']);
}

function utility(x) {
  return x * 2;
}

module.exports = { DataProcessor, main, utility };
"""


@pytest.fixture
async def typescript_source() -> str:
    return """\
/**
 * TypeScript module with class and functions.
 */

interface Config {
  mode: string;
  timeout?: number;
}

class DataProcessor<T> {
  constructor(private config: Config) {}

  process(items: T[]): T[] {
    return items.map(i => this.transform(i));
  }

  private transform(item: T): T {
    return item;
  }
}

function main(): string[] {
  const processor = new DataProcessor<string>({ mode: 'test' });
  return processor.process(['a', 'b']);
}

function utility(x: number): number {
  return x * 2;
}

export { DataProcessor, main, utility };
"""


@pytest.fixture
async def java_source() -> str:
    return """\
package com.example;

import java.util.*;
import java.io.*;

/**
 * Java class with methods.
 */
public class DataProcessor<T> {
    private final Map<String, Object> config;

    public DataProcessor(Map<String, Object> config) {
        this.config = config;
    }

    public List<T> process(List<T> items) {
        return items.stream()
            .map(this::transform)
            .collect(Collectors.toList());
    }

    private T transform(T item) {
        return item;
    }

    public static void main(String[] args) {
        DataProcessor<String> processor = new DataProcessor<>(new HashMap<>());
        System.out.println(processor.process(Arrays.asList("a", "b")));
    }

    public int utility(int x) {
        return x * 2;
    }
}
"""


@pytest.fixture
async def cpp_source() -> str:
    return """\
#include <iostream>
#include <vector>
#include <string>
#include <memory>

/**
 * C++ class with templates.
 */
template<typename T>
class DataProcessor {
private:
    std::map<std::string, T> config;

public:
    DataProcessor(const std::map<std::string, T>& cfg) : config(cfg) {}

    std::vector<T> process(const std::vector<T>& items) {
        std::vector<T> result;
        for (const auto& item : items) {
            result.push_back(transform(item));
        }
        return result;
    }

private:
    T transform(const T& item) {
        return item;
    }
};

int utility(int x) {
    return x * 2;
}

int main() {
    std::map<std::string, int> config;
    config["mode"] = 1;
    DataProcessor<int> processor(config);
    std::vector<int> items = {1, 2, 3};
    auto result = processor.process(items);
    return 0;
}
"""


@pytest.fixture
async def c_source() -> str:
    return """\
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
    char mode[32];
    int timeout;
} Config;

typedef struct {
    Config config;
    int count;
} DataProcessor;

DataProcessor* create_processor(Config* config) {
    DataProcessor* proc = malloc(sizeof(DataProcessor));
    if (proc) {
        memcpy(&proc->config, config, sizeof(Config));
        proc->count = 0;
    }
    return proc;
}

int process(DataProcessor* proc, int* items, int size) {
    int result = 0;
    for (int i = 0; i < size; i++) {
        result += items[i];
    }
    return result;
}

int utility(int x) {
    return x * 2;
}

void destroy_processor(DataProcessor* proc) {
    free(proc);
}

int main() {
    Config config = {"test", 100};
    DataProcessor* proc = create_processor(&config);
    int items[] = {1, 2, 3};
    int result = process(proc, items, 3);
    printf("Result: %d\\n", result);
    destroy_processor(proc);
    return 0;
}
"""


@pytest.fixture
async def go_source() -> str:
    return """\
package main

import (
    "fmt"
    "strings"
)

type Config struct {
    Mode string
    Timeout int
}

type DataProcessor struct {
    config Config
    count int
}

func NewDataProcessor(config Config) *DataProcessor {
    return &DataProcessor{
        config: config,
        count: 0,
    }
}

func (p *DataProcessor) Process(items []string) []string {
    result := make([]string, len(items))
    for i, item := range items {
        result[i] = p.transform(item)
    }
    return result
}

func (p *DataProcessor) transform(item string) string {
    return strings.ToUpper(item)
}

func utility(x int) int {
    return x * 2
}

func main() {
    processor := NewDataProcessor(Config{Mode: "test"})
    result := processor.Process([]string{"a", "b"})
    fmt.Println(result)
}
"""


@pytest.fixture
async def rust_source() -> str:
    return """\
use std::collections::HashMap;

/**
 * Rust struct with implementation.
 */
struct DataProcessor<T> {
    config: HashMap<String, T>,
    count: u32,
}

impl<T> DataProcessor<T> {
    fn new(config: HashMap<String, T>) -> Self {
        Self { config, count: 0 }
    }

    fn process(&self, items: Vec<T>) -> Vec<T> {
        items.into_iter().map(|i| self.transform(i)).collect()
    }

    fn transform(&self, item: T) -> T {
        item
    }
}

fn utility(x: i32) -> i32 {
    x * 2
}

fn main() {
    let mut config = HashMap::new();
    config.insert("mode".to_string(), 1);
    let processor = DataProcessor::new(config);
    let result = processor.process(vec![1, 2, 3]);
    println!("{:?}", result);
}
"""


@pytest.fixture
async def language_fixtures(
    python_source: str,
    javascript_source: str,
    typescript_source: str,
    java_source: str,
    cpp_source: str,
    c_source: str,
    go_source: str,
    rust_source: str,
) -> dict[str, str]:
    return {
        "python": python_source,
        "javascript": javascript_source,
        "typescript": typescript_source,
        "java": java_source,
        "cpp": cpp_source,
        "c": c_source,
        "go": go_source,
        "rust": rust_source,
    }


@pytest.fixture
async def store_pair(tmp_path: Path) -> AsyncIterator[tuple[MMapGraphStore, MMapVectorStore]]:
    graph_path = tmp_path / "test.graph.smpg"
    vector_path = tmp_path / "test.vector.smpv"

    graph = MMapGraphStore(path=str(graph_path))
    vector = MMapVectorStore(path=str(vector_path), dimension=128)

    await graph.connect()
    await vector.connect()

    try:
        yield graph, vector
    finally:
        await graph.close()
        await vector.close()


@pytest.fixture
def make_lang_node() -> type[GraphNode]:
    _counter = 0

    def _create_node(
        name: str = "test_function",
        node_type: NodeType = NodeType.FUNCTION,
        language: Language = Language.PYTHON,
        file_path: str = "/test/file.py",
        properties: dict[str, Any] | None = None,
    ) -> GraphNode:
        nonlocal _counter
        _counter += 1
        return GraphNode(
            id=f"lang_node_{_counter}_{name}",
            type=node_type,
            file_path=file_path,
            structural=StructuralProperties(name=name),
            semantic=SemanticProperties(docstring=properties.get("docstring", "") if properties else ""),
        )

    return _create_node


@pytest.fixture
def make_lang_edge() -> type[GraphEdge]:
    _counter = 0

    def _create_edge(
        source_id: str = "source_node",
        target_id: str = "target_node",
        edge_type: EdgeType = EdgeType.CALLS,
        properties: dict[str, Any] | None = None,
    ) -> GraphEdge:
        nonlocal _counter
        _counter += 1
        return GraphEdge(
            source_id=source_id,
            target_id=target_id,
            type=edge_type,
            metadata=properties or {},
        )

    return _create_edge


class TestMultilangIngestionBasics:
    """Basic tests for multi-language ingestion capabilities."""

    @pytest.mark.asyncio
    async def test_ingest_python_file(self, store_pair, python_source, multilang_project):
        graph, _ = store_pair
        py_file = multilang_project.add_language(".py", python_source)

        node = GraphNode(
            id="py_node",
            type=NodeType.FILE,
            file_path=str(py_file),
        )
        await graph.upsert_node(node)

        retrieved = await graph.get_node("py_node")
        assert retrieved is not None

        nodes = await graph.parse_file(str(py_file))
        names = [n.structural.name for n in nodes if n.type == NodeType.FUNCTION]
        assert "main" in names
        assert "utility" in names
        assert await graph.get_node(nodes[0].id) is not None

    @pytest.mark.asyncio
    async def test_ingest_javascript_file(self, store_pair, javascript_source, multilang_project):
        graph, _ = store_pair
        js_file = multilang_project.add_language(".js", javascript_source)

        node = GraphNode(
            id="js_node",
            type=NodeType.FILE,
            file_path=str(js_file),
        )
        await graph.upsert_node(node)

        retrieved = await graph.get_node("js_node")
        assert retrieved is not None

        nodes = await graph.parse_file(str(js_file))
        names = [n.structural.name for n in nodes if n.type == NodeType.FUNCTION]
        assert "main" in names
        assert "utility" in names
        assert await graph.get_node(nodes[0].id) is not None

    @pytest.mark.asyncio
    async def test_ingest_typescript_file(self, store_pair, typescript_source, multilang_project):
        graph, _ = store_pair
        ts_file = multilang_project.add_language(".ts", typescript_source)

        node = GraphNode(
            id="ts_node",
            type=NodeType.FILE,
            file_path=str(ts_file),
        )
        await graph.upsert_node(node)

        retrieved = await graph.get_node("ts_node")
        assert retrieved is not None

        nodes = await graph.parse_file(str(ts_file))
        names = [n.structural.name for n in nodes if n.type == NodeType.FUNCTION]
        assert "main" in names
        assert "utility" in names
        assert await graph.get_node(nodes[0].id) is not None

    @pytest.mark.asyncio
    async def test_ingest_java_file(self, store_pair, java_source, multilang_project):
        graph, _ = store_pair
        java_file = multilang_project.add_language(".java", java_source)

        node = GraphNode(
            id="java_node",
            type=NodeType.FILE,
            file_path=str(java_file),
        )
        await graph.upsert_node(node)

        retrieved = await graph.get_node("java_node")
        assert retrieved is not None

        nodes = await graph.parse_file(str(java_file))
        names = [n.structural.name for n in nodes if n.type == NodeType.FUNCTION]
        assert "main" in names
        assert "utility" in names
        assert await graph.get_node(nodes[0].id) is not None

    @pytest.mark.asyncio
    async def test_ingest_cpp_file(self, store_pair, cpp_source, multilang_project):
        graph, _ = store_pair
        cpp_file = multilang_project.add_language(".cpp", cpp_source)

        node = GraphNode(
            id="cpp_node",
            type=NodeType.FILE,
            file_path=str(cpp_file),
        )
        await graph.upsert_node(node)

        retrieved = await graph.get_node("cpp_node")
        assert retrieved is not None

        nodes = await graph.parse_file(str(cpp_file))
        names = [n.structural.name for n in nodes if n.type == NodeType.FUNCTION]
        assert "main" in names
        assert "utility" in names
        assert await graph.get_node(nodes[0].id) is not None


class TestMultilangIngestionExtended:
    """Extended tests for multi-language ingestion."""

    @pytest.mark.asyncio
    async def test_ingest_c_file(self, store_pair, c_source, multilang_project):
        graph, _ = store_pair
        c_file = multilang_project.add_language(".c", c_source)

        node = GraphNode(
            id="c_node",
            type=NodeType.FILE,
            file_path=str(c_file),
        )
        await graph.upsert_node(node)

        retrieved = await graph.get_node("c_node")
        assert retrieved is not None

        nodes = await graph.parse_file(str(c_file))
        names = [n.structural.name for n in nodes if n.type == NodeType.FUNCTION]
        assert "main" in names
        assert "utility" in names
        assert await graph.get_node(nodes[0].id) is not None

    @pytest.mark.asyncio
    async def test_ingest_go_file(self, store_pair, go_source, multilang_project):
        graph, _ = store_pair
        go_file = multilang_project.add_language(".go", go_source)

        node = GraphNode(
            id="go_node",
            type=NodeType.FILE,
            file_path=str(go_file),
        )
        await graph.upsert_node(node)

        retrieved = await graph.get_node("go_node")
        assert retrieved is not None

        nodes = await graph.parse_file(str(go_file))
        names = [n.structural.name for n in nodes if n.type == NodeType.FUNCTION]
        assert "main" in names
        assert "utility" in names
        assert await graph.get_node(nodes[0].id) is not None

    @pytest.mark.asyncio
    async def test_ingest_rust_file(self, store_pair, rust_source, multilang_project):
        graph, _ = store_pair
        rs_file = multilang_project.add_language(".rs", rust_source)

        node = GraphNode(
            id="rust_node",
            type=NodeType.FILE,
            file_path=str(rs_file),
        )
        await graph.upsert_node(node)

        retrieved = await graph.get_node("rust_node")
        assert retrieved is not None

        nodes = await graph.parse_file(str(rs_file))
        names = [n.structural.name for n in nodes if n.type == NodeType.FUNCTION]
        assert "main" in names
        assert "utility" in names
        assert await graph.get_node(nodes[0].id) is not None


class TestMultilangNodeEdges:
    """Tests for nodes and edges across multiple languages."""

    @pytest.mark.asyncio
    async def test_cross_language_edges_python_to_javascript(self, store_pair, make_lang_node, make_lang_edge):
        graph, _ = store_pair

        py_node = make_lang_node("py_func", node_type=NodeType.FUNCTION)
        js_node = make_lang_node("js_func", node_type=NodeType.FUNCTION)

        await graph.upsert_node(py_node)
        await graph.upsert_node(js_node)

        edge = make_lang_edge(source_id=py_node.id, target_id=js_node.id)
        await graph.upsert_edge(edge)

        retrieved_py = await graph.get_node(py_node.id)
        retrieved_js = await graph.get_node(js_node.id)
        assert retrieved_py is not None
        assert retrieved_js is not None

    @pytest.mark.asyncio
    async def test_cross_language_call_links(self, store_pair, multilang_project):
        graph, _ = store_pair

        multilang_project.root.mkdir(parents=True, exist_ok=True)
        py_file = multilang_project.root / "app.py"
        js_file = multilang_project.root / "handler.js"
        py_file.write_text("def validate(x):\n    return x\n\n\ndef compute(x):\n    return validate(x) * 2\n")
        js_file.write_text("function handle(x) {\n  return compute(x);\n}\n")

        py_nodes = await graph.parse_file(str(py_file))
        await graph.parse_file(str(js_file))
        await graph.resolve_placeholders()

        compute = next(n for n in py_nodes if n.type == NodeType.FUNCTION and n.structural.name == "compute")
        incoming = await graph.get_edges(compute.id, EdgeType.CALLS, direction="incoming")
        assert incoming
        sources = [await graph.get_node(edge.source_id) for edge in incoming]
        assert any(source is not None and source.file_path.endswith(".js") for source in sources)

    @pytest.mark.asyncio
    async def test_language_detection_from_extension(self, store_pair, multilang_project):
        graph, _ = store_pair

        extensions = {
            ".py": Language.PYTHON,
            ".js": Language.JAVASCRIPT,
            ".ts": Language.TYPESCRIPT,
            ".java": Language.JAVA,
            ".cpp": Language.CPP,
            ".c": Language.C,
            ".go": Language.GO,
            ".rs": Language.RUST,
            ".swift": Language.SWIFT,
            ".kt": Language.KOTLIN,
            ".rb": Language.RUBY,
        }

        for ext, _expected_lang in extensions.items():
            content = f"// {ext} file"
            file_path = multilang_project.add_language(ext, content)
            node = GraphNode(
                id=f"node_{ext.replace('.', '_')}",
                type=NodeType.FILE,
                file_path=str(file_path),
            )
            await graph.upsert_node(node)

        results = await graph.query_nodes(type=NodeType.FILE)
        result_ids = [n.id for n in results]
        assert "node__py" in result_ids


class TestMultilangGraphOperations:
    """Tests for graph operations with multilingual data."""

    @pytest.mark.asyncio
    async def test_batch_ingest_multiple_languages(self, store_pair, make_lang_node):
        graph, _ = store_pair

        languages = [
            Language.PYTHON,
            Language.JAVASCRIPT,
            Language.TYPESCRIPT,
            Language.JAVA,
            Language.CPP,
            Language.C,
            Language.GO,
            Language.RUST,
        ]

        for i, lang in enumerate(languages):
            node = make_lang_node(
                name=f"func_{lang.value}",
                node_type=NodeType.FUNCTION,
                file_path=f"/src/file_{i}.{lang.value}",
            )
            await graph.upsert_node(node)

        all_nodes = await graph.query_nodes()
        assert len(all_nodes) == len(languages)

    @pytest.mark.asyncio
    async def test_query_by_node_type(self, store_pair, make_lang_node):
        graph, _ = store_pair

        node_class = make_lang_node(name="class_node", node_type=NodeType.CLASS)
        node_func = make_lang_node(name="func_node", node_type=NodeType.FUNCTION)
        node_var = make_lang_node(name="var_node", node_type=NodeType.VARIABLE)

        await graph.upsert_node(node_class)
        await graph.upsert_node(node_func)
        await graph.upsert_node(node_var)

        class_nodes = await graph.query_nodes(type=NodeType.CLASS)
        assert len(class_nodes) == 1
        assert class_nodes[0].id == node_class.id

    @pytest.mark.asyncio
    async def test_traverse_multilingual_edges(self, store_pair, make_lang_node, make_lang_edge):
        graph, _ = store_pair

        source = make_lang_node("source", node_type=NodeType.FUNCTION)
        target = make_lang_node("target", node_type=NodeType.FUNCTION)

        await graph.upsert_node(source)
        await graph.upsert_node(target)

        edge = make_lang_edge(source_id=source.id, target_id=target.id)
        await graph.upsert_edge(edge)

        neighbors = await graph.traverse(source.id, relationship=EdgeType.CALLS)
        assert target.id in [n.id for n in neighbors]


class TestMultilangVectorOperations:
    """Tests for vector operations with multilingual data."""

    @pytest.mark.asyncio
    async def test_vector_upsert_for_multiple_languages(self, store_pair, make_lang_node):
        _, vector = store_pair

        import numpy as np

        languages = [Language.PYTHON, Language.JAVASCRIPT, Language.JAVA]
        for lang in languages:
            embedding = np.random.rand(128).astype(np.float32)
            await vector.upsert(
                ids=[f"vec_{lang.value}"],
                embeddings=[embedding.tolist()],
                metadatas=[{"language": lang.value}],
                documents=[lang.value],
            )

        results = await vector.query(embedding=np.random.rand(128).astype(np.float32), top_k=10)
        assert len(results) >= 3


class TestMultilangEdgeCases:
    """Edge case tests for multilingual ingestion."""

    @pytest.mark.asyncio
    async def test_unknown_language_handling(self, store_pair):
        graph, _ = store_pair

        node = GraphNode(
            id="unknown_lang",
            type=NodeType.FILE,
            file_path="/src/unknown.xyz",
        )
        await graph.upsert_node(node)

        retrieved = await graph.get_node("unknown_lang")
        assert retrieved is not None

    @pytest.mark.asyncio
    async def test_mixed_language_project(self, store_pair, language_fixtures):
        graph, _ = store_pair

        for lang, _content in language_fixtures.items():
            node = GraphNode(
                id=f"mixed_{lang}",
                type=NodeType.FILE,
                file_path=f"/src/main.{lang}",
            )
            await graph.upsert_node(node)

        all_nodes = await graph.query_nodes()
        assert len(all_nodes) == len(language_fixtures)


class TestMultilangComplex:
    """Complex tests for multilingual ingestion scenarios."""

    @pytest.mark.asyncio
    async def test_class_and_functions_per_language(self, store_pair, make_lang_node):
        graph, _ = store_pair

        node_type = NodeType.CLASS

        class_node = make_lang_node("DataProcessor", node_type=node_type)
        method_node = make_lang_node("process", node_type=NodeType.FUNCTION)
        utility_node = make_lang_node("utility", node_type=NodeType.VARIABLE)

        await graph.upsert_node(class_node)
        await graph.upsert_node(method_node)
        await graph.upsert_node(utility_node)

        edges = [
            GraphEdge(
                source_id=class_node.id,
                target_id=method_node.id,
                type=EdgeType.DEFINES,
            ),
            GraphEdge(
                source_id=class_node.id,
                target_id=utility_node.id,
                type=EdgeType.DEFINES,
            ),
        ]

        for edge in edges:
            await graph.upsert_edge(edge)

        retrieved_class = await graph.get_node(class_node.id)
        assert retrieved_class.type == NodeType.CLASS

        method_neighbors = await graph.traverse(class_node.id, relationship=EdgeType.DEFINES)
        assert method_node.id in [n.id for n in method_neighbors]
        assert utility_node.id in [n.id for n in method_neighbors]


class TestMultilangStructuralProperties:
    """Tests for structural properties with multilingual data."""

    @pytest.mark.asyncio
    async def test_structural_props_with_language(self, store_pair, multilang_project):
        graph, _ = store_pair

        source = "def main(): pass"
        file_path = multilang_project.add_language(".py", source)

        node = GraphNode(
            id="struct_py",
            type=NodeType.FUNCTION,
            file_path=str(file_path),
            structural=StructuralProperties(
                name="main",
                start_line=1,
                end_line=1,
                lines=1,
                parameters=0,
            ),
        )
        await graph.upsert_node(node)

        retrieved = await graph.get_node("struct_py")
        assert retrieved is not None
        assert retrieved.structural.name == "main"


class TestMultilangSemanticProperties:
    """Tests for semantic properties with multilingual data."""

    @pytest.mark.asyncio
    async def test_semantic_props_with_language(self, store_pair, multilang_project):
        graph, _ = store_pair

        py_source = """\
def main():
    \"\"\"Main entry point.\"\"\"
    pass
"""
        file_path = multilang_project.add_language(".py", py_source)

        node = GraphNode(
            id="semantic_py",
            type=NodeType.FUNCTION,
            file_path=str(file_path),
            semantic=SemanticProperties(
                docstring="Main entry point.",
                tags=["entry", "public"],
            ),
        )
        await graph.upsert_node(node)

        retrieved = await graph.get_node("semantic_py")
        assert retrieved is not None
        assert retrieved.semantic.docstring == "Main entry point."


class TestMultilangUpdateDelete:
    """Tests for update and delete operations with multilingual data."""

    @pytest.mark.asyncio
    async def test_update_node_type(self, store_pair, make_lang_node):
        graph, _ = store_pair

        node = make_lang_node(name="update_test", node_type=NodeType.FUNCTION)
        await graph.upsert_node(node)

        node.type = NodeType.CLASS
        await graph.upsert_node(node)

        retrieved = await graph.get_node(node.id)
        assert retrieved.type == NodeType.CLASS

    @pytest.mark.asyncio
    async def test_delete_node_by_id(self, store_pair, make_lang_node):
        graph, _ = store_pair

        node = make_lang_node(name="delete_test", node_type=NodeType.FUNCTION)
        await graph.upsert_node(node)

        await graph.delete_node(node.id)

        retrieved = await graph.get_node(node.id)
        assert retrieved is None


class TestMultilangCoordinatedOps:
    """Tests for coordinated graph and vector operations across languages."""

    @pytest.mark.asyncio
    async def test_coordinated_multilang_upsert(self, store_pair, make_lang_node):
        import numpy as np

        graph, vector = store_pair

        node = make_lang_node(
            name="coordinated",
            node_type=NodeType.FUNCTION,
            file_path="/src/coordinated.py",
        )
        embedding = np.random.rand(128).astype(np.float32)

        await graph.upsert_node(node)
        await vector.upsert(
            ids=[node.id],
            embeddings=[embedding.tolist()],
            metadatas=[{"language": "python"}],
            documents=["python"],
        )

        graph_node = await graph.get_node(node.id)
        assert graph_node is not None

        vec_results = await vector.query(embedding=embedding, top_k=1)
        assert len(vec_results) > 0
