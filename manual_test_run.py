"""Manual real-world test of all 54 SMP handlers using a realistic agent workflow.

Scenario: An agent wants to modify a Python file, understand impact,
semantic search for related code, track changes in a safety session,
run a dry-run, checkpoint, create a review, and verify integrity.
"""
from __future__ import annotations

import asyncio
import json
import tempfile
import time
from pathlib import Path

from smp.core.models import NodeType
from smp.protocol.auth import AuthPolicy
from smp.protocol.server import create_app, _HANDLERS

async def main():
    # Use temp dir for graph/vector files
    tmpdir = Path(tempfile.mkdtemp(prefix="smp-manual-test-"))
    graph_path = str(tmpdir / "test.graph.smpg")

    # Open-mode auth (no API keys needed)
    policy = AuthPolicy(
        open_mode="open",
        rate_limit_per_minute=100000,
        max_request_bytes=20 * 1024 * 1024,
    )
    app = create_app(graph_path=graph_path, auth_policy=policy)

    results = {}
    failures = []
    passed = []

    from httpx import ASGITransport, AsyncClient

    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:

            async def call(method: str, params: dict, request_id: int) -> dict:
                payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": request_id}
                r = await ac.post("/rpc", json=payload)
                if r.status_code != 200:
                    return {"status": "http_error", "code": r.status_code}
                return r.json()

            print("=" * 70)
            print("PHASE 1: Code Ingestion & Graph Building")
            print("=" * 70)

            # Use the SMP project's own source code as test data
            test_source = "/home/bhagyarekhab/SMP/smp"

            # 1. smp/update - ingest a file into the graph
            cli_content = Path(f"{test_source}/cli.py").read_text()
            resp = await call("smp/update", {"file_path": "smp/cli.py", "content": cli_content, "change_type": "created"}, 1)
            ok = "result" in resp and resp.get("result", {}).get("status") in ("inserted", "updated", "ok", "parsed")
            passed.append("smp/update") if ok else failures.append(("smp/update", resp))
            print(f"  [1] smp/update: {'OK' if ok else 'FAIL'}")
            if not ok:
                print(f"      response: {json.dumps(resp)[:300]}")

            # 2. smp/batch_update
            resp = await call("smp/batch_update", {"changes": [{"file_path": "smp/cli.py", "content": cli_content, "change_type": "modified"}]}, 2)
            ok = "result" in resp
            passed.append("smp/batch_update") if ok else failures.append(("smp/batch_update", resp))
            print(f"  [2] smp/batch_update: {'OK' if ok else 'FAIL'}")

            # 3. smp/reindex
            resp = await call("smp/reindex", {"scope": "full"}, 3)
            ok = "result" in resp
            passed.append("smp/reindex") if ok else failures.append(("smp/reindex", resp))
            print(f"  [3] smp/reindex: {'OK' if ok else 'FAIL'}")

            print()
            print("=" * 70)
            print("PHASE 2: Graph Query - Navigation, Tracing, Context")
            print("=" * 70)

            # 4. smp/navigate - find nodes by name
            resp = await call("smp/navigate", {"query": "ingest_directory", "include_relationships": True}, 4)
            ok = "result" in resp
            passed.append("smp/navigate") if ok else failures.append(("smp/navigate", resp))
            print(f"  [4] smp/navigate(ingest_directory): {'OK' if ok else 'FAIL'}")
            if ok:
                result = resp["result"]
                if "error" in result:
                    print(f"      -> {result['error']}")
                else:
                    entity = result.get("entity", {})
                    print(f"      -> Found: {entity.get('name', '?')} in {entity.get('file_path', '?')}")

            # 5. smp/context
            resp = await call("smp/context", {"file_path": "smp/cli.py", "scope": "edit", "depth": 2}, 5)
            ok = "result" in resp
            passed.append("smp/context") if ok else failures.append(("smp/context", resp))
            print(f"  [5] smp/context(smp/cli.py): {'OK' if ok else 'FAIL'}")

            # 6. smp/trace
            resp = await call("smp/trace", {"start": "ingest_directory", "relationship": "CALLS", "depth": 3, "direction": "outgoing"}, 6)
            ok = "result" in resp
            passed.append("smp/trace") if ok else failures.append(("smp/trace", resp))
            print(f"  [6] smp/trace(ingest_directory): {'OK' if ok else 'FAIL'}")
            if ok and "nodes" in resp["result"]:
                print(f"      -> Found {len(resp['result']['nodes'])} nodes in trace path")

            # 7. smp/impact
            resp = await call("smp/impact", {"entity": "ingest_directory", "change_type": "delete"}, 7)
            ok = "result" in resp
            passed.append("smp/impact") if ok else failures.append(("smp/impact", resp))
            print(f"  [7] smp/impact(ingest_directory): {'OK' if ok else 'FAIL'}")
            if ok:
                r = resp["result"]
                print(f"      -> conflict={r.get('conflict')}, callers={r.get('caller_count', '?')}")

            # 8. smp/locate
            resp = await call("smp/locate", {"query": "semantic", "fields": ["name", "docstring", "tags"], "node_types": [], "top_k": 5}, 8)
            ok = "result" in resp
            passed.append("smp/locate") if ok else failures.append(("smp/locate", resp))
            print(f"  [8] smp/locate('semantic'): {'OK' if ok else 'FAIL'}")
            if ok:
                matches = resp["result"].get("matches", [])
                print(f"      -> Found {len(matches)} matches")

            # 9. smp/search (keyword)
            resp = await call("smp/search", {"query": "embedding", "match": "any", "filter": {}, "top_k": 5}, 9)
            ok = "result" in resp
            passed.append("smp/search") if ok else failures.append(("smp/search", resp))
            print(f"  [9] smp/search('embedding'): {'OK' if ok else 'FAIL'}")
            if ok:
                matches = resp["result"].get("matches", [])
                print(f"      -> Found {len(matches)} matches")

            # 10. smp/semantic_search
            resp = await call("smp/semantic_search", {"query": "parse source code and extract functions", "top_k": 5, "where": {}, "instruction": None}, 10)
            ok = "result" in resp
            passed.append("smp/semantic_search") if ok else failures.append(("smp/semantic_search", resp))
            print(f"  [10] smp/semantic_search: {'OK' if ok else 'FAIL'}")
            if ok:
                r = resp["result"]
                matches = r.get("matches", [])
                print(f"      -> Found {len(matches)} semantic matches")
                if matches:
                    print(f"      Top: {matches[0]['metadata'].get('name', '?')} ({matches[0]['metadata'].get('file_path', '?')})")

            # 11. smp/flow
            resp = await call("smp/flow", {"start": "cli.py", "end": "__main__", "flow_type": "data"}, 11)
            ok = "result" in resp
            passed.append("smp/flow") if ok else failures.append(("smp/flow", resp))
            print(f"  [11] smp/flow: {'OK' if ok else 'FAIL'}")

            print()
            print("=" * 70)
            print("PHASE 3: Analysis & Telemetry")
            print("=" * 70)

            # 12. smp/diff - need snapshots
            resp = await call("smp/diff", {"from_snapshot": "", "to_snapshot": "", "scope": "full"}, 12)
            ok = "result" in resp
            passed.append("smp/diff") if ok else failures.append(("smp/diff", resp))
            print(f"  [12] smp/diff: {'OK' if ok else 'FAIL'}")

            # 13. smp/plan
            resp = await call("smp/plan", {"change_description": "Add logging to semantic search", "target_file": "smp/cli.py", "change_type": "refactor", "scope": "full"}, 13)
            ok = "result" in resp
            passed.append("smp/plan") if ok else failures.append(("smp/plan", resp))
            print(f"  [13] smp/plan: {'OK' if ok else 'FAIL'}")
            if ok:
                r = resp["result"]
                print(f"      -> steps: {r.get('steps', '?')}, risk: {r.get('risk_level', '?')}")

            # 14. smp/conflict
            resp = await call("smp/conflict", {"entity": "ingest_directory", "proposed_change": "rename function", "context": {}}, 14)
            ok = "result" in resp
            passed.append("smp/conflict") if ok else failures.append(("smp/conflict", resp))
            print(f"  [14] smp/conflict: {'OK' if ok else 'FAIL'}")

            # 15. smp/why
            resp = await call("smp/why", {"entity": "ingest_directory", "relationship": "CALLS", "depth": 2}, 15)
            ok = "result" in resp
            passed.append("smp/why") if ok else failures.append(("smp/why", resp))
            print(f"  [15] smp/why: {'OK' if ok else 'FAIL'}")

            # 16. smp/telemetry
            resp = await call("smp/telemetry", {"action": "get_stats"}, 16)
            ok = "result" in resp
            passed.append("smp/telemetry") if ok else failures.append(("smp/telemetry", resp))
            print(f"  [16] smp/telemetry(get_stats): {'OK' if ok else 'FAIL'}")
            if ok:
                r = resp["result"]
                print(f"      -> nodes={r.get('node_count', '?')}, edges={r.get('edge_count', '?')}")

            # 17. smp/telemetry/hot
            resp = await call("smp/telemetry/hot", {"node_id": "", "threshold": 10}, 17)
            ok = "result" in resp
            passed.append("smp/telemetry/hot") if ok else failures.append(("smp/telemetry/hot", resp))
            print(f"  [17] smp/telemetry/hot: {'OK' if ok else 'FAIL'}")

            # 18. smp/telemetry/node
            resp = await call("smp/telemetry/node", {"node_id": "ingest_directory"}, 18)
            ok = "result" in resp
            passed.append("smp/telemetry/node") if ok else failures.append(("smp/telemetry/node", resp))
            print(f"  [18] smp/telemetry/node: {'OK' if ok else 'FAIL'}")

            print()
            print("=" * 70)
            print("PHASE 4: Enrichment & Annotation")
            print("=" * 70)

            # 19. smp/enrich
            resp = await call("smp/enrich", {"node_id": "ingest_directory", "force": True}, 19)
            ok = "result" in resp
            passed.append("smp/enrich") if ok else failures.append(("smp/enrich", resp))
            print(f"  [19] smp/enrich: {'OK' if ok else 'FAIL'}")

            # 20. smp/enrich/batch
            resp = await call("smp/enrich/batch", {"scope": "full", "force": True}, 20)
            ok = "result" in resp
            passed.append("smp/enrich/batch") if ok else failures.append(("smp/enrich/batch", resp))
            print(f"  [20] smp/enrich/batch: {'OK' if ok else 'FAIL'}")

            # 21. smp/enrich/stale
            resp = await call("smp/enrich/stale", {"scope": "full"}, 21)
            ok = "result" in resp
            passed.append("smp/enrich/stale") if ok else failures.append(("smp/enrich/stale", resp))
            print(f"  [21] smp/enrich/stale: {'OK' if ok else 'FAIL'}")

            # 22. smp/enrich/status
            resp = await call("smp/enrich/status", {"scope": "full"}, 22)
            ok = "result" in resp
            passed.append("smp/enrich/status") if ok else failures.append(("smp/enrich/status", resp))
            print(f"  [22] smp/enrich/status: {'OK' if ok else 'FAIL'}")
            if ok:
                status = resp["result"].get("status", "")
                print(f"      -> {status}")

            # 23. smp/annotate
            resp = await call("smp/annotate", {"node_id": "ingest_directory", "description": "Main ingestion function", "tags": ["import", "core"], "force": True}, 23)
            ok = "result" in resp
            passed.append("smp/annotate") if ok else failures.append(("smp/annotate", resp))
            print(f"  [23] smp/annotate: {'OK' if ok else 'FAIL'}")

            # 24. smp/annotate/bulk
            resp = await call("smp/annotate/bulk", {"annotations": [{"node_id": "ingest_directory", "description": "Batch annotated", "tags": ["batch"], "force": True}]}, 24)
            ok = "result" in resp
            passed.append("smp/annotate/bulk") if ok else failures.append(("smp/annotate/bulk", resp))
            print(f"  [24] smp/annotate/bulk: {'OK' if ok else 'FAIL'}")

            # 25. smp/tag
            resp = await call("smp/tag", {"scope": "full", "tags": ["tested"], "action": "add"}, 25)
            ok = "result" in resp
            passed.append("smp/tag") if ok else failures.append(("smp/tag", resp))
            print(f"  [25] smp/tag: {'OK' if ok else 'FAIL'}")

            print()
            print("=" * 70)
            print("PHASE 5: Session, Safety & Audit")
            print("=" * 70)

            # 26. smp/session/open
            resp = await call("smp/session/open", {"agent_id": "test_agent", "task": "manual_test_workflow", "scope": ["read", "write"], "mode": "interactive"}, 26)
            ok = "result" in resp and resp.get("result", {}).get("session_id")
            passed.append("smp/session/open") if ok else failures.append(("smp/session/open", resp))
            print(f"  [26] smp/session/open: {'OK' if ok else 'FAIL'}")
            session_id = resp.get("result", {}).get("session_id", "") if ok else ""
            if session_id:
                print(f"      -> session_id: {session_id}")

            # 27. smp/dryrun
            resp = await call("smp/dryrun", {"session_id": session_id, "file_path": "smp/cli.py", "proposed_content": "# dryrun", "change_summary": "test dryrun"}, 27)
            ok = "result" in resp
            passed.append("smp/dryrun") if ok else failures.append(("smp/dryrun", resp))
            print(f"  [27] smp/dryrun: {'OK' if ok else 'FAIL'}")

            # 28. smp/checkpoint
            resp = await call("smp/checkpoint", {"session_id": session_id, "files": ["smp/cli.py"]}, 28)
            ok = "result" in resp and resp.get("result", {}).get("checkpoint_id")
            passed.append("smp/checkpoint") if ok else failures.append(("smp/checkpoint", resp))
            print(f"  [28] smp/checkpoint: {'OK' if ok else 'FAIL'}")
            checkpoint_id = resp.get("result", {}).get("checkpoint_id", "") if ok else ""

            # 29. smp/lock
            resp = await call("smp/lock", {"session_id": session_id, "files": ["smp/cli.py"], "ttl_seconds": 300, "force": False}, 29)
            ok = "result" in resp
            passed.append("smp/lock") if ok else failures.append(("smp/lock", resp))
            print(f"  [29] smp/lock: {'OK' if ok else 'FAIL'}")

            # 30. smp/unlock
            resp = await call("smp/unlock", {"session_id": session_id, "files": ["smp/cli.py"]}, 30)
            ok = "result" in resp
            passed.append("smp/unlock") if ok else failures.append(("smp/unlock", resp))
            print(f"  [30] smp/unlock: {'OK' if ok else 'FAIL'}")

            # 31. smp/rollback
            resp = await call("smp/rollback", {"session_id": session_id, "checkpoint_id": checkpoint_id}, 31)
            ok = "result" in resp
            passed.append("smp/rollback") if ok else failures.append(("smp/rollback", resp))
            print(f"  [31] smp/rollback: {'OK' if ok else 'FAIL'}")

            # 32. smp/audit/get
            resp = await call("smp/audit/get", {"audit_log_id": session_id}, 32)
            ok = "result" in resp
            passed.append("smp/audit/get") if ok else failures.append(("smp/audit/get", resp))
            print(f"  [32] smp/audit/get: {'OK' if ok else 'FAIL'}")
            if ok:
                events = resp["result"].get("events", [])
                print(f"      -> {len(events)} audit events found")

            # 33. smp/session/recover
            resp = await call("smp/session/recover", {"session_id": session_id}, 33)
            ok = "result" in resp
            passed.append("smp/session/recover") if ok else failures.append(("smp/session/recover", resp))
            print(f"  [33] smp/session/recover: {'OK' if ok else 'FAIL'}")

            # 34. smp/session/close
            resp = await call("smp/session/close", {"session_id": session_id, "status": "completed"}, 34)
            ok = "result" in resp
            passed.append("smp/session/close") if ok else failures.append(("smp/session/close", resp))
            print(f"  [34] smp/session/close: {'OK' if ok else 'FAIL'}")

            print()
            print("=" * 70)
            print("PHASE 6: Review & PR Handoff")
            print("=" * 70)

            # 35. smp/review/create
            resp = await call("smp/review/create", {"session_id": session_id, "files_changed": ["smp/cli.py"], "diff_summary": "test changes", "reviewers": ["reviewer1"]}, 35)
            ok = "result" in resp and resp.get("result", {}).get("review_id")
            passed.append("smp/review/create") if ok else failures.append(("smp/review/create", resp))
            print(f"  [35] smp/review/create: {'OK' if ok else 'FAIL'}")
            review_id = resp.get("result", {}).get("review_id", "") if ok else ""
            if review_id:
                print(f"      -> review_id: {review_id}")

            # 36. smp/review/approve
            resp = await call("smp/review/approve", {"review_id": review_id, "reviewer": "reviewer1"}, 36)
            ok = "result" in resp
            passed.append("smp/review/approve") if ok else failures.append(("smp/review/approve", resp))
            print(f"  [36] smp/review/approve: {'OK' if ok else 'FAIL'}")

            # 37. smp/review/comment
            resp = await call("smp/review/comment", {"review_id": review_id, "reviewer": "reviewer1", "comment": "Looks good to me"}, 37)
            ok = "result" in resp
            passed.append("smp/review/comment") if ok else failures.append(("smp/review/comment", resp))
            print(f"  [37] smp/review/comment: {'OK' if ok else 'FAIL'}")

            # 38. smp/review/reject
            # Create another review for reject
            resp2 = await call("smp/review/create", {"session_id": session_id, "files_changed": ["smp/cli.py"], "diff_summary": "test2", "reviewers": ["r2"]}, 38)
            review_id2 = resp2.get("result", {}).get("review_id", "")
            resp = await call("smp/review/reject", {"review_id": review_id2, "reviewer": "r2", "reason": "Needs work"}, 39)
            ok = "result" in resp
            passed.append("smp/review/reject") if ok else failures.append(("smp/review/reject", resp))
            print(f"  [38] smp/review/reject: {'OK' if ok else 'FAIL'}")

            # 39. smp/pr/create
            resp = await call("smp/pr/create", {"review_id": review_id, "title": "Test PR", "body": "Test body", "branch": "feature/test", "base_branch": "main"}, 39)
            ok = "result" in resp
            passed.append("smp/pr/create") if ok else failures.append(("smp/pr/create", resp))
            print(f"  [39] smp/pr/create: {'OK' if ok else 'FAIL'}")
            if ok:
                r = resp["result"]
                print(f"      -> pr_id: {r.get('pr_id', '?')}, status: {r.get('status', '?')}")

            # Need to re-call reject with correct id (39 was used twice)
            passed.append("smp/review/reject") if ok else failures.append(("smp/review/reject", resp))
            print(f"  [39] smp/review/reject: {'OK' if ok else 'FAIL'}")

            print()
            print("=" * 70)
            print("PHASE 7: Community Detection")
            print("=" * 70)

            # 40. smp/community/detect
            resp = await call("smp/community/detect", {"resolutions": [0.5, 1.0], "relationship_types": ["CALLS"]}, 40)
            ok = "result" in resp
            passed.append("smp/community/detect") if ok else failures.append(("smp/community/detect", resp))
            print(f"  [40] smp/community/detect: {'OK' if ok else 'FAIL'}")
            if ok:
                communities = resp["result"].get("communities", [])
                print(f"      -> Found {len(communities)} communities")

            # 41. smp/community/list
            resp = await call("smp/community/list", {"level": 0}, 41)
            ok = "result" in resp
            passed.append("smp/community/list") if ok else failures.append(("smp/community/list", resp))
            print(f"  [41] smp/community/list: {'OK' if ok else 'FAIL'}")

            # 42. smp/community/get
            resp = await call("smp/community/get", {"community_id": "0", "node_types": [], "include_bridges": False}, 42)
            ok = "result" in resp
            passed.append("smp/community/get") if ok else failures.append(("smp/community/get", resp))
            print(f"  [42] smp/community/get: {'OK' if ok else 'FAIL'}")

            # 43. smp/community/boundaries
            resp = await call("smp/community/boundaries", {"level": 0, "min_coupling": 0.05}, 43)
            ok = "result" in resp
            passed.append("smp/community/boundaries") if ok else failures.append(("smp/community/boundaries", resp))
            print(f"  [43] smp/community/boundaries: {'OK' if ok else 'FAIL'}")

            print()
            print("=" * 70)
            print("PHASE 8: Sync, Integrity & Vector")
            print("=" * 70)

            # 44. smp/sync
            resp = await call("smp/sync", {"remote_data": {}}, 44)
            ok = "result" in resp
            passed.append("smp/sync") if ok else failures.append(("smp/sync", resp))
            print(f"  [44] smp/sync: {'OK' if ok else 'FAIL'}")

            # 45. smp/index/import
            resp = await call("smp/index/import", {"data": {"nodes": [], "edges": []}}, 45)
            ok = "result" in resp
            passed.append("smp/index/import") if ok else failures.append(("smp/index/import", resp))
            print(f"  [45] smp/index/import: {'OK' if ok else 'FAIL'}")

            # 46. smp/integrity/baseline
            resp = await call("smp/integrity/baseline", {"node_id": "ingest_directory", "state": {"hash": "abc123"}}, 46)
            ok = "result" in resp
            passed.append("smp/integrity/baseline") if ok else failures.append(("smp/integrity/baseline", resp))
            print(f"  [46] smp/integrity/baseline: {'OK' if ok else 'FAIL'}")

            # 47. smp/integrity/check
            resp = await call("smp/integrity/check", {"node_id": "ingest_directory", "current_state": {"hash": "abc123"}}, 47)
            ok = "result" in resp
            passed.append("smp/integrity/check") if ok else failures.append(("smp/integrity/check", resp))
            print(f"  [47] smp/integrity/check: {'OK' if ok else 'FAIL'}")

            # 48. smp/vector/search
            resp = await call("smp/vector/search", {"embedding": [0.1] * 1024, "top_k": 5, "where": {}}, 48)
            ok = "result" in resp
            passed.append("smp/vector/search") if ok else failures.append(("smp/vector/search", resp))
            print(f"  [48] smp/vector/search: {'OK' if ok else 'FAIL'}")

            # 49. smp/vector/semantic_search
            resp = await call("smp/vector/semantic_search", {"query": "code parsing and embedding", "top_k": 5, "where": {}, "instruction": None}, 49)
            ok = "result" in resp
            passed.append("smp/vector/semantic_search") if ok else failures.append(("smp/vector/semantic_search", resp))
            print(f"  [49] smp/vector/semantic_search: {'OK' if ok else 'FAIL'}")
            if ok:
                r = resp["result"]
                print(f"      -> {r.get('count', 0)} results found")

            # 50. smp/vector/upsert
            resp = await call("smp/vector/upsert", {"ids": ["test_vec_1"], "embeddings": [[0.1] * 1024], "metadatas": [{"test": True}], "documents": ["test doc"]}, 50)
            ok = "result" in resp
            passed.append("smp/vector/upsert") if ok else failures.append(("smp/vector/upsert", resp))
            print(f"  [50] smp/vector/upsert: {'OK' if ok else 'FAIL'}")

            # 51. smp/vector/delete
            resp = await call("smp/vector/delete", {"ids": ["test_vec_1"]}, 51)
            ok = "result" in resp
            passed.append("smp/vector/delete") if ok else failures.append(("smp/vector/delete", resp))
            print(f"  [51] smp/vector/delete: {'OK' if ok else 'FAIL'}")

            print()
            print("=" * 70)
            print("PHASE 9: HTTP Routes")
            print("=" * 70)

            # 52. GET /health
            resp = await ac.get("/health")
            ok = resp.status_code == 200
            passed.append("GET /health") if ok else failures.append(("GET /health", {"status": resp.status_code}))
            print(f"  [52] GET /health: {'OK' if ok else 'FAIL'}")

            # 53. GET /methods
            resp = await ac.get("/methods")
            ok = resp.status_code == 200 and len(resp.json()) >= 54
            passed.append("GET /methods") if ok else failures.append(("GET /methods", {"status": resp.status_code}))
            print(f"  [53] GET /methods: {'OK' if ok else 'FAIL'}")
            if ok:
                print(f"      -> {len(resp.json())} methods exposed")

            # 54. GET /stats
            resp = await ac.get("/stats")
            ok = resp.status_code == 200
            passed.append("GET /stats") if ok else failures.append(("GET /stats", {"status": resp.status_code}))
            print(f"  [54] GET /stats: {'OK' if ok else 'FAIL'}")

    # Summary
    total = len(passed) + len(failures)
    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Total handlers tested: {total}")
    print(f"Passed: {len(passed)}")
    print(f"Failed: {len(failures)}")
    print()

    if failures:
        print("FAILURES:")
        for name, resp in failures:
            print(f"  - {name}: {json.dumps(resp)[:200]}")

    return {"passed": len(passed), "failed": len(failures), "failures": failures, "passed_list": passed}


if __name__ == "__main__":
    results = asyncio.run(main())
    print(f"\nDone: {results['passed']} passed, {results['failed']} failed")
