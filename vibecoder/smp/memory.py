from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, cast

import chromadb
import networkx as nx
from chromadb.api.models.Collection import Collection
from google import genai
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from vibecoder.context import AppContext
from vibecoder.smp.parser import ParsedNode


class SMPMemory:
    """Structural + semantic memory built from parsed source nodes."""

    def __init__(self, app_context: AppContext) -> None:
        self.context = app_context
        self.workspace = app_context.config.workspace_dir.resolve()
        self.state_dir = self._resolve_state_dir()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.graph_path = self.state_dir / "smp_graph.json"

        self.graph: nx.DiGraph = self._load_graph()
        self.chroma_client = chromadb.PersistentClient(path=str(self.state_dir / "chroma"))
        self.collection: Collection = self.chroma_client.get_or_create_collection("smp_semantics")
        self._genai_client = genai.Client(api_key=app_context.config.gemini_api_key)

    def _resolve_state_dir(self) -> Path:
        configured = self.context.config.smp_db_dir
        return configured if configured.is_absolute() else self.workspace / configured

    def _load_graph(self) -> nx.DiGraph:
        graph = nx.DiGraph()
        if not self.graph_path.exists():
            return graph

        payload = json.loads(self.graph_path.read_text(encoding="utf-8"))
        for node in payload.get("nodes", []):
            graph.add_node(node["id"], **node.get("attrs", {}))
        for edge in payload.get("edges", []):
            graph.add_edge(edge["source"], edge["target"], **edge.get("attrs", {}))
        return graph

    def save_graph(self) -> None:
        payload = {
            "nodes": [
                {"id": node_id, "attrs": attrs}
                for node_id, attrs in self.graph.nodes(data=True)
            ],
            "edges": [
                {"source": source, "target": target, "attrs": attrs}
                for source, target, attrs in self.graph.edges(data=True)
            ],
        }
        self.graph_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def build_graph(self, parsed_nodes: Iterable[ParsedNode]) -> None:
        """Builds structural edges: file DEFINES symbols, IMPORTS modules, CALLS symbols."""
        for node in parsed_nodes:
            file_path = str(node["file_path"])
            file_id = f"file:{file_path}"
            node_id = str(node["id"])

            self.graph.add_node(file_id, type="file", file_path=file_path, name=file_path)
            self.graph.add_node(node_id, **node)
            self.graph.add_edge(file_id, node_id, relation="DEFINES")

            if node.get("type") == "import":
                module_name = str(node.get("module") or node.get("name") or "")
                if module_name:
                    module_id = f"module:{module_name}"
                    self.graph.add_node(module_id, type="module", name=module_name)
                    self.graph.add_edge(file_id, module_id, relation="IMPORTS")

            if node.get("type") == "function":
                for call in cast(list[str], node.get("calls", [])):
                    call_id = f"symbol:{call}"
                    self.graph.add_node(call_id, type="symbol", name=call)
                    self.graph.add_edge(node_id, call_id, relation="CALLS")

        self.save_graph()

    def replace_file_nodes(self, file_path: str, parsed_nodes: Iterable[ParsedNode]) -> None:
        file_id = f"file:{file_path}"
        stale_nodes = [
            node
            for node, attrs in self.graph.nodes(data=True)
            if attrs.get("file_path") == file_path and node != file_id
        ]
        self.graph.remove_nodes_from(stale_nodes)

        if self.graph.has_node(file_id):
            self.graph.remove_edges_from(list(self.graph.out_edges(file_id)))

        self.build_graph(parsed_nodes)

    @retry(
        retry=retry_if_exception(lambda exc: SMPMemory._is_rate_limit_error(exc)),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        stop=stop_after_attempt(6),
        reraise=True,
    )
    def _summarize_entity(self, prompt: str) -> str:
        response = self._genai_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        return (response.text or "").strip()

    @staticmethod
    def _is_rate_limit_error(exc: BaseException) -> bool:
        code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
        return str(code) == "429" or "rate" in str(exc).lower() or "resource exhausted" in str(exc).lower()

    def enrich_nodes(self, batch_size: int = 8) -> int:
        """Adds semantic summaries and stores them in ChromaDB for retrieval."""
        targets = [
            (node_id, attrs)
            for node_id, attrs in self.graph.nodes(data=True)
            if attrs.get("type") in {"file", "class", "function"} and not attrs.get("semantic_summary")
        ]

        enriched = 0
        for start in range(0, len(targets), batch_size):
            for node_id, attrs in targets[start : start + batch_size]:
                source_text = str(attrs.get("text") or attrs.get("name") or attrs.get("file_path") or "")
                prompt = (
                    "Summarize this code entity in a single crisp sentence. "
                    "Include core responsibility and side effects if any.\n\n"
                    f"Type: {attrs.get('type')}\n"
                    f"Name: {attrs.get('name', '')}\n"
                    f"Code:\n{source_text[:8000]}"
                )
                summary = self._summarize_entity(prompt)
                if not summary:
                    continue

                self.graph.nodes[node_id]["semantic_summary"] = summary
                self.collection.upsert(
                    ids=[node_id],
                    documents=[summary],
                    metadatas=[
                        {
                            "node_id": node_id,
                            "type": str(attrs.get("type", "")),
                            "name": str(attrs.get("name", "")),
                            "file_path": str(attrs.get("file_path", "")),
                        }
                    ],
                )
                enriched += 1

        self.save_graph()
        return enriched

    def semantic_search(self, query: str, n_results: int = 5) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self.collection.query(query_texts=[query], n_results=n_results),
        )

    def get_compressed_context(self, file_path: str) -> str:
        """Returns dense JSON context for a file and nearby blast-radius nodes."""
        file_id = f"file:{file_path}"
        if not self.graph.has_node(file_id):
            raise ValueError(f"File not found in SMP graph: {file_path}")

        neighbors = {file_id}
        neighbors.update(nx.single_source_shortest_path_length(self.graph, file_id, cutoff=2).keys())
        neighbors.update(nx.single_source_shortest_path_length(self.graph.reverse(copy=False), file_id, cutoff=2).keys())

        entities: list[dict[str, Any]] = []
        for node_id in neighbors:
            attrs = dict(self.graph.nodes[node_id])
            outgoing = [
                {"to": target, "relation": edge.get("relation", "UNKNOWN")}
                for _, target, edge in self.graph.out_edges(node_id, data=True)
                if target in neighbors
            ]
            entities.append(
                {
                    "id": node_id,
                    "type": attrs.get("type"),
                    "name": attrs.get("name"),
                    "file_path": attrs.get("file_path"),
                    "semantic_summary": attrs.get("semantic_summary"),
                    "outgoing": outgoing,
                }
            )

        prompt = (
            "Compress this blast-radius graph into dense JSON for an autonomous coding agent. "
            "Output valid JSON with keys: file, primary_entities, risky_dependencies, edit_guidance.\n\n"
            f"Target file: {file_path}\n"
            f"Graph data:\n{json.dumps(entities, ensure_ascii=False)[:20000]}"
        )
        response = self._genai_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        return (response.text or "{}").strip()
