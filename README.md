# SMP — Structural Memory Protocol

Graph-based codebase intelligence for AI coding agents.

SMP parses your repository into a knowledge graph (memory-mapped, no database)
and exposes it over MCP. Instead of reading files to answer questions, an agent
asks the graph — so understanding a 40-million-line codebase costs a few
thousand tokens, not a few hundred thousand.

## Install — one line

```bash
curl -fsSL https://raw.githubusercontent.com/offx-zinth/SMP/main/install.sh | bash
```

No sudo, no clone, no manual venv. The installer:

1. builds an isolated runtime at `~/.smp` (venv + all 14 language grammars),
2. drops `smp` (CLI) and `smp-mcp` (MCP launcher) into `~/.local/bin`,
3. **asks once: global or repo-only wiring**, then
   - global → installs the agent skill into `~/.agents`, `~/.claude`,
     `~/.config/opencode`, `~/.codex` and registers the MCP server into any
     harness it detects (Claude Code, OpenCode, Codex, Cursor, Gemini CLI,
     Windsurf, VS Code, Claude Desktop),
   - local → wires only the current repo (`./.mcp.json`, `./opencode.json`,
     `./.cursor/mcp.json`, `./.gemini/settings.json`, skills in `./.agents`).
4. per-repo graphs are always automatic: each project gets its own
   `.smp/graph.smpg`, ingested on first use.

**Your existing configs are safe.** The installer only *adds* a missing `smp`
entry; entries you wrote yourself are detected and left untouched (with a
note), every file gets a timestamped backup before its first change, TOML
fragments are validated after writing, and `--uninstall` removes only what the
installer itself created.

Useful variants:

```bash
... | bash -s -- --local            # only for the repo in .  (no prompt)
... | bash -s -- --global          # machine-wide (no prompt)
... | bash -s -- --skip-skills     # don't install SKILL.md copies
... | bash -s -- --all-harnesses   # register even undetected harnesses
... | bash -s -- --uninstall       # remove everything the installer added
```

Requirements: Linux or macOS, Python 3.11+ (also fetched via `uv` when
missing). Windows: use WSL.

Once installed, restart your agent harness and ask things like
*"what calls `handle_error()`?"* — the 60+ `smp_*` tools will answer from the
graph. One number to remember: **~60,000 Linux-kernel files indexed in
3 min 9 s on a mid-range 8-core i5 laptop** — the pace competitors reach on
M3 Max machines.

---

## The problem

An agent working in an unfamiliar repo has two options:

- **Read files.** Discover that `handle_error()` lives somewhere, grep for it,
  read three files, find it calls another helper, read that too. Context fills
  with source that mostly does not matter.
- **Ask a graph.** One call returns the definition, its callers, and its file
  location — already sized to what you need.

Reading is linear in the size of the codebase. A graph query is not.

## How it works

```
source files ──► tree-sitter parse ──► nodes + edges ──► .smpg (mmap journal)
```

- **14 languages** via tree-sitter (Python, JS/TS, Java, C/C++, C#, Go, Rust,
  PHP, Ruby, Swift, Kotlin, MATLAB), plus Markdown.
- **Code and docs in one graph**, so `smp_why` can cite the runbook that
  describes a function.
- **No database.** The store is a memory-mapped journal (`.smpg`) you can
  copy, back up, or git-ignore.
- **No embeddings required.** Structural parsing is enough for every tool
  except the optional vector search.

### Register the MCP server (manual, if you didn't use the installer)

Each repo gets its own graph (`.smp/graph.smpg`, relative), so one global
server entry serves every workspace — each harness spawns the server with the
project as its cwd:

```json
{
  "mcp": {
    "smp": {
      "type": "local",
      "command": ["/home/you/.local/bin/smp-mcp"]
    }
  }
}
```

The only requirement is that each repository has been ingested once
(`smp ingest .` from inside it) — which the launcher does automatically on
first use.

### First questions to ask an agent

| Question | Tool |
| --- | --- |
| Where is this defined? | `smp_search_code` |
| What calls this function? | `smp_trace` (direction `incoming`) |
| What breaks if I change it? | `smp_impact` |
| What does this file contain? | `smp_file_outline` |
| Show me the code | `smp_code_snippet` |
| What is this repo made of? | `smp_architecture` |

## The agent skill

