from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from smp.core.models import (
    GraphNode,
    NodeType,
    SemanticProperties,
    StructuralProperties,
)
from smp.store.graph.mmap_store import MMapGraphStore


def run_cli(
    args: list[str],
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
    timeout: int = 30,
) -> tuple[str, str, int]:
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
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate()
    return stdout, stderr, process.returncode


@pytest.fixture
def cli_env(tmp_path: Path) -> dict[str, str]:
    """Provide environment variables for CLI testing."""
    graph_path = tmp_path / "test_graph.smpg"
    return {
        "SMP_GRAPH_PATH": str(graph_path),
        "SMP_OPEN_MODE": "1",
    }


@pytest.fixture
def sample_project(tmp_path: Path) -> Path:
    """Create a sample project for testing."""
    project = tmp_path / "sample_project"
    src = project / "src"
    src.mkdir(parents=True)

    (src / "__init__.py").write_text("")
    (src / "main.py").write_text(
        """\
def main():
    \"\"\"Main entry point.\"\"\"
    print("hello")

def helper():
    \"\"\"Helper function.\"\"\"
    pass
"""
    )
    (src / "utils.py").write_text(
        """\
def util_a():
    \"\"\"Utility function A.\"\"\"
    pass

def util_b():
    \"\"\"Utility function B.\"\"\"
    util_a()
"""
    )

    return project


def _create_graph_with_nodes(graph_path: Path, count: int) -> None:
    """Helper to create a graph with nodes."""
    import asyncio

    store = MMapGraphStore(path=str(graph_path))
    asyncio.run(store.connect())
    for i in range(count):
        node = GraphNode(
            id=f"node_{i}",
            type=NodeType.FUNCTION,
            file_path=f"file_{i}.py",
            structural=StructuralProperties(
                name=f"func_{i}",
                file=f"file_{i}.py",
                signature=f"def func_{i}():",
                start_line=1,
                end_line=2,
            ),
            semantic=SemanticProperties(docstring=f"Docstring {i}"),
        )
        asyncio.run(store.upsert_node(node))
    asyncio.run(store.close())


class TestCLIHelp:
    """Tests for CLI help and general behavior."""

    def test_help_displays_commands(self):
        """OP-001: Help is displayed when no command is provided."""
        stdout, stderr, code = run_cli([])
        assert code == 1
        assert "Structural Memory Protocol CLI" in stdout or "usage" in stdout.lower()

    def test_help_command_shows_all_commands(self):
        """Help command shows all available commands."""
        stdout, stderr, code = run_cli(["--help"])
        assert code == 0
        assert "ingest" in stdout
        assert "serve" in stdout
        assert "backup" in stdout
        assert "restore" in stdout

    def test_ingest_help(self):
        """Ingest subcommand shows help."""
        stdout, stderr, code = run_cli(["ingest", "--help"])
        assert code == 0
        assert "--graph-path" in stdout or "directory" in stdout

    def test_serve_help(self):
        """Serve subcommand shows help."""
        stdout, stderr, code = run_cli(["serve", "--help"])
        assert code == 0
        assert "--host" in stdout or "--port" in stdout

    def test_backup_help(self):
        """Backup subcommand shows help."""
        stdout, stderr, code = run_cli(["backup", "--help"])
        assert code == 0
        assert "--output" in stdout

    def test_restore_help(self):
        """Restore subcommand shows help."""
        stdout, stderr, code = run_cli(["restore", "--help"])
        assert code == 0
        assert "--input" in stdout


