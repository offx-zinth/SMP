# SMP .deb Package

A standalone Debian package that installs SMP (Structural Memory Protocol)
with the Qwen3-Embedding-0.6B GGUF model bundled — ready to use on any Linux laptop.

## Quick Install

```bash
sudo dpkg -i smp_0.1.0-1_all.deb
source /etc/profile.d/smp.sh  # sets SMP_MODEL_PATH
```

## Usage

### Ingest a codebase

```bash
smp ingest /path/to/your/project --semantic-search
```

### Start the JSON-RPC server

```bash
smp serve --json-log
```

### Start the MCP server (for AI agents)

```bash
smp mcp
```

### Use the Python API

```python
import asyncio
from smp.embedding import get_embedding_service
from smp.vector.mmap_vector import MMapVectorStore

async def main():
    embedding_service = await get_embedding_service()
    vector_store = MMapVectorStore(path=".smp/smp.smpv", dimension=1024)
    await vector_store.connect()
    vector_store.set_embedding_service(embedding_service)

    results = await vector_store.semantic_search("authentication function", k=5)
    for r in results:
        print(r["id"], r["score"])

    await vector_store.close()

asyncio.run(main())
```

## What's Included

| Component | Location |
|-----------|----------|
| SMP Python package | `/usr/lib/python3/dist-packages/smp/` |
| Qwen3-Embedding-0.6B model | `/usr/lib/smp/models/Qwen3-Embedding-0.6B-Q8_0.gguf` |
| Environment setup | `/etc/profile.d/smp.sh` |
| Systemd service | `/lib/systemd/system/smp-server.service` |
| CLI entry point | `/usr/lib/python3/dist-packages/bin/smp` |

## Configuration

The following environment variables are set by `/etc/profile.d/smp.sh`:

- `SMP_MODEL_PATH` — Path to the Qwen3 model (set to bundled model)
- `SMP_GRAPH_PATH` — Path to the graph file (default: `.smp/graph.smpg`)
- `SMP_VECTOR_PATH` — Path to the vector store (default: `.smp/smp.smpv`)
- `SMP_HOST` — Server bind address (default: `0.0.0.0`)
- `SMP_PORT` — Server port (default: `8420`)

Override any variable in `~/.bashrc` or `/etc/environment`.

## Uninstall

```bash
sudo dpkg -r smp
```

## Requirements

- Debian/Ubuntu-based Linux
- Python 3.11+
- 2 GB RAM minimum (model is ~610 MB)
- 1.5 GB disk space

## License

MIT
