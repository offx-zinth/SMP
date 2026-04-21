"""Parser registry — dispatches to the correct language parser."""

from __future__ import annotations

from pathlib import Path

from smp.core.models import Document, Language
from smp.logging import get_logger
from smp.parser.base import TreeSitterParser, detect_language

log = get_logger(__name__)


class ParserRegistry:
    """Lazy-initialised registry of language-specific parsers."""

    def __init__(self) -> None:
        self._parsers: dict[Language, TreeSitterParser] = {}

    def _ensure_parser(self, language: Language) -> TreeSitterParser | None:
        if language in self._parsers:
            return self._parsers[language]

        parser: TreeSitterParser | None = None

        if language == Language.PYTHON:
            from smp.parser.python_parser import PythonParser

            parser = PythonParser()
        elif language == Language.JAVASCRIPT:
            from smp.parser.javascript_parser import JavaScriptParser

            parser = JavaScriptParser()
        elif language == Language.TYPESCRIPT:
            from smp.parser.typescript_parser import TypeScriptParser

            parser = TypeScriptParser()
        elif language == Language.JAVA:
            from smp.parser.java_parser import JavaParser

            parser = JavaParser()
        elif language == Language.C:
            from smp.parser.cpp_parser import CParser

            parser = CParser()
        elif language == Language.CPP:
            from smp.parser.cpp_parser import CppParser

            parser = CppParser()
        elif language == Language.CSHARP:
            from smp.parser.csharp_parser import CSharpParser

            parser = CSharpParser()
        elif language == Language.GO:
            from smp.parser.go_parser import GoParser

            parser = GoParser()
        elif language == Language.RUST:
            from smp.parser.rust_parser import RustParser

            parser = RustParser()
        elif language == Language.PHP:
            from smp.parser.php_parser import PhpParser

            parser = PhpParser()
        elif language == Language.SWIFT:
            from smp.parser.swift_parser import SwiftParser

            parser = SwiftParser()
        elif language == Language.KOTLIN:
            from smp.parser.kotlin_parser import KotlinParser

            parser = KotlinParser()
        elif language == Language.RUBY:
            from smp.parser.ruby_parser import RubyParser

            parser = RubyParser()
        elif language == Language.MATLAB:
            from smp.parser.matlab_parser import MatlabParser

            parser = MatlabParser()

        if parser:
            self._parsers[language] = parser
            log.debug("parser_registered", language=language.value)
        return parser

    def get(self, language: Language) -> TreeSitterParser | None:
        """Return the parser for *language*, or ``None`` if unsupported."""
        return self._ensure_parser(language)

    def parse_file(self, file_path: str) -> Document:
        """Detect language, read file, and parse.

        Returns a Document with nodes, edges, and errors.
        """
        lang = detect_language(file_path)
        parser = self.get(lang)
        if not parser:
            from smp.core.models import ParseError

            return Document(
                file_path=file_path,
                language=lang,
                errors=[ParseError(message=f"No parser available for {lang.value}")],
            )

        try:
            source = Path(file_path).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            from smp.core.models import ParseError

            log.error("file_read_error", file_path=file_path, error=str(exc))
            return Document(
                file_path=file_path,
                language=lang,
                errors=[ParseError(message=f"Cannot read file: {exc}")],
            )

        return parser.parse(source, file_path)
