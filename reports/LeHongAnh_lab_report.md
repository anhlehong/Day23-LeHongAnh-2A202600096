# Day 08 Lab Report

## 1. Team / student

- **Name:** Le Hong Anh
- **MSSV:** 2A202600096
- **Date:** 2025-05-11

## 2. Architecture

The workflow is a LangGraph `StateGraph` with 11 nodes connected by both static edges and conditional routing functions. The overall flow is:

```
START -> intake -> classify -> [conditional routing]
  simple       -> answer -> finalize -> END
  tool         -> tool -> evaluate -> answer -> finalize -> END
  missing_info -> clarify -> finalize -> END
  risky        -> risky_action -> approval -> tool -> evaluate -> answer -> finalize -> END
  error        -> retry -> tool -> evaluate -> [retry loop or dead_letter] -> finalize -> END
```

### Nodes

| Node | Responsibility |
|---|---|
| `intake` | Normalize raw query, strip whitespace, emit first audit event |
| `classify` | Keyword-based routing with priority: risky > tool > missing_info > error > simple |
| `answer` | Produce final response grounded in `tool_results` when available |
| `tool` | Mock tool execution; simulates transient failures for error-route scenarios |
| `evaluate` | Inspect latest tool result for `"ERROR"` string; set `evaluation_result` to `"needs_retry"` or `"success"` |
| `clarify` | Generate clarification question for vague/missing-info queries |
| `risky_action` | Prepare proposed action description for approval gate |
| `approval` | Human-in-the-loop approval (mock by default, real `interrupt()` when `LANGGRAPH_INTERRUPT=true`) |
| `retry` | Increment `attempt` counter and log transient failure |
| `dead_letter` | Log unresolvable failure after max retries exceeded |
| `finalize` | Emit final audit event; all paths converge here before `END` |

### Conditional routing functions

| Function | Decision logic |
|---|---|
| `route_after_classify` | Map route string to next node: simple->answer, tool->tool, missing_info->clarify, risky->risky_action, error->retry |
| `route_after_evaluate` | If `evaluation_result == "needs_retry"` -> retry node, else -> answer node |
| `route_after_retry` | If `attempt >= max_attempts` -> dead_letter, else -> tool (retry loop) |
| `route_after_approval` | If `approved == true` -> tool, else -> clarify |

### Classify node keyword sets

Priority order (highest first):

1. **Risky:** refund, delete, send, cancel, remove, revoke
2. **Tool:** status, order, lookup, check, track, find, search
3. **Missing info:** < 5 words + vague pronoun (it, this, that)
4. **Error:** timeout, fail, failure, error, crash, unavailable
5. **Simple:** default fallback

Words are cleaned with `re.sub(r"[^a-z0-9]", "", w)` to strip punctuation before matching, preventing substring false positives (e.g., "it" inside "item").

## 3. State schema

`AgentState` is a `TypedDict(total=False)` with both overwrite and append-only fields.

| Field | Reducer | Why |
|---|---|---|
| `thread_id` | overwrite | Unique per run, used for checkpointer |
| `scenario_id` | overwrite | Identifies the scenario |
| `query` | overwrite | Normalized user query |
| `route` | overwrite | Current classification result |
| `risk_level` | overwrite | "low" or "high" based on route |
| `attempt` | overwrite | Current retry counter |
| `max_attempts` | overwrite | Retry bound (default 3) |
| `final_answer` | overwrite | Final response to user |
| `pending_question` | overwrite | Clarification question for missing_info route |
| `proposed_action` | overwrite | Action description for approval gate |
| `approval` | overwrite | Approval decision dict |
| `evaluation_result` | overwrite | "success" or "needs_retry" — retry loop gate |
| `messages` | **append** (`Annotated[list, add]`) | Audit trail of node messages |
| `tool_results` | **append** (`Annotated[list, add]`) | Accumulated tool outputs across retries |
| `errors` | **append** (`Annotated[list, add]`) | Error log across retries |
| `events` | **append** (`Annotated[list, add]`) | Structured audit events for metrics |

Append-only fields use the `operator.add` reducer so that each node appends without overwriting previous entries. This is critical for auditability and metrics collection.

## 4. Scenario results

### 4a. Sample scenarios (`data/sample/scenarios.jsonl`)

**Summary:** 14 scenarios, **100% success rate**, avg 6.50 nodes visited, 5 total retries, 4 total interrupts.

