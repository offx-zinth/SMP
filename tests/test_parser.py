"""Tests for the tree-sitter parser layer — SMP(3)."""

from __future__ import annotations

from smp.core.models import EdgeType, Language, NodeType
from smp.parser.base import detect_language
from smp.parser.python_parser import PythonParser
from smp.parser.registry import ParserRegistry
from smp.parser.typescript_parser import TypeScriptParser

# =========================================================================
# Language detection
# =========================================================================


class TestDetectLanguage:
    def test_python(self) -> None:
        assert detect_language("foo.py") == Language.PYTHON

    def test_typescript(self) -> None:
        assert detect_language("foo.ts") == Language.TYPESCRIPT

    def test_tsx(self) -> None:
        assert detect_language("foo.tsx") == Language.TYPESCRIPT

    def test_jsx(self) -> None:
        assert detect_language("foo.jsx") == Language.TYPESCRIPT

    def test_unknown(self) -> None:
        assert detect_language("foo.rs") == Language.UNKNOWN

    def test_no_extension(self) -> None:
        assert detect_language("Makefile") == Language.UNKNOWN


# =========================================================================
# Python parser
# =========================================================================


class TestPythonParser:
    def _parse(self, src: str):
        p = PythonParser()
        return p.parse(src, "test.py")

    def test_empty_file(self) -> None:
        doc = self._parse("")
        assert len(doc.errors) == 0
        assert any(n.type == NodeType.FILE for n in doc.nodes)

    def test_simple_function(self) -> None:
        doc = self._parse("def hello():\n    pass\n")
        funcs = [n for n in doc.nodes if n.type == NodeType.FUNCTION]
        assert len(funcs) == 1
        assert funcs[0].structural.name == "hello"
        assert funcs[0].structural.signature == "def hello()"

    def test_typed_function(self) -> None:
        doc = self._parse("def add(a: int, b: int) -> int:\n    return a + b\n")
        funcs = [n for n in doc.nodes if n.type == NodeType.FUNCTION]
        assert len(funcs) == 1
        assert funcs[0].structural.name == "add"
        assert "int" in funcs[0].structural.signature

    def test_function_with_docstring(self) -> None:
        doc = self._parse('def foo():\n    """A docstring."""\n    pass\n')
        funcs = [n for n in doc.nodes if n.type == NodeType.FUNCTION]
        assert len(funcs) == 1
        assert funcs[0].semantic.docstring == "A docstring."

    def test_class(self) -> None:
        doc = self._parse("class Foo:\n    pass\n")
        classes = [n for n in doc.nodes if n.type == NodeType.CLASS]
        assert len(classes) == 1
        assert classes[0].structural.name == "Foo"
        assert classes[0].structural.signature == "class Foo"

    def test_class_with_bases(self) -> None:
        doc = self._parse("class Child(Parent):\n    pass\n")
        classes = [n for n in doc.nodes if n.type == NodeType.CLASS]
        assert len(classes) == 1
        assert "Parent" in classes[0].structural.signature
        inherits = [e for e in doc.edges if e.type == EdgeType.IMPLEMENTS]
        assert len(inherits) == 1

    def test_method_in_class(self) -> None:
        doc = self._parse("class Foo:\n    def bar(self):\n        pass\n")
        funcs = [n for n in doc.nodes if n.type == NodeType.FUNCTION]
        bar_funcs = [f for f in funcs if f.structural.name == "bar"]
        assert len(bar_funcs) == 1

    def test_import(self) -> None:
        doc = self._parse("import os\nimport sys\n")
        imports = [n for n in doc.nodes if n.structural.signature.startswith("import")]
        assert len(imports) == 2
        names = {i.structural.name for i in imports}
        assert "os" in names
        assert "sys" in names

    def test_from_import(self) -> None:
        doc = self._parse("from os.path import join\n")
        imports = [n for n in doc.nodes if n.structural.signature.startswith("from")]
        assert len(imports) == 1
        assert "os.path" in imports[0].structural.name

    def test_call_edge(self) -> None:
        doc = self._parse("def a():\n    b()\n")
        calls = [e for e in doc.edges if e.type == EdgeType.CALLS]
        assert len(calls) == 1

    def test_decorator(self) -> None:
        doc = self._parse("@app.route('/home')\ndef handler():\n    pass\n")
        funcs = [n for n in doc.nodes if n.type == NodeType.FUNCTION]
        assert len(funcs) == 1
        assert "app.route" in funcs[0].semantic.decorators

    def test_contains_edge_file_to_func(self) -> None:
        doc = self._parse("def foo():\n    pass\n")
        defines = [e for e in doc.edges if e.type == EdgeType.DEFINES]
        file_defines = [e for e in defines if "File" in e.source_id]
        assert len(file_defines) >= 1

    def test_contains_edge_class_to_method(self) -> None:
        doc = self._parse("class Foo:\n    def bar(self):\n        pass\n")
        defines = [e for e in doc.edges if e.type == EdgeType.DEFINES]
        class_defines = [e for e in defines if "Class" in e.source_id]
        assert len(class_defines) == 1

    def test_no_duplicate_nodes(self) -> None:
        doc = self._parse("class Foo:\n    def bar(self):\n        pass\n")
        ids = [n.id for n in doc.nodes]
        assert len(ids) == len(set(ids))

    def test_syntax_error_partial(self) -> None:
        doc = self._parse("def foo(\n    pass\n")
        assert any(n.type == NodeType.FILE for n in doc.nodes)
        assert len(doc.errors) > 0

    def test_nested_class(self) -> None:
        doc = self._parse("class Outer:\n    class Inner:\n        def deep(self):\n            pass\n")
        classes = [n for n in doc.nodes if n.type == NodeType.CLASS]
        assert len(classes) == 2
        names = {c.structural.name for c in classes}
        assert names == {"Outer", "Inner"}

    def test_multiple_functions(self) -> None:
        doc = self._parse("def a():\n    pass\n\ndef b():\n    pass\n\ndef c():\n    pass\n")
        funcs = [n for n in doc.nodes if n.type == NodeType.FUNCTION]
        assert len(funcs) == 3

    def test_annotations_extracted(self) -> None:
        doc = self._parse("def add(a: int, b: int) -> int:\n    return a + b\n")
        funcs = [n for n in doc.nodes if n.type == NodeType.FUNCTION]
        assert len(funcs) == 1
        ann = funcs[0].semantic.annotations
        assert ann is not None
        assert "a" in ann.params
        assert "b" in ann.params
        assert ann.returns == "int"