SMP ships an agent skill (`skills/smp/SKILL.md`) that teaches your agent how
to drive the tools properly — graph-first discovery, blast-radius before
edits, dry-run before risky writes, session hygiene. The installer copies it
into:

- `~/.agents/skills/smp/SKILL.md` (universal agents dir)
- `~/.claude/skills/smp/SKILL.md` (Claude Code)
- `~/.config/opencode/skills/smp/SKILL.md` (OpenCode)
- `~/.codex/skills/smp/SKILL.md` (Codex)

## Ecosystem comparison matrix

| Tool | **SMP** (Structural Memory Protocol) | Graphify | Codebase-Memory-MCP | cgraphy |
| --- | --- | --- | --- | --- |
| **Graph architecture** | Live structural code graph | NetworkX + multi-modal layers | Embedded SQLite database | In-memory NetworkX subgraphs |
| **Core strength** | Blast-radius maps & community tracking | Image, PDF & doc parsing | Statically compiled local execution | Git co-change commit history |
| **Best used for** | Deep caller/callee tracing in active agents | Mixed-asset repos with design docs | Massive monorepos with a zero cloud footprint | Finding implicit logical dependencies across files |
| **Visualizer** | Terminal / JSON structure maps | Static `graph.html` graphs | Interactive 3D CBM Lens UI | None (data output) |

Supplementary dimensions that decide real agent deployments:

| | **SMP** | Graphify | Codebase-Memory-MCP | cgraphy |
| --- | --- | --- | --- | --- |
| Index speed, big repos | **~60k kernel files in 3m09s on an 8-core i5** | varies — extraction-bound for non-code assets | ~3 min on M3 Max (user-reported) | varies with git history depth |
| Agent-safety tooling | **guard checks · dry-run verdicts · checkpoints · rollback · audit · locks** | no | no | no |
| Risk context per file | **`smp_context`: role, blast radius, heat score, test coverage** | no | partial | no |
| Keyword search over graph | **BM25 (field-weighted) + structural expansion, no embeddings** | yes | keyword | — |
| Agent wiring | **curl\|bash → MCP server + SKILL.md across Claude Code / OpenCode / Codex / Cursor / Gemini / Windsurf / VS Code (global or per-repo)** | manual | manual config per harness | manual |
| Languages | **14 + Markdown in the same graph** | agnostic (multi-modal assets) | multi | git-history based |

*Comparison rows reflect each project's own documentation as of Oct 2026 —
judge from the linked upstream repos before deciding for your stack.*

**Pick Graphify** for a general-purpose knowledge graph across arbitrary
domains (documents, chats, events) where LLM-driven entity extraction is the
point.
**Pick Codebase-Memory-MCP** for a zero-cloud monorepo graph with a polished
UI and no write-safety needs.
**Pick cgraphy** when mining *implicit* co-change dependencies from git
history is the goal.
**Pick SMP** when the things above matter together: source-code-shaped graph +
zero-ops single-file storage + laptop-class indexing speed + a safe-write layer
that stops agents from stepping on each other — with a one-line install that
wires itself into every harness you already use.

## Tools

All tools are prefixed `smp_` over MCP.

**Discovery** — `smp_architecture`, `smp_locate`, `smp_search`,
`smp_search_code`, `smp_file_outline`, `smp_navigate`, `smp_context`
**Relationships** — `smp_trace`, `smp_impact`, `smp_flow`, `smp_why`,
`smp_query`, `smp_dead_code`, `smp_telemetry`
**Analysis** — `smp_community_list`, `smp_community_get`,
`smp_community_detect`, `smp_community_boundaries`
**Maintenance** — `smp_reindex`, `smp_sync`, `smp_update`,
`smp_batch_update`, `smp_detect_changes`, `smp_diff`
**Safe writes** — `smp_session_open`, `smp_checkpoint`, `smp_rollback`,
`smp_lock`, `smp_dryrun`, `smp_annotate`, `smp_tag`
**Optional vector search** — `smp_vector_upsert`, `smp_vector_search`

> `smp_reindex` registers a directory with the file watcher. It does **not**
> reparse files that are already indexed — to rebuild after a parser change,
> delete `.smp/graph.smpg` and re-run `ingest`.

## Performance

**Real measurements, same laptop for every tool** — 8-thread 11th-gen Intel
i7-1165G7, 14 GB RAM, NVMe, Linux, no GPU. Each tool performed a fresh full
index of the identical directory tree and served every query through its MCP
server, driven by the same benchmark client.

