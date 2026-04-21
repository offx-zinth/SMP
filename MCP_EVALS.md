# SMP MCP Evaluation Suite

This document defines a set of "Golden Scenarios" to evaluate the effectiveness of an LLM using the SMP MCP tools. A successful evaluation is when the LLM uses a logical sequence of tools to arrive at the correct answer.

## Evaluation Dataset: The "Multi-Lang Microservice"
For these evals, assume a repository containing:
- A **Python** API layer (`api.py`)
- A **Rust** high-performance core (`core.rs`)
- A **Java** legacy integration module (`Integration.java`)
- A **TypeScript** frontend client (`client.ts`)

---

## Scenario 1: Cross-Language Dependency Trace
**Question**: "The `api.py` calls a function that eventually triggers a process in `core.rs`. Can you trace the full path from the API endpoint `/process` to the Rust implementation?"

**Expected Tool Sequence**:
1. `smp_locate("process", node_types=["Function"])` $\rightarrow$ Find the endpoint in `api.py`.
2. `smp_navigate("process_endpoint")` $\rightarrow$ See it calls a service method.
3. `smp_trace("service_method", depth=3)` $\rightarrow$ Follow the calls.
4. `smp_search("rust core process")` $\rightarrow$ Find the corresponding Rust function if the trace breaks at the FFI boundary.
5. `smp_flow("api_endpoint", "rust_function")` $\rightarrow$ Confirm the end-to-end path.

**Success Criteria**: The LLM identifies the exact sequence of functions across Python and Rust.

---

## Scenario 2: Impact Analysis of a Breaking Change
**Question**: "We need to change the signature of `calculate_metrics` in `core.rs` to add a `timeout` parameter. What other files and functions will be affected?"

**Expected Tool Sequence**:
1. `smp_locate("calculate_metrics")` $\rightarrow$ Find the function in `core.rs`.
2. `smp_impact("calculate_metrics", "modify")` $\rightarrow$ Identify all callers.
3. `smp_navigate("caller_function")` $\rightarrow$ For each caller, see if it's an internal Rust call or an external FFI call from Python/Java.
4. `smp_context("affected_file.py")` $\rightarrow$ See how the caller is implemented to determine the effort of the change.

**Success Criteria**: The LLM lists all affected functions and files across all languages.

---

## Scenario 3: Logic Bug Localization
**Question**: "Users are reporting that the data in the frontend (`client.ts`) is occasionally reversed. Where in the backend (Python/Rust/Java) could this be happening?"

**Expected Tool Sequence**:
1. `smp_search("reverse", "sort", "order")` $\rightarrow$ Find all entities related to ordering/reversing.
2. `smp_locate("reverse")` $\rightarrow$ Narrow down to specific functions.
3. `smp_trace("reverse_function")` $\rightarrow$ See where this function is called from.
4. `smp_context("file_with_reverse_logic.java")` $\rightarrow$ Inspect the logic for potential bugs.

**Success Criteria**: The LLM identifies the specific file and function responsible for the reversing logic.

---

## Scenario 4: Architectural Understanding
**Question**: "How does the system ensure that the Java integration module stays in sync with the Rust core?"

**Expected Tool Sequence**:
1. `smp_search("sync", "synchronization", "update")` $\rightarrow$ Find synchronization-related entities.
2. `smp_navigate("SyncManager")` $\rightarrow$ See how the manager interacts with both Java and Rust.
3. `smp_flow("JavaModule", "RustCore")` $\rightarrow$ Map the communication path.
4. `smp_context("sync_logic.rs")` $\rightarrow$ Understand the actual synchronization algorithm.

**Success Criteria**: The LLM provides a high-level architectural summary based on the structural graph.

---

## Scenario 5: Safe Refactor with Pre-Flight Guards
**Question**: "Refactor the `validate_input` function in `api.py` to consolidate duplicated sanitization logic. Make sure the change is safe to apply."

**Expected Tool Sequence**:
1. `smp_locate("validate_input", node_types=["Function"])` $\rightarrow$ Find the target function in `api.py`.
2. `smp_impact("validate_input", "modify")` $\rightarrow$ Identify all callers to understand the blast radius.
3. `smp/session/open(agent_id, task="refactor validate_input", scope=["api.py"], mode="write")` $\rightarrow$ Acquire a write session on the target file.
4. `smp/guard/check(session_id, target="validate_input")` $\rightarrow$ Check for hot-node status, zero-coverage flags, or active locks. Abort if `verdict == "red_alert"`.
5. `smp/dryrun(session_id, file_path="api.py", proposed_content=refactored_code)` $\rightarrow$ Perform structural impact assessment on the proposed change.
6. `smp/checkpoint(session_id, files=["api.py"])` $\rightarrow$ Snapshot state before writing.
7. `smp/update(file_path="api.py", content=new_code, change_type="modified")` $\rightarrow$ Sync the updated graph after the write.
8. `smp/session/close(session_id, status="completed")` $\rightarrow$ Release the session.

**Success Criteria**: The LLM follows the full session lifecycle without skipping the guard or dryrun steps. It correctly aborts if the guard returns a blocking verdict.

---

## Scenario 6: Runtime vs. Static Call Discrepancy
**Question**: "Static analysis shows `api.py` does not directly call `auth_check` in `Integration.java`, but we're seeing it in production traces. How is this possible, and which runtime path triggers it?"

**Expected Tool Sequence**:
1. `smp_locate("auth_check")` $\rightarrow$ Find the function node in `Integration.java`.
2. `smp_navigate("auth_check", include_relationships=True)` $\rightarrow$ Inspect edges; note absence of `CALLS_STATIC` from `api.py`.
3. `smp_trace("auth_check", relationship="CALLS_RUNTIME")` $\rightarrow$ Follow only runtime edges to find the DI-injected or metaprogramming-resolved caller chain.
4. `smp_context("api.py")` $\rightarrow$ Inspect the file for dynamic dispatch patterns (e.g., a plugin registry or decorator) that static analysis would miss.
5. `smp_flow("api_module", "auth_check", edge_type="CALLS_RUNTIME")` $\rightarrow$ Confirm the full runtime execution path.

**Success Criteria**: The LLM distinguishes between `CALLS_STATIC` and `CALLS_RUNTIME` edges, correctly identifies the dynamic dispatch mechanism, and explains why static analysis alone is insufficient.

---

## Scenario 7: Hot Node Identification and Test Gap Analysis
**Question**: "Before we start the next sprint, which functions are most risky to change? We want to know what's both frequently called and poorly tested."

