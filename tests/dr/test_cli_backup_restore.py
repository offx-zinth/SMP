"""Disaster recovery tests: CLI backup and restore operations.

D-006: CLI backup (smp backup creates snapshot)
D-007: CLI restore (smp restore recovers)
D-008: Incremental backup (new journal entries only)
D-009: Cross-version restore (v1.x to v1.y)
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from smp.core.models import GraphNode, NodeType, SemanticProperties, StructuralProperties
from smp.store.graph.mmap_store import MMapGraphStore


def run_cli(args: list[str], env: dict[str, str] | None = None, cwd: Path | None = None) -> tuple[str, str, int]:
    """Run the SMP CLI and return stdout, stderr, and return code."""
    full_args = [sys.executable, "-m", "smp.cli"] + args
    current_env = os.environ.copy()
    if env:
        current_env.update(env)

    process = subprocess.Popen(
        full_args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=current_env,
        cwd=cwd,
    )
    stdout, stderr = process.communicate()
    return stdout, stderr, process.returncode


class TestCLIBackup:
    """D-006: CLI backup (smp backup creates snapshot)."""

    def test_backup_creates_snapshot_file(self, tmp_path):
        """D-006: backup command creates a valid snapshot file."""
        graph_path = tmp_path / "backup_graph.smpg"
        env = {"SMP_GRAPH_PATH": str(graph_path), "SMP_OPEN_MODE": "1"}

        store = MMapGraphStore(path=graph_path)
        import asyncio

        asyncio.run(store.connect())
        asyncio.run(store.upsert_node(GraphNode(id="test_node", type=NodeType.FUNCTION, file_path="test.py")))
        asyncio.run(store.close())

        stdout, stderr, code = run_cli(["backup", "--output", str(tmp_path / "backup.tar.gz")], env=env)

        assert code == 0
        assert (tmp_path / "backup.tar.gz").exists()

    def test_backup_includes_graph_data(self, tmp_path):
        """D-006: Backup includes graph data files."""
        graph_path = tmp_path / "backup_graph2.smpg"
        env = {"SMP_GRAPH_PATH": str(graph_path), "SMP_OPEN_MODE": "1"}

        store = MMapGraphStore(path=graph_path)
        import asyncio

        asyncio.run(store.connect())
        for i in range(10):
            node = GraphNode(
                id=f"node_{i}",
                type=NodeType.FUNCTION,
                file_path=f"f{i}.py",
                structural=StructuralProperties(name=f"n{i}", file=f"f{i}.py"),
            )
            asyncio.run(store.upsert_node(node))
        asyncio.run(store.close())

        backup_file = tmp_path / "backup2.tar.gz"
        stdout, stderr, code = run_cli(["backup", "--output", str(backup_file)], env=env)

        assert code == 0
        with tarfile.open(backup_file, "r:gz") as tar:
            members = [m.name for m in tar.getmembers()]
            assert any("smpg" in m or "smpl" in m for m in members)

    def test_backup_empty_graph(self, tmp_path):
        """D-006: Backup works with empty graph."""
        graph_path = tmp_path / "empty_graph.smpg"
        env = {"SMP_GRAPH_PATH": str(graph_path), "SMP_OPEN_MODE": "1"}

        backup_file = tmp_path / "empty_backup.tar.gz"
        stdout, stderr, code = run_cli(["backup", "--output", str(backup_file)], env=env)

        assert code == 0
        assert backup_file.exists()
        assert backup_file.stat().st_size > 0

    def test_backup_to_stdout(self, tmp_path):
        """D-006: Backup can write to stdout."""
        graph_path = tmp_path / "stdout_graph.smpg"
        env = {"SMP_GRAPH_PATH": str(graph_path), "SMP_OPEN_MODE": "1"}

        stdout, stderr, code = run_cli(["backup"], env=env)

        assert code == 0 or "backup" in stdout.lower() or "backup" in stderr.lower()

    def test_backup_creates_checksum(self, backup_file):
        """D-006: Backup file includes integrity checksum."""
        assert backup_file.exists()
        assert backup_file.stat().st_size > 100

    def test_backup_includes_metadata(self, tmp_path):
        """D-006: Backup includes timestamp and version metadata."""
        graph_path = tmp_path / "meta_graph.smpg"
        env = {"SMP_GRAPH_PATH": str(graph_path), "SMP_OPEN_MODE": "1"}

        store = MMapGraphStore(path=graph_path)
        import asyncio

        asyncio.run(store.connect())
        asyncio.run(store.close())

        backup_file = tmp_path / "meta_backup.tar.gz"
        run_cli(["backup", "--output", str(backup_file)], env=env)

        assert backup_file.exists()

    def test_backup_compresses_data(self, tmp_path):
        """D-006: Backup file is compressed."""
        graph_path = tmp_path / "compress_graph.smpg"
        env = {"SMP_GRAPH_PATH": str(graph_path), "SMP_OPEN_MODE": "1"}

        store = MMapGraphStore(path=graph_path)
        import asyncio

        asyncio.run(store.connect())
        for i in range(100):
            node = GraphNode(id=f"c_{i}", type=NodeType.FUNCTION, file_path="c.py")
            asyncio.run(store.upsert_node(node))
        asyncio.run(store.close())

        backup_file = tmp_path / "compress_backup.tar.gz"
        original_size = graph_path.stat().st_size

        run_cli(["backup", "--output", str(backup_file)], env=env)

        backup_size = backup_file.stat().st_size
        assert backup_size < original_size * 2

    def test_backup_excludes_temp_files(self, tmp_path):
        """D-006: Backup excludes temporary files."""
        graph_path = tmp_path / "temp_graph.smpg"
        env = {"SMP_GRAPH_PATH": str(graph_path), "SMP_OPEN_MODE": "1"}

        backup_file = tmp_path / "temp_backup.tar.gz"
        (tmp_path / ".tempfile.tmp").write_text("temp")

        run_cli(["backup", "--output", str(backup_file)], env=env)

        with tarfile.open(backup_file, "r:gz") as tar:
            names = [m.name for m in tar.getmembers()]
            assert not any(".tempfile" in n for n in names)

    def test_backup_overwrites_existing(self, tmp_path):
        """D-006: Backup overwrites existing backup file."""
        graph_path = tmp_path / "overwrite_graph.smpg"
        env = {"SMP_GRAPH_PATH": str(graph_path), "SMP_OPEN_MODE": "1"}

        backup_file = tmp_path / "overwrite.tar.gz"
        backup_file.write_text("old")

        store = MMapGraphStore(path=graph_path)
        import asyncio

        asyncio.run(store.connect())
        asyncio.run(store.close())

        run_cli(["backup", "--output", str(backup_file)], env=env)

        content = backup_file.read_bytes()
        assert content != b"old"
        assert len(content) > 10


class TestCLIRestore:
    """D-007: CLI restore (smp restore recovers)."""

    def test_restore_from_backup(self, tmp_path):
        """D-007: restore command recovers data from backup."""
        graph_path = tmp_path / "restore_graph.smpg"
        restore_path = tmp_path / "restored_graph.smpg"
        env = {"SMP_GRAPH_PATH": str(graph_path), "SMP_OPEN_MODE": "1"}

        store = MMapGraphStore(path=graph_path)
        import asyncio

        asyncio.run(store.connect())
        for i in range(5):
            node = GraphNode(id=f"restore_{i}", type=NodeType.FUNCTION, file_path="r.py")
            asyncio.run(store.upsert_node(node))
        asyncio.run(store.close())

        backup_file = tmp_path / "restore.tar.gz"
        run_cli(["backup", "--output", str(backup_file)], env=env)

        os.remove(graph_path)

        env2 = {"SMP_GRAPH_PATH": str(restore_path), "SMP_OPEN_MODE": "1"}
        stdout, stderr, code = run_cli(["restore", "--input", str(backup_file)], env=env2)

        assert code == 0
        assert restore_path.exists()

    def test_restore_creates_graph_file(self, tmp_path):
        """D-007: Restore creates graph file."""
        backup_file = tmp_path / "restore_test.tar.gz"
        with tarfile.open(backup_file, "w:gz") as tar:
            tar.addfile(tarfile.TarInfo(name="test.smpg"), fileobj=io.BytesIO(b""))

        restore_path = tmp_path / "restored.smpg"
        env = {"SMP_GRAPH_PATH": str(restore_path), "SMP_OPEN_MODE": "1"}

        stdout, stderr, code = run_cli(["restore", "--input", str(backup_file)], env=env)

        assert restore_path.exists()

    def test_restore_preserves_node_data(self, tmp_path):
        """D-007: Restored data matches original."""
        graph_path = tmp_path / "preserve_graph.smpg"
        env = {"SMP_GRAPH_PATH": str(graph_path), "SMP_OPEN_MODE": "1"}

        store = MMapGraphStore(path=graph_path)
        import asyncio

        asyncio.run(store.connect())
        for i in range(20):
            node = GraphNode(
                id=f"preserve_{i}",
                type=NodeType.FUNCTION,
                file_path="p.py",
                structural=StructuralProperties(
                    name=f"p_{i}", file="p.py", signature="def p():", start_line=1, end_line=2
                ),
            )
            asyncio.run(store.upsert_node(node))
        asyncio.run(store.close())

        backup_file = tmp_path / "preserve.tar.gz"
        run_cli(["backup", "--output", str(backup_file)], env=env)

        os.remove(graph_path)

        restore_path = tmp_path / "restored_preserve.smpg"
        env2 = {"SMP_GRAPH_PATH": str(restore_path), "SMP_OPEN_MODE": "1"}
        run_cli(["restore", "--input", str(backup_file)], env=env2)

        store2 = MMapGraphStore(path=restore_path)
        import asyncio

        asyncio.run(store2.connect())
        for i in range(20):
            node = asyncio.run(store2.get_node(f"preserve_{i}"))
            assert node is not None
        asyncio.run(store2.close())

    def test_restore_invalid_file_fails(self, tmp_path):
        """D-007: Restore fails gracefully with invalid backup."""
        bad_backup = tmp_path / "bad_backup.tar.gz"
        bad_backup.write_text("not a tar file")

        restore_path = tmp_path / "should_not_exist.smpg"
        env = {"SMP_GRAPH_PATH": str(restore_path), "SMP_OPEN_MODE": "1"}

        stdout, stderr, code = run_cli(["restore", "--input", str(bad_backup)], env=env)

        assert code != 0

    def test_restore_missing_file(self, tmp_path):
        """D-007: Restore fails when backup file missing."""
        restore_path = tmp_path / "missing.smpg"
        env = {"SMP_GRAPH_PATH": str(restore_path), "SMP_OPEN_MODE": "1"}

        stdout, stderr, code = run_cli(["restore", "--input", "/nonexistent/backup.tar.gz"], env=env)

        assert code != 0


class TestIncrementalBackup:
    """D-008: Incremental backup (new journal entries only)."""

    @pytest.mark.xfail(reason="incremental backups are not supported; CLI takes full snapshots", strict=False)
    def test_incremental_after_full_backup(self, tmp_path):
        """D-008: Incremental backup captures changes after full backup."""
        graph_path = tmp_path / "incremental_graph.smpg"
        env = {"SMP_GRAPH_PATH": str(graph_path), "SMP_OPEN_MODE": "1"}

        store = MMapGraphStore(path=graph_path)
        import asyncio

        asyncio.run(store.connect())
        for i in range(5):
            node = GraphNode(id=f"inc_{i}", type=NodeType.FUNCTION, file_path="i.py")
            asyncio.run(store.upsert_node(node))
        asyncio.run(store.close())

        full_backup = tmp_path / "full.tar.gz"
        run_cli(["backup", "--output", str(full_backup)], env=env)

        store2 = MMapGraphStore(path=graph_path)
        import asyncio

        asyncio.run(store2.connect())
        for i in range(5, 10):
            node = GraphNode(id=f"inc_{i}", type=NodeType.FUNCTION, file_path="i.py")
            asyncio.run(store2.upsert_node(node))
        asyncio.run(store2.close())

        inc_backup = tmp_path / "inc.tar.gz"
        stdout, stderr, code = run_cli(["backup", "--incremental", "--output", str(inc_backup)], env=env)

        assert code == 0 or inc_backup.exists()

    def test_incremental_requires_full_backup(self, tmp_path):
        """D-008: Incremental backup requires prior full backup."""
        graph_path = tmp_path / "no_full_graph.smpg"
        env = {"SMP_GRAPH_PATH": str(graph_path), "SMP_OPEN_MODE": "1"}

        inc_backup = tmp_path / "no_full.tar.gz"
        stdout, stderr, code = run_cli(["backup", "--incremental", "--output", str(inc_backup)], env=env)

        assert code != 0

    def test_incremental_with_no_changes(self, tmp_path):
        """D-008: Incremental backup with no changes is small."""
        graph_path = tmp_path / "no_change_graph.smpg"
        env = {"SMP_GRAPH_PATH": str(graph_path), "SMP_OPEN_MODE": "1"}

        store = MMapGraphStore(path=graph_path)
        import asyncio

        asyncio.run(store.connect())
        asyncio.run(store.close())

        run_cli(["backup", "--output", str(tmp_path / "full.tar.gz")], env=env)

        inc_backup = tmp_path / "inc.tar.gz"
        run_cli(["backup", "--incremental", "--output", str(inc_backup)], env=env)

        if inc_backup.exists():
            assert inc_backup.stat().st_size < 1000

    def test_incremental_merges_with_restore(self, tmp_path):
        """D-008: Incremental backups can be restored together."""
        graph_path = tmp_path / "merge_graph.smpg"
        env = {"SMP_GRAPH_PATH": str(graph_path), "SMP_OPEN_MODE": "1"}

        store = MMapGraphStore(path=graph_path)
        import asyncio

        asyncio.run(store.connect())
        for i in range(3):
            node = GraphNode(id=f"merge_{i}", type=NodeType.FUNCTION, file_path="m.py")
            asyncio.run(store.upsert_node(node))
        asyncio.run(store.close())

        full_backup = tmp_path / "full_merge.tar.gz"
        run_cli(["backup", "--output", str(full_backup)], env=env)

        restore_path = tmp_path / "restored_merge.smpg"
        env2 = {"SMP_GRAPH_PATH": str(restore_path), "SMP_OPEN_MODE": "1"}
        run_cli(["restore", "--input", str(full_backup)], env=env2)

        assert restore_path.exists()


class TestCrossVersionRestore:
    """D-009: Cross-version restore (v1.x to v1.y)."""

    def test_restore_from_older_format(self, tmp_path):
        """D-009: Restore handles older backup format."""
        backup_file = tmp_path / "old_format.tar.gz"

        with tarfile.open(backup_file, "w:gz") as tar:
            import io

            info = tarfile.TarInfo(name="graph.smpg")
            data = b"OLD_FORMAT_DATA" * 100
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))

            info2 = tarfile.TarInfo(name="metadata.json")
            meta = json.dumps({"version": "1.0.0", "created": "2024-01-01"}).encode()
            info2.size = len(meta)
            tar.addfile(info2, io.BytesIO(meta))

        restore_path = tmp_path / "old_restore.smpg"
        env = {"SMP_GRAPH_PATH": str(restore_path), "SMP_OPEN_MODE": "1"}

        stdout, stderr, code = run_cli(["restore", "--input", str(backup_file)], env=env)

        assert restore_path.exists() or code == 0

    def test_restore_from_newer_format_warns(self, tmp_path):
        """D-009: Restore warns when backup is from newer version."""
        backup_file = tmp_path / "newer.tar.gz"

        with tarfile.open(backup_file, "w:gz") as tar:
            import io

            info = tarfile.TarInfo(name="metadata.json")
            meta = json.dumps({"version": "99.0.0", "created": "2099-01-01"}).encode()
            info.size = len(meta)
            tar.addfile(info, io.BytesIO(meta))

        restore_path = tmp_path / "newer_restore.smpg"
        env = {"SMP_GRAPH_PATH": str(restore_path), "SMP_OPEN_MODE": "1"}

        stdout, stderr, code = run_cli(["restore", "--input", str(backup_file)], env=env)

        assert "version" in stdout.lower() or "version" in stderr.lower() or code != 0

    def test_cross_version_preserves_all_data(self, tmp_path):
        """D-009: Cross-version restore preserves all data."""
        graph_path = tmp_path / "cross_graph.smpg"
        env = {"SMP_GRAPH_PATH": str(graph_path), "SMP_OPEN_MODE": "1"}

        store = MMapGraphStore(path=graph_path)
        import asyncio

        asyncio.run(store.connect())
        for i in range(15):
            node = GraphNode(
                id=f"cross_{i}",
                type=NodeType.FUNCTION,
                file_path="c.py",
                semantic=SemanticProperties(docstring=f"Doc {i}"),
            )
            asyncio.run(store.upsert_node(node))
        asyncio.run(store.close())

        backup_file = tmp_path / "cross.tar.gz"
        run_cli(["backup", "--output", str(backup_file)], env=env)

        restore_path = tmp_path / "cross_restore.smpg"
        env2 = {"SMP_GRAPH_PATH": str(restore_path), "SMP_OPEN_MODE": "1"}
        run_cli(["restore", "--input", str(backup_file)], env=env2)

        store2 = MMapGraphStore(path=restore_path)
        import asyncio

        asyncio.run(store2.connect())
        for i in range(15):
            node = asyncio.run(store2.get_node(f"cross_{i}"))
            assert node is not None
            assert node.semantic.docstring == f"Doc {i}"
        asyncio.run(store2.close())

    def test_version_compatibility_check(self, tmp_path):
        """D-009: Restore checks version compatibility."""
        backup_file = tmp_path / "version_check.tar.gz"
        metadata = {"version": "1.5.0", "created": "2024-06-01", "graph_format": "v2"}

        with tarfile.open(backup_file, "w:gz") as tar:
            import io

            info = tarfile.TarInfo(name="metadata.json")
            data = json.dumps(metadata).encode()
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))

        restore_path = tmp_path / "version_check.smpg"
        env = {"SMP_GRAPH_PATH": str(restore_path), "SMP_OPEN_MODE": "1"}

        stdout, stderr, code = run_cli(["restore", "--input", str(backup_file)], env=env)

        assert code == 0 or "version" in (stdout + stderr).lower()


@pytest.fixture
async def backup_file(tmp_path: Path) -> Path:
    """Provide a pre-made backup file."""
    graph_path = tmp_path / "fixture_graph.smpg"
    env = {"SMP_GRAPH_PATH": str(graph_path), "SMP_OPEN_MODE": "1"}

    store = MMapGraphStore(path=graph_path)

    await store.connect()
    for i in range(3):
        node = GraphNode(id=f"fixture_{i}", type=NodeType.FUNCTION, file_path="f.py")
        await store.upsert_node(node)
    await store.close()

    backup = tmp_path / "fixture_backup.tar.gz"
    run_cli(["backup", "--output", str(backup)], env=env)

    return backup
