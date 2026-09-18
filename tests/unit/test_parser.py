"""Unit tests for AST parsing with CodeParser."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from smp.store.graph.parser import (
    LANG_PYTHON,
    LANG_UNKNOWN,
    CodeParser,
    EdgeCandidate,
    ParsedFile,
    ParsedNode,
)


class MockTreeNode:
    """Mock tree-sitter node for testing."""

    def __init__(
        self,
        node_type: str,
        start_byte: int = 0,
        end_byte: int = 10,
        start_point: tuple[int, int] = (0, 0),
        end_point: tuple[int, int] = (0, 10),
        children: list[MockTreeNode] | None = None,
        text: str = "mock",
    ) -> None:
        self.type = node_type
        self.start_byte = start_byte
        self.end_byte = end_byte
        self.start_point = start_point
        self.end_point = end_point
        self.children = children or []
        self._text = text
        self._mock_text = text

    def child_by_field_name(self, name: str) -> MockTreeNode | None:
        if name == "name":
            name_node = MockTreeNode("identifier", text=self._mock_text)
            name_node.start_byte = self.start_byte
            name_node.end_byte = self.end_byte
            return name_node
        if name == "parameters":
            return MockTreeNode("parameters", text="()")
        if name == "body":
            return MockTreeNode("block")
        return None

    @property
    def prev_sibling(self) -> MockTreeNode | None:
        return None


class TestParsedNode:
    """Tests for ParsedNode dataclass."""

    def test_defaults(self) -> None:
        node = ParsedNode(
            node_id="test::Function::foo::1",
            type="Function",
            name="foo",
            signature="def foo()",
            docstring="",
            start_line=1,
            end_line=10,
        )
        assert node.node_id == "test::Function::foo::1"
        assert node.type == "Function"
        assert node.name == "foo"
        assert node.signature == "def foo()"
        assert node.docstring == ""
        assert node.start_line == 1
        assert node.end_line == 10
        assert node.tags == []
        assert node.decorators == []
        assert node.parent_id is None

    def test_with_optional_fields(self) -> None:
        node = ParsedNode(
            node_id="test::Class::Foo::1",
            type="Class",
            name="Foo",
            signature="class Foo",
            docstring="A class",
            start_line=1,
            end_line=20,
            tags=["important"],
            decorators=["@dataclass"],
            parent_id="module::module::1",
        )
        assert node.tags == ["important"]
        assert node.decorators == ["@dataclass"]
        assert node.parent_id == "module::module::1"

    def test_with_tags(self) -> None:
        node = ParsedNode(
            node_id="n1",
            type="Function",
            name="foo",
            signature="def foo()",
            docstring="",
            start_line=1,
            end_line=5,
            tags=["api", "critical"],
        )
        assert node.tags == ["api", "critical"]

    def test_with_decorators(self) -> None:
        node = ParsedNode(
            node_id="n1",
            type="Function",
            name="foo",
            signature="def foo()",
            docstring="",
            start_line=1,
            end_line=5,
            decorators=["@property", "@staticmethod"],
        )
        assert node.decorators == ["@property", "@staticmethod"]


class TestEdgeCandidate:
    """Tests for EdgeCandidate dataclass."""

    def test_defaults(self) -> None:
        edge = EdgeCandidate(
            source_id="source1",
            target_name="Target",
            edge_type="IMPORTS",
        )
        assert edge.source_id == "source1"
        assert edge.target_name == "Target"
        assert edge.edge_type == "IMPORTS"
        assert edge.target_file_hint is None

    def test_with_file_hint(self) -> None:
        edge = EdgeCandidate(
            source_id="source1",
            target_name="Target",
            edge_type="CALLS",
            target_file_hint="helpers.py",
        )
        assert edge.target_file_hint == "helpers.py"


class TestParsedFile:
    """Tests for ParsedFile dataclass."""

    def test_defaults(self) -> None:
        pf = ParsedFile(
            file_path="/path/to/file.py",
            language=LANG_PYTHON,
            line_count=100,
            content_hash="abc123",
        )
        assert pf.file_path == "/path/to/file.py"
        assert pf.language == LANG_PYTHON
        assert pf.line_count == 100
        assert pf.content_hash == "abc123"
        assert pf.nodes == []
        assert pf.edge_candidates == []
        assert pf.resolved_edges == []

    def test_with_nodes_and_edges(self) -> None:
        node = ParsedNode(
            node_id="n1",
            type="Function",
            name="foo",
            signature="def foo()",
            docstring="",
            start_line=1,
            end_line=5,
        )
        edge = EdgeCandidate(
            source_id="n1",
            target_name="bar",
            edge_type="CALLS",
        )
        pf = ParsedFile(
            file_path="/p.py",
            language=LANG_PYTHON,
            line_count=10,
            content_hash="def",
            nodes=[node],
            edge_candidates=[edge],
        )
        assert len(pf.nodes) == 1
        assert len(pf.edge_candidates) == 1


class TestCodeParserInit:
    """Tests for CodeParser initialization."""

    def test_init_without_tree_sitter_raises(self) -> None:
        with (
            patch("smp.store.graph.parser.HAS_TREE_SITTER", False),
            pytest.raises(ImportError, match="tree-sitter not installed"),
        ):
            CodeParser()

    @patch("smp.store.graph.parser.HAS_TREE_SITTER", True)
    def test_init_with_tree_sitter(self) -> None:
        with patch("smp.store.graph.parser.tree_sitter_languages") as mock_ts:
            with patch("smp.store.graph.parser.Parser") as mock_parser_cls:
                mock_parser_cls.return_value = MagicMock()
                mock_ts.get_language.return_value = MagicMock()
                parser = CodeParser()
                assert parser._parsers == {}
                assert parser._languages == {}
                assert parser._python_ready is False


class TestLanguageDetection:
    """Tests for language detection."""

    @patch("smp.store.graph.parser.HAS_TREE_SITTER", True)
    def test_is_python_py_extension(self) -> None:
        with patch("smp.store.graph.parser.tree_sitter_languages") as mock_ts:
            with patch("smp.store.graph.parser.Parser") as mock_parser_cls:
                mock_parser_cls.return_value = MagicMock()
                mock_ts.get_language.return_value = MagicMock()
                parser = CodeParser()
                assert parser._is_python("/path/to/file.py") is True

    @patch("smp.store.graph.parser.HAS_TREE_SITTER", True)
    def test_is_python_pyi_extension(self) -> None:
        with patch("smp.store.graph.parser.tree_sitter_languages") as mock_ts:
            with patch("smp.store.graph.parser.Parser") as mock_parser_cls:
                mock_parser_cls.return_value = MagicMock()
                mock_ts.get_language.return_value = MagicMock()
                parser = CodeParser()
                assert parser._is_python("/path/to/file.pyi") is True

    @patch("smp.store.graph.parser.HAS_TREE_SITTER", True)
    def test_is_python_pyi_case_insensitive(self) -> None:
        with patch("smp.store.graph.parser.tree_sitter_languages") as mock_ts:
            with patch("smp.store.graph.parser.Parser") as mock_parser_cls:
                mock_parser_cls.return_value = MagicMock()
                mock_ts.get_language.return_value = MagicMock()
                parser = CodeParser()
                assert parser._is_python("/path/to/file.PYI") is True

    @patch("smp.store.graph.parser.HAS_TREE_SITTER", True)
    def test_is_not_python_js_extension(self) -> None:
        with patch("smp.store.graph.parser.tree_sitter_languages") as mock_ts:
            with patch("smp.store.graph.parser.Parser") as mock_parser_cls:
                mock_parser_cls.return_value = MagicMock()
                mock_ts.get_language.return_value = MagicMock()
                parser = CodeParser()
                assert parser._is_python("/path/to/file.js") is False

    @patch("smp.store.graph.parser.HAS_TREE_SITTER", True)
    def test_is_not_python_ts_extension(self) -> None:
        with patch("smp.store.graph.parser.tree_sitter_languages") as mock_ts:
            with patch("smp.store.graph.parser.Parser") as mock_parser_cls:
                mock_parser_cls.return_value = MagicMock()
                mock_ts.get_language.return_value = MagicMock()
                parser = CodeParser()
                assert parser._is_python("/path/to/file.ts") is False

    @patch("smp.store.graph.parser.HAS_TREE_SITTER", True)
    def test_is_not_python_rust_extension(self) -> None:
        with patch("smp.store.graph.parser.tree_sitter_languages") as mock_ts:
            with patch("smp.store.graph.parser.Parser") as mock_parser_cls:
                mock_parser_cls.return_value = MagicMock()
                mock_ts.get_language.return_value = MagicMock()
                parser = CodeParser()
                assert parser._is_python("/path/to/file.rs") is False

    @patch("smp.store.graph.parser.HAS_TREE_SITTER", True)
    def test_is_not_python_go_extension(self) -> None:
        with patch("smp.store.graph.parser.tree_sitter_languages") as mock_ts:
            with patch("smp.store.graph.parser.Parser") as mock_parser_cls:
                mock_parser_cls.return_value = MagicMock()
                mock_ts.get_language.return_value = MagicMock()
                parser = CodeParser()
                assert parser._is_python("/path/to/file.go") is False

    @patch("smp.store.graph.parser.HAS_TREE_SITTER", True)
    def test_is_not_python_no_extension(self) -> None:
        with patch("smp.store.graph.parser.tree_sitter_languages") as mock_ts:
            with patch("smp.store.graph.parser.Parser") as mock_parser_cls:
                mock_parser_cls.return_value = MagicMock()
                mock_ts.get_language.return_value = MagicMock()
                parser = CodeParser()
                assert parser._is_python("/path/to/README") is False

    @patch("smp.store.graph.parser.HAS_TREE_SITTER", True)
    def test_is_python_pathlib_path(self) -> None:
        with patch("smp.store.graph.parser.tree_sitter_languages") as mock_ts:
            with patch("smp.store.graph.parser.Parser") as mock_parser_cls:
                mock_parser_cls.return_value = MagicMock()
                mock_ts.get_language.return_value = MagicMock()
                parser = CodeParser()
                assert parser._is_python(Path("/path/to/file.py")) is True


class TestParseFile:
    """Tests for parse_file method."""

    @patch("smp.store.graph.parser.HAS_TREE_SITTER", True)
    def test_parse_nonexistent_file_raises(self) -> None:
        with patch("smp.store.graph.parser.tree_sitter_languages") as mock_ts:
            with patch("smp.store.graph.parser.Parser") as mock_parser_cls:
                mock_parser_cls.return_value = MagicMock()
                mock_ts.get_language.return_value = MagicMock()
                parser = CodeParser()
                with pytest.raises(FileNotFoundError, match="File not found"):
                    parser.parse_file("/nonexistent/file.py")

    @patch("smp.store.graph.parser.HAS_TREE_SITTER", True)
    def test_parse_python_file_returns_parsed(self) -> None:
        with patch("smp.store.graph.parser.tree_sitter_languages") as mock_ts:
            with patch("smp.store.graph.parser.Parser") as mock_parser_cls:
                mock_parser_instance = MagicMock()
                mock_parser_cls.return_value = mock_parser_instance
                mock_ts.get_language.return_value = MagicMock()
                parser = CodeParser()
                with tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode="w") as f:
                    f.write("def foo():\n    pass\n")
                    f.flush()
                    result = parser.parse_file(f.name)
                assert result.language == LANG_PYTHON
                assert result.file_path == f.name

    @patch("smp.store.graph.parser.HAS_TREE_SITTER", True)
    def test_parse_non_python_file_returns_empty(self) -> None:
        parser = CodeParser()
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w") as f:
            f.write("function foo() {}")
            f.flush()
            result = parser.parse_file(f.name)
        assert result.language == "javascript"
        assert [n.name for n in result.nodes] == ["foo"]


class TestParseContent:
    """Tests for parse_content method."""

    @patch("smp.store.graph.parser.HAS_TREE_SITTER", True)
    def test_parse_python_bytes(self) -> None:
        with patch("smp.store.graph.parser.tree_sitter_languages") as mock_ts:
            with patch("smp.store.graph.parser.Parser") as mock_parser_cls:
                mock_parser_cls.return_value = MagicMock()
                mock_ts.get_language.return_value = MagicMock()
                parser = CodeParser()
                content = b"def foo():\n    pass\n"
                result = parser.parse_content("/path/to/file.py", content)
                assert result.language == LANG_PYTHON

    @patch("smp.store.graph.parser.HAS_TREE_SITTER", True)
    def test_parse_non_python_returns_empty(self) -> None:
        parser = CodeParser()
        content = b"console.log('hello');"
        result = parser.parse_content("/path/to/file.js", content)
        assert result.language == "javascript"
        assert result.nodes == []


class TestParseMethod:
    """Tests for parse convenience method."""

    @patch("smp.store.graph.parser.HAS_TREE_SITTER", True)
    def test_parse_string_content(self) -> None:
        with patch("smp.store.graph.parser.tree_sitter_languages") as mock_ts:
            with patch("smp.store.graph.parser.Parser") as mock_parser_cls:
                mock_parser_cls.return_value = MagicMock()
                mock_ts.get_language.return_value = MagicMock()
                parser = CodeParser()
                content = "def foo():\n    pass"
                result = parser.parse(content, "/path/to/file.py")
                assert result.language == LANG_PYTHON

    @patch("smp.store.graph.parser.HAS_TREE_SITTER", True)
    def test_parse_bytes_content(self) -> None:
        with patch("smp.store.graph.parser.tree_sitter_languages") as mock_ts:
            with patch("smp.store.graph.parser.Parser") as mock_parser_cls:
                mock_parser_cls.return_value = MagicMock()
                mock_ts.get_language.return_value = MagicMock()
                parser = CodeParser()
                content = b"def bar():\n    return 42"
                result = parser.parse(content, "/path/to/file.py")
                assert result.language == LANG_PYTHON


class TestEmptyParsedFile:
    """Tests for _empty_parsed_file helper."""

    @patch("smp.store.graph.parser.HAS_TREE_SITTER", True)
    def test_empty_parsed_file_basic(self) -> None:
        with patch("smp.store.graph.parser.tree_sitter_languages") as mock_ts:
            with patch("smp.store.graph.parser.Parser") as mock_parser_cls:
                mock_parser_cls.return_value = MagicMock()
                mock_ts.get_language.return_value = MagicMock()
                parser = CodeParser()
                content = b"some content"
                result = parser._empty_parsed_file("/path/to/file.js", content)
                assert result.language == LANG_UNKNOWN
                assert result.file_path == "/path/to/file.js"

    @patch("smp.store.graph.parser.HAS_TREE_SITTER", True)
    def test_empty_parsed_file_line_count(self) -> None:
        with patch("smp.store.graph.parser.tree_sitter_languages") as mock_ts:
            with patch("smp.store.graph.parser.Parser") as mock_parser_cls:
                mock_parser_cls.return_value = MagicMock()
                mock_ts.get_language.return_value = MagicMock()
                parser = CodeParser()
                content = b"line1\nline2\nline3"
                result = parser._empty_parsed_file("/path/to/file.js", content)
                assert result.line_count == 3


class TestHashComputation:
    """Tests for content hash computation."""

    @patch("smp.store.graph.parser.HAS_TREE_SITTER", True)
    def test_compute_hash(self) -> None:
        with patch("smp.store.graph.parser.tree_sitter_languages") as mock_ts:
            with patch("smp.store.graph.parser.Parser") as mock_parser_cls:
                mock_parser_cls.return_value = MagicMock()
                mock_ts.get_language.return_value = MagicMock()
                parser = CodeParser()
                content = b"test content"
                result = parser._compute_hash(content)
                assert isinstance(result, str)
                assert len(result) == 16

    @patch("smp.store.graph.parser.HAS_TREE_SITTER", True)
    def test_compute_hash_deterministic(self) -> None:
        with patch("smp.store.graph.parser.tree_sitter_languages") as mock_ts:
            with patch("smp.store.graph.parser.Parser") as mock_parser_cls:
                mock_parser_cls.return_value = MagicMock()
                mock_ts.get_language.return_value = MagicMock()
                parser = CodeParser()
                content = b"same content"
                hash1 = parser._compute_hash(content)
                hash2 = parser._compute_hash(content)
                assert hash1 == hash2

    @patch("smp.store.graph.parser.HAS_TREE_SITTER", True)
    def test_compute_hash_different_content(self) -> None:
        with patch("smp.store.graph.parser.tree_sitter_languages") as mock_ts:
            with patch("smp.store.graph.parser.Parser") as mock_parser_cls:
                mock_parser_cls.return_value = MagicMock()
                mock_ts.get_language.return_value = MagicMock()
                parser = CodeParser()
                hash1 = parser._compute_hash(b"content1")
                hash2 = parser._compute_hash(b"content2")
                assert hash1 != hash2


class TestNodeIdGeneration:
    """Tests for node ID generation."""

    @patch("smp.store.graph.parser.HAS_TREE_SITTER", True)
    def test_make_node_id(self) -> None:
        with patch("smp.store.graph.parser.tree_sitter_languages") as mock_ts:
            with patch("smp.store.graph.parser.Parser") as mock_parser_cls:
                mock_parser_cls.return_value = MagicMock()
                mock_ts.get_language.return_value = MagicMock()
                parser = CodeParser()
                node_id = parser._make_node_id("/path/to/file.py", "Function", "foo", 10)
                assert "Function" in node_id
                assert "foo" in node_id
                assert "10" in node_id

    @patch("smp.store.graph.parser.HAS_TREE_SITTER", True)
    def test_make_node_id_different_types(self) -> None:
        with patch("smp.store.graph.parser.tree_sitter_languages") as mock_ts:
            with patch("smp.store.graph.parser.Parser") as mock_parser_cls:
                mock_parser_cls.return_value = MagicMock()
                mock_ts.get_language.return_value = MagicMock()
                parser = CodeParser()
                func_id = parser._make_node_id("/p.py", "Function", "foo", 1)
                class_id = parser._make_node_id("/p.py", "Class", "Bar", 1)
                assert "Function" in func_id
                assert "Class" in class_id


class TestInvalidSyntaxHandling:
    """Tests for handling invalid syntax."""

    @patch("smp.store.graph.parser.HAS_TREE_SITTER", True)
    def test_parse_invalid_syntax_returns_empty_nodes(self) -> None:
        with patch("smp.store.graph.parser.tree_sitter_languages") as mock_ts:
            with patch("smp.store.graph.parser.Parser") as mock_parser_cls:
                mock_parser_instance = MagicMock()
                mock_parser_cls.return_value = mock_parser_instance

                mock_tree = MagicMock()
                mock_tree.root_node = MagicMock()
                mock_tree.root_node.children = []
                mock_tree.root_node.type = "ERROR"
                mock_parser_instance.parse.return_value = mock_tree

                mock_ts.get_language.return_value = MagicMock()

                parser = CodeParser()
                parser._python_ready = True
                parser._parsers[LANG_PYTHON] = mock_parser_instance
                parser._languages[LANG_PYTHON] = MagicMock()

                content = b"def foo(\n    pass"
                result = parser._parse_python("/path/to/file.py", content)
                assert result.language == LANG_PYTHON

    @patch("smp.store.graph.parser.HAS_TREE_SITTER", True)
    def test_parse_incomplete_code(self) -> None:
        with patch("smp.store.graph.parser.tree_sitter_languages") as mock_ts:
            with patch("smp.store.graph.parser.Parser") as mock_parser_cls:
                mock_parser_instance = MagicMock()
                mock_parser_cls.return_value = mock_parser_instance

                mock_tree = MagicMock()
                mock_tree.root_node = MagicMock()
                mock_tree.root_node.children = []
                mock_tree.root_node.type = "module"
                mock_parser_instance.parse.return_value = mock_tree

                mock_ts.get_language.return_value = MagicMock()

                parser = CodeParser()
                parser._python_ready = True
                parser._parsers[LANG_PYTHON] = mock_parser_instance
                parser._languages[LANG_PYTHON] = MagicMock()

                content = b"def foo("
                result = parser._parse_python("/path/to/file.py", content)
                assert result.language == LANG_PYTHON


class TestLargeFileHandling:
    """Tests for handling large files."""

    @patch("smp.store.graph.parser.HAS_TREE_SITTER", True)
    def test_parse_large_file_memory(self) -> None:
        with patch("smp.store.graph.parser.tree_sitter_languages") as mock_ts:
            with patch("smp.store.graph.parser.Parser") as mock_parser_cls:
                mock_parser_instance = MagicMock()
                mock_parser_cls.return_value = mock_parser_instance

                mock_tree = MagicMock()
                mock_tree.root_node = MagicMock()
                mock_tree.root_node.children = []
                mock_tree.root_node.type = "module"
                mock_parser_instance.parse.return_value = mock_tree

                mock_ts.get_language.return_value = MagicMock()

                parser = CodeParser()
                parser._python_ready = True
                parser._parsers[LANG_PYTHON] = mock_parser_instance

                large_content = b"x = 1\n" * 10000
                result = parser._parse_python("/path/to/large.py", large_content)
                assert result.line_count == 10000

    @patch("smp.store.graph.parser.HAS_TREE_SITTER", True)
    def test_parse_empty_file(self) -> None:
        with patch("smp.store.graph.parser.tree_sitter_languages") as mock_ts:
            with patch("smp.store.graph.parser.Parser") as mock_parser_cls:
                mock_parser_instance = MagicMock()
                mock_parser_cls.return_value = mock_parser_instance

                mock_tree = MagicMock()
                mock_tree.root_node = MagicMock()
                mock_tree.root_node.children = []
                mock_tree.root_node.type = "module"
                mock_parser_instance.parse.return_value = mock_tree

                mock_ts.get_language.return_value = MagicMock()

                parser = CodeParser()
                parser._python_ready = True
                parser._parsers[LANG_PYTHON] = mock_parser_instance

                result = parser._parse_python("/path/to/empty.py", b"")
                assert result.line_count == 0

    @patch("smp.store.graph.parser.HAS_TREE_SITTER", True)
    def test_parse_file_with_many_lines(self) -> None:
        with patch("smp.store.graph.parser.tree_sitter_languages") as mock_ts:
            with patch("smp.store.graph.parser.Parser") as mock_parser_cls:
                mock_parser_instance = MagicMock()
                mock_parser_cls.return_value = mock_parser_instance

                mock_tree = MagicMock()
                mock_tree.root_node = MagicMock()
                mock_tree.root_node.children = []
                mock_tree.root_node.type = "module"
                mock_parser_instance.parse.return_value = mock_tree

                mock_ts.get_language.return_value = MagicMock()

                parser = CodeParser()
                parser._python_ready = True
                parser._parsers[LANG_PYTHON] = mock_parser_instance

                lines = "\n".join(f"y = {i}" for i in range(1000))
                content = lines.encode()
                result = parser._parse_python("/path/to/file.py", content)
                assert result.line_count == 1000


class TestMultipleLanguageFiles:
    """Tests for various non-Python files."""

    @pytest.mark.parametrize(
        "extension,content,language,expected_names",
        [
            (".js", b"const x = 1;", "javascript", []),
            (".ts", b"const x: number = 1;", "typescript", []),
            (".jsx", b"const x = <div/>;", "javascript", []),
            (".tsx", b"const x: React.FC = () => <div/>;", "tsx", ["x"]),
            (".go", b"package main\nfunc main() {}", "go", ["main"]),
            (".rs", b"fn main() {}", "rust", ["main"]),
            (".java", b"public class Main {}", "java", ["Main"]),
            (".cpp", b"#include <iostream>", "cpp", []),
            (".c", b"#include <stdio.h>", "c", []),
            (".rb", b"def foo; end", "ruby", ["foo"]),
            (".php", b"<?php echo 'hello'; ?>", "php", []),
        ],
    )
    def test_non_python_extensions(
        self, extension: str, content: bytes, language: str, expected_names: list[str]
    ) -> None:
        parser = CodeParser()
        with tempfile.NamedTemporaryFile(suffix=extension, delete=False, mode="wb") as f:
            f.write(content)
            f.flush()
            result = parser.parse_file(f.name)
        assert result.language == language
        assert [n.name for n in result.nodes] == expected_names

    @patch("smp.store.graph.parser.HAS_TREE_SITTER", True)
    def test_file_with_no_extension(self) -> None:
        with patch("smp.store.graph.parser.tree_sitter_languages") as mock_ts:
            with patch("smp.store.graph.parser.Parser") as mock_parser_cls:
                mock_parser_cls.return_value = MagicMock()
                mock_ts.get_language.return_value = MagicMock()
                parser = CodeParser()
                with tempfile.NamedTemporaryFile(delete=False, mode="w") as f:
                    f.write("FROM python:3.11")
                    f.flush()
                    result = parser.parse_file(f.name)
                    assert result.language == LANG_UNKNOWN


class TestEnsurePython:
    """Tests for _ensure_python method."""

    @patch("smp.store.graph.parser.HAS_TREE_SITTER", True)
    def test_ensure_python_already_ready(self) -> None:
        with patch("smp.store.graph.parser.tree_sitter_languages") as mock_ts:
            with patch("smp.store.graph.parser.Parser") as mock_parser_cls:
                mock_parser_cls.return_value = MagicMock()
                mock_ts.get_language.return_value = MagicMock()
                parser = CodeParser()
                parser._python_ready = True
                parser._ensure_python()
                assert parser._python_ready is True

    @patch("smp.store.graph.parser.HAS_TREE_SITTER", True)
    def test_ensure_python_first_call(self) -> None:
        with patch("smp.store.graph.parser.tree_sitter_languages") as mock_ts:
            with patch("smp.store.graph.parser.Parser") as mock_parser_cls:
                mock_parser_instance = MagicMock()
                mock_parser_cls.return_value = mock_parser_instance
                mock_ts.get_language.return_value = MagicMock()
                parser = CodeParser()
                parser._ensure_python()
                assert parser._python_ready is True
                assert LANG_PYTHON in parser._parsers


class TestWalkTree:
    """Tests for _walk_tree method."""

    @patch("smp.store.graph.parser.HAS_TREE_SITTER", True)
    def test_walk_tree_module_node(self) -> None:
        with patch("smp.store.graph.parser.tree_sitter_languages") as mock_ts:
            with patch("smp.store.graph.parser.Parser") as mock_parser_cls:
                mock_parser_cls.return_value = MagicMock()
                mock_ts.get_language.return_value = MagicMock()
                parser = CodeParser()

                mock_root = MagicMock()
                mock_root.type = "module"
                mock_root.children = []
                mock_root.end_point = (0, 0)

                nodes: list[ParsedNode] = []
                edge_candidates: list[EdgeCandidate] = []
                scope_stack: list[tuple[str, int]] = []

                parser._walk_tree(
                    mock_root,
                    b"content",
                    "/p.py",
                    nodes,
                    edge_candidates,
                    scope_stack,
                    LANG_PYTHON,
                )
                assert nodes == []

    @patch("smp.store.graph.parser.HAS_TREE_SITTER", True)
    def test_walk_tree_handles_function(self) -> None:
        with patch("smp.store.graph.parser.tree_sitter_languages") as mock_ts:
            with patch("smp.store.graph.parser.Parser") as mock_parser_cls:
                mock_parser_cls.return_value = MagicMock()
                mock_ts.get_language.return_value = MagicMock()
                parser = CodeParser()

                mock_node = MagicMock()
                mock_node.type = "function_definition"
                mock_node.children = []
                mock_node.end_point = (5, 0)
                mock_node.start_point = (1, 0)
                mock_node.start_byte = 0
                mock_node.end_byte = 20
                mock_node.child_by_field_name = MagicMock(return_value=None)

                nodes: list[ParsedNode] = []
                edge_candidates: list[EdgeCandidate] = []
                scope_stack: list[tuple[str, int]] = []

                parser._walk_tree(
                    mock_node,
                    b"def foo():\n    pass",
                    "/p.py",
                    nodes,
                    edge_candidates,
                    scope_stack,
                    LANG_PYTHON,
                )


class TestExtractDocstring:
    """Tests for _extract_docstring method."""

    @patch("smp.store.graph.parser.HAS_TREE_SITTER", True)
    def test_extract_docstring_empty(self) -> None:
        with patch("smp.store.graph.parser.tree_sitter_languages") as mock_ts:
            with patch("smp.store.graph.parser.Parser") as mock_parser_cls:
                mock_parser_cls.return_value = MagicMock()
                mock_ts.get_language.return_value = MagicMock()
                parser = CodeParser()

                mock_node = MagicMock()
                mock_node.child_by_field_name = MagicMock(return_value=None)

                result = parser._extract_docstring(mock_node, b"content")
                assert result == ""


class TestExtractDecorators:
    """Tests for _extract_decorators method."""

    @patch("smp.store.graph.parser.HAS_TREE_SITTER", True)
    def test_extract_decorators_none(self) -> None:
        with patch("smp.store.graph.parser.tree_sitter_languages") as mock_ts:
            with patch("smp.store.graph.parser.Parser") as mock_parser_cls:
                mock_parser_cls.return_value = MagicMock()
                mock_ts.get_language.return_value = MagicMock()
                parser = CodeParser()

                mock_node = MagicMock()
                mock_node.prev_sibling = None

                result = parser._extract_decorators(mock_node, b"@decorator\ndef foo():")
                assert result == []


class TestParsePythonWithMockTree:
    """Tests for _parse_python with mocked tree."""

    @patch("smp.store.graph.parser.HAS_TREE_SITTER", True)
    def test_parse_python_no_parser_ready(self) -> None:
        with patch("smp.store.graph.parser.tree_sitter_languages") as mock_ts:
            with patch("smp.store.graph.parser.Parser") as mock_parser_cls:
                mock_parser_instance = MagicMock()
                mock_parser_cls.return_value = mock_parser_instance
                mock_ts.get_language.return_value = MagicMock()
                parser = CodeParser()
                parser._ensure_python()

                if LANG_PYTHON in parser._parsers:
                    del parser._parsers[LANG_PYTHON]

                result = parser._parse_python("/path/to/file.py", b"def foo(): pass")
                assert result.language == LANG_PYTHON
                assert result.nodes == []


class TestPythonExtensions:
    """Tests for Python extension detection."""

    @patch("smp.store.graph.parser.HAS_TREE_SITTER", True)
    def test_pyw_extension(self) -> None:
        with patch("smp.store.graph.parser.tree_sitter_languages") as mock_ts:
            with patch("smp.store.graph.parser.Parser") as mock_parser_cls:
                mock_parser_cls.return_value = MagicMock()
                mock_ts.get_language.return_value = MagicMock()
                parser = CodeParser()
                assert parser._is_python("/path/to/script.pyw") is True


class TestEdgeCandidates:
    """Tests for edge candidate generation."""

    @patch("smp.store.graph.parser.HAS_TREE_SITTER", True)
    def test_import_edge_candidate(self) -> None:
        edge = EdgeCandidate(
            source_id="source1",
            target_name="os",
            edge_type="IMPORTS",
        )
        assert edge.edge_type == "IMPORTS"
        assert edge.target_name == "os"

    @patch("smp.store.graph.parser.HAS_TREE_SITTER", True)
    def test_calls_edge_candidate(self) -> None:
        edge = EdgeCandidate(
            source_id="func1",
            target_name="helper.do_something",
            edge_type="CALLS",
        )
        assert edge.edge_type == "CALLS"
        assert edge.target_name == "helper.do_something"


class TestParsedFileHash:
    """Tests for hash in ParsedFile."""

    @patch("smp.store.graph.parser.HAS_TREE_SITTER", True)
    def test_content_hash_format(self) -> None:
        with patch("smp.store.graph.parser.tree_sitter_languages") as mock_ts:
            with patch("smp.store.graph.parser.Parser") as mock_parser_cls:
                mock_parser_instance = MagicMock()
                mock_parser_cls.return_value = mock_parser_instance
                mock_tree = MagicMock()
                mock_tree.root_node = MagicMock()
                mock_tree.root_node.children = []
                mock_tree.root_node.type = "module"
                mock_parser_instance.parse.return_value = mock_tree

                mock_ts.get_language.return_value = MagicMock()

                parser = CodeParser()
                parser._python_ready = True
                parser._parsers[LANG_PYTHON] = mock_parser_instance

                result = parser._parse_python("/path/to/file.py", b"hello world")
                assert len(result.content_hash) == 16


class TestLineCount:
    """Tests for line counting."""

    @patch("smp.store.graph.parser.HAS_TREE_SITTER", True)
    def test_line_count_with_empty_lines(self) -> None:
        with patch("smp.store.graph.parser.tree_sitter_languages") as mock_ts:
            with patch("smp.store.graph.parser.Parser") as mock_parser_cls:
                mock_parser_cls.return_value = MagicMock()
                mock_ts.get_language.return_value = MagicMock()
                parser = CodeParser()

                result = parser._empty_parsed_file("/p.js", b"\n\n\n")
                assert result.line_count == 3


class TestEncodingHandling:
    """Tests for encoding edge cases."""

    @patch("smp.store.graph.parser.HAS_TREE_SITTER", True)
    def test_utf8_content(self) -> None:
        with patch("smp.store.graph.parser.tree_sitter_languages") as mock_ts:
            with patch("smp.store.graph.parser.Parser") as mock_parser_cls:
                mock_parser_instance = MagicMock()
                mock_parser_cls.return_value = mock_parser_instance

                mock_tree = MagicMock()
                mock_tree.root_node = MagicMock()
                mock_tree.root_node.children = []
                mock_tree.root_node.type = "module"
                mock_parser_instance.parse.return_value = mock_tree

                mock_ts.get_language.return_value = MagicMock()

                parser = CodeParser()
                parser._python_ready = True
                parser._parsers[LANG_PYTHON] = mock_parser_instance

                content = 'def foo():\n    return "héllo wörld"'.encode()
                result = parser._parse_python("/path/to/file.py", content)
                assert result.language == LANG_PYTHON

    @patch("smp.store.graph.parser.HAS_TREE_SITTER", True)
    def test_invalid_utf8_replacement(self) -> None:
        with patch("smp.store.graph.parser.tree_sitter_languages") as mock_ts:
            with patch("smp.store.graph.parser.Parser") as mock_parser_cls:
                mock_parser_cls.return_value = MagicMock()
                mock_ts.get_language.return_value = MagicMock()
                parser = CodeParser()

                result = parser._empty_parsed_file("/p.js", b"\xff\xfe")
                assert result.line_count == 1