**Expected Tool Sequence**:
1. `smp/telemetry/hot(window_days=30)` $\rightarrow$ Retrieve nodes with high heat scores (high churn + high PageRank).
2. `smp_navigate("hot_node_function")` $\rightarrow$ For each hot node, inspect its relationships.
3. `smp/guard/check(target="hot_node_function")` $\rightarrow$ Check for test coverage flags; a `red_alert` verdict confirms zero or weak coverage.
4. `smp_trace("hot_node_function", relationship="TESTS", depth=1)` $\rightarrow$ Find existing test nodes, if any, to assess coverage quality.
5. `smp_context("test_file.py")` $\rightarrow$ Inspect the test implementation to determine if assertions are meaningful or tautological.

**Success Criteria**: The LLM produces a ranked list of high-risk functions with an explanation of their heat score, call depth, and test coverage status. It does not attempt to modify any hot node without first addressing the test gap.

---

## Scenario 8: Multi-Agent Conflict Detection
**Question**: "Two agents are assigned tasks that both require editing `core.rs`. Agent A is refactoring `serialize_payload` and Agent B is optimizing `deserialize_payload`. Will they conflict?"

**Expected Tool Sequence**:
1. `smp_locate("serialize_payload")` $\rightarrow$ Find node for Agent A's target.
2. `smp_locate("deserialize_payload")` $\rightarrow$ Find node for Agent B's target.
3. `smp/plan(tasks=[task_A, task_B])` $\rightarrow$ Submit both planned edits to the SMP planner.
4. `smp/conflict(session_ids=[session_A, session_B])` $\rightarrow$ Detect overlapping file scopes, shared dependencies, or structural coupling between the two functions.
5. `smp_navigate("shared_dependency")` $\rightarrow$ If a conflict is found, inspect the shared node (e.g., a common `PayloadSchema` struct) to understand the coupling.
6. `smp/session/open(..., mode="mvcc")` $\rightarrow$ If no hard conflict, open MVCC sessions so both agents can proceed in parallel isolated sandboxes.

**Success Criteria**: The LLM correctly identifies whether a hard conflict exists. If it does, it proposes serialization of the tasks. If it does not, it opens MVCC sessions rather than unnecessarily blocking one agent.

---

## Scenario 9: Sandbox Execution and Integrity Verification
**Question**: "Agent A has written new tests for `calculate_metrics` in `core.rs`. Verify that the tests are meaningful and not tautological before merging."

**Expected Tool Sequence**:
1. `smp_locate("calculate_metrics")` $\rightarrow$ Find the target function node.
2. `smp_trace("calculate_metrics", relationship="TESTS")` $\rightarrow$ Find all test nodes linked to the function.
3. `smp/sandbox/spawn(base_commit=current_sha)` $\rightarrow$ Spawn an ephemeral microVM with a CoW copy of the codebase.
4. `smp/sandbox/execute(sandbox_id, command="pytest tests/test_core.rs")` $\rightarrow$ Run the test suite inside the sandbox to confirm baseline pass.
5. `smp/verify/integrity(sandbox_id, target="calculate_metrics")` $\rightarrow$ Run the two-gate integrity check: (a) AST data-flow check to confirm `assert()` receives function output; (b) mutation testing to confirm surviving mutants are zero.
6. `smp/sandbox/destroy(sandbox_id)` $\rightarrow$ Tear down the ephemeral environment after verification.

**Success Criteria**: The LLM does not skip the integrity gate. It correctly interprets surviving mutants as a test failure and reports that the tests must be tightened before the merge is approved.

---

## Scenario 10: Community Boundary and Architecture Drift Detection
**Question**: "Our architecture review flagged that the `api.py` module seems to be calling functions deep inside what should be the data layer's private implementation. Is this an actual architecture violation?"

**Expected Tool Sequence**:
1. `smp_locate("api.py", node_types=["File"])` $\rightarrow$ Find the file node and its `community_id`.
2. `smp/community/get(community_id="comm_api_gateway")` $\rightarrow$ Get the community definition, centroid, and declared boundaries.
3. `smp_trace("api_function", relationship="CALLS_STATIC", depth=4)` $\rightarrow$ Follow the call chain from `api.py` into the data layer.
4. `smp/community/boundaries(source_community="comm_api_gateway", target_community="comm_data_layer")` $\rightarrow$ Check if any traversed nodes belong to the data layer's fine-grained community and whether the `BRIDGES` relationship is declared or undeclared.
5. `smp_navigate("undeclared_bridge_node")` $\rightarrow$ Inspect the offending cross-community call to confirm the violation.

**Success Criteria**: The LLM correctly uses community membership (`MEMBER_OF`, `BRIDGES`) to distinguish a declared inter-community interface from an undeclared internal coupling. It reports the specific functions breaching the boundary.

---

## Scenario 11: Incremental Index Sync After a Batch Commit
**Question**: "A developer just pushed a commit that modified 40 files across the Python and Rust layers. How do we efficiently update the structural memory without re-indexing the entire codebase?"

**Expected Tool Sequence**:
1. `smp/merkle/tree(commit_sha=new_sha)` $\rightarrow$ Compute the Merkle tree for the new commit.
2. `smp/sync(local_sha=current_root_hash, remote_sha=new_root_hash)` $\rightarrow$ Diff the two Merkle trees to identify only the changed file-leaf hashes in O(log n).
3. `smp/batch_update(file_paths=[changed_files], change_type="modified")` $\rightarrow$ Re-parse and re-index only the delta files returned by the sync diff.
4. `smp_navigate("re_indexed_function")` $\rightarrow$ Spot-check a key changed node to confirm its edges were correctly re-resolved by the static linker.
5. `smp/community/detect()` $\rightarrow$ Re-run Louvain community detection if the structural diff crosses community boundaries, to update centroids.

**Success Criteria**: The LLM uses `smp/sync` with Merkle diffing rather than triggering a full re-index. It correctly limits `smp/batch_update` to only the changed files and conditionally re-runs community detection.

---

## Scenario 12: Peer Review Handoff and Structured PR Generation
**Question**: "Agent A (Coder) has finished its changes to `Integration.java`. Hand off the work to Agent B (Reviewer) and produce a structured PR."

