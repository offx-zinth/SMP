"""Memory-mapped vector store backend for SMP.

Provides :class:`~smp.vector.mmap_vector.MMapVectorStore`, a
:class:`~smp.store.interfaces.VectorStore` implementation backed by a
single ``.smpv`` mmap'd file plus a JSON sidecar for ID and metadata
bookkeeping.
"""

from __future__ import annotations

from smp.vector.mmap_vector import MMapVectorStore

__all__ = ["MMapVectorStore"]
