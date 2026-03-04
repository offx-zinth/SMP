from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import networkx as nx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from vibecoder.agent.orchestrator import AgentOrchestrator
from vibecoder.config import Config
from vibecoder.context import AppContext
from vibecoder.smp.memory import SMPMemory
from vibecoder.smp.parser import ASTParser


class SMPRequest(BaseModel):
    action: Literal["navigate", "trace", "search"]
    query: str = Field(..., min_length=1)
    file_path: str | None = None
    depth: int = Field(default=2, ge=1, le=4)
    limit: int = Field(default=20, ge=1, le=200)


class SMPResponse(BaseModel):
    ok: bool
    action: str
    data: dict[str, Any]


class AgentChatRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    max_steps: int = Field(default=24, ge=1, le=100)


class WorkspaceInitRequest(BaseModel):
    workspace_dir: str | None = None
    recursive: bool = True


def create_app() -> FastAPI:
    config = Config()
    context = AppContext.from_config(config)
    memory = SMPMemory(context)
    orchestrator = AgentOrchestrator(context, memory=memory)
    parser = ASTParser()

    app = FastAPI(title="VibeCoder API", version="1.0.0")

    @app.post("/smp/query", response_model=SMPResponse)
    def query_smp(req: SMPRequest) -> SMPResponse:
        if req.action == "search":
            return SMPResponse(ok=True, action=req.action, data=memory.semantic_search(req.query, n_results=req.limit))

        if req.action == "navigate":
            query = req.query.lower().strip()
            matches: list[dict[str, Any]] = []
            for node_id, attrs in memory.graph.nodes(data=True):
                name = str(attrs.get("name", "")).lower()
                file_path = str(attrs.get("file_path", "")).lower()
                if query not in node_id.lower() and query not in name and query not in file_path:
                    continue
                matches.append({"id": node_id, "attrs": attrs})
                if len(matches) >= req.limit:
                    break
            return SMPResponse(ok=True, action=req.action, data={"matches": matches})

        if req.action == "trace":
            if req.file_path:
                start_node = f"file:{req.file_path}"
            else:
                start_node = req.query
            if not memory.graph.has_node(start_node):
                raise HTTPException(status_code=404, detail=f"Node not found: {start_node}")
            sub_nodes = nx.single_source_shortest_path_length(memory.graph, start_node, cutoff=req.depth).keys()
            edges = [
                {"source": src, "target": dst, "relation": attrs.get("relation", "UNKNOWN")}
                for src, dst, attrs in memory.graph.edges(data=True)
                if src in sub_nodes and dst in sub_nodes
            ]
            return SMPResponse(ok=True, action=req.action, data={"node": start_node, "edges": edges})

        raise HTTPException(status_code=400, detail=f"Unsupported action: {req.action}")

    @app.post("/agent/chat")
    def agent_chat(req: AgentChatRequest) -> dict[str, Any]:
        try:
            result = orchestrator.chat_turn(user_prompt=req.prompt, max_steps=req.max_steps)
            return {"ok": True, "result": result}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/workspace/init")
    def workspace_init(req: WorkspaceInitRequest) -> dict[str, Any]:
        root = Path(req.workspace_dir).resolve() if req.workspace_dir else context.config.workspace_dir.resolve()
        if not root.exists():
            raise HTTPException(status_code=400, detail=f"Workspace does not exist: {root}")

        patterns = ["*.py", "*.ts", "*.tsx", "*.js", "*.jsx"]
        files: list[Path] = []
        for pattern in patterns:
            files.extend(root.rglob(pattern) if req.recursive else root.glob(pattern))

        parsed_count = 0
        all_nodes: list[dict[str, Any]] = []
        for file_path in sorted(set(files)):
            try:
                nodes = parser.parse_file(file_path)
            except ValueError:
                continue
            parsed_count += 1
            all_nodes.extend(nodes)

        memory.build_graph(all_nodes)
        return {
            "ok": True,
            "workspace": str(root),
            "files_indexed": parsed_count,
            "nodes_indexed": len(all_nodes),
        }

    return app


app = create_app()
