#!/usr/bin/env python3
"""MCP stdio query-latency benchmark.

Spawns an MCP server subprocess (newline-delimited JSON-RPC over stdio),
performs the initialize handshake, lists tools, then runs warmup + timed
loops against selected tool calls and prints p50/p95 latency per op.

The same harness drives every server, so numbers are directly comparable
across implementations (the server just has to be a stdio MCP server).

Example — time ``smp_locate`` against an existing graph::

    SMP_GRAPH_PATH=/tmp/kernel.smpg \
    python benchmarks/mcp_query_bench.py \
        --cmd "python -m smp.protocol.mcp" \
        --tools '[["smp_locate", {"query": "mutex_lock", "top_k": 5}]]' \
        --repeats 20

Example — see what tools a server exposes::

    python benchmarks/mcp_query_bench.py \
        --cmd "python -m smp.protocol.mcp" --tools "[]"
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time


def read_msg(proc: subprocess.Popen) -> dict:
    line = proc.stdout.readline()
    if not line:
        raise RuntimeError("server stdout closed (process died)")
    return json.loads(line)


def call(proc: subprocess.Popen, method: str, params: dict, rid: int) -> tuple[float, dict]:
    """Send one JSON-RPC request; return ``(elapsed_ms, response)``."""
    payload = {"jsonrpc": "2.0", "id": rid, "method": method, "params": params}
    t0 = time.perf_counter()
    proc.stdin.write(json.dumps(payload) + "\n")
    proc.stdin.flush()
    while True:
        msg = read_msg(proc)
        if msg.get("id") == rid:
            break
    return (time.perf_counter() - t0) * 1000.0, msg


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cmd", required=True, help="MCP server command (run via shell)")
    ap.add_argument(
        "--tools",
        required=True,
        help='JSON list of [toolName, arguments] pairs, e.g. \'[["smp_locate", {"query": "main"}]]\'',
    )
    ap.add_argument("--repeats", type=int, default=20, help="timed calls per tool (default 20)")
    ap.add_argument("--warmup", type=int, default=3, help="untimed warmup calls per tool (default 3)")
    ap.add_argument("--list-only", action="store_true", help="list tools and exit")
    args = ap.parse_args()

    proc = subprocess.Popen(
        args.cmd,
        shell=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )

    try:
        call(
            proc,
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "smp-bench", "version": "0"},
            },
            0,
        )
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        proc.stdin.flush()

        _, resp = call(proc, "tools/list", {}, 1)
        names = sorted(t["name"] for t in resp["result"]["tools"])
        print("TOOLS_N:", len(names))
        print("TOOLS:", json.dumps(names))

        ops = json.loads(args.tools)
        if args.list_only or not ops:
            return

        results: dict[str, dict] = {}
        rid = 10
        for tool, tool_args in ops:
            if tool not in names:
                results[tool] = {"error": "tool not found"}
                continue
            latencies: list[float] = []
            errors = 0
            for i in range(args.warmup + args.repeats):
                rid += 1
                elapsed, msg = call(proc, "tools/call", {"name": tool, "arguments": tool_args}, rid)
                if i < args.warmup:
                    continue
                if msg.get("result", {}).get("isError"):
                    errors += 1
                latencies.append(elapsed)
            if not latencies:
                results[tool] = {"error": "no samples"}
                continue
            latencies.sort()
            results[tool] = {
                "n": len(latencies),
                "p50_ms": round(latencies[len(latencies) // 2], 2),
                "p95_ms": round(latencies[min(len(latencies) - 1, int(len(latencies) * 0.95) - 1)], 2),
                "errors": errors,
            }
        print("BENCH:", json.dumps(results, indent=1))
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
