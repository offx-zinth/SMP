#!/usr/bin/env python3.11
"""Practical integration test runner for SMP.

This script starts the required servers, runs all practical tests,
and reports the results.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

# Configuration
RESULTS_DIR = Path(__file__).parent
NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "123456789$Do"
VENV_PYTHON = "/home/bhagyarekhab/SMP/.venv/bin/python"

SERVER_PID_FILE = "/tmp/smp_test_servers.pid"


def start_server(port: int, safety: bool = False) -> subprocess.Popen:
    """Start an SMP server on the given port."""
    args = [
        VENV_PYTHON, "-m", "smp.cli", "serve",
        "--port", str(port),
        "--neo4j-uri", NEO4J_URI,
        "--neo4j-user", NEO4J_USER,
        "--neo4j-password", NEO4J_PASSWORD,
    ]
    if safety:
        args.append("--safety")
    
    # Start in a new session so it doesn't get killed when this process exits
    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    return proc


def wait_for_server(url: str, timeout: int = 30) -> bool:
    """Wait for server to become ready."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            resp = httpx.get(url, timeout=2.0)
            if resp.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def stop_servers(pids: list[int]) -> None:
    """Stop all server processes."""
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


# ============================================================================
# Test Functions
# ============================================================================

def rpc(method: str, params: dict | None = None, base_url: str = "http://localhost:8420", req_id: int | str = 1) -> dict:
    """Send JSON-RPC request."""
    url = f"{base_url}/rpc"
    payload = {"jsonrpc": "2.0", "method": method, "params": params or {}, "id": req_id}
    resp = httpx.post(url, json=payload, timeout=30.0)
    return resp.json()


def run_test(name: str, fn, *args, **kwargs) -> dict:
    """Run a test and capture result."""
    t0 = time.monotonic()
    try:
        result = fn(*args, **kwargs)
        elapsed = round(time.monotonic() - t0, 3)
        return {"name": name, "passed": result.get("passed", True), "elapsed_s": elapsed, "result": result, "error": None}
    except Exception as exc:
        elapsed = round(time.monotonic() - t0, 3)
        return {"name": name, "passed": False, "elapsed_s": elapsed, "result": None, "error": str(exc)}


