"""Tests for the tree-sitter parser layer."""

from __future__ import annotations

from smp.core.models import EdgeType, Language, NodeType
from smp.parser.python_parser import PythonParser
from smp.parser.typescript_parser import TypeScriptParser
from smp.parser.registry import ParserRegistry
from smp.parser.base import detect_language


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
    def _parse(self, src: str) -> list:
        p = PythonParser()
        doc = p.parse(src, "test.py")
        return doc

    def test_empty_file(self) -> None:
        doc = self._parse("")
        assert len(doc.errors) == 0
        # Should have at least the FILE node
        assert any(n.type == NodeType.FILE for n in doc.nodes)

    def test_simple_function(self) -> None:
        doc = self._parse("def hello():\n    pass\n")
        funcs = [n for n in doc.nodes if n.type == NodeType.FUNCTION]
        assert len(funcs) == 1
        assert funcs[0].name == "hello"
        assert funcs[0].signature == "def hello()"

    def test_typed_function(self) -> None:
        doc = self._parse("def add(a: int, b: int) -> int:\n    return a + b\n")
        funcs = [n for n in doc.nodes if n.type == NodeType.FUNCTION]
        assert len(funcs) == 1
        assert funcs[0].name == "add"
        assert "int" in funcs[0].signature

    def test_function_with_docstring(self) -> None:
        doc = self._parse('def foo():\n    """A docstring."""\n    pass\n')
        funcs = [n for n in doc.nodes if n.type == NodeType.FUNCTION]
        assert len(funcs) == 1
        assert funcs[0].docstring == "A docstring."

    def test_class(self) -> None:
        doc = self._parse("class Foo:\n    pass\n")
        classes = [n for n in doc.nodes if n.type == NodeType.CLASS]
        assert len(classes) == 1
        assert classes[0].name == "Foo"
        assert classes[0].signature == "class Foo"

    def test_class_with_bases(self) -> None:
        doc = self._parse("class Child(Parent):\n    pass\n")
        classes = [n for n in doc.nodes if n.type == NodeType.CLASS]
        assert len(classes) == 1
        assert "Parent" in classes[0].signature
        inherits = [e for e in doc.edges if e.type == EdgeType.INHERITS]
        assert len(inherits) == 1

    def test_method(self) -> None:
        doc = self._parse("class Foo:\n    def bar(self):\n        pass\n")
        methods = [n for n in doc.nodes if n.type == NodeType.METHOD]
        assert len(methods) == 1
        assert methods[0].name == "bar"
        assert methods[0].metadata.get("class") == "Foo"

    def test_import(self) -> None:
        doc = self._parse("import os\nimport sys\n")
        imports = [n for n in doc.nodes if n.type == NodeType.IMPORT]
        assert len(imports) == 2
        names = {i.name for i in imports}
        assert "os" in names
        assert "sys" in names

    def test_from_import(self) -> None:
        doc = self._parse("from os.path import join\n")
        imports = [n for n in doc.nodes if n.type == NodeType.IMPORT]
        assert len(imports) == 1
        assert "os.path" in imports[0].name

    def test_call_edge(self) -> None:
        doc = self._parse("def a():\n    b()\n")
        calls = [e for e in doc.edges if e.type == EdgeType.CALLS]
        assert len(calls) == 1

    def test_decorator(self) -> None:
        doc = self._parse("@app.route('/home')\ndef handler():\n    pass\n")
        funcs = [n for n in doc.nodes if n.type == NodeType.FUNCTION]
        assert len(funcs) == 1
        assert funcs[0].metadata.get("decorators") == "app.route"

    def test_contains_edge_file_to_func(self) -> None:
        doc = self._parse("def foo():\n    pass\n")
        contains = [e for e in doc.edges if e.type == EdgeType.CONTAINS]
        file_contains = [e for e in contains if "FILE" in e.source_id]
        assert len(file_contains) >= 1

    def test_contains_edge_class_to_method(self) -> None:
        doc = self._parse("class Foo:\n    def bar(self):\n        pass\n")
        contains = [e for e in doc.edges if e.type == EdgeType.CONTAINS]
        class_contains = [e for e in contains if "CLASS" in e.source_id]
        assert len(class_contains) == 1
        assert "METHOD" in class_contains[0].target_id

    def test_no_duplicate_nodes(self) -> None:
        doc = self._parse("class Foo:\n    def bar(self):\n        pass\n")
        ids = [n.id for n in doc.nodes]
        assert len(ids) == len(set(ids))

    def test_syntax_error_partial(self) -> None:
        doc = self._parse("def foo(\n    pass\n")
        # Should still have FILE node and at least one error
        assert any(n.type == NodeType.FILE for n in doc.nodes)
        assert len(doc.errors) > 0

    def test_nested_class(self) -> None:
        doc = self._parse(
            "class Outer:\n"
            "    class Inner:\n"
            "        def deep(self):\n"
            "            pass\n"
        )
        classes = [n for n in doc.nodes if n.type == NodeType.CLASS]
        assert len(classes) == 2
        names = {c.name for c in classes}
        assert names == {"Outer", "Inner"}

    def test_multiple_functions(self) -> None:
        doc = self._parse(
            "def a():\n    pass\n\ndef b():\n    pass\n\ndef c():\n    pass\n"
        )
        funcs = [n for n in doc.nodes if n.type == NodeType.FUNCTION]
        assert len(funcs) == 3