**Expected Tool Sequence**:
1. `smp/diff(session_id=agent_a_session)` $\rightarrow$ Generate the structural diff: new/modified nodes, added `CALLS` edges, and any changed `CALLS_RUNTIME` edges captured during sandbox execution.
2. `smp/telemetry/hot()` $\rightarrow$ Check if any modified nodes are hot nodes, which should be flagged in the PR for extra scrutiny.
3. `smp/handoff/review(session_id=agent_a_session, reviewer_agent_id="agent_b")` $\rightarrow$ Pass the session and structural diff to Agent B (Reviewer), including the audit log.
4. `smp/handoff/pr(session_id=agent_a_session, title="...", body="...")` $\rightarrow$ Generate the structured PR, embedding the structural diff, runtime edge changes, mutation score, and integrity gate results.
5. `smp/session/close(session_id=agent_a_session, status="handed_off")` $\rightarrow$ Close Agent A's session in `handed_off` state rather than `completed`, preserving the audit trail for Agent B.

**Success Criteria**: The LLM produces a PR that includes structural diff, runtime telemetry, and mutation test results. It correctly closes the session as `handed_off` and does not destroy the audit context.

---

## Scenario 13: Dead Code and Orphan Node Detection
**Question**: "We're planning a cleanup sprint. Which functions in `Integration.java` are never called by any other module, have no tests, and have not been changed in over 90 days?"

**Expected Tool Sequence**:
1. `smp_search("Integration.java", node_types=["Function"])` $\rightarrow$ Enumerate all function nodes in the file.
2. `smp_impact("candidate_function", "delete")` $\rightarrow$ For each candidate, check if `impact` returns zero callers (confirming it is an orphan).
3. `smp_trace("candidate_function", relationship="TESTS", depth=1)` $\rightarrow$ Confirm no `TESTS` edges exist.
4. `smp/telemetry/hot(window_days=90)` $\rightarrow$ Check heat scores; functions with a heat score of zero have not been touched or called in the window.
5. `smp/guard/check(target="candidate_function")` $\rightarrow$ Confirm the node is safe to delete (no lock, no active session referencing it).

**Success Criteria**: The LLM correctly combines orphan detection (zero callers via `smp_impact`), test absence, and telemetry staleness to produce a safe deletion candidate list. It does not flag a function as dead if it has `CALLS_RUNTIME` edges that static analysis missed.

---

## Scenario 14: Taint Flow / SQL Injection Audit
**Question**: "Security review flagged that user-supplied input from the `/search` endpoint in `api.py` might reach a raw SQL call in `Integration.java` without sanitization. Can you confirm the taint path?"

**Expected Tool Sequence**:
1. `smp_locate("search_endpoint", node_types=["Function"])` $\rightarrow$ Find the `/search` handler in `api.py` as the taint source.
2. `smp_trace("search_endpoint", relationship="CALLS_STATIC", depth=5)` $\rightarrow$ Follow the static call chain from the handler downward.
3. `smp_search("raw_sql", "execute", "query", node_types=["Function"])` $\rightarrow$ Find candidate sink functions in `Integration.java` that issue raw SQL.
4. `smp_flow("search_endpoint", "raw_sql_function")` $\rightarrow$ Confirm a direct or indirect path between the source and sink.
5. `smp_navigate("intermediate_function", include_relationships=True)` $\rightarrow$ For each node on the path, check for any `sanitize`, `escape`, or `validate` calls that would break the taint.
6. `smp_context("Integration.java")` $\rightarrow$ Inspect the sink function to confirm user data reaches a string interpolation without parameterization.

**Success Criteria**: The LLM maps the full source-to-sink taint path, correctly identifies whether any sanitization breaks the chain, and names the exact unsanitized SQL call site.

---

## Scenario 15: Performance Regression — Slow Endpoint Trace
**Question**: "The `/report` endpoint in `api.py` has degraded from 80ms to 2s after the last release. Trace the full execution path to find where the latency was introduced."

**Expected Tool Sequence**:
1. `smp_locate("report_endpoint", node_types=["Function"])` $\rightarrow$ Find the handler.
2. `smp/telemetry/hot(window_days=7)` $\rightarrow$ Check if any nodes on the path have a sudden spike in heat score correlating with the release.
3. `smp_trace("report_endpoint", relationship="CALLS_STATIC", depth=6)` $\rightarrow$ Walk the full call chain to the database or Rust layer.
4. `smp_diff(commit_sha_before, commit_sha_after)` $\rightarrow$ Identify which nodes and edges changed between the two releases.
5. `smp_navigate("changed_node")` $\rightarrow$ Inspect the modified function to look for added synchronous I/O, removed caching, or N+1 query patterns.
6. `smp_context("changed_file.py")` $\rightarrow$ Read the full implementation of the suspected bottleneck to confirm.

**Success Criteria**: The LLM narrows the regression to a specific function introduced or modified in the diff, explains the structural change that caused it, and does not guess without evidence.

---

## Scenario 16: Circular Dependency Detection
**Question**: "The build is failing with an import cycle error somewhere between `api.py`, `Integration.java`, and a shared utility. Find the cycle."

**Expected Tool Sequence**:
1. `smp_trace("api_module", relationship="IMPORTS", depth=6)` $\rightarrow$ Walk the import graph starting from `api.py`.
2. `smp_trace("integration_module", relationship="IMPORTS", depth=6)` $\rightarrow$ Walk the import graph from `Integration.java`.
3. `smp_navigate("shared_utility_module", include_relationships=True)` $\rightarrow$ Inspect the utility module's own `IMPORTS` edges to find if it imports back into the caller chain.
4. `smp_flow("api_module", "api_module", relationship="IMPORTS")` $\rightarrow$ Attempt to find a cycle path from the module back to itself.
5. `smp_context("shared_utility.py")` $\rightarrow$ Confirm which specific import statement closes the cycle.

**Success Criteria**: The LLM reconstructs the exact cyclic import chain (e.g., `api.py` → `utils.py` → `Integration.java` → `api.py`) and identifies the single import that, if removed or lazily loaded, would break the cycle.

---

## Scenario 17: Feature Flag Audit
**Question**: "We are removing the `enable_v2_pipeline` feature flag. Find every place it is read, what code it gates, and confirm it is safe to delete."

**Expected Tool Sequence**:
1. `smp_search("enable_v2_pipeline")` $\rightarrow$ Find all variable nodes, constants, or string references matching the flag name.
2. `smp_locate("enable_v2_pipeline", node_types=["Variable", "Function"])` $\rightarrow$ Narrow to the flag's declaration site and reader functions.
3. `smp_trace("flag_reader_function", relationship="CALLS_STATIC", depth=1)` $\rightarrow$ For each reader, find the conditional branches it controls.
4. `smp_navigate("gated_function")` $\rightarrow$ Inspect each gated code path to understand what behavior is enabled vs. disabled.
5. `smp_impact("enable_v2_pipeline", "delete")` $\rightarrow$ Confirm the full set of nodes that would become unreachable or need updating when the flag is removed.
6. `smp/guard/check(target="flag_declaration")` $\rightarrow$ Confirm no active session is currently operating on the flag before deleting it.

