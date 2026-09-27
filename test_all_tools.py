#!/usr/bin/env python3
"""Use all 54 SMP tools systematically."""

import json
import requests
import subprocess
import os
from pathlib import Path

BASE_URL = "http://127.0.0.1:8765/rpc"

def call_rpc(method, params):
    payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
    response = requests.post(BASE_URL, json=payload)
    return response.json()

def main():
    print("=== Using ALL 54 SMP Tools ===\n")
    tools_results = {}

    # Define all 54 methods with test parameters
    tools = [
        # === Query & Navigation (8) ===
        ("smp/navigate", {"query": "query"}),
        ("smp/trace", {"start": "query", "relationship": "CALLS", "depth": 2, "direction": "outgoing"}),
        ("smp/context", {"file_path": "/home/bhagyarekhab/SMP/smp/cli.py"}),
        ("smp/impact", {"entity": "query", "change_type": "delete"}),
        ("smp/locate", {"query": "smp", "match": "all"}),
        ("smp/search", {"query": "smp", "match": "any"}),
        ("smp/semantic_search", {"query": "graph", "top_k": 5}),
        ("smp/flow", {"start": "smp/cli.py", "end": "smp/cli.py", "flow_type": "calls"}),

        # === Memory Management (3) ===
        ("smp/update", {"file_path": "/home/bhagyarekhab/SMP/smp/cli.py"}),
        ("smp/batch_update", {"file_paths": ["/home/bhagyarekhab/SMP/smp/cli.py"]}),
        ("smp/reindex", {"directory": "/home/bhagyarekhab/SMP/smp"}),

        # === Analysis & Telemetry (7) ===
        ("smp/diff", {"scope_a": "file:///tmp/smp-demo.smpg", "scope_b": "file:///tmp/smp-demo.smpg"}),
        ("smp/plan", {"change_description": "Add new feature"}),
        ("smp/conflict", {"proposed_changes": []}),
        ("smp/why", {"entity": "query"}),
        ("smp/telemetry", {"action": "get_stats"}),
        ("smp/telemetry/hot", {"action": "hot_nodes"}),
        ("smp/telemetry/node", {"node_id": "query", "action": "get"}),

        # === Enrichment & Annotation (7) ===
        ("smp/enrich", {"node_id": "smp/cli.py"}),
        ("smp/enrich/batch", {"scope": "file_path:glob:/home/bhagyarekhab/SMP/smp/*.py"}),
        ("smp/enrich/stale", {"status": "no_metadata"}),
        ("smp/enrich/status", {"status": "all"}),
        ("smp/annotate", {"node_id": "smp/cli.py", "description": "Test annotation", "tags": ["test", "cli"]}),
        ("smp/annotate/bulk", {"annotations": [{"node_id": "smp/cli.py", "description": "Test", "tags": ["t"]}]}),
        ("smp/tag", {"node_id": "smp/cli.py", "action": "add", "tags": ["important"]}),

        # === Session & Safety (10) ===
        ("smp/session/open", {"agent_id": "test-agent", "task": "test"}),
        ("smp/session/close", {"session_id": "test"}),
        ("smp/session/recover", {"session_id": "test"}),
        ("smp/dryrun", {"file_path": "/home/bhagyarekhab/SMP/smp/cli.py", "new_content": "# test\ndef test(): pass"}),
        ("smp/checkpoint", {"session_id": "test", "node_ids": ["query"]}),
        ("smp/rollback", {"session_id": "test", "checkpoint_id": "test"}),
        ("smp/lock", {"file_path": "/home/bhagyarekhab/SMP/smp/cli.py"}),
        ("smp/unlock", {"file_path": "/home/bhagyarekhab/SMP/smp/cli.py", "lease_id": "test"}),
        ("smp/audit/get", {"session_id": "test"}),

        # === Review & PR Handoff (5) ===
        ("smp/review/create", {"title": "Test Review", "description": "Test"}),
        ("smp/review/approve", {"review_id": "test", "comment": "Looks good"}),
        ("smp/review/reject", {"review_id": "test", "reason": "Needs work"}),
        ("smp/review/comment", {"review_id": "test", "line": 1, "comment": "Fix this"}),
        ("smp/pr/create", {"title": "Test PR"}),

        # === Sandbox Lifecycle (3) ===
        ("smp/sandbox/spawn", {"name": "test-sandbox"}),
        ("smp/sandbox/execute", {"sandbox_id": "test", "command": "echo hello"}),
        ("smp/sandbox/kill", {"sandbox_id": "test"}),

        # === Community Detection (4) ===
        ("smp/community/detect", {"edge_types": ["CALLS", "IMPORTS", "DEPENDS_ON"]}),
        ("smp/community/list", {}),
        ("smp/community/get", {"community_id": 0}),
        ("smp/community/boundaries", {}),

        # === Synchronization & Integrity (4) ===
        ("smp/sync", {"scope": "file_path:/home/bhagyarekhab/SMP/smp"}),
        ("smp/index/import", {"nodes": [], "edges": []}),
        ("smp/integrity/check", {"mode": "store"}),
        ("smp/integrity/baseline", {"node_id": "query"}),

        # === Vector Store (4) ===
        ("smp/vector/search", {"embedding": [0.1] * 1024, "k": 5}),
        ("smp/vector/upsert", {"vectors": [], "metadata": {}}),
        ("smp/vector/delete", {"vector_ids": ["test"]}),
        ("smp/vector/semantic_search", {"query": "test", "k": 5}),
    ]

    total = len(tools)
    successful = 0
    failed = 0
    errors = []

    for method, params in tools:
        try:
            result = call_rpc(method, params)
            if "error" in result:
                failed += 1
                errors.append((method, result["error"].get("message", "Unknown error")))
                print(f"[FAIL] {method}: {result['error'].get('message', 'Unknown')}")
            else:
                successful += 1
                tools_results[method] = result.get("result", {})
                print(f"[OK] {method}")
        except Exception as e:
            failed += 1
            errors.append((method, str(e)))
            print(f"[ERROR] {method}: {e}")

    print(f"\n=== Summary ===")
    print(f"Total: {total}")
    print(f"Successful: {successful}")
    print(f"Failed/Error: {failed}")
    if errors:
        print("\n--- Errors ---")
        for method, err in errors:
            print(f"  {method}: {err}")

if __name__ == "__main__":
    main()
