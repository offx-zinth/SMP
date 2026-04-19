# User Guide: Using the Structural Memory Protocol (SMP)

This guide provides practical instructions for using SMP to analyze, navigate, and maintain complex codebases.

## 🌟 What can you do with SMP?

SMP is designed to help you (or your AI agents) answer structural questions that traditional search cannot:
- **"Where is the logic for X implemented?"** $\rightarrow$ Use `locate` (Graph RAG).
- **"If I change this function, what else will break?"** $\rightarrow$ Use `assess_impact` (Blast Radius).
- **"How does data flow from the API to the Database?"** $\rightarrow$ Use `trace` (Call Graph).
- **"What are the main architectural modules of this project?"** $\rightarrow$ Use `community/list`.

---

## ⌨️ CLI Usage

The `smp` CLI is the fastest way to interact with the memory server.

### 1. Ingesting a Codebase
To analyze a project, you must first ingest it into the graph.
```bash
# Basic ingestion
smp ingest /path/to/your/project

# Ingest and clear previous data for that project
smp ingest /path/to/your/project --clear
```

### 2. Querying the Intelligence Layer
Once ingested, you can ask natural language questions.
```bash
smp query "Find the part of the code that handles JWT validation"
```

### 3. Running the Server
If you are using the SDK or an MCP client, the server must be running.
```bash
smp serve --port 8420 --safety
```

---

## 🐍 Python SDK Usage

For integrating SMP into your own AI agents or scripts, use the `SMPClient`.

### Basic Setup
```python
from smp.client import SMPClient
import asyncio

async def main():
    async with SMPClient("http://localhost:8420") as client:
        # Your code here
        pass

asyncio.run(main())
```

### Feature Location (`locate`)
Use this to find the "seed" of a feature using semantic and structural search.
```python
results = await client.locate("payment gateway integration")
for res in results.results:
    print(f"Found {res.name} in {res.file} (Score: {res.final_score})")
```

### Impact Analysis (`assess_impact`)
Determine the "Blast Radius" of a change to a specific function or class.
```python
impact = await client.assess_impact("src/auth/manager.py::authenticate")
print(f"Total affected nodes: {impact['total_affected_nodes']}")
# The response includes a list of all dependent functions across the repo.
```

### Programmer's Context (`get_context`)
Get a structural summary of a file, including who imports it and its complexity.
```python
context = await client.get_context("src/api/routes.py")
print(f"Role: {context['summary']['role']}")
print(f"Blast Radius: {context['summary']['blast_radius']}")
```

---

## 🔌 Advanced Workflows

### Using SMP with MCP
SMP natively supports the **Model Context Protocol (MCP)**. You can add SMP as a server in MCP-compatible IDEs (like Cursor or Windsurf). This allows the AI to automatically call `locate` and `get_context` as it writes code, preventing it from making assumptions about your architecture.

### Architectural Review
Use the community tools to understand the boundaries of your system:
1. **List Communities:** `smp/community/list` to see the high-level domains.
2. **Analyze Coupling:** `smp/community/boundaries` to find "bridge nodes" that connect two different domains. If a bridge node has too many connections, it's a sign of high coupling (architectural debt).

### Maintaining the Graph
As you change your code, the graph can become "stale."
- Use `smp/enrich/stale` to find nodes that need updating.
- Run `smp/enrich/batch` to refresh the metadata for an entire package.

---

## 🛠 Troubleshooting

| Issue | Solution |
| :--- | :--- |
| **`SyntaxError` or `ImportError`** | Ensure you are using **Python 3.11**. |
| **Neo4j Connection Failure** | Check your `.env` file and ensure the Neo4j container is running (`docker ps`). |
| **Empty Search Results** | Ensure you ran `smp ingest` and that the project has docstrings/type annotations for the enricher to find. |