| Scenario | Expected route | Actual route | Success | Retries | Interrupts |
|---|---|---|:---:|---:|---:|
| S01_simple | simple | simple | Yes | 0 | 0 |
| S02_tool | tool | tool | Yes | 0 | 0 |
| S03_missing | missing_info | missing_info | Yes | 0 | 0 |
| S04_risky | risky | risky | Yes | 0 | 1 |
| S05_error | error | error | Yes | 2 | 0 |
| S06_delete | risky | risky | Yes | 0 | 1 |
| S07_dead_letter | error | error | Yes | 1 | 0 |
| S08_cancel | risky | risky | Yes | 0 | 1 |
| S09_track | tool | tool | Yes | 0 | 0 |
| S10_vague | missing_info | missing_info | Yes | 0 | 0 |
| S11_crash | error | error | Yes | 2 | 0 |
| S12_remove | risky | risky | Yes | 0 | 1 |
| S13_search | tool | tool | Yes | 0 | 0 |
| S14_greeting | simple | simple | Yes | 0 | 0 |

### 4b. Hidden scenarios (`data/scenarios_hidden.jsonl`)

**Summary:** 15 scenarios, **100% success rate**, avg 6.60 nodes visited, 5 total retries, 5 total interrupts.

| Scenario | Expected route | Actual route | Success | Retries | Interrupts |
|---|---|---|:---:|---:|---:|
| G01_simple | simple | simple | Yes | 0 | 0 |
| G02_simple2 | simple | simple | Yes | 0 | 0 |
| G03_tool | tool | tool | Yes | 0 | 0 |
| G04_tool2 | tool | tool | Yes | 0 | 0 |
| G05_tool3 | tool | tool | Yes | 0 | 0 |
| G06_missing | missing_info | missing_info | Yes | 0 | 0 |
| G07_missing2 | missing_info | missing_info | Yes | 0 | 0 |
| G08_risky | risky | risky | Yes | 0 | 1 |
| G09_risky2 | risky | risky | Yes | 0 | 1 |
| G10_risky3 | risky | risky | Yes | 0 | 1 |
| G11_risky4 | risky | risky | Yes | 0 | 1 |
| G12_error | error | error | Yes | 2 | 0 |
| G13_error2 | error | error | Yes | 2 | 0 |
| G14_dead | error | error | Yes | 1 | 0 |
| G15_mixed | risky | risky | Yes | 0 | 1 |

### Why the numbers look this way

- **Simple routes (S01, S14, G01, G02):** 4 nodes — intake, classify, answer, finalize. Shortest path.
- **Tool routes (S02, S09, S13, G03, G04, G05):** 6 nodes — adds tool + evaluate between classify and answer.
- **Missing info (S03, S10, G06, G07):** 4 nodes — intake, classify, clarify, finalize. No tool call needed.
- **Risky routes (S04, S06, S08, S12, G08–G11, G15):** 8 nodes — risky_action + approval + tool + evaluate added to the path. Each fires 1 interrupt (approval node).
- **Error routes (S05, S11, G12, G13):** 10 nodes — retry loop executes twice (transient failure at attempt 0 and 1), succeeds at attempt 2. Two retry events logged.
- **Dead letter (S07, G14):** 5 nodes — `max_attempts=1`, so first retry immediately exceeds limit -> dead_letter. Only 1 retry event.
- **Priority conflict (G15):** "Check refund status for order 456" contains both tool keywords (`check`, `status`, `order`) and risky keyword (`refund`). Risky is checked first → correctly routed to risky with approval.

## 5. Failure analysis

### 1. Retry exhaustion / dead letter

When `tool_node` returns an `"ERROR"` result, `evaluate_node` sets `evaluation_result = "needs_retry"`, and `route_after_evaluate` sends control to the `retry` node. The `retry_or_fallback_node` increments `attempt`, and `route_after_retry` checks `attempt >= max_attempts`. If exceeded, it routes to `dead_letter` instead of looping back to `tool`. This prevents unbounded retry loops.

**Evidence:** S07_dead_letter has `max_attempts=1`. The retry node increments attempt to 1, which equals max_attempts, so `route_after_retry` returns `"dead_letter"`. The dead letter node logs the failure and sets a final answer for manual review.

### 2. Risky action without approval

If a query contains risky keywords (refund, delete, cancel, remove, send, revoke), `classify_node` routes to `risky_action`. The `risky_action_node` prepares a `proposed_action`, and `approval_node` gates execution. Without approval (`approved=False`), `route_after_approval` redirects to `clarify` instead of proceeding to the tool — preventing unauthorized destructive actions.

