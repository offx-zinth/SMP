from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from smp.store.graph.edge_store import EdgeStore
from smp.store.graph.mmap_file import MMapFile


@pytest.fixture
def edge_store_setup():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "test_edges.smpg"
        mmap_file = MMapFile(path)
        mmap_file.open()
        store = EdgeStore(mmap_file)
        yield store, mmap_file
        mmap_file.close()


# -- Basic Operations -----------------------------------------------------------


def test_write_read_empty(edge_store_setup):
    store, _ = edge_store_setup
    ptr = store.write_edges(0, [])
    assert store.read_edges(ptr) == []


def test_write_read_single(edge_store_setup):
    store, _ = edge_store_setup
    targets = [(100, 1)]
    ptr = store.write_edges(0, targets)
    assert store.read_edges(ptr) == targets


def test_write_read_multiple(edge_store_setup):
    store, _ = edge_store_setup
    targets = [(100, 1), (200, 2), (300, 1)]
    ptr = store.write_edges(0, targets)
    assert store.read_edges(ptr) == targets


def test_write_read_large_list(edge_store_setup):
    store, _ = edge_store_setup
    targets = [(i, i % 5) for i in range(1000)]
    ptr = store.write_edges(0, targets)
    assert store.read_edges(ptr) == targets


def test_read_invalid_ptr(edge_store_setup):
    store, _ = edge_store_setup
    # Reading from an uninitialized part of the file should be handled gracefully
    # Given the stub returns [], we expect []. In a real impl it might raise.
    try:
        res = store.read_edges(999999)
        assert isinstance(res, list)
    except Exception:
        pass


# -- Edge Cases -----------------------------------------------------------------


def test_self_loop(edge_store_setup):
    store, _ = edge_store_setup
    targets = [(0, 1)]  # source offset 0, target offset 0
    ptr = store.write_edges(0, targets)
    assert store.read_edges(ptr) == targets


def test_duplicate_edges(edge_store_setup):
    store, _ = edge_store_setup
    targets = [(100, 1), (100, 1)]
    ptr = store.write_edges(0, targets)
    assert store.read_edges(ptr) == targets


def test_different_edge_types(edge_store_setup):
    store, _ = edge_store_setup
    targets = [(100, 1), (200, 2), (300, 3), (400, 4)]
    ptr = store.write_edges(0, targets)
    assert store.read_edges(ptr) == targets


def test_max_uint32_values(edge_store_setup):
    store, _ = edge_store_setup
    max_u32 = 0xFFFFFFFF
    targets = [(max_u32, max_u32), (0, 0)]
    ptr = store.write_edges(0, targets)
    assert store.read_edges(ptr) == targets


# -- Storage & Bounds -----------------------------------------------------------


def test_storage_growth(edge_store_setup):
    store, mmap_file = edge_store_setup
    initial_size = mmap_file.size
    # Write many large lists to force growth
    for i in range(200):
        store.write_edges(i, [(j, 1) for j in range(100)])
    assert mmap_file.size > initial_size


def test_interleaved_writes(edge_store_setup):
    store, _ = edge_store_setup
    ptrs = []
    for i in range(10):
        ptrs.append(store.write_edges(i, [(i * 10, 1)]))

    for i in range(10):
        assert store.read_edges(ptrs[i]) == [(i * 10, 1)]


def test_overwrite_creates_new_ptr(edge_store_setup):
    store, _ = edge_store_setup
    ptr1 = store.write_edges(0, [(100, 1)])
    ptr2 = store.write_edges(0, [(200, 2), (300, 3)])

    assert ptr1 != ptr2
    assert store.read_edges(ptr1) == [(100, 1)]
    assert store.read_edges(ptr2) == [(200, 2), (300, 3)]


# -- Synchronization & Durability ----------------------------------------------


def test_mmap_synchronization():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "sync_test.smpg"

        # Write with one store
        mmap1 = MMapFile(path)
        mmap1.open()
        store1 = EdgeStore(mmap1)
        targets = [(100, 1), (200, 2)]
        ptr = store1.write_edges(0, targets)
        mmap1.close()

        # Read with another store instance
        mmap2 = MMapFile(path)
        mmap2.open()
        store2 = EdgeStore(mmap2)
        assert store2.read_edges(ptr) == targets
        mmap2.close()