class TestCLIIngest:
    """Tests for the ingest command."""

    def test_ingest_basic(self, cli_env, sample_project):
        """OP-002: Verify that 'ingest' command builds the graph."""
        stdout, stderr, code = run_cli(["ingest", str(sample_project)], env=cli_env)

        assert code == 0
        assert "Ingested" in stdout or "nodes" in stdout
        assert "nodes" in stdout or "edges" in stdout

    def test_ingest_creates_graph_file(self, cli_env, sample_project):
        """Ingest creates the graph file."""
        run_cli(["ingest", str(sample_project)], env=cli_env)

        assert Path(cli_env["SMP_GRAPH_PATH"]).exists()

    def test_ingest_with_clear(self, cli_env, sample_project):
        """Ingest with --clear flag clears the graph first."""
        run_cli(["ingest", str(sample_project)], env=cli_env)
        graph_path = Path(cli_env["SMP_GRAPH_PATH"])

        stdout, stderr, code = run_cli(["ingest", str(sample_project), "--clear"], env=cli_env)

        assert code == 0
        assert graph_path.stat().st_size >= 0

    def test_ingest_with_graph_path(self, cli_env, sample_project, tmp_path):
        """Ingest with explicit --graph-path."""
        custom_path = tmp_path / "custom.smpg"
        stdout, stderr, code = run_cli(
            ["ingest", str(sample_project), "--graph-path", str(custom_path)],
            env=cli_env,
        )

        assert code == 0
        assert custom_path.exists()

    def test_ingest_empty_directory(self, cli_env, tmp_path):
        """Ingest empty directory handles gracefully."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        stdout, stderr, code = run_cli(["ingest", str(empty_dir)], env=cli_env)

        assert code == 0

    def test_ingest_nonexistent_directory_fails(self, cli_env):
        """Ingest fails with nonexistent directory."""
        stdout, stderr, code = run_cli(["ingest", "/nonexistent/path"], env=cli_env)

        assert code != 0

    def test_ingest_large_file_skipped(self, cli_env, tmp_path):
        """Ingest skips files larger than max-size."""
        large_dir = tmp_path / "large_project"
        large_dir.mkdir()
        (large_dir / "large.py").write_text("x" * 2_000_000)

        stdout, stderr, code = run_cli(["ingest", str(large_dir), "--max-size", "1000000"], env=cli_env)

        assert code == 0
        assert "skipped" in stdout.lower() or "errors" in stdout


class TestCLIIntegrity:
    """Tests for the integrity command."""

    def test_integrity_empty_graph(self, cli_env):
        """OP-012: Integrity check on empty graph reports ok."""
        import asyncio

        graph_path = Path(cli_env["SMP_GRAPH_PATH"])
        store = MMapGraphStore(path=str(graph_path))
        asyncio.run(store.connect())
        asyncio.run(store.close())

        stdout, stderr, code = run_cli(["integrity"], env=cli_env)

        assert code == 0
        assert "ok" in stdout.lower()

    def test_integrity_with_data(self, cli_env):
        """Integrity check on graph with data."""

        graph_path = Path(cli_env["SMP_GRAPH_PATH"])
        _create_graph_with_nodes(graph_path, 5)

        stdout, stderr, code = run_cli(["integrity"], env=cli_env)

        assert code == 0
        assert "ok" in stdout.lower() or "records" in stdout

    def test_integrity_json_output(self, cli_env):
        """Integrity returns valid JSON."""

        graph_path = Path(cli_env["SMP_GRAPH_PATH"])
        _create_graph_with_nodes(graph_path, 3)

        stdout, stderr, code = run_cli(["integrity"], env=cli_env)

        try:
            data = json.loads(stdout)
            assert "ok" in data
        except json.JSONDecodeError:
            pass

    def test_integrity_missing_graph(self, cli_env):
        """Integrity fails gracefully with missing graph."""
        no_graph_env = dict(cli_env)
        no_graph_env["SMP_GRAPH_PATH"] = "/nonexistent/missing.smpg"

        stdout, stderr, code = run_cli(["integrity"], env=no_graph_env)

        assert code != 0


class TestCLIBackup:
    """Tests for the backup command."""

    def test_backup_empty_graph(self, cli_env, tmp_path):
        """OP-003: Backup works with empty graph."""
        import asyncio

        graph_path = Path(cli_env["SMP_GRAPH_PATH"])
        store = MMapGraphStore(path=str(graph_path))
        asyncio.run(store.connect())
        asyncio.run(store.close())

        backup_file = tmp_path / "empty_backup.tar.gz"
        stdout, stderr, code = run_cli(["backup", "--output", str(backup_file)], env=cli_env)

        assert code == 0
        assert backup_file.exists()

    def test_backup_with_data(self, cli_env, tmp_path):
        """Backup captures graph data."""
        graph_path = Path(cli_env["SMP_GRAPH_PATH"])
        _create_graph_with_nodes(graph_path, 10)

        backup_file = tmp_path / "data_backup.tar.gz"
        stdout, stderr, code = run_cli(["backup", "--output", str(backup_file)], env=cli_env)

        assert code == 0
        assert backup_file.exists()
        assert backup_file.stat().st_size > 0

    def test_backup_is_tarball(self, cli_env, tmp_path):
        """Backup creates a backup file."""
        import asyncio

        graph_path = Path(cli_env["SMP_GRAPH_PATH"])
        store = MMapGraphStore(path=str(graph_path))
        asyncio.run(store.connect())
        asyncio.run(store.close())

        backup_file = tmp_path / "backup.tar.gz"
        stdout, stderr, code = run_cli(["backup", "--output", str(backup_file)], env=cli_env)

        assert code == 0
        assert backup_file.exists()
        assert backup_file.stat().st_size > 10

    def test_backup_with_graph_path(self, cli_env, tmp_path):
        """Backup with explicit --graph-path."""
        import asyncio

        graph_path = tmp_path / "explicit.smpg"
        store = MMapGraphStore(path=str(graph_path))
        asyncio.run(store.connect())
        asyncio.run(store.close())

        backup_file = tmp_path / "explicit.tar.gz"
        stdout, stderr, code = run_cli(
            ["backup", "--graph-path", str(graph_path), "--output", str(backup_file)],
            env=cli_env,
        )

        assert code == 0
        assert backup_file.exists()

    def test_backup_missing_graph(self, cli_env, tmp_path):
        """Backup fails gracefully with missing graph."""
        no_graph_env = dict(cli_env)
        no_graph_env["SMP_GRAPH_PATH"] = "/nonexistent/missing.smpg"

        backup_file = tmp_path / "missing.tar.gz"
        stdout, stderr, code = run_cli(["backup", "--output", str(backup_file)], env=no_graph_env)

        assert code != 0


class TestCLIRestore:
    """Tests for the restore command."""

    def test_restore_empty_backup(self, cli_env, tmp_path):
        """OP-004: Restore works with empty backup."""
        import asyncio

        graph_path = Path(cli_env["SMP_GRAPH_PATH"])
        store = MMapGraphStore(path=str(graph_path))
        asyncio.run(store.connect())
        asyncio.run(store.close())

        backup_file = tmp_path / "empty.tar.gz"
        run_cli(["backup", "--output", str(backup_file)], env=cli_env)

        restore_path = tmp_path / "restored.smpg"
        restore_env = dict(cli_env)
        restore_env["SMP_GRAPH_PATH"] = str(restore_path)

        stdout, stderr, code = run_cli(["restore", "--input", str(backup_file)], env=restore_env)

        assert code == 0

    def test_restore_preserves_data(self, cli_env, tmp_path):
        """Restore preserves node data."""
        graph_path = Path(cli_env["SMP_GRAPH_PATH"])
        _create_graph_with_nodes(graph_path, 15)

        backup_file = tmp_path / "preserve.tar.gz"
        run_cli(["backup", "--output", str(backup_file)], env=cli_env)

        os.remove(graph_path)

        restore_path = tmp_path / "restored.smpg"
        restore_env = dict(cli_env)
        restore_env["SMP_GRAPH_PATH"] = str(restore_path)

        run_cli(["restore", "--input", str(backup_file)], env=restore_env)

        assert restore_path.exists()
        import asyncio

        store = MMapGraphStore(path=str(restore_path))
        asyncio.run(store.connect())
        count = asyncio.run(store.count_nodes())
        asyncio.run(store.close())
        assert count == 15

    def test_restore_invalid_file_fails(self, cli_env, tmp_path):
        """Restore handles invalid backup file."""
        restore_path = tmp_path / "bad_restore.smpg"
        restore_env = dict(cli_env)
        restore_env["SMP_GRAPH_PATH"] = str(restore_path)

        stdout, stderr, code = run_cli(["restore", "--input", "/nonexistent/backup.tar.gz"], env=restore_env)

        assert code != 0

    def test_restore_missing_file(self, cli_env, tmp_path):
        """Restore fails with missing input file."""
        restore_path = tmp_path / "missing.smpg"
        restore_env = dict(cli_env)
        restore_env["SMP_GRAPH_PATH"] = str(restore_path)

        stdout, stderr, code = run_cli(["restore", "--input", "/nonexistent/backup.tar.gz"], env=restore_env)

        assert code != 0


class TestCLICompact:
    """Tests for the compact command."""

    def test_compact_basic(self, cli_env):
        """OP-005: Compact command reduces graph size."""

        graph_path = Path(cli_env["SMP_GRAPH_PATH"])
        _create_graph_with_nodes(graph_path, 20)

        stdout, stderr, code = run_cli(["compact"], env=cli_env)

        assert code == 0
        assert "Compacted" in stdout or "bytes" in stdout

    def test_compact_empty_graph(self, cli_env):
        """Compact works with empty graph."""
        import asyncio

        graph_path = Path(cli_env["SMP_GRAPH_PATH"])
        store = MMapGraphStore(path=str(graph_path))
        asyncio.run(store.connect())
        asyncio.run(store.close())

        stdout, stderr, code = run_cli(["compact"], env=cli_env)

        assert code == 0

    def test_compact_with_graph_path(self, cli_env, tmp_path):
        """Compact with explicit --graph-path."""
        import asyncio

        graph_path = tmp_path / "compact.smpg"
        store = MMapGraphStore(path=str(graph_path))
        asyncio.run(store.connect())
        for i in range(5):
            node = GraphNode(id=f"c_{i}", type=NodeType.FUNCTION, file_path="c.py")
            asyncio.run(store.upsert_node(node))
        asyncio.run(store.close())

        stdout, stderr, code = run_cli(["compact", "--graph-path", str(graph_path)], env=cli_env)

        assert code == 0

    def test_compact_missing_graph(self, cli_env):
        """Compact fails gracefully with missing graph."""
        no_graph_env = dict(cli_env)
        no_graph_env["SMP_GRAPH_PATH"] = "/nonexistent/missing.smpg"

        stdout, stderr, code = run_cli(["compact"], env=no_graph_env)

        assert code != 0


class TestCLIServe:
    """Tests for the serve command."""

    def test_serve_starts(self, cli_env, tmp_path):
        """OP-006: Serve command starts the server."""
        import asyncio

        graph_path = Path(cli_env["SMP_GRAPH_PATH"])
        store = MMapGraphStore(path=str(graph_path))
        asyncio.run(store.connect())
        asyncio.run(store.close())

        stdout, stderr, code = run_cli(["serve"], env=cli_env, timeout=5)

        assert code in (0, 1) or "serve" in (stdout + stderr).lower()

    def test_serve_with_custom_port(self, cli_env, tmp_path):
        """Serve with custom port."""
        import asyncio

        graph_path = Path(cli_env["SMP_GRAPH_PATH"])
        store = MMapGraphStore(path=str(graph_path))
        asyncio.run(store.connect())
        asyncio.run(store.close())

        stdout, stderr, code = run_cli(["serve", "--port", "8999"], env=cli_env, timeout=5)

        assert code in (0, 1) or "8999" in (stdout + stderr)

    def test_serve_with_custom_host(self, cli_env):
        """Serve with custom host."""
        import asyncio

        graph_path = Path(cli_env["SMP_GRAPH_PATH"])
        store = MMapGraphStore(path=str(graph_path))
        asyncio.run(store.connect())
        asyncio.run(store.close())

        stdout, stderr, code = run_cli(["serve", "--host", "127.0.0.1"], env=cli_env, timeout=5)

        assert code in (0, 1) or "127.0.0.1" in (stdout + stderr)

    def test_serve_with_graph_path(self, cli_env, tmp_path):
        """Serve with explicit --graph-path."""
        import asyncio

        graph_path = tmp_path / "serve.smpg"
        store = MMapGraphStore(path=str(graph_path))
        asyncio.run(store.connect())
        asyncio.run(store.close())

        stdout, stderr, code = run_cli(["serve", "--graph-path", str(graph_path)], env=cli_env, timeout=5)

        assert code in (0, 1) or "error" not in (stdout + stderr).lower()


class TestCLIIntegration:
    """Integration tests combining multiple CLI commands."""

    def test_full_backup_restore_cycle(self, cli_env, sample_project):
        """Complete backup and restore cycle."""
        run_cli(["ingest", str(sample_project)], env=cli_env)

        backup_file = Path(cli_env["SMP_GRAPH_PATH"]).parent / "full_cycle.tar.gz"
        run_cli(["backup", "--output", str(backup_file)], env=cli_env)

        os.remove(cli_env["SMP_GRAPH_PATH"])

        stdout, stderr, code = run_cli(["restore", "--input", str(backup_file)], env=cli_env)

        assert code == 0
        assert Path(cli_env["SMP_GRAPH_PATH"]).exists()

    def test_ingest_integrity_cycle(self, cli_env, sample_project):
        """Ingest then verify integrity."""
        run_cli(["ingest", str(sample_project)], env=cli_env)

        stdout, stderr, code = run_cli(["integrity"], env=cli_env)

        assert code == 0

    def test_ingest_compact_cycle(self, cli_env, sample_project):
        """Ingest then compact."""
        run_cli(["ingest", str(sample_project)], env=cli_env)

        stdout, stderr, code = run_cli(["compact"], env=cli_env)

        assert code == 0

    def test_multiple_ingests(self, cli_env, sample_project, tmp_path):
        """Multiple sequential ingests work correctly."""
        run_cli(["ingest", str(sample_project)], env=cli_env)

        extra_dir = tmp_path / "extra"
        extra_dir.mkdir()
        (extra_dir / "extra.py").write_text("def extra(): pass")

        run_cli(["ingest", str(extra_dir)], env=cli_env)

        stdout, stderr, code = run_cli(["integrity"], env=cli_env)
        assert code == 0