**Success Criteria**: The LLM enumerates every read site, maps each to its gated behaviour, and confirms whether both the `true` and `false` branches are still needed before recommending deletion.

---

## Scenario 18: PII Leakage — Sensitive Data Reaching Logs
**Question**: "A compliance audit requires us to verify that no user PII (email, password, token) flows into any logging call anywhere in the system."

**Expected Tool Sequence**:
1. `smp_search("log", "logger", "print", "console.log", node_types=["Function"])` $\rightarrow$ Find all logging sink functions across all four files.
2. `smp_locate("user_model", node_types=["Class", "Interface"])` $\rightarrow$ Find the data model nodes that carry PII fields.
3. `smp_trace("log_function", relationship="CALLS_STATIC", depth=-1)` $\rightarrow$ Walk backwards (callers of the log function) to find which functions pass data to it.
4. `smp_navigate("caller_of_logger", include_relationships=True)` $\rightarrow$ Check if any caller has a `USES` relationship to a PII-carrying variable or model field.
5. `smp_flow("user_model_field", "log_function")` $\rightarrow$ Confirm or deny a direct structural path from the PII field to the logger.
6. `smp_context("offending_file.ts")` $\rightarrow$ Inspect the specific call site to determine if the PII is masked or logged raw.

**Success Criteria**: The LLM either confirms no path exists or identifies the exact variable and log call site where raw PII is exposed. It does not produce false negatives by only checking static edges.

---

## Scenario 19: Third-Party Library Upgrade Impact
**Question**: "We are upgrading `pydantic` from v1 to v2. The `BaseModel.dict()` method is removed in v2. Find every call site in the Python codebase that uses it."

**Expected Tool Sequence**:
1. `smp_search("BaseModel", node_types=["Class"])` $\rightarrow$ Find all classes that inherit from `BaseModel`.
2. `smp_trace("BaseModel_subclass", relationship="INHERITS", depth=2)` $\rightarrow$ Enumerate all subclasses that would be affected.
3. `smp_search(".dict()", "BaseModel.dict")` $\rightarrow$ Find all call nodes invoking the deprecated method.
4. `smp_navigate("dict_call_site")` $\rightarrow$ For each call site, identify the enclosing function and file.
5. `smp_impact("BaseModel.dict", "delete")` $\rightarrow$ Confirm the blast radius across all Python files.
6. `smp_context("affected_file.py")` $\rightarrow$ Inspect each call site to determine whether the replacement is `.model_dump()` or requires a more complex migration.

**Success Criteria**: The LLM enumerates all call sites including those on subclasses, not just direct `BaseModel` references, and categorizes each by migration complexity.

---

## Scenario 20: Finding the Right Extension Point for a New Feature
**Question**: "We want to add a rate-limiting check to all authenticated API routes in `api.py`. Where is the correct place to inject it without modifying each endpoint handler individually?"

**Expected Tool Sequence**:
1. `smp_search("auth", "authenticate", "middleware", node_types=["Function", "Class"])` $\rightarrow$ Find all authentication-related nodes.
2. `smp_trace("authenticate_function", relationship="CALLS_STATIC", depth=1)` $\rightarrow$ Identify what calls the auth function — this reveals if a shared middleware chain exists.
3. `smp_navigate("middleware_chain_node", include_relationships=True)` $\rightarrow$ Inspect the chain's structure to find where a new step can be inserted.
4. `smp/community/get(community_id="comm_api_gateway")` $\rightarrow$ Confirm that the middleware chain is the boundary point for the API Gateway community.
5. `smp_context("api.py")` $\rightarrow$ Read the decorator pattern or framework hook mechanism to confirm the injection point.

**Success Criteria**: The LLM identifies a single, shared injection point (a decorator, middleware stack, or request hook) rather than listing individual endpoint handlers. It does not suggest modifying business logic functions.

---

## Scenario 21: Error Handling Gap Analysis
**Question**: "After a silent failure in production, we need to audit which functions in the Rust and Python layers catch exceptions or `Result::Err` variants but do not propagate or log them."

**Expected Tool Sequence**:
1. `smp_search("except", "unwrap", "catch", "Ok(", "Err(", node_types=["Function"])` $\rightarrow$ Find all functions with error handling constructs.
2. `smp_locate("error_handling_function")` $\rightarrow$ Narrow to functions that handle but do not re-raise or return the error.
3. `smp_navigate("error_swallowing_function", include_relationships=True)` $\rightarrow$ Check if the function has any `CALLS` edge to a logger or a metric emitter after the catch block.
4. `smp_trace("error_swallowing_function", relationship="CALLS_STATIC", depth=1)` $\rightarrow$ Confirm that no downstream call propagates the error either.
5. `smp_context("core.rs")` $\rightarrow$ Read the specific `match Err(e) => {}` or `except Exception: pass` site to confirm the swallow.

**Success Criteria**: The LLM produces a list of functions that silently absorb errors with no logging, metric, or re-raise. It distinguishes between intentional no-ops (documented) and genuine gaps.

---

## Scenario 22: Authentication Bypass Audit
**Question**: "A penetration test found an unauthenticated route. Audit all endpoints in `api.py` to confirm which ones lack an auth middleware call in their execution path."

**Expected Tool Sequence**:
1. `smp_locate("api.py", node_types=["Function"])` $\rightarrow$ Get all route handler functions in the file.
2. `smp_search("require_auth", "verify_token", "is_authenticated", node_types=["Function"])` $\rightarrow$ Find the auth guard functions.
3. `smp_trace("route_handler", relationship="CALLS_STATIC", depth=3)` $\rightarrow$ For each handler, walk its call tree to check if any auth function appears.
4. `smp_flow("route_handler", "require_auth")` $\rightarrow$ Attempt to confirm a path to the auth guard; an empty result means the handler is unprotected.
5. `smp_navigate("unprotected_handler", include_relationships=True)` $\rightarrow$ Inspect the unprotected handler for any inline auth logic that `smp_flow` may have missed.

**Success Criteria**: The LLM produces a definitive two-column list: protected routes and unprotected routes, with evidence from the call graph for each classification.

---

## Scenario 23: Race Condition Detection — Shared Mutable State
**Question**: "We have a suspected race condition in `core.rs`: multiple threads may be modifying `GlobalCache` simultaneously. Map all write paths to this struct."