### Indexing

| Corpus | SMP | codebase-memory-mcp |
|---|---|---|
| Linux kernel snapshot — 95,937 files (72,171 source files parsed) | **2 min 51 s** — 839,516 nodes, 4,066,943 edges, 2.2 GB graph, 6.5 GB peak RAM | **13 min 14 s** — `fast` (structural) mode, 4.8 GB index |
| Real Python repo — 208 files | **0.99 s** — 4,575 nodes, 18,862 edges | **5.27 s** |

That is **4.6× faster** on the kernel corpus and **5.3× faster** on the small
repo — same machine, same files, fresh indexes. Directory selection and graph
models differ (codebase-memory-mcp skips gitignored paths and some vendor
directories by design; SMP indexes the full tree), so node counts are not
directly comparable — wall-clock on the same input is the headline.

### Queries (after indexing, warm cache)

| Operation | p50 | p95 |
|---|---|---|
| Point lookup (60k-node store micro-benchmark) | 0.000 ms | 0.001 ms |
| Depth-3 traversal (BFS) | 0.057 ms | 0.084 ms |
| `smp_locate` symbol search (4,575-node graph) | 40–85 ms | ≤ 90 ms |
| `smp_context` file context | 29.9 ms | 34.4 ms |
| `smp_file_outline` | 9.3 ms | 10.0 ms |

`smp_locate` took **1,493 ms p50** on that graph before this release — it
rebuilt the BM25 corpus on every query. The corpus is now cached per store
revision (~15–37× faster) with byte-identical results, while still falling
back cleanly for very large graphs. Structural queries read from the
memory-mapped graph: memory cost is O(graph), not O(context).

### Maintainer-reported cross-hardware run

- **~60,000 files of the Linux kernel indexed in 3 min 9 s** on an 8-core
  11th-gen Intel i5 with 16 GB RAM — no GPU, no database, no embeddings.
- codebase-memory-mcp needs **3 min for the same corpus on an M3 Max**
  (user-reported). SMP holds that pace on budget Intel laptops — agent-scale
  codegraphs no longer require flagship hardware.
- **Disclosure:** the i5 figure is Intel-only. Apple Silicon (M1/M2/M3) runs
  are pending — if you have one, run `benchmark_scale.py` and open a PR with
  your timings. The i7 figures in the tables above are the project's own
  measured runs.

### Reproduce

```bash
# Graph-store micro-benchmark (60k nodes / 240k edges)
python benchmarks/benchmark_scale.py --nodes 60000 --depth 3

# Full index: time it on your own corpus
time smp ingest /path/to/linux --graph-path /tmp/kernel.smpg

# MCP query latency: spawns the server, does warmup + timed calls
SMP_GRAPH_PATH=/tmp/kernel.smpg python benchmarks/mcp_query_bench.py \
  --cmd "python -m smp.protocol.mcp" \
  --tools '[["smp_locate", {"query": "mutex_lock", "top_k": 5}]]'
```

Exact numbers vary with disk and CPU. Methodology and scripts:
[`benchmarks/`](benchmarks/).

## Operations

```bash
smp integrity          # verify the on-disk journal
smp backup --output g.tar.gz
smp restore --input g.tar.gz
smp compact            # reclaim space
```

Configuration is via environment variables: `SMP_GRAPH_PATH`,
`SMP_VECTOR_PATH`, `SMP_AUTO_INGEST`, `SMP_HOST`, `SMP_PORT`. See
[`.env.example`](.env.example).

## Architecture

`core` (models) → `engine` (query/graph logic) → `protocol` (HTTP + MCP) →
`store` (mmap persistence). See [ARCHITECTURE.md](ARCHITECTURE.md) for the
detailed design and [SPEC.md](SPEC.md) for the JSON-RPC protocol.

## Development

```bash
git clone https://github.com/offx-zinth/SMP && cd SMP
bash install.sh          # installs from this checkout
```

```bash
pip install -e ".[dev]"
pytest
ruff check . && ruff format .
mypy smp/
```

## Contributing

Issues and pull requests are welcome. Please read
[CONTRIBUTING.md](CONTRIBUTING.md) first — in particular the rule that parser
changes need a re-ingest and a test proving the new edges are correct.

## License

MIT — see [LICENSE](LICENSE).