# =========================================================================
# TypeScript parser
# =========================================================================


class TestTypeScriptParser:
    def _parse(self, src: str, fname: str = "test.ts"):
        p = TypeScriptParser()
        return p.parse(src, fname)

    def test_empty_file(self) -> None:
        doc = self._parse("")
        assert len(doc.errors) == 0

    def test_function_declaration(self) -> None:
        doc = self._parse("function hello(): void {\n}\n")
        funcs = [n for n in doc.nodes if n.type == NodeType.FUNCTION]
        assert len(funcs) == 1
        assert funcs[0].structural.name == "hello"

    def test_class(self) -> None:
        doc = self._parse("class Foo {\n  bar(): void {}\n}\n")
        classes = [n for n in doc.nodes if n.type == NodeType.CLASS]
        assert len(classes) == 1

    def test_no_duplicate_nodes(self) -> None:
        doc = self._parse("class Foo {\n  bar(): void {}\n}\n")
        ids = [n.id for n in doc.nodes]
        assert len(ids) == len(set(ids))


# =========================================================================
# Registry
# =========================================================================


class TestParserRegistry:
    def test_get_python(self) -> None:
        reg = ParserRegistry()
        parser = reg.get(Language.PYTHON)
        assert parser is not None

    def test_get_typescript(self) -> None:
        reg = ParserRegistry()
        parser = reg.get(Language.TYPESCRIPT)
        assert parser is not None

    def test_get_unknown(self) -> None:
        reg = ParserRegistry()
        parser = reg.get(Language.UNKNOWN)
        assert parser is None

    def test_parse_file_python(self, tmp_path) -> None:
        f = tmp_path / "test.py"
        f.write_text("def hello():\n    pass\n")
        reg = ParserRegistry()
        doc = reg.parse_file(str(f))
        assert len(doc.errors) == 0
        funcs = [n for n in doc.nodes if n.type == NodeType.FUNCTION]
        assert len(funcs) == 1

    def test_parse_file_missing(self) -> None:
        reg = ParserRegistry()
        doc = reg.parse_file("/nonexistent/test.py")
        assert len(doc.errors) > 0