**Expected Tool Sequence**:
1. `smp_locate("GlobalCache", node_types=["Class", "Variable"])` $\rightarrow$ Find the struct definition in `core.rs`.
2. `smp_trace("GlobalCache", relationship="USES", depth=3)` $\rightarrow$ Find all functions that use the struct.
3. `smp_navigate("write_function", include_relationships=True)` $\rightarrow$ For each user function, determine whether it performs a write operation (mutation of fields).
4. `smp_trace("write_function", relationship="CALLS_RUNTIME", depth=3)` $\rightarrow$ Use runtime edges to find which threads or async tasks actually invoke the write function concurrently.
5. `smp_search("Mutex", "RwLock", "Arc", node_types=["Variable"])` $\rightarrow$ Check if `GlobalCache` is wrapped in a synchronization primitive; if the search returns nothing near the struct definition, the race is confirmed.
6. `smp_context("core.rs")` $\rightarrow$ Read the struct definition and its call sites to confirm absence of locking.

**Success Criteria**: The LLM identifies all write paths to `GlobalCache`, confirms whether a synchronization primitive is present, and enumerates which concurrent callers create the race window.

---

## Scenario 24: Database Schema Migration Safety Check
**Question**: "We need to add a `NOT NULL` constraint to the `user_id` column in the `orders` table. Which functions across Python and Java read or write this column and must be verified before migration?"

**Expected Tool Sequence**:
1. `smp_search("orders", "user_id", node_types=["Variable", "Function", "Class"])` $\rightarrow$ Find all nodes that reference the table or column by name.
2. `smp_locate("OrderModel", node_types=["Class"])` $\rightarrow$ Find the ORM model class that maps to the `orders` table.
3. `smp_trace("OrderModel", relationship="USES", depth=4)` $\rightarrow$ Find all functions that read or write through the model.
4. `smp_navigate("write_function", include_relationships=True)` $\rightarrow$ For each writer, check whether it can produce a `NULL` `user_id` (e.g., optional parameters, default `None`).
5. `smp_impact("OrderModel.user_id", "modify")` $\rightarrow$ Confirm the full set of affected functions across `api.py` and `Integration.java`.
6. `smp_context("Integration.java")` $\rightarrow$ Check the Java layer for raw SQL `INSERT` statements that do not include `user_id`.

**Success Criteria**: The LLM identifies every code path that could emit a `NULL` `user_id`, enabling the team to fix all writers before applying the migration.

---

## Scenario 25: Logging and Observability Gap
**Question**: "We are adding distributed tracing. Find all public functions in `api.py` and `core.rs` that make outbound calls but have no OpenTelemetry span creation."

**Expected Tool Sequence**:
1. `smp_search("span", "tracer", "start_span", "opentelemetry", node_types=["Variable", "Function"])` $\rightarrow$ Find all existing instrumentation points to build a whitelist.
2. `smp_locate("api.py", node_types=["Function"])` $\rightarrow$ Get all public API functions.
3. `smp_trace("api_function", relationship="CALLS_STATIC", depth=2)` $\rightarrow$ Check if the function or its immediate callees include a span creation call.
4. `smp_locate("core.rs", node_types=["Function"])` $\rightarrow$ Get all public Rust functions.
5. `smp_navigate("rust_function", include_relationships=True)` $\rightarrow$ For each function, check for `CALLS` edges to network I/O or DB clients and confirm absence of tracing.
6. `smp/telemetry/hot(window_days=30)` $\rightarrow$ Prioritize the uninstrumented functions by heat score to create a ranked instrumentation backlog.

**Success Criteria**: The LLM produces a prioritized list of uninstrumented functions that make outbound calls, ranked by heat score. It does not flag internal pure functions with no I/O.

---

## Scenario 26: God Class Decomposition Planning
**Question**: "`DataProcessor` in `api.py` has grown to 47 methods. It seems to own responsibilities for validation, transformation, persistence, and event emission. Plan a decomposition."

**Expected Tool Sequence**:
1. `smp_navigate("DataProcessor", include_relationships=True)` $\rightarrow$ Get the full list of methods and all outbound `CALLS` edges.
2. `smp_trace("DataProcessor", relationship="CALLS_STATIC", depth=2)` $\rightarrow$ Map which external modules each method depends on.
3. `smp/community/detect()` $\rightarrow$ Check if the Louvain algorithm has already sub-clustered `DataProcessor`'s methods into distinct fine-grained communities.
4. `smp_navigate("community_centroid_node")` $\rightarrow$ Inspect each detected sub-cluster to confirm it maps to a coherent responsibility.
5. `smp_impact("DataProcessor", "split")` $\rightarrow$ Simulate a split to understand which callers outside the class would need import path updates.
6. `smp/plan(tasks=[split_task_A, split_task_B, split_task_C])` $\rightarrow$ Submit the decomposition plan to the SMP planner to detect intra-plan conflicts before work begins.

**Success Criteria**: The LLM uses community detection to propose a data-driven decomposition (not an opinion-based one), lists the external call sites that need updating, and submits the split tasks through `smp/plan` to catch conflicts.

---

## Scenario 27: Webhook End-to-End Trace
**Question**: "When a `payment.succeeded` webhook arrives from Stripe, trace the complete execution path from the HTTP handler all the way to the database write and any downstream event emissions."

**Expected Tool Sequence**:
1. `smp_search("payment.succeeded", "webhook", node_types=["Function"])` $\rightarrow$ Find the HTTP handler that receives the event.
2. `smp_trace("webhook_handler", relationship="CALLS_STATIC", depth=8)` $\rightarrow$ Follow the full downstream call chain.
3. `smp_navigate("db_write_function", include_relationships=True)` $\rightarrow$ Confirm the database write node and inspect its `DEPENDS_ON` relationships.
4. `smp_search("emit", "publish", "enqueue", node_types=["Function"])` $\rightarrow$ Find any event emission or queue publish calls in the trace.
5. `smp_flow("webhook_handler", "event_emitter")` $\rightarrow$ Confirm the path from handler to downstream event publication.
6. `smp_context("api.py")` $\rightarrow$ Check for idempotency keys or duplicate-event guards in the handler.

**Success Criteria**: The LLM produces a complete sequence diagram narrative: HTTP receipt → validation → DB write → event emission, and flags any missing idempotency guard.

---

## Scenario 28: Understanding a Module as a New Developer (Onboarding)
**Question**: "I'm a new engineer and I've been assigned to the Java integration layer. Give me a structural tour: what does it do, what does it depend on, and what depends on it?"

