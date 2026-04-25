import pytest
from smp.core.models import EdgeType, GraphEdge, GraphNode, NodeType, SemanticProperties, StructuralProperties
from smp.store.graph.mmap_store import MMapGraphStore


@pytest.mark.asyncio
async def test_mmap_store_lifecycle(tmp_path):
    db_path = tmp_path / "test.smpg"
    store = MMapGraphStore(db_path)

    await store.connect()
    assert db_path.exists()

    await store.close()


@pytest.mark.asyncio
async def test_mmap_store_upsert_node(tmp_path):
    db_path = tmp_path / "test.smpg"
    store = MMapGraphStore(db_path)
    await store.connect()

    node = GraphNode(
        id="test.py::Function::test_func::10",
        type=NodeType.FUNCTION,
        file_path="test.py",
        structural=StructuralProperties(
            name="test_func",
            file="test.py",
            signature="def test_func():",
            start_line=10,
            end_line=12,
        ),
    )

    await store.upsert_node(node)

    await store.close()


@pytest.mark.asyncio
async def test_mmap_store_crud(tmp_path):
    db_path = tmp_path / "test.smpg"
    store = MMapGraphStore(db_path)
    await store.connect()

    node1 = GraphNode(
        id="a::Function::f1::1",
        type=NodeType.FUNCTION,
        file_path="a.py",
        structural=StructuralProperties(name="f1", file="a.py", signature="def f1():", start_line=1, end_line=2),
    )
    node2 = GraphNode(
        id="a::Function::f2::10",
        type=NodeType.FUNCTION,
        file_path="a.py",
        structural=StructuralProperties(name="f2", file="a.py", signature="def f2():", start_line=10, end_line=12),
    )
    node3 = GraphNode(
        id="b::Class::C::1",
        type=NodeType.CLASS,
        file_path="b.py",
        structural=StructuralProperties(name="C", file="b.py", signature="class C", start_line=1, end_line=5),
    )

    await store.upsert_nodes([node1, node2, node3])

    assert await store.count_nodes() == 3
    assert await store.get_node("a::Function::f1::1") == node1
    assert await store.get_node("nonexistent") is None

    edge = GraphEdge(
        source_id="a::Function::f1::1",
        target_id="a::Function::f2::10",
        type=EdgeType.CALLS,
    )
    await store.upsert_edge(edge)
    assert await store.count_edges() == 1

    edges = await store.get_edges("a::Function::f1::1")
    assert len(edges) == 1
    assert edges[0].target_id == "a::Function::f2::10"

    await store.close()


@pytest.mark.asyncio
async def test_mmap_store_traverse(tmp_path):
    db_path = tmp_path / "test.smpg"
    store = MMapGraphStore(db_path)
    await store.connect()

    nodes = [
        GraphNode(
            id="a::Function::main::1",
            type=NodeType.FUNCTION,
            file_path="a.py",
            structural=StructuralProperties(
                name="main", file="a.py", signature="def main():", start_line=1, end_line=2
            ),
        ),
        GraphNode(
            id="a::Function::helper::10",
            type=NodeType.FUNCTION,
            file_path="a.py",
            structural=StructuralProperties(
                name="helper", file="a.py", signature="def helper():", start_line=10, end_line=12
            ),
        ),
        GraphNode(
            id="a::Function::deep::20",
            type=NodeType.FUNCTION,
            file_path="a.py",
            structural=StructuralProperties(
                name="deep", file="a.py", signature="def deep():", start_line=20, end_line=22
            ),
        ),
    ]
    await store.upsert_nodes(nodes)

    await store.upsert_edge(
        GraphEdge(
            source_id="a::Function::main::1",
            target_id="a::Function::helper::10",
            type=EdgeType.CALLS,
        )
    )
    await store.upsert_edge(
        GraphEdge(
            source_id="a::Function::helper::10",
            target_id="a::Function::deep::20",
            type=EdgeType.CALLS,
        )
    )

    results = await store.traverse(
        "a::Function::main::1",
        EdgeType.CALLS,
        depth=2,
    )
    assert len(results) >= 2

    neighbors = await store.get_neighbors("a::Function::main::1", depth=1)
    assert len(neighbors) >= 1

    await store.close()


@pytest.mark.asyncio
async def test_mmap_store_find_nodes(tmp_path):
    db_path = tmp_path / "test.smpg"
    store = MMapGraphStore(db_path)
    await store.connect()

    await store.upsert_nodes(
        [
            GraphNode(
                id="a::Function::foo::1",
                type=NodeType.FUNCTION,
                file_path="a.py",
                structural=StructuralProperties(
                    name="foo", file="a.py", signature="def foo():", start_line=1, end_line=2
                ),
            ),
            GraphNode(
                id="a::Class::Foo::5",
                type=NodeType.CLASS,
                file_path="a.py",
                structural=StructuralProperties(
                    name="Foo", file="a.py", signature="class Foo", start_line=5, end_line=10
                ),
            ),
            GraphNode(
                id="b::Function::bar::1",
                type=NodeType.FUNCTION,
                file_path="b.py",
                structural=StructuralProperties(
                    name="bar", file="b.py", signature="def bar():", start_line=1, end_line=2
                ),
            ),
        ]
    )

    results = await store.find_nodes(type=NodeType.FUNCTION)
    assert len(results) == 2

    results = await store.find_nodes(file_path="a.py")
    assert len(results) == 2

    results = await store.find_nodes(name="foo")
    assert len(results) == 1

    await store.close()


@pytest.mark.asyncio
async def test_mmap_store_search_nodes(tmp_path):
    db_path = tmp_path / "test.smpg"
    store = MMapGraphStore(db_path)
    await store.connect()

    await store.upsert_nodes(
        [
            GraphNode(
                id="a::Function::get_user::1",
                type=NodeType.FUNCTION,
                file_path="a.py",
                structural=StructuralProperties(
                    name="get_user",
                    file="a.py",
                    signature="def get_user():",
                    start_line=1,
                    end_line=10,
                ),
                semantic=SemanticProperties(docstring="Get a user by ID"),
            ),
            GraphNode(
                id="a::Function::create_user::15",
                type=NodeType.FUNCTION,
                file_path="a.py",
                structural=StructuralProperties(
                    name="create_user",
                    file="a.py",
                    signature="def create_user():",
                    start_line=15,
                    end_line=25,
                ),
                semantic=SemanticProperties(docstring="Create a new user"),
            ),
        ]
    )

    results = await store.search_nodes(["user"])
    assert len(results) == 2
    assert all("user" in r["name"].lower() for r in results)

    await store.close()
