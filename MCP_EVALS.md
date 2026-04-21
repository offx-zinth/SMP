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

## Scoring Rubric

| Score | Description |
| :--- | :--- |
| **0 - Fail** | LLM failed to find the answer or used tools randomly. |
| **1 - Partial** | LLM found the answer but took an inefficient path or missed some dependencies. |
| **2 - Efficient** | LLM used a logical, minimal sequence of tools to find the correct answer. |
| **3 - Expert** | LLM not only found the answer but provided a comprehensive analysis of the impact/flow. |
