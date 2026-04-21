# SMP MCP Tool Guide

This guide describes the Model Context Protocol (MCP) tools provided by the Structural Memory Protocol (SMP). These tools enable LLMs to interact with a codebase's structural and semantic knowledge graph.

## Core Philosophy

The SMP MCP interface allows an LLM to move from a high-level understanding (search/locate) to a detailed structural analysis (navigate/trace/context) and finally to impact analysis or modifications (impact/update).

## Tool Reference

### 1. Knowledge Acquisition & Discovery

#### `smp_search`
Performs a semantic search across the codebase to find relevant entities based on meaning.
- **Use Case**: "Where is the authentication logic handled?" or "Find code related to payment processing."
- **Parameters**:
    - `query` (string): The natural language query.
- **Returns**: A list of the most semantically similar entities (nodes) in the graph.

#### `smp_locate`
Finds specific entities by name or property. More precise than semantic search.
- **Use Case**: "Find the `UserSession` class" or "Locate all functions named `validate_token`."
- **Parameters**:
    - `query` (string): The name or pattern to search for.
    - `node_types` (list[string], optional): Filter by type (e.g., `["Class", "Function"]`).
- **Returns**: A list of matching entities.

#### `smp_navigate`
Explores the relationships around a starting point.
- **Use Case**: "What does the `PaymentGateway` class depend on?" or "What calls the `process_order` function?"
- **Parameters**:
    - `query` (string): The starting entity name or ID.
    - `include_relationships` (bool): Whether to return the edges connecting to other nodes.
- **Returns**: The starting node and its immediate neighborhood in the structural graph.

---

### 2. Deep Analysis & Context

#### `smp_context`
Extracts the structural and semantic context for a specific file.
- **Use Case**: "I need to see the imports and class definitions in `auth_service.py` to understand how it's structured."
- **Parameters**:
    - `file_path` (string): Path to the file.
    - `scope` (string): `edit` (local), `read` (moderate), or `full` (entire file).
- **Returns**: A structured view of the file's contents and its role in the project.

#### `smp_trace`
Traces a chain of dependencies or calls across multiple levels.
- **Use Case**: "Trace the call path from the API endpoint `/login` down to the database query."
- **Parameters**:
    - `start` (string): The starting entity ID/name.
    - `relationship` (string): The edge type to follow (e.g., `CALLS`, `DEFINES`).
    - `depth` (int): How many levels to trace (1-10).
- **Returns**: A path of entities and relationships.

#### `smp_flow`
Finds a path between two specific entities.
- **Use Case**: "How does data flow from the `UserRequest` object to the `DatabaseWriter`?"
- **Parameters**:
    - `start` (string): Starting entity.
    - `end` (string): Ending entity.
    - `flow_type` (string): The type of flow (e.g., `data`, `control`).
- **Returns**: The shortest path between the two entities.

---

### 3. Modification & Impact

#### `smp_impact`
Analyzes what would happen if an entity were changed or deleted.
- **Use Case**: "If I rename the `calculate_tax` function, which other parts of the system will break?"
- **Parameters**:
    - `entity` (string): The entity to analyze.
    - `change_type` (string): `modify` or `delete`.
- **Returns**: A list of affected entities (the "blast radius").

#### `smp_update`
Updates the codebase and the knowledge graph.
- **Use Case**: "Refactor the `calculate_tax` function to support VAT" or "Add a new method to the `User` class."
- **Parameters**:
    - `file_path` (string): Path to the file.
    - `content` (string): The new content of the file.
    - `change_type` (string): `modified` or `added`.
- **Returns**: The result of the parsing and graph update operation.

## Recommended Tool Chains for LLMs

### Task: Understanding a New Feature
1. `smp_search("description of feature")` $\rightarrow$ Find relevant entry points.
2. `smp_locate("EntityName")` $\rightarrow$ Pinpoint the exact classes/functions.
3. `smp_navigate("EntityName")` $\rightarrow$ Understand immediate dependencies.
4. `smp_trace("EntryPoint")` $\rightarrow$ Map the full execution flow.
5. `smp_context("file_path")` $\rightarrow$ Read the actual code for implementation details.

### Task: Safe Refactoring
1. `smp_locate("FunctionToChange")` $\rightarrow$ Find the target.
2. `smp_impact("FunctionToChange", "modify")` $\rightarrow$ Identify all dependent callers.
3. `smp_context("caller_file_path")` $\rightarrow$ Analyze how callers use the function.
4. `smp_update(...)` $\rightarrow$ Apply the change.
5. `smp_update(...)` $\rightarrow$ Update callers to match the new signature.

### Task: Debugging a Bug
1. `smp_search("symptom or error message")` $\rightarrow$ Find potentially related code.
2. `smp_trace("SuspectFunction")` $\rightarrow$ See where the data comes from.
3. `smp_flow("StartNode", "EndNode")` $\rightarrow$ Verify the path the data actually takes.
4. `smp_context("file_path")` $\rightarrow$ Inspect the logic for the bug.
