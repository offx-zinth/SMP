"""Tests for the semantic enricher."""

from __future__ import annotations

import pytest

from smp.core.models import GraphNode, NodeType, SemanticInfo
from smp.engine.enricher import LLMSemanticEnricher, _hash_embed, _split_name, _static_purpose


# ---------------------------------------------------------------------------
# Name splitting
# ---------------------------------------------------------------------------

class TestSplitName:
    def test_snake_case(self) -> None:
        assert _split_name("get_user_by_id") == ["get", "user", "by", "id"]

    def test_camel_case(self) -> None:
        assert _split_name("getUserById") == ["get", "User", "By", "Id"]

    def test_single_word(self) -> None:
        assert _split_name("login") == ["login"]

    def test_acronym(self) -> None:
        result = _split_name("HTTPResponse")
        assert len(result) >= 2


# ---------------------------------------------------------------------------
# Static purpose inference
# ---------------------------------------------------------------------------

class TestStaticPurpose:
    def _make(self, **kwargs) -> GraphNode:
        defaults = dict(
            id="test::FUNCTION::foo::1",
            type=NodeType.FUNCTION,
            name="foo",
            file_path="test.py",
            start_line=1,
            end_line=5,
        )
        defaults.update(kwargs)
        return GraphNode(**defaults)

    def test_docstring_purpose(self) -> None:
        node = self._make(docstring="Authenticates a user and returns a token.")
        purpose, conf = _static_purpose(node)
        assert "Authenticates" in purpose
        assert conf == 0.6

    def test_function_from_name(self) -> None:
        node = self._make(name="get_user_by_id")
        purpose, conf = _static_purpose(node)
        assert "Retrieves" in purpose or "get" in purpose.lower()
        assert conf >= 0.2

    def test_class_purpose(self) -> None:
        node = self._make(
            type=NodeType.CLASS,
            id="test::CLASS::UserRepository::1",
            name="UserRepository",
            signature="class UserRepository",
        )
        purpose, _ = _static_purpose(node)
        assert "Class" in purpose
        assert "UserRepository" in purpose

    def test_init_purpose(self) -> None:
        node = self._make(
            type=NodeType.METHOD,
            name="__init__",
            metadata={"class": "MyClass"},
        )
        purpose, _ = _static_purpose(node)
        assert "MyClass" in purpose

    def test_import_purpose(self) -> None:
        node = self._make(
            type=NodeType.IMPORT,
            id="test::IMPORT::os::1",
            name="os",
        )
        purpose, _ = _static_purpose(node)
        assert "os" in purpose

    def test_decorator_purpose(self) -> None:
        node = self._make(
            name="test_something",
            metadata={"decorators": "pytest.fixture"},
        )
        purpose, _ = _static_purpose(node)
        assert "Test" in purpose


# ---------------------------------------------------------------------------
# Hash embedding
# ---------------------------------------------------------------------------

class TestHashEmbed:
    def test_deterministic(self) -> None:
        emb1 = _hash_embed("hello world")
        emb2 = _hash_embed("hello world")
        assert emb1 == emb2

    def test_dimensionality(self) -> None:
        emb = _hash_embed("test")
        assert len(emb) == 768

    def test_different_texts_differ(self) -> None:
        emb1 = _hash_embed("authentication")
        emb2 = _hash_embed("database connection")
        assert emb1 != emb2

    def test_normalized(self) -> None:
        import math
        emb = _hash_embed("test normalization")
        norm = math.sqrt(sum(v * v for v in emb))
        assert abs(norm - 1.0) < 0.01


# ---------------------------------------------------------------------------
# Enricher (static mode, no API key)
# ---------------------------------------------------------------------------

