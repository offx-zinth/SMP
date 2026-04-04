"""Parser registry — dispatches to the correct language parser."""

from __future__ import annotations

from pathlib import Path

from smp.core.models import Document, Language
from smp.engine.interfaces import Parser
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
        elif language == Language.TYPESCRIPT:
            from smp.parser.typescript_parser import TypeScriptParser
            parser = TypeScriptParser()

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