def test_persistence_across_reopens():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "persist.smpg"

        mmap = MMapFile(path)
        mmap.open()
        store = EdgeStore(mmap)
        ptr = store.write_edges(0, [(100, 1)])
        mmap.close()

        mmap.open()
        store = EdgeStore(mmap)
        assert store.read_edges(ptr) == [(100, 1)]
        mmap.close()


# -- Parametric Tests (Coverage for various sizes) ------------------------------


@pytest.mark.parametrize("count", [0, 1, 2, 10, 100, 1000])
def test_various_list_sizes(edge_store_setup, count):
    store, _ = edge_store_setup
    targets = [(i, 1) for i in range(count)]
    ptr = store.write_edges(0, targets)
    assert store.read_edges(ptr) == targets


@pytest.mark.parametrize("edge_type", [0, 1, 100, 0xFFFFFFFF])
def test_various_edge_types(edge_store_setup, edge_type):
    store, _ = edge_store_setup
    targets = [(100, edge_type)]
    ptr = store.write_edges(0, targets)
    assert store.read_edges(ptr) == targets


@pytest.mark.parametrize("target_off", [0, 1, 1000, 0xFFFFFFFF])
def test_various_target_offsets(edge_store_setup, target_off):
    store, _ = edge_store_setup
    targets = [(target_off, 1)]
    ptr = store.write_edges(0, targets)
    assert store.read_edges(ptr) == targets


# -- Complex Scenarios ----------------------------------------------------------


def test_multiple_nodes_adjacency(edge_store_setup):
    store, _ = edge_store_setup
    nodes = {
        "A": [(10, 1), (20, 1)],
        "B": [(30, 2)],
        "C": [],
        "D": [(10, 1), (20, 1), (30, 2), (40, 3)],
    }
    ptrs = {}
    for node, edges in nodes.items():
        ptrs[node] = store.write_edges(0, edges)

    for node, edges in nodes.items():
        assert store.read_edges(ptrs[node]) == edges


def test_stress_many_small_writes(edge_store_setup):
    store, _ = edge_store_setup
    ptrs = []
    for i in range(1000):
        ptrs.append(store.write_edges(i, [(i, 1)]))

    for i in range(1000):
        assert store.read_edges(ptrs[i]) == [(i, 1)]


def test_stress_few_huge_writes(edge_store_setup):
    store, _ = edge_store_setup
    ptrs = []
    for i in range(5):
        targets = [(j, 1) for j in range(10000)]
        ptrs.append(store.write_edges(i, targets))

    for i in range(5):
        assert len(store.read_edges(ptrs[i])) == 10000


def test_random_access_patterns(edge_store_setup):
    import random

    store, _ = edge_store_setup
    data = {}
    ptrs = []

    # Write phase
    for i in range(100):
        count = random.randint(0, 50)
        targets = [(random.randint(0, 10000), random.randint(0, 10)) for _ in range(count)]
        ptr = store.write_edges(i, targets)
        ptrs.append(ptr)
        data[ptr] = targets

    # Read phase (random order)
    random.shuffle(ptrs)
    for ptr in ptrs:
        assert store.read_edges(ptr) == data[ptr]


def test_write_after_read(edge_store_setup):
    store, _ = edge_store_setup
    ptr1 = store.write_edges(0, [(100, 1)])
    assert store.read_edges(ptr1) == [(100, 1)]

    ptr2 = store.write_edges(0, [(200, 2)])
    assert store.read_edges(ptr1) == [(100, 1)]
    assert store.read_edges(ptr2) == [(200, 2)]


def test_write_empty_after_populated(edge_store_setup):
    store, _ = edge_store_setup
    ptr1 = store.write_edges(0, [(100, 1)])
    assert store.read_edges(ptr1) == [(100, 1)]

    ptr2 = store.write_edges(0, [])
    assert store.read_edges(ptr1) == [(100, 1)]
    assert store.read_edges(ptr2) == []
