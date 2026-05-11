"""Streamlit UI for Day 08 LangGraph Agent Lab.

Demonstrates:
- Interactive scenario execution with real-time node tracking
- Human-in-the-Loop (HITL) approval for risky actions via LangGraph interrupt()
- Graph visualization (Mermaid diagram)
- Metrics dashboard
"""

import json
import os
from pathlib import Path

import streamlit as st

# Enable HITL interrupt mode
os.environ["LANGGRAPH_INTERRUPT"] = "true"

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from langgraph_agent_lab.graph import build_graph
from langgraph_agent_lab.metrics import metric_from_state, summarize_metrics
from langgraph_agent_lab.scenarios import load_scenarios
from langgraph_agent_lab.state import Route, Scenario, initial_state

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="LangGraph Agent Lab",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Session state init ───────────────────────────────────────────────────────
if "checkpointer" not in st.session_state:
    st.session_state.checkpointer = MemorySaver()
if "graph" not in st.session_state:
    st.session_state.graph = build_graph(checkpointer=st.session_state.checkpointer)
if "run_history" not in st.session_state:
    st.session_state.run_history = []
if "thread_counter" not in st.session_state:
    st.session_state.thread_counter = 0


def get_thread_id():
    st.session_state.thread_counter += 1
    return f"streamlit-thread-{st.session_state.thread_counter}"


# ── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("🤖 Agent Lab")
    st.markdown("**Day 08 — LangGraph Agentic Orchestration**")
    st.divider()

    page = st.radio(
        "Navigate",
        ["Interactive Demo", "Batch Scenarios", "Graph Diagram", "Metrics Dashboard"],
        index=0,
    )

    st.divider()
    st.caption("Le Hong Anh — 2A202600096")


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 1: Interactive Demo with HITL
# ══════════════════════════════════════════════════════════════════════════════
if page == "Interactive Demo":
    st.header("Interactive Query Demo")
    st.markdown(
        "Enter a support ticket query. **Risky actions** (refund, delete, cancel...) "
        "will trigger a **Human-in-the-Loop approval** gate via LangGraph `interrupt()`."
    )

    # Preset examples
    preset = st.selectbox(
        "Quick presets",
        [
            "(Custom query)",
            "How do I reset my password?",
            "Please lookup order status for order 12345",
            "Can you fix it?",
            "Refund this customer and send confirmation email",
            "Timeout failure while processing request",
            "Delete customer account after support verification",
            "Cancel my subscription immediately",
            "Track my package shipment please",
        ],
    )

    query = st.text_input(
        "Support ticket query",
        value="" if preset == "(Custom query)" else preset,
        placeholder="Type a support ticket query...",
    )

    col_run, col_clear = st.columns([1, 1])
    with col_clear:
        if st.button("Clear history", use_container_width=True):
            st.session_state.pop("active_run", None)
            st.session_state.checkpointer = MemorySaver()
            st.session_state.graph = build_graph(checkpointer=st.session_state.checkpointer)
            st.rerun()

    with col_run:
        run_clicked = st.button("Run query", type="primary", use_container_width=True, disabled=not query.strip())

    # ── Execute query ────────────────────────────────────────────────────────
    if run_clicked and query.strip():
        thread_id = get_thread_id()
        scenario = Scenario(id=f"interactive-{thread_id}", query=query.strip(), expected_route=Route.SIMPLE)
        state = initial_state(scenario)
        state["thread_id"] = thread_id
        run_config = {"configurable": {"thread_id": thread_id}}

        graph = st.session_state.graph

        # First invocation — may hit interrupt
        result = graph.invoke(state, config=run_config)

        st.session_state.active_run = {
            "thread_id": thread_id,
            "query": query.strip(),
            "result": result,
            "config": run_config,
            "interrupted": False,
            "approved": None,
        }

        # Check if graph is interrupted (pending approval)
        graph_state = graph.get_state(run_config)
        if graph_state.next:
            st.session_state.active_run["interrupted"] = True
            st.session_state.active_run["pending_tasks"] = list(graph_state.next)
        st.rerun()

    # ── Display active run ───────────────────────────────────────────────────
    if "active_run" in st.session_state:
        run = st.session_state.active_run
        result = run["result"]

        st.divider()
        st.subheader(f"Query: \"{run['query']}\"")

        # Route badge
        route = result.get("route", "unknown")
        route_colors = {
            "simple": "green", "tool": "blue", "missing_info": "orange",
            "risky": "red", "error": "violet",
        }
        st.markdown(f"**Route:** :{route_colors.get(route, 'gray')}[{route}] &nbsp; **Risk:** {result.get('risk_level', 'unknown')}")

        # Show node execution trace
        events = result.get("events", [])
        if events:
            st.markdown("#### Execution trace")
            trace_cols = st.columns(min(len(events), 8))
            for i, event in enumerate(events):
                col = trace_cols[i % len(trace_cols)]
                node = event.get("node", "?")
                etype = event.get("event_type", "")
                icon = {
                    "intake": "📥", "classify": "🏷️", "answer": "💬",
                    "tool": "🔧", "evaluate": "🔍", "clarify": "❓",
                    "risky_action": "⚠️", "approval": "✅", "retry": "🔄",
                    "dead_letter": "💀", "finalize": "🏁",
                }.get(node, "⚙️")
                col.markdown(f"{icon} **{node}**\n\n`{etype}`")

        # ── HITL Approval Gate ───────────────────────────────────────────────
        if run["interrupted"] and run["approved"] is None:
            st.divider()
            st.markdown("### 🛑 Human-in-the-Loop Approval Required")
            st.warning(
                f"**Proposed action:** {result.get('proposed_action', 'N/A')}\n\n"
                f"**Risk level:** {result.get('risk_level', 'unknown')}\n\n"
                "The graph is **paused** via `interrupt()`. Choose an action below to resume."
            )

            col_approve, col_reject = st.columns(2)
            with col_approve:
                if st.button("✅ Approve", type="primary", use_container_width=True):
                    graph = st.session_state.graph
                    resumed = graph.invoke(
                        Command(resume={"approved": True, "reviewer": "streamlit-user", "comment": "Approved via UI"}),
                        config=run["config"],
                    )
                    st.session_state.active_run["result"] = resumed
                    st.session_state.active_run["interrupted"] = False
                    st.session_state.active_run["approved"] = True
                    st.rerun()

            with col_reject:
                if st.button("❌ Reject", type="secondary", use_container_width=True):
                    graph = st.session_state.graph
                    resumed = graph.invoke(
                        Command(resume={"approved": False, "reviewer": "streamlit-user", "comment": "Rejected via UI"}),
                        config=run["config"],
                    )
                    st.session_state.active_run["result"] = resumed
                    st.session_state.active_run["interrupted"] = False
                    st.session_state.active_run["approved"] = False
                    st.rerun()

        # ── Final result ─────────────────────────────────────────────────────
        if not run["interrupted"] or run["approved"] is not None:
            st.divider()

            if run.get("approved") is True:
                st.success("**HITL Decision:** Approved by reviewer")
            elif run.get("approved") is False:
                st.error("**HITL Decision:** Rejected by reviewer")

            answer = result.get("final_answer") or result.get("pending_question")
            if answer:
                st.markdown("#### Final Answer")
                st.info(answer)

            # Approval details
            approval = result.get("approval")
            if approval:
                st.markdown("#### Approval Details")
                st.json(approval)

            # Errors
            errors = result.get("errors", [])
            if errors:
                st.markdown("#### Errors / Retries")
                for err in errors:
                    st.warning(err)

            # Tool results
            tool_results = result.get("tool_results", [])
            if tool_results:
                st.markdown("#### Tool Results")
                for tr in tool_results:
                    st.code(tr)

            # Full state expander
            with st.expander("Full state (JSON)"):
                display_state = {k: v for k, v in result.items() if v is not None}
                st.json(display_state)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 2: Batch Scenarios
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Batch Scenarios":
    st.header("Batch Scenario Runner")
    st.markdown("Run all scenarios from `data/sample/scenarios.jsonl` and see results.")

    scenarios_path = Path("data/sample/scenarios.jsonl")
    if not scenarios_path.exists():
        st.error(f"Scenarios file not found: {scenarios_path}")
    else:
        # Disable interrupt for batch mode
        os.environ["LANGGRAPH_INTERRUPT"] = "false"

        if st.button("Run all scenarios", type="primary"):
            checkpointer = MemorySaver()
            graph = build_graph(checkpointer=checkpointer)
            scenarios = load_scenarios(scenarios_path)
            metrics = []

            progress = st.progress(0, text="Running scenarios...")
            for i, scenario in enumerate(scenarios):
                state = initial_state(scenario)
                run_config = {"configurable": {"thread_id": state["thread_id"]}}
                final_state = graph.invoke(state, config=run_config)
                m = metric_from_state(final_state, scenario.expected_route.value, scenario.requires_approval)
                metrics.append(m)
                progress.progress((i + 1) / len(scenarios), text=f"Scenario {i+1}/{len(scenarios)}: {scenario.id}")

            progress.empty()
            report = summarize_metrics(metrics)
            st.session_state.batch_report = report
            st.session_state.batch_metrics = metrics

        # Re-enable interrupt
        os.environ["LANGGRAPH_INTERRUPT"] = "true"

        if "batch_metrics" in st.session_state:
            report = st.session_state.batch_report
            metrics = st.session_state.batch_metrics

            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Total Scenarios", report.total_scenarios)
            col2.metric("Success Rate", f"{report.success_rate:.0%}")
            col3.metric("Total Retries", report.total_retries)
            col4.metric("Total Interrupts", report.total_interrupts)

            st.divider()
            st.markdown("### Scenario Details")

            for m in metrics:
                icon = "✅" if m.success else "❌"
                route_match = "match" if m.expected_route == m.actual_route else "MISMATCH"
                with st.expander(f"{icon} {m.scenario_id} — {m.expected_route} ({route_match})"):
                    c1, c2, c3, c4 = st.columns(4)
                    c1.markdown(f"**Expected:** `{m.expected_route}`")
                    c2.markdown(f"**Actual:** `{m.actual_route}`")
                    c3.markdown(f"**Retries:** {m.retry_count}")
                    c4.markdown(f"**Interrupts:** {m.interrupt_count}")
                    if m.approval_required:
                        st.markdown(f"**Approval required:** Yes | **Observed:** {'Yes' if m.approval_observed else 'No'}")
                    if m.errors:
                        st.warning("Errors: " + "; ".join(m.errors))


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 3: Graph Diagram
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Graph Diagram":
    st.header("Graph Architecture")
    st.markdown("Mermaid diagram exported from the compiled LangGraph `StateGraph`.")

    try:
        graph = st.session_state.graph
        mermaid_code = graph.get_graph().draw_mermaid()
        st.markdown(f"```mermaid\n{mermaid_code}\n```")

        with st.expander("Raw Mermaid code"):
            st.code(mermaid_code, language="text")

        # Also show the text-based architecture
        st.divider()
        st.markdown("### Flow summary")
        st.code(
            "START -> intake -> classify -> [conditional routing]\n"
            "  simple       -> answer -> finalize -> END\n"
            "  tool         -> tool -> evaluate -> answer -> finalize -> END\n"
            "  missing_info -> clarify -> finalize -> END\n"
            "  risky        -> risky_action -> approval -> [HITL] -> tool -> evaluate -> answer -> finalize -> END\n"
            "  error        -> retry -> tool -> evaluate -> [retry loop or dead_letter] -> finalize -> END",
            language="text",
        )
    except Exception as e:
        st.error(f"Could not generate diagram: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 4: Metrics Dashboard
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Metrics Dashboard":
    st.header("Metrics Dashboard")

    metrics_path = Path("outputs/metrics.json")
    if metrics_path.exists():
        data = json.loads(metrics_path.read_text(encoding="utf-8"))

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Scenarios", data["total_scenarios"])
        col2.metric("Success Rate", f"{data['success_rate']:.0%}")
        col3.metric("Avg Nodes Visited", f"{data['avg_nodes_visited']:.1f}")
        col4.metric("Total Retries", data["total_retries"])

        st.divider()

        # Route distribution
        st.markdown("### Route Distribution")
        route_counts = {}
        for sm in data["scenario_metrics"]:
            r = sm["actual_route"] or "unknown"
            route_counts[r] = route_counts.get(r, 0) + 1
        col_chart, col_table = st.columns([1, 1])
        with col_chart:
            st.bar_chart(route_counts)
        with col_table:
            st.dataframe(
                [{"Route": k, "Count": v} for k, v in sorted(route_counts.items())],
                use_container_width=True,
            )

        st.divider()

        # Detailed table
        st.markdown("### All Scenario Metrics")
        table_data = []
        for sm in data["scenario_metrics"]:
            table_data.append({
                "Scenario": sm["scenario_id"],
                "Expected": sm["expected_route"],
                "Actual": sm["actual_route"],
                "Success": "✅" if sm["success"] else "❌",
                "Nodes": sm["nodes_visited"],
                "Retries": sm["retry_count"],
                "Interrupts": sm["interrupt_count"],
                "Approval Req": "Yes" if sm["approval_required"] else "",
                "Approval Obs": "Yes" if sm["approval_observed"] else "",
            })
        st.dataframe(table_data, use_container_width=True, hide_index=True)

        st.divider()
        with st.expander("Raw metrics.json"):
            st.json(data)
    else:
        st.warning(
            "No `outputs/metrics.json` found. Run `make run-scenarios` first, "
            "or use the **Batch Scenarios** page to generate metrics."
        )
