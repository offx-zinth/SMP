from __future__ import annotations

import json
import os
import pickle
from pathlib import Path
from typing import Any, Iterable

import chromadb
import networkx as nx
from google import genai
from tenacity import Retrying, retry_if_exception, stop_after_attempt, wait_exponential

from vibecoder.smp.parser import ParsedNode


class SMPMemory:
    def __init__(self, workspace: str | Path = ".", state_dir: str | Path = ".vibecoder") -> None:
        self.workspace = Path(workspace).resolve()
        self.state_dir = self.workspace / state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.graph_path = self.state_dir / "smp_graph.pkl"

        self.graph: nx.DiGraph = self._load_graph()
        self.chroma_client = chromadb.PersistentClient(path=str(self.state_dir / "chroma"))
        self.collection = self.chroma_client.get_or_create_collection("smp_semantics")
        self._genai_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    def _load_graph(self) -> nx.DiGraph:
        if self.graph_path.exists():
            with self.graph_path.open("rb") as handle:
                return pickle.load(handle)
        return nx.DiGraph()

    def save_graph(self) -> None:
        with self.graph_path.open("wb") as handle:
            pickle.dump(self.graph, handle)

    def build_graph(self, parsed_nodes: Iterable[ParsedNode]) -> None:
        for node in parsed_nodes:
            node_id = node["id"]
            file_id = f"file:{node['file_path']}"

            self.graph.add_node(file_id, type="file", file_path=node["file_path"])
            self.graph.add_node(node_id, **node)
            self.graph.add_edge(file_id, node_id, relation="DEFINES")

            if node.get("type") == "import":
                module_name = node.get("module") or node.get("name")
                if module_name:
                    module_id = f"module:{module_name}"
                    self.graph.add_node(module_id, type="module", name=module_name)
                    self.graph.add_edge(file_id, module_id, relation="IMPORTS")

            if node.get("type") == "function":
                for call in node.get("calls", []):
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
            outgoing = list(self.graph.out_edges(file_id))
            self.graph.remove_edges_from(outgoing)

        self.build_graph(parsed_nodes)

    def enrich_nodes(self, batch_size: int = 8) -> int:
        targets = [
            (node_id, attrs)
            for node_id, attrs in self.graph.nodes(data=True)
            if attrs.get("type") in {"class", "function", "file"}
            and not attrs.get("semantic_summary")
        ]

        enriched = 0
        for idx in range(0, len(targets), batch_size):
            for node_id, attrs in targets[idx : idx + batch_size]:
                raw_text = attrs.get("text") or attrs.get("name") or attrs.get("file_path")
                prompt = (
                    "Summarize the following code entity in one precise sentence. "
                    "Focus on responsibility and side effects.\n\n"
                    f"Entity type: {attrs.get('type')}\n"
                    f"Entity name: {attrs.get('name', '')}\n"
                    f"Source:\n{raw_text}"
                )
                response = self._generate_content_with_backoff(prompt)
                summary = (response.text or "").strip()
                if not summary:
                    continue

                self.graph.nodes[node_id]["semantic_summary"] = summary
                metadata = {
                    "node_id": node_id,
                    "file_path": attrs.get("file_path", ""),
                    "name": attrs.get("name", ""),
                    "type": attrs.get("type", ""),
                }
                self.collection.upsert(
                    ids=[node_id],
                    documents=[summary],
                    metadatas=[metadata],
                )
                enriched += 1

        self.save_graph()
        return enriched

    def _generate_content_with_backoff(self, prompt: str) -> Any:
        for attempt in Retrying(
            retry=retry_if_exception(self._is_gemini_rate_limit_error),
            wait=wait_exponential(multiplier=1, min=1, max=30),
            stop=stop_after_attempt(6),
            reraise=True,
        ):
            with attempt:
                return self._genai_client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt,
                )
        raise RuntimeError("Gemini response retry loop exited unexpectedly.")

    @staticmethod
    def _is_gemini_rate_limit_error(exc: BaseException) -> bool:
        status_candidates = [
            getattr(exc, "status_code", None),
            getattr(exc, "code", None),
            getattr(exc, "http_status", None),
        ]
        if any(str(status) == "429" for status in status_candidates if status is not None):
            return True

        message = str(exc).lower()
        return "429" in message or "rate limit" in message or "resource exhausted" in message

    def get_compressed_context(self, file_path: str) -> dict[str, Any]:
        file_id = f"file:{file_path}"
        if not self.graph.has_node(file_id):
            raise ValueError(f"File is not indexed in SMP graph: {file_path}")

        outgoing = []
        for _, target, edge_data in self.graph.out_edges(file_id, data=True):
            attrs = self.graph.nodes[target]
            outgoing.append(
                {
                    "target": target,
                    "relation": edge_data.get("relation"),
                    "type": attrs.get("type"),
                    "name": attrs.get("name") or attrs.get("file_path"),
                    "semantic_summary": attrs.get("semantic_summary", ""),
                }
            )

        incoming = []
        for source, _, edge_data in self.graph.in_edges(file_id, data=True):
            attrs = self.graph.nodes[source]
            incoming.append(
                {
                    "source": source,
                    "relation": edge_data.get("relation"),
                    "type": attrs.get("type"),
                    "name": attrs.get("name") or attrs.get("file_path"),
                    "semantic_summary": attrs.get("semantic_summary", ""),
                }
            )

        raw_context = {
            "file_path": file_path,
            "outgoing": outgoing,
            "incoming": incoming,
        }

        response = self._genai_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=(
                "Compress the following software graph context into highly dense JSON. "
                "Return valid JSON only with keys: file_role, dependencies, dependents, risks, "
                "touch_points.\n\n"
                f"Raw graph context:\n{json.dumps(raw_context, indent=2)}"
            ),
        )
        text = (response.text or "{}").strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {
                "file_role": "unknown",
                "dependencies": [],
                "dependents": [],
                "risks": ["LLM returned non-JSON context compression output."],
                "touch_points": raw_context,
            }

    def semantic_search(self, query: str, n_results: int = 8) -> dict[str, Any]:
        return self.collection.query(query_texts=[query], n_results=n_results)