class TestLLMSemanticEnricherStatic:
    @pytest.fixture()
    def enricher(self) -> LLMSemanticEnricher:
        return LLMSemanticEnricher()

    @pytest.mark.asyncio
    async def test_enrich_function(self, enricher: LLMSemanticEnricher) -> None:
        node = GraphNode(
            id="test::FUNCTION::foo::1",
            type=NodeType.FUNCTION,
            name="foo",
            file_path="test.py",
            start_line=1,
            end_line=5,
        )
        enriched = await enricher.enrich_node(node)
        assert enriched.semantic is not None
        assert enriched.semantic.purpose != ""
        assert enriched.semantic.confidence > 0
        assert enriched.semantic.embedding is not None
        assert len(enriched.semantic.embedding) == 768

    @pytest.mark.asyncio
    async def test_enrich_with_docstring(self, enricher: LLMSemanticEnricher) -> None:
        node = GraphNode(
            id="test::FUNCTION::auth::10",
            type=NodeType.FUNCTION,
            name="auth",
            file_path="auth.py",
            start_line=10,
            end_line=20,
            docstring="Validates credentials and issues JWT.",
        )
        enriched = await enricher.enrich_node(node)
        assert enriched.semantic is not None
        assert "Validates" in enriched.semantic.purpose
        assert enriched.semantic.confidence == 0.6

    @pytest.mark.asyncio
    async def test_skip_already_enriched(self, enricher: LLMSemanticEnricher) -> None:
        node = GraphNode(
            id="test::FUNCTION::x::1",
            type=NodeType.FUNCTION,
            name="x",
            file_path="x.py",
            start_line=1,
            end_line=2,
            semantic=SemanticInfo(purpose="existing", confidence=0.9),
        )
        enriched = await enricher.enrich_node(node)
        assert enriched.semantic is not None
        assert enriched.semantic.purpose == "existing"

    @pytest.mark.asyncio
    async def test_enrich_batch(self, enricher: LLMSemanticEnricher) -> None:
        nodes = [
            GraphNode(id=f"test::FUNCTION::f{i}::{i}", type=NodeType.FUNCTION, name=f"f{i}", file_path="t.py", start_line=i, end_line=i + 1)
            for i in range(5)
        ]
        enriched = await enricher.enrich_batch(nodes)
        assert len(enriched) == 5
        for n in enriched:
            assert n.semantic is not None
            assert n.semantic.purpose != ""

    @pytest.mark.asyncio
    async def test_embed(self, enricher: LLMSemanticEnricher) -> None:
        emb = await enricher.embed("test text")
        assert len(emb) == 768
        assert all(isinstance(v, float) for v in emb)

    @pytest.mark.asyncio
    async def test_caching(self, enricher: LLMSemanticEnricher) -> None:
        node = GraphNode(
            id="test::FUNCTION::cached::1",
            type=NodeType.FUNCTION,
            name="cached",
            file_path="t.py",
            start_line=1,
            end_line=2,
        )
        enriched1 = await enricher.enrich_node(node)
        enriched2 = await enricher.enrich_node(node)
        assert enriched1.semantic == enriched2.semantic

    @pytest.mark.asyncio
    async def test_no_llm_mode(self, enricher: LLMSemanticEnricher) -> None:
        assert enricher.has_llm is False


# ---------------------------------------------------------------------------
# Enricher with Gemini API key
# ---------------------------------------------------------------------------

class TestLLMSemanticEnricherGemini:
    @pytest.mark.asyncio
    async def test_with_api_key(self) -> None:
        enricher = LLMSemanticEnricher(api_key="AIzaSyCPGNbIy7veCz7itQC3SeATBGPFBXEc55o")
        assert enricher.has_llm is True

        node = GraphNode(
            id="test::FUNCTION::authenticate::10",
            type=NodeType.FUNCTION,
            name="authenticate",
            file_path="auth.py",
            start_line=10,
            end_line=30,
            signature="def authenticate(username: str, password: str) -> Token:",
            docstring="Validates user credentials against the database and issues a JWT token.",
        )
        enriched = await enricher.enrich_node(node)
        assert enriched.semantic is not None
        assert enriched.semantic.purpose != ""
        assert enriched.semantic.confidence > 0.5
        assert enriched.semantic.embedding is not None
        assert len(enriched.semantic.embedding) == 768
        print(f"  Gemini purpose: {enriched.semantic.purpose}")
        print(f"  Confidence: {enriched.semantic.confidence}")