**Expected Tool Sequence**:
1. `smp/community/get(community_id="comm_java_integration")` $\rightarrow$ Get the high-level community description, centroid function, and declared interfaces.
2. `smp_navigate("Integration.java", include_relationships=True)` $\rightarrow$ Inspect the file node's `IMPORTS`, `DEFINES`, and `DEPENDS_ON` relationships.
3. `smp_trace("Integration.java", relationship="IMPORTS", depth=1)` $\rightarrow$ See what the module imports (its dependencies).
4. `smp_impact("Integration.java", "context")` $\rightarrow$ See what depends on the module (its consumers).
5. `smp_locate("Integration.java", node_types=["Class", "Function"])` $\rightarrow$ List the key public classes and functions to understand the module's API surface.
6. `smp/telemetry/hot(window_days=90)` $\rightarrow$ Identify the most actively changed and called functions to guide where to focus first.

**Success Criteria**: The LLM synthesizes a coherent module overview: purpose, dependencies, consumers, public API surface, and hottest entry points — all from structural data, without reading the full source.

---

## Scenario 29: Cross-Commit Structural Diff Between Two Releases
**Question**: "We need a post-mortem comparing the architecture of `v2.4.0` and `v2.5.0`. What structural changes were introduced — new call paths, deleted functions, new cross-community edges?"