**Evidence:** S04, S06, S08, S12 all hit the approval node (interrupt_count=1) and have `approval_observed=true` in metrics.

### 3. Keyword priority conflicts

A query like "Check and cancel my order" contains both tool keywords ("check", "order") and risky keywords ("cancel"). The classify node checks risky keywords **first** (highest priority), ensuring destructive actions are never accidentally routed to the tool path without approval. This is tested by the keyword priority ordering in the classify function.

## 6. Persistence / recovery evidence

- **Checkpointer:** `MemorySaver` is wired via `build_checkpointer("memory")` in `persistence.py` and passed to `graph.compile(checkpointer=checkpointer)`.
- **Thread ID:** Each scenario run uses a unique `thread_id` (format: `thread-{scenario_id}`), set in `initial_state()` and passed via `config={"configurable": {"thread_id": state["thread_id"]}}` to `graph.invoke()`.
- **SQLite support:** `persistence.py` includes a `"sqlite"` path using `SqliteSaver` for production-grade persistence. Configurable via `configs/lab.yaml` by setting `checkpointer: sqlite`.
- **State recovery:** With a checkpointer active, LangGraph automatically persists state after each node. If a process crashes mid-execution, re-invoking `graph.invoke()` with the same `thread_id` resumes from the last checkpoint.

## 7. Extension work

### Extended scenario coverage

Added 7 custom scenarios (S08-S14) beyond the required 7, testing additional keyword coverage:

- `cancel`, `remove` (risky keywords not in original scenarios)
- `track`, `search` (tool keywords not in original scenarios)
- `crash` (error keyword not in original scenarios)
- Vague query with `this` pronoun (missing_info edge case)
- Generic greeting (simple fallback)

### Improved keyword-based classification

Enhanced `classify_node` with:
- Full keyword sets per README specification
- Word-boundary matching via regex cleaning (`re.sub`) to prevent substring false positives
- Extended pronoun detection (`it`, `this`, `that`) for missing_info classification

### Streamlit UI with real HITL (Human-in-the-Loop)

Built a full Streamlit application (`streamlit_app.py`) with 4 pages:

1. **Interactive Demo** — Enter any query; risky queries trigger a real `interrupt()` pause. The UI shows Approve/Reject buttons. On approve, the graph resumes via `Command(resume=...)`. On reject, it redirects to the clarify node. This is a genuine LangGraph HITL flow, not mocked.

2. **Batch Scenarios** — Run all 14 scenarios from `scenarios.jsonl` with progress bar, metrics cards, and expandable per-scenario details.

3. **Graph Diagram** — Exports the Mermaid diagram from `graph.get_graph().draw_mermaid()` and renders it live. Also shows a text-based flow summary.

4. **Metrics Dashboard** — Reads `outputs/metrics.json` and displays route distribution bar chart, summary cards (success rate, retries, interrupts), and a full scenario table.

**How to run:** `streamlit run streamlit_app.py`

**HITL flow:**
- `LANGGRAPH_INTERRUPT=true` is set automatically
- When a risky query (e.g., "Refund this customer") reaches `approval_node`, `interrupt()` pauses the graph
- The UI detects the paused state via `graph.get_state(config).next`
- Reviewer clicks Approve or Reject
- `graph.invoke(Command(resume={...}), config)` resumes execution with the decision

### Graph diagram export

The Mermaid diagram is auto-generated from the compiled graph on the Graph Diagram page. This provides a visual confirmation that all nodes and edges are correctly wired.

## 8. Improvement plan

If I had one more day, I would prioritize:

1. **LLM-based classification:** Replace keyword heuristics in `classify_node` with an LLM call (e.g., GPT-4o-mini) using structured output to classify queries. This handles ambiguous queries and unseen phrasing that keyword matching misses.

2. **SQLite persistence with crash-resume demo:** Switch to `checkpointer: sqlite`, kill the process mid-scenario, and demonstrate that re-running with the same `thread_id` resumes from the last completed node.

3. **Parallel fan-out:** Use LangGraph `Send()` API to call multiple mock tools concurrently (e.g., order lookup + payment status), merging results via the `add` reducer on `tool_results`.

4. **Observability:** Add latency tracking (`time.perf_counter()` around each node), structured logging with `rich`, and tracing integration with LangSmith.

5. **Reject/edit flow:** Extend the approval UI to allow reviewers to edit the proposed action text before approving, and add a timeout escalation path.