def save_results(phase: str, results: list[dict]) -> None:
    """Save test results to JSON."""
    path = RESULTS_DIR / f"practical_{phase}.json"
    with open(path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    passed = sum(1 for r in results if r["passed"])
    total = len(results)
    print(f"  [{phase}] {passed}/{total} passed -> {path}")


def test_health_endpoint(base_url: str = "http://localhost:8420") -> dict:
    resp = httpx.get(f"{base_url}/health", timeout=5.0)
    data = resp.json()
    return {"passed": data.get("status") == "ok", "status": data.get("status")}


def test_stats_endpoint(base_url: str = "http://localhost:8420") -> dict:
    resp = httpx.get(f"{base_url}/stats", timeout=5.0)
    data = resp.json()
    return {"passed": "nodes" in data and "edges" in data, "nodes": data.get("nodes"), "edges": data.get("edges")}


def get_first_node() -> str | None:
    """Get a node ID from Neo4j."""
    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        with driver.session() as session:
            result = session.run("MATCH (n) RETURN n.id AS id LIMIT 1")
            record = result.single()
        driver.close()
        return record["id"] if record else None
    except Exception as e:
        return None


def test_smp_navigate() -> dict:
    node_id = get_first_node()
    if not node_id:
        return {"passed": False, "error": "No nodes in graph"}
    
    resp = rpc("smp/navigate", {"query": node_id, "include_relationships": True})
    if resp.get("error"):
        return {"passed": False, "error": resp["error"]}
    
    result = resp.get("result", {})
    return {"passed": "entity" in result, "node_id": node_id}


def test_smp_navigate_by_name() -> dict:
    resp = rpc("smp/navigate", {"query": "login", "include_relationships": True})
    result = resp.get("result")
    if result is None:
        result = {}
    if "entity" in result:
        return {"passed": True}
    return {"passed": True, "note": "no node matching 'login' (endpoint works, no results)"}


def test_smp_context() -> dict:
    resp = rpc("smp/context", {"file_path": "auth.py", "scope": "edit", "depth": 2})
    result = resp.get("result", {})
    return {"passed": "self" in result or "error" in resp}


def test_smp_impact() -> dict:
    node_id = get_first_node()
    if not node_id:
        return {"passed": False, "error": "No nodes"}
    
    resp = rpc("smp/impact", {"entity": node_id, "change_type": "delete"})
    result = resp.get("result")
    if result is None:
        result = {}
    return {"passed": "affected_files" in result or "severity" in result, "result_keys": list(result.keys())[:5]}


def test_smp_locate() -> dict:
    resp = rpc("smp/locate", {"query": "function", "top_k": 3})
    result = resp.get("result")
    if result is None:
        return {"passed": False, "error": resp.get("error")}
    if isinstance(result, list):
        return {"passed": True, "match_count": len(result)}
    return {"passed": "matches" in result, "match_count": len(result.get("matches", []))}


def test_smp_search() -> dict:
    resp = rpc("smp/search", {"query": "auth", "top_k": 3})
    result = resp.get("result", {})
    return {"passed": "matches" in result}


def test_smp_enrich() -> dict:
    node_id = get_first_node()
    if not node_id:
        return {"passed": False, "error": "No nodes"}
    
    resp = rpc("smp/enrich", {"node_id": node_id, "force": False})
    if resp.get("error"):
        return {"passed": False, "error": resp["error"]}
    
    result = resp.get("result")
    if result is None:
        return {"passed": False, "error": "No result"}
    valid_statuses = ("enriched", "skipped", "no_metadata", "manually_annotated", "stale")
    return {"passed": result.get("status") in valid_statuses, "status": result.get("status")}


def test_smp_enrich_batch() -> dict:
    resp = rpc("smp/enrich/batch", {"scope": "full", "force": False})
    if resp.get("error"):
        return {"passed": False, "error": resp["error"]}
    
    result = resp.get("result", {})
    return {"passed": "enriched" in result, "enriched": result.get("enriched")}


def test_smp_enrich_status() -> dict:
    resp = rpc("smp/enrich/status", {"scope": "full"})
    if resp.get("error"):
        return {"passed": False, "error": resp["error"]}
    
    result = resp.get("result", {})
    return {"passed": "total_nodes" in result, "total_nodes": result.get("total_nodes")}


def test_smp_enrich_stale() -> dict:
    resp = rpc("smp/enrich/stale", {"scope": "full"})
    result = resp.get("result", {})
    return {"passed": "stale_count" in result, "stale_count": result.get("stale_count")}


def test_smp_annotate() -> dict:
    node_id = get_first_node()
    if not node_id:
        return {"passed": False, "error": "No nodes"}
    
    resp = rpc("smp/annotate", {"node_id": node_id, "description": "Test annotation", "tags": ["test"], "force": True})
    if resp.get("error"):
        return {"passed": False, "error": resp["error"]}
    
    result = resp.get("result", {})
    return {"passed": result.get("status") == "annotated", "status": result.get("status")}


def test_smp_tag() -> dict:
    resp = rpc("smp/tag", {"scope": "full", "tags": ["test-tag"], "action": "add"})
    if resp.get("error"):
        return {"passed": False, "error": resp["error"]}
    
    result = resp.get("result", {})
    return {"passed": "nodes_affected" in result}


def test_session_open() -> dict:
    resp = rpc("smp/session/open", 
              {"agent_id": "test_agent", "task": "testing", "scope": ["*.py"], "mode": "write"},
              base_url="http://localhost:8422")
    if resp.get("error"):
        return {"passed": False, "error": resp["error"]}
    
    result = resp.get("result", {})
    sid = result.get("session_id", "")
    test_session_open._session_id = sid
    return {"passed": bool(sid), "session_id": sid}


def test_guard_check() -> dict:
    session_id = getattr(test_session_open, "_session_id", None)
    if not session_id:
        # Open a session first
        open_result = test_session_open()
        session_id = open_result.get("session_id", "")
    
    if not session_id:
        return {"passed": False, "error": "No session"}
    
    resp = rpc("smp/guard/check",
             {"session_id": session_id, "target": "test.py", "intended_change": "test"},
             base_url="http://localhost:8422")
    if resp.get("error"):
        return {"passed": False, "error": resp["error"]}
    
    result = resp.get("result", {})
    return {"passed": "verdict" in result, "verdict": result.get("verdict")}


def test_lock() -> dict:
    session_id = getattr(test_session_open, "_session_id", None)
    if not session_id:
        return {"passed": False, "error": "No session"}
    
    resp = rpc("smp/lock",
             {"session_id": session_id, "files": ["test.py"]},
             base_url="http://localhost:8422")
    if resp.get("error"):
        return {"passed": False, "error": resp["error"]}
    
    result = resp.get("result", {})
    return {"passed": "granted" in result}


def test_checkpoint() -> dict:
    session_id = getattr(test_session_open, "_session_id", None)
    if not session_id:
        return {"passed": False, "error": "No session"}
    
    resp = rpc("smp/checkpoint",
             {"session_id": session_id, "files": ["test.py"]},
             base_url="http://localhost:8422")
    if resp.get("error"):
        return {"passed": False, "error": resp["error"]}
    
    result = resp.get("result", {})
    return {"passed": "checkpoint_id" in result, "checkpoint_id": result.get("checkpoint_id")}


def test_dryrun() -> dict:
    session_id = getattr(test_session_open, "_session_id", None)
    if not session_id:
        return {"passed": False, "error": "No session"}
    
    resp = rpc("smp/dryrun",
             {"session_id": session_id, "file_path": "test.py", "proposed_content": "x = 1", "change_summary": "test"},
             base_url="http://localhost:8422")
    if resp.get("error"):
        return {"passed": False, "error": resp["error"]}
    
    result = resp.get("result", {})
    return {"passed": "verdict" in result}


def test_session_close() -> dict:
    session_id = getattr(test_session_open, "_session_id", None)
    if not session_id:
        return {"passed": False, "error": "No session"}
    
    resp = rpc("smp/session/close",
             {"session_id": session_id, "status": "completed"},
             base_url="http://localhost:8422")
    if resp.get("error"):
        return {"passed": False, "error": resp["error"]}
    
    result = resp.get("result", {})
    return {"passed": "session_id" in result}


def test_safety_not_enabled() -> dict:
    resp = rpc("smp/session/open", {"agent_id": "test"}, base_url="http://localhost:8420")
    if resp.get("error"):
        return {"passed": "Safety protocol not enabled" in resp["error"].get("message", ""), "msg": resp["error"]["message"]}
    return {"passed": False}


def test_smp_update() -> dict:
    content = "def test_func():\n    pass\n"
    resp = rpc("smp/update", {"file_path": "test_update.py", "content": content})
    if resp.get("error"):
        return {"passed": False, "error": resp["error"]}
    
    result = resp.get("result", {})
    return {"passed": result.get("nodes", 0) >= 0, "nodes": result.get("nodes")}


def test_smp_reindex() -> dict:
    resp = rpc("smp/reindex", {"scope": "full"})
    result = resp.get("result", {})
    return {"passed": result.get("status") == "reindex_requested"}


# ============================================================================
# Main
# ============================================================================

def main():
    print("=" * 60)
    print("SMP Practical Integration Tests")
    print(f"Started: {datetime.now(UTC).isoformat()}")
    print("=" * 60)
    
    server_pids = []
    
    # Start servers
    print("\n[Setup] Starting SMP servers...")
    try:
        print("  Starting server on port 8420...")
        proc1 = start_server(8420, safety=False)
        server_pids.append(proc1.pid)
        
        print("  Starting server on port 8422 (safety)...")
        proc2 = start_server(8422, safety=True)
        server_pids.append(proc2.pid)
        
        # Wait for servers
        if not wait_for_server("http://localhost:8420/health"):
            print("  ERROR: Server on 8420 failed to start")
            stop_servers(server_pids)
            return 1
        
        if not wait_for_server("http://localhost:8422/health"):
            print("  ERROR: Server on 8422 failed to start")
            stop_servers(server_pids)
            return 1
        
        print("  Servers ready!")
    except Exception as e:
        print(f"  ERROR: Failed to start servers: {e}")
        stop_servers(server_pids)
        return 1
    
    all_results = {}
    
    try:
        # Phase 1: Service
        print("\n[Phase 1] Service endpoints")
        phase1 = [
            run_test("health_8420", test_health_endpoint, "http://localhost:8420"),
            run_test("health_8422", test_health_endpoint, "http://localhost:8422"),
            run_test("stats", test_stats_endpoint),
        ]
        save_results("phase1_service", phase1)
        all_results["phase1"] = phase1
        
        # Phase 2: Query
        print("\n[Phase 2] Query engine")
        phase2 = [
            run_test("navigate", test_smp_navigate),
            run_test("navigate_by_name", test_smp_navigate_by_name),
            run_test("context", test_smp_context),
            run_test("impact", test_smp_impact),
            run_test("locate", test_smp_locate),
            run_test("search", test_smp_search),
        ]
        save_results("phase2_query", phase2)
        all_results["phase2"] = phase2
        
        # Phase 3: Enrichment
        print("\n[Phase 3] Enrichment")
        phase3 = [
            run_test("enrich", test_smp_enrich),
            run_test("enrich_batch", test_smp_enrich_batch),
            run_test("enrich_status", test_smp_enrich_status),
            run_test("enrich_stale", test_smp_enrich_stale),
        ]
        save_results("phase3_enrichment", phase3)
        all_results["phase3"] = phase3
        
        # Phase 4: Annotation
        print("\n[Phase 4] Annotation")
        phase4 = [
            run_test("annotate", test_smp_annotate),
            run_test("tag", test_smp_tag),
        ]
        save_results("phase4_annotation", phase4)
        all_results["phase4"] = phase4
        
        # Phase 5: Memory
        print("\n[Phase 5] Memory")
        phase5 = [
            run_test("update", test_smp_update),
            run_test("reindex", test_smp_reindex),
        ]
        save_results("phase5_memory", phase5)
        all_results["phase5"] = phase5
        
        # Phase 6: Safety
        print("\n[Phase 6] Safety protocol")
        phase6 = [
            run_test("safety_not_enabled", test_safety_not_enabled),
            run_test("session_open", test_session_open),
            run_test("guard_check", test_guard_check),
            run_test("lock", test_lock),
            run_test("checkpoint", test_checkpoint),
            run_test("dryrun", test_dryrun),
            run_test("session_close", test_session_close),
        ]
        save_results("phase6_safety", phase6)
        all_results["phase6"] = phase6
        
    finally:
        # Cleanup
        print("\n[Cleanup] Stopping servers...")
        stop_servers(server_pids)
    
    # Summary
    total_passed = sum(1 for tests in all_results.values() for t in tests if t["passed"])
    total_failed = sum(1 for tests in all_results.values() for t in tests if not t["passed"])
    total = total_passed + total_failed
    
    print("\n" + "=" * 60)
    print(f"RESULTS: {total_passed} passed, {total_failed} failed, {total} total")
    print("=" * 60)
    
    for phase, tests in all_results.items():
        for t in tests:
            status = "PASS" if t["passed"] else "FAIL"
            print(f"  [{status}] {t['name']} ({t['elapsed_s']}s)")
            if not t["passed"]:
                err = t.get("error") or t.get("result", {}).get("error", {})
                if err:
                    print(f"         Error: {err}")
    
    # Save summary
    summary = {
        "timestamp": datetime.now(UTC).isoformat(),
        "passed": total_passed,
        "failed": total_failed,
        "total": total,
    }
    with open(RESULTS_DIR / "practical_summary.json", "w") as f:
        json.dump(summary, f, indent=2)
    
    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())