**Expected Tool Sequence**:
1. `smp/merkle/tree(commit_sha="v2.4.0")` $\rightarrow$ Compute the Merkle root for the old release.
2. `smp/merkle/tree(commit_sha="v2.5.0")` $\rightarrow$ Compute the Merkle root for the new release.
3. `smp/sync(local_sha=v2_4_root, remote_sha=v2_5_root)` $\rightarrow$ Diff the two trees to get the list of changed files.
4. `smp_diff(commit_sha_a="v2.4.0", commit_sha_b="v2.5.0")` $\rightarrow$ Generate the structural diff: added/removed nodes and edges, signature changes, new `CALLS` paths.
5. `smp/community/boundaries(compare_sha_a="v2.4.0", compare_sha_b="v2.5.0")` $\rightarrow$ Check whether any new `BRIDGES` relationships appeared (new cross-community coupling that wasn't in v2.4.0).
6. `smp_navigate("new_bridge_node")` $\rightarrow$ Inspect any newly introduced cross-boundary calls for architectural intent or accidental coupling.

**Success Criteria**: The LLM produces a categorized structural changelog: added functions, removed functions, signature changes, and new cross-community couplings, not just a file-level diff.

---

## Scenario 30: Retry and Timeout Pattern Audit
**Question**: "Our system makes outbound HTTP and gRPC calls in Python and Java. Audit all such call sites to confirm each one has an explicit timeout and retry policy."

**Expected Tool Sequence**:
1. `smp_search("http_client", "requests.get", "requests.post", "grpc.stub", "HttpClient", node_types=["Function", "Variable"])` $\rightarrow$ Find all outbound network call sites.
2. `smp_navigate("http_call_site", include_relationships=True)` $\rightarrow$ For each call site, inspect its parameters and `USES` relationships for a `timeout` variable.
3. `smp_search("retry", "backoff", "RetryPolicy", node_types=["Variable", "Class", "Function"])` $\rightarrow$ Find all retry-related constructs.
4. `smp_trace("http_call_site", relationship="CALLS_STATIC", depth=1)` $\rightarrow$ Check if a retry wrapper calls the raw HTTP function rather than the call site having inline retry logic.
5. `smp_context("api.py")` $\rightarrow$ Inspect the specific call sites that returned no timeout or retry edges to confirm the gap.

**Success Criteria**: The LLM enumerates every outbound call site and classifies each as: (a) timeout + retry present, (b) timeout only, (c) retry only, or (d) neither. It does not conflate a global default with an explicit per-call setting.

---

## Scenario 31: Test Flakiness Root Cause Analysis
**Question**: "`test_process_pipeline` in the test suite passes locally but fails intermittently in CI. Trace its structural dependencies to find any shared state or external resources that could cause non-determinism."

**Expected Tool Sequence**:
1. `smp_locate("test_process_pipeline", node_types=["Test"])` $\rightarrow$ Find the test node.
2. `smp_trace("test_process_pipeline", relationship="TESTS", depth=1)` $\rightarrow$ Find the production functions under test.
3. `smp_trace("tested_function", relationship="CALLS_STATIC", depth=4)` $\rightarrow$ Walk the full dependency chain of the tested function.
4. `smp_search("global", "singleton", "cache", "file", "socket", node_types=["Variable"])` $\rightarrow$ Find shared-state or I/O nodes within the dependency chain.
5. `smp_navigate("shared_state_node", include_relationships=True)` $\rightarrow$ Inspect which other test functions also `USES` the same shared node (potential test order dependency).
6. `smp_trace("test_process_pipeline", relationship="CALLS_RUNTIME", depth=4)` $\rightarrow$ Check runtime edges for any dynamic dependency (e.g., a singleton initialized by a different test) that static analysis misses.

**Success Criteria**: The LLM identifies the specific shared resource (a global variable, a cached singleton, or an undrained queue) that is the source of non-determinism, distinguishing static from runtime-only dependencies.

---

## Scenario 32: Blast Radius Assessment Before Deleting a Shared Utility Module
**Question**: "We want to delete `utils/serializers.py` entirely as part of a cleanup. What is the full blast radius across all four language layers?"

**Expected Tool Sequence**:
1. `smp_locate("utils/serializers.py", node_types=["File"])` $\rightarrow$ Find the file node.
2. `smp_impact("utils/serializers.py", "delete")` $\rightarrow$ Get the first-order list of all files and functions that import from it.
3. `smp_trace("serializers_file", relationship="IMPORTS", depth=-1)` $\rightarrow$ Walk the full transitive import graph to find second- and third-order dependents.
4. `smp_navigate("dependent_file", include_relationships=True)` $\rightarrow$ For each dependent, check if it re-exports anything from `serializers.py` to further dependents.
5. `smp/community/boundaries(source_community="comm_utils", target_community="comm_data_layer")` $\rightarrow$ Confirm if removing the file breaks any declared community interface.
6. `smp/plan(tasks=[deletion_task])` $\rightarrow$ Submit the deletion plan to the planner to surface any conflicts with in-flight agent sessions that reference the file.

**Success Criteria**: The LLM reports the full transitive blast radius (not just direct importers), flags any re-exports that silently propagate the dependency, and confirms whether the deletion breaks a community boundary contract.

---

## Scenario 33: Finding All Callers of a Deprecated Interface Before Removal
**Question**: "`ILegacyProcessor` in `Integration.java` is marked deprecated. Before we remove it, find every class that implements it and every call site that uses its methods."

**Expected Tool Sequence**:
1. `smp_locate("ILegacyProcessor", node_types=["Interface"])` $\rightarrow$ Find the interface node.
2. `smp_trace("ILegacyProcessor", relationship="IMPLEMENTS", depth=1)` $\rightarrow$ Find all concrete classes that implement it.
3. `smp_impact("ILegacyProcessor", "delete")` $\rightarrow$ Get all nodes that would be affected by its removal.
4. `smp_trace("implementing_class", relationship="CALLS_STATIC", depth=-1)` $\rightarrow$ Find all callers of the implementing classes' methods.
5. `smp_navigate("caller_function", include_relationships=True)` $\rightarrow$ Determine if callers reference `ILegacyProcessor` by interface type (safe to replace) or by concrete class (harder migration).
6. `smp_context("Integration.java")` $\rightarrow$ Confirm that the replacement interface `IProcessor` is already available and structurally compatible.

**Success Criteria**: The LLM distinguishes interface-typed call sites from concrete-typed ones, lists the migration effort for each, and confirms whether the replacement interface is already present.

---

## Scenario 34: Caching Layer Audit — Cache Hit/Miss Path Analysis
**Question**: "Response times vary wildly for the same `/metrics` endpoint. Determine whether the result is being cached, what invalidates the cache, and which code path bypasses it."

**Expected Tool Sequence**:
1. `smp_locate("metrics_endpoint", node_types=["Function"])` $\rightarrow$ Find the handler.
2. `smp_trace("metrics_endpoint", relationship="CALLS_STATIC", depth=4)` $\rightarrow$ Walk the call chain looking for cache read nodes.
3. `smp_search("cache_get", "cache_set", "redis", "lru_cache", node_types=["Function", "Variable"])` $\rightarrow$ Find all caching primitives in the codebase.
4. `smp_flow("metrics_endpoint", "cache_get")` $\rightarrow$ Confirm whether a cache-read path exists.
5. `smp_search("cache_invalidate", "cache_delete", "cache.clear")` $\rightarrow$ Find cache invalidation sites and trace back to their callers to understand what triggers a miss.
6. `smp_navigate("cache_bypass_function", include_relationships=True)` $\rightarrow$ Identify any function in the call chain that calls the underlying compute directly without checking the cache first.

**Success Criteria**: The LLM produces a clear map of: cache-hit path, cache-miss path, invalidation triggers, and any bypass path — with the specific function responsible for the inconsistency.

---

## Scenario 35: Onboarding a New Protocol Method (Dispatcher Pattern)
**Question**: "I need to add a new `smp/telemetry/latency` endpoint to the SMP server. Where exactly do I add it, and will it conflict with anything?"

**Expected Tool Sequence**:
1. `smp_locate("dispatcher.py", node_types=["File"])` $\rightarrow$ Find the dispatcher to understand the `@rpc_method` registration pattern.
2. `smp_navigate("rpc_method_decorator", include_relationships=True)` $\rightarrow$ Inspect the decorator's `DEFINES` and `CALLS` relationships to understand how handlers are registered.
3. `smp_locate("telemetry.py", node_types=["File"])` $\rightarrow$ Find the existing telemetry handler file where the new method should live.
4. `smp_search("smp/telemetry", node_types=["Function"])` $\rightarrow$ Check existing `smp/telemetry/*` registrations to avoid naming conflicts.
5. `smp_context("server/protocol/handlers/telemetry.py")` $\rightarrow$ Read the existing handler implementations to match style and confirm the correct `ctx.engine` accessor to use.
6. `smp/conflict(planned_method="smp/telemetry/latency")` $\rightarrow$ Confirm no other in-flight agent or PR has already registered this method name.

**Success Criteria**: The LLM identifies the exact file, the decorator syntax, the correct `ctx.engine` accessor, and confirms no naming collision — without suggesting modifications to `dispatcher.py` itself.

---

## Scenario 36: Data Pipeline Provenance Trace
**Question**: "Trace the journey of a raw `event` object from the moment it enters the system via `api.py` to the moment it is persisted to the database, including all transformations applied."

**Expected Tool Sequence**:
1. `smp_locate("ingest_event", node_types=["Function"])` $\rightarrow$ Find the ingestion entry point in `api.py`.
2. `smp_trace("ingest_event", relationship="CALLS_STATIC", depth=8)` $\rightarrow$ Follow the full transformation chain.
3. `smp_navigate("transformation_function", include_relationships=True)` $\rightarrow$ For each node in the chain, identify `USES` edges to schemas or models that describe the shape change.
4. `smp_search("persist", "save", "insert", "commit", node_types=["Function"])` $\rightarrow$ Find the terminal persistence sink.
5. `smp_flow("ingest_event", "persist_function")` $\rightarrow$ Confirm the end-to-end provenance path.
6. `smp_context("core.rs")` $\rightarrow$ Inspect any Rust-layer transformation to confirm whether data is enriched, filtered, or normalized before persistence.

**Success Criteria**: The LLM produces an ordered list of every transformation applied to the event, the function responsible for each, and the final schema shape written to the database.

---

## Scenario 37: Rollback Planning After a Bad Deploy
**Question**: "The deploy of commit `abc123` introduced a regression. We need to roll back. Which files were changed in that commit, and what other live code depends on those exact functions so we can assess rollback risk?"

**Expected Tool Sequence**:
1. `smp/merkle/tree(commit_sha="abc123")` $\rightarrow$ Compute the Merkle tree for the bad commit.
2. `smp/sync(local_sha=prev_root, remote_sha=abc123_root)` $\rightarrow$ Diff to get the exact set of changed files.
3. `smp_diff(commit_sha_a=prev_sha, commit_sha_b="abc123")` $\rightarrow$ Get the node-level structural diff: which functions changed signatures or bodies.
4. `smp_impact("changed_function", "modify")` $\rightarrow$ For each changed function, get the set of callers that depend on its current (broken) signature.
5. `smp/telemetry/hot(window_days=1)` $\rightarrow$ Check if any callers of the changed functions are hot nodes currently under active load.
6. `smp_navigate("hot_caller")` $\rightarrow$ Inspect the hot caller to determine if rolling back the changed function would introduce a second breakage at the call site.

**Success Criteria**: The LLM produces a rollback risk report: files to revert, downstream callers of changed functions, and any callers that have themselves been updated to depend on the new (broken) signature.

---

## Scenario 38: Interface Drift Between TypeScript Client and Python API
**Question**: "`client.ts` is sending a `userId` field in requests, but the Python API handler expects `user_id`. Find all field name mismatches between the frontend client models and the API contracts."

**Expected Tool Sequence**:
1. `smp_locate("client.ts", node_types=["Interface", "Class"])` $\rightarrow$ Find all TypeScript request/response model types.
2. `smp_locate("api.py", node_types=["Class", "Function"])` $\rightarrow$ Find all Python request model classes and handler signatures.
3. `smp_navigate("ts_request_model", include_relationships=True)` $\rightarrow$ Inspect each TS model's field names via its `DEFINES` variable nodes.
4. `smp_navigate("python_request_model", include_relationships=True)` $\rightarrow$ Inspect each Python model's field names.
5. `smp_flow("ts_model_field", "python_model_field")` $\rightarrow$ Attempt to find a structural link between corresponding fields; absence of a link implies a name mismatch.
6. `smp_context("client.ts")` $\rightarrow$ Confirm the serialization/deserialization layer to determine if camelCase→snake_case conversion is supposed to happen automatically.

**Success Criteria**: The LLM produces a field-level mismatch report across all request/response types and determines whether the fix belongs in the serialization layer or the model definitions.

---

## Scenario 39: Identifying Missing Null Checks Before an API Contract Change
**Question**: "We're making the `metadata` field on the `Job` struct in `core.rs` optional (changing from `String` to `Option<String>`). Find every caller that currently assumes it is non-null."

**Expected Tool Sequence**:
1. `smp_locate("Job", node_types=["Class"])` $\rightarrow$ Find the `Job` struct node in `core.rs`.
2. `smp_navigate("Job.metadata", include_relationships=True)` $\rightarrow$ Find all `USES` edges from functions that read the `metadata` field.
3. `smp_trace("metadata_reader_function", relationship="CALLS_STATIC", depth=2)` $\rightarrow$ Walk callers to find who passes the value further downstream without unwrapping.
4. `smp_search("unwrap", ".metadata", "metadata.length", node_types=["Function"])` $\rightarrow$ Find call sites that dereference `metadata` directly, implying a non-null assumption.
5. `smp_impact("Job.metadata", "modify")` $\rightarrow$ Confirm the full blast radius across Python and Java FFI call sites.
6. `smp_context("api.py")` $\rightarrow$ Inspect the Python FFI layer to confirm whether it deserializes `metadata` with or without a null guard.

**Success Criteria**: The LLM enumerates every site that would panic or throw a null pointer exception after the change, classified by language layer and urgency.

---

## Scenario 40: Community Centroid Identification for Graph RAG Routing
**Question**: "We are building a new agent specialization for the 'auth' domain. Which community centroid node should it use as its entry point, and what is the structural boundary of that community?"

**Expected Tool Sequence**:
1. `smp/community/list()` $\rightarrow$ List all detected communities and their Level-0 and Level-1 labels.
2. `smp/community/get(community_id="comm_auth_core")` $\rightarrow$ Retrieve the community metadata: centroid node, member count, intra-community edge density.
3. `smp_navigate("community_centroid_node", include_relationships=True)` $\rightarrow$ Inspect the centroid function's relationships to confirm it is the highest-PageRank node in the cluster.
4. `smp/community/boundaries(source_community="comm_auth_core")` $\rightarrow$ Get all declared `BRIDGES` to neighbouring communities (e.g., `comm_data_layer`, `comm_api_gateway`).
5. `smp_trace("centroid_node", relationship="CALLS_STATIC", depth=3)` $\rightarrow$ Confirm that a walk from the centroid reaches all key auth functions without crossing into an unrelated community.

**Success Criteria**: The LLM returns the centroid node ID, the declared community boundary interfaces, and confirms the centroid is structurally central (not a peripheral node) so the agent's Graph RAG routing is accurate.

---

## Scenario 41: Multi-Repo Index Distribution and Integrity Verification
**Question**: "We are distributing the SMP structural index from the main repo server to a read-only replica used by a remote agent pool. How do we verify the replica received an uncorrupted, complete index?"

**Expected Tool Sequence**:
1. `smp/index/export(output_path="index_snapshot.bin")` $\rightarrow$ Export the current structural index with its Merkle root hash and a cryptographic signature.
2. `smp/merkle/tree(commit_sha=current_sha)` $\rightarrow$ Record the expected root hash on the source.
3. *(On the replica):* `smp/index/import(input_path="index_snapshot.bin")` $\rightarrow$ Import the snapshot on the receiving server.
4. `smp/verify/integrity(mode="index")` $\rightarrow$ Re-compute the Merkle root from the imported data and compare against the exported signature.
5. `smp/sync(local_sha=replica_root, remote_sha=source_root)` $\rightarrow$ If the roots differ, run a Merkle diff to identify which file-leaf hashes are missing or corrupted.
6. `smp/batch_update(file_paths=[corrupted_files])` $\rightarrow$ Re-request only the corrupted file nodes from the source to patch the replica.

**Success Criteria**: The LLM uses Merkle root comparison for O(1) integrity confirmation, falls back to Merkle diff for partial corruption, and targets only the corrupted file nodes for re-transfer rather than re-importing the full index.

---

## Scenario 42: Identifying Overly Broad Session Scopes
**Question**: "Agent A opened a session scoped to the entire repository rather than just the files it needs to modify. Audit its session and narrow the scope before it acquires any locks."

**Expected Tool Sequence**:
1. `smp/session/list(agent_id="agent_a")` $\rightarrow$ Retrieve Agent A's active sessions and their declared scopes.
2. `smp_navigate("broad_scope_session", include_relationships=True)` $\rightarrow$ Inspect the session node to see which files are locked or reserved.
3. `smp/plan(session_id=agent_a_session)` $\rightarrow$ Retrieve the agent's planned tasks to determine which files it will actually touch.
4. `smp_impact("planned_change_function", "modify")` $\rightarrow$ Compute the real blast radius of the planned change to derive the minimum necessary file scope.
5. `smp/session/close(session_id=agent_a_session, status="aborted")` $\rightarrow$ Abort the over-scoped session.
6. `smp/session/open(agent_id="agent_a", scope=[minimal_file_list], mode="write")` $\rightarrow$ Re-open a correctly scoped session.

**Success Criteria**: The LLM computes the minimum required scope from `smp_impact` rather than guessing, correctly aborts the over-scoped session before re-opening, and does not leave a dangling lock.

---

## Scoring Rubric

| Score | Description |
| :--- | :--- |
| **0 - Fail** | LLM failed to find the answer or used tools randomly. |
| **1 - Partial** | LLM found the answer but took an inefficient path or missed some dependencies. |
| **2 - Efficient** | LLM used a logical, minimal sequence of tools to find the correct answer. |
| **3 - Expert** | LLM not only found the answer but provided a comprehensive analysis of the impact/flow. |
