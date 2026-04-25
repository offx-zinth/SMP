from __future__ import annotations

from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from smp.store.graph.mmap_file import MMapFile

MANIFEST_ENTRY_SIZE: Final[int] = 128


class FileManifest:
    """Tracks source files and their parse status."""

    def __init__(self, mmap_file: MMapFile, manifest_ptr_offset: int) -> None:
        self.mmap = mmap_file
        self.manifest_ptr_offset = manifest_ptr_offset

    def get_entry(self, path_off: int) -> dict[str, int] | None:
        """Get manifest entry for a file path."""
        return None

    def upsert_entry(self, path_off: int, hash_val: int, status: int) -> None:
        """Update or insert file status."""
        pass
