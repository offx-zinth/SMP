from __future__ import annotations

import pytest

from smp.core.models import GraphNode, NodeType, SemanticProperties, StructuralProperties

# Encryption-at-rest is a known unimplemented control: the journal is
# msgpack plaintext by design (see SPEC.md). These tests document the
# requirement and are expected to fail until the feature lands.
pytestmark = pytest.mark.xfail(reason="encryption-at-rest not implemented", strict=False)


@pytest.mark.asyncio
async def test_data_at_rest_encryption(graph_store, tmp_path):
    """C-001: Verify that data at rest is encrypted.

    This test writes a known string to the graph and checks if that
    string exists in plaintext in the underlying file.
    """
    secret_text = "SUPER_SECRET_DATA_12345"
    node = GraphNode(
        id="secret_node",
        type=NodeType.FUNCTION,
        file_path="secret.py",
        structural=StructuralProperties(
            name=secret_text, file="secret.py", signature="", start_line=0, end_line=0, lines=0
        ),
        semantic=SemanticProperties(docstring=secret_text, status="enriched"),
    )
    await graph_store.upsert_node(node)
    await graph_store.flush()

    file_path = graph_store.path
    content = file_path.read_bytes()

    assert secret_text.encode() not in content, "Sensitive data found in plaintext on disk"


@pytest.mark.asyncio
async def test_encryption_key_not_in_plaintext(graph_store, clean_graph):
    """C-001: Verify encryption keys are not stored in plaintext."""
    secret_key = "ENCRYPTION_KEY_ABC123"
    node = GraphNode(
        id="key_node",
        type=NodeType.VARIABLE,
        file_path="config.py",
        structural=StructuralProperties(name=secret_key, file="config.py"),
        semantic=SemanticProperties(docstring=f"key={secret_key}"),
    )
    await graph_store.upsert_node(node)
    await graph_store.flush()

    content = graph_store.path.read_bytes()
    assert secret_key.encode() not in content


@pytest.mark.asyncio
async def test_encrypted_docstring_not_readable(graph_store, clean_graph):
    """C-001: Verify docstrings are not stored in plaintext."""
    sensitive_doc = "This doc contains API_KEY=sk_live_123456789"
    node = GraphNode(
        id="doc_node",
        type=NodeType.FUNCTION,
        file_path="api.py",
        structural=StructuralProperties(name="fetch_data", file="api.py"),
        semantic=SemanticProperties(docstring=sensitive_doc, status="enriched"),
    )
    await graph_store.upsert_node(node)
    await graph_store.flush()

    content = graph_store.path.read_bytes()
    assert b"API_KEY=" not in content
    assert b"sk_live_" not in content


@pytest.mark.asyncio
async def test_multiple_sensitive_nodes_encrypted(graph_store, clean_graph):
    """C-001: Verify multiple sensitive nodes are encrypted."""
    secrets = ["secret_a", "secret_b", "secret_c"]
    for i, secret in enumerate(secrets):
        node = GraphNode(
            id=f"node_{i}",
            type=NodeType.VARIABLE,
            file_path="secrets.py",
            structural=StructuralProperties(name=secret, file="secrets.py"),
            semantic=SemanticProperties(docstring=secret),
        )
        await graph_store.upsert_node(node)
    await graph_store.flush()

    content = graph_store.path.read_bytes()
    for secret in secrets:
        assert secret.encode() not in content


@pytest.mark.asyncio
async def test_large_data_encrypted(graph_store, clean_graph):
    """C-001: Verify large data payloads are encrypted."""
    large_secret = "x" * 10000
    node = GraphNode(
        id="large_node",
        type=NodeType.FILE,
        file_path="large.bin",
        structural=StructuralProperties(file="large.bin", lines=10000),
        semantic=SemanticProperties(description=large_secret),
    )
    await graph_store.upsert_node(node)
    await graph_store.flush()

    content = graph_store.path.read_bytes()
    assert "x" * 1000 not in content.decode("utf-8", errors="ignore")


