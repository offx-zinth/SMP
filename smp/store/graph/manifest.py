from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from smp.store.graph.mmap_file import MMapFile

MANIFEST_ENTRY_SIZE: Final[int] = 128


class FileManifest:
    """Tracks source files and their parse status.

    In-memory index backed by the journal ``PARSE_STATUS`` records
    (rebuilt on replay). Exposes generation/freshness for
    ``smp/coverage`` transparency parity with codebase-memory.
    """

    def __init__(self, mmap_file: MMapFile, manifest_ptr_offset: int) -> None:
        self.mmap = mmap_file
        self.manifest_ptr_offset = manifest_ptr_offset
        self._entries: dict[int, dict[str, int]] = {}
        self._indexed_at: str = datetime.now(UTC).isoformat()

    def get_entry(self, path_off: int) -> dict[str, int] | None:
        """Get manifest entry for a file path."""
        return self._entries.get(path_off)

    def upsert_entry(self, path_off: int, hash_val: int, status: int) -> None:
        """Update or insert file status."""
        self._entries[path_off] = {"hash": hash_val, "status": status}
        self._indexed_at = datetime.now(UTC).isoformat()

    @property
    def indexed_at(self) -> str:
        """Last mutation timestamp (ISO-8601)."""
        return self._indexed_at

    @property
    def generation(self) -> str:
        """Deterministic generation fingerprint of tracked files."""
        import hashlib

        src = "|".join(f"{k}:{v.get('hash', 0)}:{v.get('status', 0)}" for k, v in sorted(self._entries.items()))
        return hashlib.blake2b(src.encode(), digest_size=8).hexdigest()

    def stats(self) -> dict[str, int | str]:
        """Summary for coverage responses."""
        return {"files": len(self._entries), "indexed_at": self._indexed_at, "generation": self.generation}
