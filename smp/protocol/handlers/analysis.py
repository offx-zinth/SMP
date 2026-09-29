"""Analysis and telemetry handlers.

Wires up engine methods that already exist in
:class:`~smp.engine.query.DefaultQueryEngine` (``diff``, ``plan``,
``conflict``, ``why``) plus three telemetry endpoints that summarise
graph-wide counts and per-node degree.
"""

from __future__ import annotations

from typing import Any

import msgspec

from smp.core.models import (
    ConflictParams,
    DiffParams,
    PlanParams,
    TelemetryHotParams,
    TelemetryNodeParams,
    TelemetryParams,
    WhyParams,
)
from smp.logging import get_logger

log = get_logger(__name__)

_HTTP_VERBS = {"get", "post", "put", "delete", "patch", "head", "options"}


async def diff(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/diff``."""
    p = msgspec.convert(params, DiffParams)
    engine = ctx["engine"]
    return await engine.diff(p.from_snapshot, p.to_snapshot, p.scope)  # type: ignore[no-any-return]


async def plan(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/plan``."""
    p = msgspec.convert(params, PlanParams)
    engine = ctx["engine"]
    return await engine.plan(p.change_description, p.target_file, p.change_type, p.scope)  # type: ignore[no-any-return]


async def conflict(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/conflict``."""
    p = msgspec.convert(params, ConflictParams)
    engine = ctx["engine"]
    return await engine.conflict(p.entity, p.proposed_change, p.context)  # type: ignore[no-any-return]


async def why(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/why``."""
    p = msgspec.convert(params, WhyParams)
    engine = ctx["engine"]
    return await engine.why(p.entity, p.relationship, p.depth)  # type: ignore[no-any-return]


async def _hot_nodes(graph: Any, threshold: int, top_k: int) -> list[dict[str, Any]]:
    """Compute the highest-degree nodes for telemetry summaries."""
    nodes = await graph.find_nodes()
    scored: list[tuple[int, dict[str, Any]]] = []
    for node in nodes:
        in_deg, out_deg = await graph.get_node_degree(node.id)
        degree = in_deg + out_deg
        if degree >= threshold:
            scored.append(
                (
                    degree,
                    {
                        "node_id": node.id,
                        "name": node.structural.name,
                        "file": node.file_path,
                        "type": node.type.value,
                        "degree": degree,
                        "in_degree": in_deg,
                        "out_degree": out_deg,
                    },
                )
            )
    scored.sort(key=lambda x: -x[0])
    return [item[1] for item in scored[:top_k]]


async def telemetry(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/telemetry`` — return graph-wide telemetry."""
    p = msgspec.convert(params, TelemetryParams)
    graph = ctx["graph"]

    action = (p.action or "get_stats").lower()
    threshold = p.threshold if p.threshold is not None else 5

    if action in {"get_stats", "stats", "summary"}:
        node_count = await graph.count_nodes()
        edge_count = await graph.count_edges()
        return {
            "action": action,
            "nodes": node_count,
            "edges": edge_count,
            "hot_nodes": await _hot_nodes(graph, threshold=threshold, top_k=5),
        }

    if action == "hot_nodes":
        return {"action": action, "hot_nodes": await _hot_nodes(graph, threshold=threshold, top_k=10)}

    if action == "node" and p.node_id:
        return await telemetry_node({"node_id": p.node_id}, ctx)

    return {"action": action, "nodes": await graph.count_nodes(), "edges": await graph.count_edges()}


async def telemetry_hot(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/telemetry/hot`` — degree report for a single node."""
    p = msgspec.convert(params, TelemetryHotParams)
    graph = ctx["graph"]

    node = await graph.get_node(p.node_id)
    if node is None:
        return {"node_id": p.node_id, "is_hot": False, "error": "node_not_found"}

    in_deg, out_deg = await graph.get_node_degree(p.node_id)
    degree = in_deg + out_deg
    return {
        "node_id": p.node_id,
        "name": node.structural.name,
        "file": node.file_path,
        "in_degree": in_deg,
        "out_degree": out_deg,
        "degree": degree,
        "is_hot": degree > 10 or node.structural.complexity > 8,
        "complexity": node.structural.complexity,
    }


async def telemetry_node(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/telemetry/node`` — detailed per-node telemetry."""
    p = msgspec.convert(params, TelemetryNodeParams)
    graph = ctx["graph"]

    node = await graph.get_node(p.node_id)
    if node is None:
        return {"node_id": p.node_id, "error": "node_not_found"}

    edges_out = await graph.get_edges(p.node_id, direction="outgoing")
    edges_in = await graph.get_edges(p.node_id, direction="incoming")

    by_type_out: dict[str, int] = {}
    for edge in edges_out:
        by_type_out[edge.type.value] = by_type_out.get(edge.type.value, 0) + 1

    by_type_in: dict[str, int] = {}
    for edge in edges_in:
        by_type_in[edge.type.value] = by_type_in.get(edge.type.value, 0) + 1

    return {
        "node_id": p.node_id,
        "name": node.structural.name,
        "file": node.file_path,
        "type": node.type.value,
        "in_degree": len(edges_in),
        "out_degree": len(edges_out),
        "edges_by_type_out": by_type_out,
        "edges_by_type_in": by_type_in,
        "complexity": node.structural.complexity,
        "lines": node.structural.lines,
        "tags": node.semantic.tags,
    }


def _is_test_path(file_path: str) -> bool:
    """Return True for test/spec files (excluded from entry points)."""
    lowered = (file_path or "").replace("\\", "/").lower()
    segments = set(lowered.split("/"))
    if segments & {"test", "tests", "spec", "__tests__"}:
        return True
    base = lowered.rsplit("/", 1)[-1]
    return base.startswith("test_") or base.endswith(("_test.py", ".test.ts", ".spec.ts"))


async def architecture(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/architecture`` — one-call codebase overview.

    Ports the codebase-memory ``get_architecture`` win: logical packages,
    real entry points (tests excluded), languages, routes, hotspots,
    layers, boundaries, file tree, and cohesive communities in a single
    response so agents need not fan out to telemetry + community/*.
    """
    from smp.protocol.handlers.community import _detect_components

    graph = ctx["graph"]
    top_k = int(params.get("top_k", 10) or 10)
    aspects = params.get("aspects") or ["all"]

    nodes = await graph.find_nodes()
    node_count = len(nodes)
    edge_count = await graph.count_edges()

    def want(name: str) -> bool:
        return "all" in aspects or "overview" in aspects or name in aspects

    # Logical packages: segment after the repo root (smp, tests, benchmarks).
    packages: dict[str, int] = {}
    languages: dict[str, int] = {}
    file_tree: dict[str, int] = {}
    for node in nodes:
        fp = (node.file_path or "").replace("\\", "/")
        parts = [p for p in fp.split("/") if p not in ("", ".")]
        pkg = "(root)"
        if "SMP" in parts:
            idx = len(parts) - 1 - parts[::-1].index("SMP")
            pkg = parts[idx + 1] if idx + 1 < len(parts) else "(root)"
            # test_realworld/foo.py -> test_realworld; smp/engine/q.py -> smp.
        elif parts:
            pkg = parts[0] if len(parts) == 1 else parts[-2]
        packages[pkg] = packages.get(pkg, 0) + 1
        ext = fp.rsplit(".", 1)[-1].lower() if "." in fp.rsplit("/", 1)[-1] else ""
        lang = {
            "py": "Python",
            "js": "JavaScript",
            "ts": "TypeScript",
            "tsx": "TypeScript",
            "java": "Java",
            "go": "Go",
            "rs": "Rust",
            "rb": "Ruby",
            "php": "PHP",
            "c": "C",
            "h": "C++",
            "cpp": "C++",
            "cs": "C#",
            "swift": "Swift",
            "kt": "Kotlin",
            "m": "MATLAB",
            "toml": "TOML",
            "yaml": "YAML",
            "yml": "YAML",
            "md": "Markdown",
        }.get(ext, ext or "unknown")
        languages[lang] = languages.get(lang, 0) + 1
        if "SMP" in parts:
            idx = len(parts) - 1 - parts[::-1].index("SMP")
            directory = "/".join(parts[idx + 1 : -1]) or "(root)"
        else:
            directory = "/".join(parts[:-1]) or "(root)"
        file_tree[directory] = file_tree.get(directory, 0) + 1

    scored: list[dict[str, Any]] = []
    entry_points: list[dict[str, Any]] = []
    routes: list[dict[str, Any]] = []
    for node in nodes:
        try:
            in_deg, out_deg = await graph.get_node_degree(node.id)
        except (NotImplementedError, AttributeError):
            outs = await graph.get_edges(node.id, direction="outgoing")
            ins = await graph.get_edges(node.id, direction="incoming")
            out_deg, in_deg = len(outs), len(ins)
        degree = in_deg + out_deg
        scored.append(
            {
                "node_id": node.id,
                "name": node.structural.name,
                "file": node.file_path,
                "type": node.type.value,
                "in_degree": in_deg,
                "out_degree": out_deg,
                "degree": degree,
            }
        )
        name_lower = (node.structural.name or "").lower()
        is_test = _is_test_path(node.file_path) or name_lower.startswith("test_")
        # Routes: HTTP verb decorators (@app.get("/path"), @router.post ...).
        for dec in node.semantic.decorators or []:
            text = dec.lstrip("@").strip()
            verb = text.split(".")[-1].split("(")[0].lower()
            if verb in _HTTP_VERBS and not is_test:
                import re as _re

                m = _re.search(r"""['\"]([^'\",)]+)['\"]""", text)
                url = m.group(1) if m else node.file_path
                routes.append(
                    {
                        "method": verb.upper(),
                        "path": url,
                        "handler": node.structural.name,
                        "node_id": node.id,
                    }
                )
        if is_test:
            continue
        # Real entry points: mains/CLIs, not dunders, wrappers, or registry fns.
        if (
            node.type.value in ("Function", "Class")
            and in_deg == 0
            and out_deg > 0
            and not name_lower.startswith(("__", "test_", "smp_", "tool_"))
            and name_lower not in {"tool_fn", "_make_tool", "_call_rpc", "_get_context"}
            and (
                name_lower in {"main", "cli", "app", "serve", "run", "mcp", "ingest_directory"}
                or node.file_path.endswith(("cli.py", "main.py", "__main__.py", "mcp.py", "server.py"))
            )
        ):
            entry_points.append({"node_id": node.id, "name": node.structural.name, "file": node.file_path})
    scored.sort(key=lambda d: d["degree"], reverse=True)
    hotspots = scored[:top_k]
    entry_points = entry_points[:top_k]
    routes = routes[:top_k]

    # Layers: entry (sources only) / core (sinks) / internal (isolated).
    layers: list[dict[str, Any]] = []
    for s in scored[: top_k * 2]:
        if s["in_degree"] == 0 and s["out_degree"] > 0:
            layer = "entry"
        elif s["in_degree"] > 5 and s["out_degree"] == 0:
            layer = "core"
        elif s["in_degree"] == 0 and s["out_degree"] == 0:
            layer = "internal"
        else:
            layer = "service"
        layers.append({"name": s["name"], "layer": layer, "reason": f"in={s['in_degree']} out={s['out_degree']}"})

    # Boundaries: package-level coupling (from -> to call counts).
    def _pkg_of(fp: str) -> str:
        segs = [p for p in (fp or "").replace("\\", "/").split("/") if p]
        if "SMP" in segs:
            idx = len(segs) - 1 - segs[::-1].index("SMP")
            return segs[idx + 1] if idx + 1 < len(segs) else "(root)"
        return segs[-2] if len(segs) > 1 else (segs[0] if segs else "(root)")

    id_to_pkg = {n.id: _pkg_of(n.file_path) for n in nodes}
    coupling: dict[tuple[str, str], int] = {}
    for n in nodes[:2000]:
        try:
            outs = await graph.get_edges(n.id, direction="outgoing")
        except (NotImplementedError, AttributeError):
            continue
        src_pkg = id_to_pkg.get(n.id, "(root)")
        for e in outs:
            dst_pkg = id_to_pkg.get(e.target_id, "external")
            if dst_pkg != src_pkg:
                key = (src_pkg, dst_pkg)
                coupling[key] = coupling.get(key, 0) + 1
    boundaries = [
        {"from": a, "to": b, "calls": c} for (a, b), c in sorted(coupling.items(), key=lambda kv: -kv[1])[:top_k]
    ]

    communities: list[dict[str, Any]] = []
    matched = 0
    try:
        components, _, matched = await _detect_components(graph)
        for cid, members in components.items():
            # Cohesion: internal edges / possible edges (sampled via degrees).
            internal = 0
            top: list[str] = []
            pkgs: dict[str, int] = {}
            for mid in members[:20]:
                top.append(mid)
                for m in nodes:
                    if m.id == mid:
                        fpp = (m.file_path or "").replace("\\", "/")
                        segs = [p for p in fpp.split("/") if p]
                        if "SMP" in segs:
                            idx = len(segs) - 1 - segs[::-1].index("SMP")
                            d = segs[idx + 1] if idx + 1 < len(segs) else "(root)"
                        else:
                            d = segs[-2] if len(segs) > 1 else (segs[0] if segs else "(root)")
                        pkgs[d] = pkgs.get(d, 0) + 1
                        break
            size = len(members)
            cohesion = round(min(1.0, (internal + size) / max(1, size * 2)), 4) if size else 0.0
            # Approximate cohesion from size: singletons 0, small clusters high.
            cohesion = round(1.0 / max(1, size**0.5), 4) if size > 1 else 0.0
            communities.append(
                {
                    "community_id": cid,
                    "size": size,
                    "cohesion": cohesion,
                    "top_nodes": top[:5],
                    "packages": sorted(pkgs.items(), key=lambda kv: -kv[1])[:3],
                }
            )
        communities.sort(key=lambda c: int(c["size"]), reverse=True)
        communities = communities[:top_k]
    except Exception:  # noqa: BLE001
        communities = []
        matched = 0

    result: dict[str, Any] = {"nodes": node_count, "edges": edge_count}
    if want("packages") or want("structure"):
        result["packages"] = sorted(packages.items(), key=lambda kv: -kv[1])[:top_k]
    if want("languages"):
        result["languages"] = sorted(languages.items(), key=lambda kv: -kv[1])
    if want("entry_points"):
        result["entry_points"] = entry_points
    if want("hotspots"):
        result["hotspots"] = hotspots
    if want("routes"):
        result["routes"] = routes
    if want("layers"):
        result["layers"] = layers[:top_k]
    if want("boundaries"):
        result["boundaries"] = boundaries
    if want("clusters") or want("structure"):
        result["communities"] = communities
        result["clusters"] = communities
    if want("file_tree"):
        result["file_tree"] = sorted(file_tree.items(), key=lambda kv: -kv[1])[: top_k * 2]
    # Back-compat keys always present.
    result.setdefault("packages", sorted(packages.items(), key=lambda kv: -kv[1])[:top_k])
    result.setdefault("entry_points", entry_points)
    result.setdefault("hotspots", hotspots)
    result.setdefault("communities", communities)
    result.setdefault("boundaries", boundaries)
    result["edges_matched"] = matched
    return result


__all__ = [
    "architecture",
    "conflict",
    "diff",
    "plan",
    "telemetry",
    "telemetry_hot",
    "telemetry_node",
    "why",
]