@pytest.mark.asyncio
async def test_special_characters_encrypted(graph_store, clean_graph):
    """C-001: Verify special characters in sensitive data are encrypted."""
    special_data = "pass!@#$%^&*()+=123"
    node = GraphNode(
        id="special_node",
        type=NodeType.VARIABLE,
        file_path="auth.py",
        structural=StructuralProperties(name="password", file="auth.py"),
        semantic=SemanticProperties(docstring=special_data),
    )
    await graph_store.upsert_node(node)
    await graph_store.flush()

    content = graph_store.path.read_bytes()
    assert special_data.encode() not in content


@pytest.mark.asyncio
async def test_unicode_sensitive_data_encrypted(graph_store, clean_graph):
    """C-001: Verify unicode sensitive data is encrypted."""
    unicode_secret = "密码123SECRET"
    node = GraphNode(
        id="unicode_node",
        type=NodeType.VARIABLE,
        file_path="secure.py",
        structural=StructuralProperties(name="unicode_pass", file="secure.py"),
        semantic=SemanticProperties(docstring=unicode_secret),
    )
    await graph_store.upsert_node(node)
    await graph_store.flush()

    content = graph_store.path.read_bytes()
    assert unicode_secret.encode() not in content


@pytest.mark.asyncio
async def test_edge_metadata_encrypted(graph_store, clean_graph):
    """C-001: Verify edge metadata is encrypted."""
    from smp.core.models import EdgeType, GraphEdge

    sensitive_meta = {"token": "Bearer eyJhbGciOiJIUzI1NiJ9"}
    edge = GraphEdge(source_id="source", target_id="target", type=EdgeType.CALLS, metadata=sensitive_meta)
    await graph_store.upsert_edge(edge)
    await graph_store.flush()

    content = graph_store.path.read_bytes()
    assert b"Bearer" not in content


@pytest.mark.asyncio
async def test_nested_structure_encrypted(graph_store, clean_graph):
    """C-001: Verify nested data structures are encrypted."""
    nested_data = {"auth": {"token": "secret_token_xyz", "nested": {"key": "deep_secret"}}}
    node = GraphNode(
        id="nested_node",
        type=NodeType.CONFIG,
        file_path="config.json",
        structural=StructuralProperties(name="config", file="config.json"),
        semantic=SemanticProperties(description=str(nested_data), tags=["config", "auth"]),
    )
    await graph_store.upsert_node(node)
    await graph_store.flush()

    content = graph_store.path.read_bytes()
    assert b"secret_token_xyz" not in content
    assert b"deep_secret" not in content


@pytest.mark.asyncio
async def test_array_sensitive_data_encrypted(graph_store, clean_graph):
    """C-001: Verify array data with secrets is encrypted."""
    sensitive_array = ["api_key_1", "api_key_2", "api_key_3"]
    node = GraphNode(
        id="array_node",
        type=NodeType.VARIABLE,
        file_path="keys.py",
        structural=StructuralProperties(name="api_keys", file="keys.py"),
        semantic=SemanticProperties(description=str(sensitive_array), tags=sensitive_array),
    )
    await graph_store.upsert_node(node)
    await graph_store.flush()

    content = graph_store.path.read_bytes()
    for key in sensitive_array:
        assert key.encode() not in content


@pytest.mark.asyncio
async def test_update_encryption_preserved(graph_store, clean_graph):
    """C-001: Verify encryption is preserved after updates."""
    initial_secret = "original_secret"
    node = GraphNode(
        id="update_node",
        type=NodeType.VARIABLE,
        file_path="secret.py",
        structural=StructuralProperties(name="secret", file="secret.py"),
        semantic=SemanticProperties(docstring=initial_secret),
    )
    await graph_store.upsert_node(node)
    await graph_store.flush()

    updated_secret = "updated_secret_456"
    node.semantic.docstring = updated_secret
    await graph_store.upsert_node(node)
    await graph_store.flush()

    content = graph_store.path.read_bytes()
    assert updated_secret.encode() not in content
    assert initial_secret.encode() not in content