# =========================================================================
# TypeScript parser
# =========================================================================

class TestTypeScriptParser:
    def _parse(self, src: str, fname: str = "test.ts") -> list:
        p = TypeScriptParser()
        doc = p.parse(src, fname)
        return doc

    def test_empty_file(self) -> None:
        doc = self._parse("")
        assert len(doc.errors) == 0

    def test_function_declaration(self) -> None:
        doc = self._parse("function hello(): void {\n}\n")
        funcs = [n for n in doc.nodes if n.type == NodeType.FUNCTION]
        assert len(funcs) == 1
        assert funcs[0].name == "hello"

    def test_arrow_function(self) -> None:
        doc = self._parse("const add = (a: number, b: number): number => a + b;\n")
        funcs = [n for n in doc.nodes if n.type == NodeType.FUNCTION]
        assert len(funcs) == 1
        assert funcs[0].name == "add"

    def test_class(self) -> None:
        doc = self._parse("class Foo {\n  bar(): void {}\n}\n")
        classes = [n for n in doc.nodes if n.type == NodeType.CLASS]
        assert len(classes) == 1
        methods = [n for n in doc.nodes if n.type == NodeType.METHOD]
        assert len(methods) == 1

    def test_interface(self) -> None:
        doc = self._parse("interface Config {\n  name: string;\n}\n")
        classes = [n for n in doc.nodes if n.type == NodeType.CLASS]
        assert len(classes) == 1
        assert classes[0].metadata.get("kind") == "interface"

    def test_import(self) -> None:
        doc = self._parse("import { foo } from './utils';\nimport Bar from 'lib';\n")
        imports = [n for n in doc.nodes if n.type == NodeType.IMPORT]
        assert len(imports) == 2

    def test_extends(self) -> None:
        doc = self._parse("class Child extends Base {\n}\n")
        inherits = [e for e in doc.edges if e.type == EdgeType.INHERITS]
        assert len(inherits) == 1

    def test_call_edge(self) -> None:
        doc = self._parse("function a() {\n  b();\n}\n")
        calls = [e for e in doc.edges if e.type == EdgeType.CALLS]
        assert len(calls) == 1

    def test_no_duplicate_nodes(self) -> None:
        doc = self._parse(
            "class Foo {\n"
            "  bar(): void {}\n"
            "}\n"
        )
        ids = [n.id for n in doc.nodes]
        assert len(ids) == len(set(ids))

    def test_tsx_extension(self) -> None:
        doc = self._parse("function App() {\n  return <div/>;\n}\n", "test.tsx")
        funcs = [n for n in doc.nodes if n.type == NodeType.FUNCTION]
        assert len(funcs) == 1

    def test_export_function(self) -> None:
        doc = self._parse("export function handler() {\n}\n")
        funcs = [n for n in doc.nodes if n.type == NodeType.FUNCTION]
        assert len(funcs) == 1


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
