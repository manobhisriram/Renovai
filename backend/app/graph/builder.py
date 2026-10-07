"""Graph topology.

    START -> entry router
      initial : intake -> vision -> requirements -> classify -> completeness
                   completeness --(critical info missing)--> clarify_prepare -> clarify_wait [INTERRUPT]
                                   -> requirements_merge -> classify -> completeness   (bounded loop)
                   completeness --(ok / assumptions)--> retrieve -> plan_<category> -> pricing
      replan  : requirements_merge -> classify -> completeness -> ...
      revise  : negotiation_parse --(no budget)--> negotiation_need_budget -> END
                                  --(budget)----> negotiation_refit -> retrieve_alternatives
      shared  : -> quote_reasoning -> validate -> (recommend) -> save_quote -> crm_prepare -> approval_decide
                   approval_decide --(required)--> approval_request -> approval_wait [INTERRUPT] -> approval_apply
                   approved/auto --> crm_sync -> finalize ;  rejected --> finalize

One ``plan_<category>`` node is generated per registered category (see app.categories.registry), so adding a
category never requires editing this file. Every transition is error-guarded: a failed step ends the run with
``state['error']`` set rather than continuing on bad data.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from app.categories.registry import DEFAULT_CATEGORY, PROFILES
from app.graph.nodes import GraphNodes
from app.graph.state import WorkflowState

NODE_LABELS = {
    "intake": "Intake", "vision": "Vision analysis", "requirements": "Requirement extraction", "classify": "Project classification",
    "completeness": "Completeness check", "clarify_prepare": "Clarification", "clarify_wait": "Client reply",
    "requirements_merge": "Merge new details", "retrieve": "RAG retrieval", "retrieve_alternatives": "Alternatives retrieval",
    "pricing": "Pricing & timeline", "negotiation_parse": "Understand new budget", "negotiation_need_budget": "Ask for budget",
    "negotiation_refit": "Re-fit to budget", "quote_reasoning": "Quote reasoning", "validate": "Validation & risk",
    "recommend": "Recommendations", "save_quote": "Save quote version", "crm_prepare": "CRM preparation",
    "approval_decide": "Approval policy", "approval_request": "Approval request", "approval_wait": "Human approval",
    "approval_apply": "Record decision", "crm_sync": "CRM sync", "finalize": "Finalize",
}
INITIAL_PATH = ["intake", "vision", "requirements", "classify", "completeness", "retrieve", "plan", "pricing", "quote_reasoning",
                "validate", "recommend", "save_quote", "crm_prepare", "approval_decide", "approval_wait", "crm_sync", "finalize"]
for _k, _p in PROFILES.items():
    NODE_LABELS[f"plan_{_k}"] = f"Scope planning · {_p.label}"
NODE_LABELS["plan"] = "Scope planning"


def build_graph(deps: Any, checkpointer: Any) -> Any:
    n = GraphNodes(deps)
    ins = n.instrument
    b: Any = StateGraph(WorkflowState)  # typed as Any: LangGraph's overloads reject our instrumented wrappers

    simple = {
        "intake": n.intake, "vision": n.vision, "requirements": n.requirements, "requirements_merge": n.requirements_merge,
        "classify": n.classify, "completeness": n.completeness, "clarify_prepare": n.clarify_prepare, "clarify_wait": n.clarify_wait,
        "retrieve": n.retrieve, "retrieve_alternatives": n.retrieve_alternatives, "pricing": n.pricing,
        "negotiation_parse": n.negotiation_parse, "negotiation_need_budget": n.negotiation_need_budget,
        "negotiation_refit": n.negotiation_refit, "quote_reasoning": n.quote_reasoning, "validate": n.validate,
        "recommend": n.recommend, "save_quote": n.save_quote, "crm_prepare": n.crm_prepare, "approval_decide": n.approval_decide,
        "approval_request": n.approval_request, "approval_wait": n.approval_wait, "approval_apply": n.approval_apply,
        "crm_sync": n.crm_sync, "finalize": n.finalize,
    }
    for name, fn in simple.items():
        b.add_node(name, ins(name, fn))
    for key in PROFILES:
        b.add_node(f"plan_{key}", ins(f"plan_{key}", n.make_planner(key)))

    def guarded(fn: Any, targets: list[str]) -> tuple[Any, dict[str, str]]:
        def route(state: dict[str, Any]) -> str:
            return END if state.get("error") else fn(state)

        return route, {**{t: t for t in targets}, END: END}

    def link(src: str, dst: str) -> None:
        route, mapping = guarded(lambda _s: dst, [dst])
        b.add_conditional_edges(src, route, mapping)

    def branch(src: str, fn: Any, targets: list[str]) -> None:
        route, mapping = guarded(fn, targets)
        b.add_conditional_edges(src, route, mapping)

    # entry
    b.add_conditional_edges(START, lambda s: {"revise": "negotiation_parse", "replan": "requirements_merge"}.get(s.get("mode", "initial"), "intake"),
                            {"intake": "intake", "negotiation_parse": "negotiation_parse", "requirements_merge": "requirements_merge"})
    # understanding
    for a, z in [("intake", "vision"), ("vision", "requirements"), ("requirements", "classify"), ("classify", "completeness"),
                 ("clarify_prepare", "clarify_wait"), ("clarify_wait", "requirements_merge"), ("requirements_merge", "classify")]:
        link(a, z)
    # NOTE: requirements -> classify and requirements_merge -> classify share the same target; classify -> completeness always.
    branch("completeness", lambda s: "clarify_prepare" if (s.get("missing_critical") and s.get("clarification_rounds", 0) < deps.settings.max_clarification_rounds) else "retrieve",
           ["clarify_prepare", "retrieve"])
    # category routing: one planner node per registered category
    plan_targets = [f"plan_{k}" for k in PROFILES]
    branch("retrieve", lambda s: f"plan_{s['category']}" if s.get("category") in PROFILES else f"plan_{DEFAULT_CATEGORY}", plan_targets)
    for t in plan_targets:
        link(t, "pricing")
    link("pricing", "quote_reasoning")
    # negotiation
    branch("negotiation_parse", lambda s: "negotiation_refit" if ((s.get("negotiation") or {}).get("constraint") or {}).get("new_budget") else "negotiation_need_budget",
           ["negotiation_refit", "negotiation_need_budget"])
    b.add_edge("negotiation_need_budget", END)
    link("negotiation_refit", "retrieve_alternatives")
    link("retrieve_alternatives", "quote_reasoning")
    # shared tail
    link("quote_reasoning", "validate")
    branch("validate", lambda s: "save_quote" if s.get("mode") == "revise" else "recommend", ["save_quote", "recommend"])
    link("recommend", "save_quote")
    link("save_quote", "crm_prepare")
    link("crm_prepare", "approval_decide")
    branch("approval_decide", lambda s: "approval_request" if s.get("approval_required") else "crm_sync", ["approval_request", "crm_sync"])
    link("approval_request", "approval_wait")
    link("approval_wait", "approval_apply")
    branch("approval_apply", lambda s: "crm_sync" if (s.get("approval_decision") or {}).get("decision") == "approved" else "finalize", ["crm_sync", "finalize"])
    link("crm_sync", "finalize")
    b.add_edge("finalize", END)
    return b.compile(checkpointer=checkpointer)