@pytest.mark.asyncio
async def test_delete_encryption_verification(graph_store, clean_graph):
    """C-001: Verify deleted data is fully removed."""
    secret = "DELETE_ME_SECRET"
    node = GraphNode(
        id="delete_node",
        type=NodeType.VARIABLE,
        file_path="temp.py",
        structural=StructuralProperties(name="temp", file="temp.py"),
        semantic=SemanticProperties(docstring=secret),
    )
    await graph_store.upsert_node(node)
    await graph_store.flush()

    await graph_store.delete_node("delete_node")
    await graph_store.flush()

    content = graph_store.path.read_bytes()
    assert secret.encode() not in content


@pytest.mark.asyncio
async def test_bulk_write_encryption(graph_store, clean_graph):
    """C-001: Verify bulk writes maintain encryption."""
    secrets = [f"bulk_secret_{i}" for i in range(50)]
    for i, secret in enumerate(secrets):
        node = GraphNode(
            id=f"bulk_{i}",
            type=NodeType.VARIABLE,
            file_path="bulk.py",
            structural=StructuralProperties(name=secret, file="bulk.py"),
            semantic=SemanticProperties(docstring=secret),
        )
        await graph_store.upsert_node(node)
    await graph_store.flush()

    content = graph_store.path.read_bytes()
    for secret in secrets[:5]:
        assert secret.encode() not in content


@pytest.mark.asyncio
async def test_concurrent_write_encryption(graph_store, clean_graph):
    """C-001: Verify concurrent writes maintain encryption."""

    async def write_node(i: int) -> None:
        secret = f"concurrent_secret_{i}"
        node = GraphNode(
            id=f"concurrent_{i}",
            type=NodeType.FUNCTION,
            file_path="concurrent.py",
            structural=StructuralProperties(name=f"func_{i}", file="concurrent.py"),
            semantic=SemanticProperties(docstring=secret),
        )
        await graph_store.upsert_node(node)

    import asyncio

    await asyncio.gather(*[write_node(i) for i in range(10)])
    await graph_store.flush()

    content = graph_store.path.read_bytes()
    assert b"concurrent_secret_" not in content


@pytest.mark.asyncio
async def test_empty_value_encryption(graph_store, clean_graph):
    """C-001: Verify empty values are handled correctly."""
    node = GraphNode(
        id="empty_node",
        type=NodeType.VARIABLE,
        file_path="empty.py",
        structural=StructuralProperties(name="empty", file="empty.py"),
        semantic=SemanticProperties(docstring=""),
    )
    await graph_store.upsert_node(node)
    await graph_store.flush()

    content = graph_store.path.read_bytes()
    assert len(content) > 0


@pytest.mark.asyncio
async def test_none_value_encryption(graph_store, clean_graph):
    """C-001: Verify None values are handled correctly."""
    node = GraphNode(
        id="none_node",
        type=NodeType.VARIABLE,
        file_path="none.py",
        structural=StructuralProperties(name="none", file="none.py"),
        semantic=SemanticProperties(description=None),
    )
    await graph_store.upsert_node(node)
    await graph_store.flush()

    content = graph_store.path.read_bytes()
    assert len(content) > 0


@pytest.mark.asyncio
async def test_whitespace_only_not_encrypted(graph_store, clean_graph):
    """C-001: Verify whitespace-only values handled correctly."""
    node = GraphNode(
        id="space_node",
        type=NodeType.VARIABLE,
        file_path="space.py",
        structural=StructuralProperties(name="space", file="space.py"),
        semantic=SemanticProperties(docstring="   "),
    )
    await graph_store.upsert_node(node)
    await graph_store.flush()

    content = graph_store.path.read_bytes()
    assert len(content) > 0


