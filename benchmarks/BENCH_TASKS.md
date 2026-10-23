# SMP A/B Benchmark — Task Prompts

Paste each prompt into a **fresh** OpenCode session on the SMP repo.

- **Run A:** without the `smp` MCP server
- **Run B:** with the `smp` MCP server

Same prompts both times. OpenCode records token usage per session. Then hand
the two sets of numbers back for scoring.

Each task asks for something with a short, checkable answer, so accuracy can
be scored alongside tokens.

---

## Task 1 — Locate a definition

```
In this repo, find where the function `_pop_closed_scopes` is defined.
Give me the file path and the line range.
```

## Task 2 — Find callers

```
Which functions in this repo call `search_nodes`? List the calling
function names and their files.
```

## Task 3 — Impact analysis

```
If I change the signature of `assess_impact` in the query engine, what
else in this codebase could break? List the affected functions and files.
```

## Task 4 — Understand a file

```
Give me an outline of smp/store/graph/parser.py: every class and function
it defines, with line numbers.
```

## Task 5 — Dead code

```
Are there any functions in this repo that are defined but never called
from anywhere else? List them.
```

## Task 6 — Trace a flow across layers

```
Trace the path of a `smp/locate` MCP request from the protocol layer down
to the graph store. Which functions does it pass through, in order?
```

## Task 7 — Plan a new feature

```
I want to add a brand new MCP tool called `smp/summarize`. Which files
would I need to touch, and what would I add to each? Don't write the
code yet, just the plan.
```

## Task 8 — Real change

```
Find the function `search_nodes` in the graph store. I want to add a new
optional keyword argument `max_results` that caps the number of returned
nodes, defaulting to no cap. Show me every place that would need to change,
including callers that should pass it through, and the diff.
```

---

## What to record per run

For each task, capture:

| Metric | Run A (no SMP) | Run B (SMP) |
| --- | --- | --- |
| Input tokens | | |
| Output tokens | | |
| Total tokens | | |
| Wall-clock time | | |
| Turns / messages | | |
| Correct? (score later) | | |

**Important:** do not tell the model whether SMP is available. Let it find
whatever tools it has, so Run A reflects genuine no-graph behaviour.