@pytest.mark.asyncio
async def test_binary_data_encryption(graph_store, clean_graph):
    """C-001: Verify binary-like data is encrypted."""
    binary_secret = b"\x00\x01\x02\x03\x04\x05\xff\xfe\xfd"
    node = GraphNode(
        id="binary_node",
        type=NodeType.VARIABLE,
        file_path="binary.py",
        structural=StructuralProperties(name="binary", file="binary.py"),
        semantic=SemanticProperties(description=binary_secret.decode("utf-8", errors="replace")),
    )
    await graph_store.upsert_node(node)
    await graph_store.flush()

    content = graph_store.path.read_bytes()
    assert b"\x00\x01\x02\x03" not in content


@pytest.mark.asyncio
async def test_mixed_content_encryption(graph_store, clean_graph):
    """C-001: Verify mixed content with sensitive and non-sensitive is encrypted."""
    mixed_content = "public_data SECRET_KEY=abc123 confidential"
    node = GraphNode(
        id="mixed_node",
        type=NodeType.FUNCTION,
        file_path="mixed.py",
        structural=StructuralProperties(name="process", file="mixed.py"),
        semantic=SemanticProperties(docstring=mixed_content),
    )
    await graph_store.upsert_node(node)
    await graph_store.flush()

    content = graph_store.path.read_bytes()
    assert b"SECRET_KEY=" not in content
    assert b"abc123" not in content
    assert b"public_data" in content or b"confidential" in content


@pytest.mark.asyncio
async def test_query_result_encryption(graph_store, clean_graph):
    """C-001: Verify query results don't expose sensitive data."""
    secret = "QUERY_SECRET_789"
    node = GraphNode(
        id="query_node",
        type=NodeType.FUNCTION,
        file_path="query.py",
        structural=StructuralProperties(name="search", file="query.py"),
        semantic=SemanticProperties(docstring=secret),
    )
    await graph_store.upsert_node(node)
    await graph_store.flush()

    await graph_store.query_nodes({"type": "Function"})

    content = graph_store.path.read_bytes()
    assert b"QUERY_SECRET_789" not in content


@pytest.mark.asyncio
async def test_semantic_enrichment_encryption(graph_store, clean_graph):
    """C-001: Verify enriched semantic data is encrypted."""
    node = GraphNode(
        id="enrich_node",
        type=NodeType.FUNCTION,
        file_path="enrich.py",
        structural=StructuralProperties(
            name="complex_function", file="enrich.py", signature="def complex_function(a, b, c)"
        ),
        semantic=SemanticProperties(
            status="enriched",
            docstring="Enriched with SEMANTIC_TOKEN=abc123xyz",
            description="This is an enriched function",
            score=0.95,
        ),
    )
    await graph_store.upsert_node(node)
    await graph_store.flush()

    content = graph_store.path.read_bytes()
    assert b"SEMANTIC_TOKEN=" not in content
    assert b"abc123xyz" not in content


@pytest.mark.asyncio
async def test_complex_fingerprint_encryption(graph_store, clean_graph):
    """C-001: Verify complex node fingerprints are encrypted."""
    node = GraphNode(
        id="complex_node",
        type=NodeType.CLASS,
        file_path="complex.py",
        structural=StructuralProperties(
            name="User", file="complex.py", signature="class User(BaseModel)", start_line=10, end_line=50
        ),
        semantic=SemanticProperties(status="enriched", docstring="User model with SECRET=password123"),
    )
    await graph_store.upsert_node(node)
    await graph_store.flush()

    content = graph_store.path.read_bytes()
    assert b"SECRET=" not in content
    assert b"password123" not in content


@pytest.mark.asyncio
async def test_encrypted_data_recovered(graph_store, clean_graph):
    """C-001: Verify encrypted data can be read correctly."""
    original_secret = "READABLE_SECRET_ABC"
    node = GraphNode(
        id="readable_node",
        type=NodeType.VARIABLE,
        file_path="readable.py",
        structural=StructuralProperties(name="secret", file="readable.py"),
        semantic=SemanticProperties(docstring=original_secret),
    )
    await graph_store.upsert_node(node)
    await graph_store.flush()

    retrieved = await graph_store.get_node("readable_node")
    assert retrieved is not None
    assert retrieved.semantic.docstring == original_secret
