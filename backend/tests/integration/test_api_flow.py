"""End-to-end flow over HTTP with the mock LLM test double, real SQLite, in-memory Qdrant, LangGraph checkpointing."""

from __future__ import annotations

from tests.conftest import jpeg_bytes


def _create_project(client, auth, text, **extra):
    body = {"lead": {"name": "Meera Iyer", "email": "meera@example.com", "phone": "+91 98765 43210"}, "title": "Kitchen refit",
            "request_text": text, **extra}
    r = client.post("/api/v1/projects", json=body, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()


def test_new_lead_to_approved_quote_and_crm(client, auth):
    p = _create_project(client, auth, "I want a modern minimalist kitchen in Chennai, about 120 sq ft, budget around 8 lakh, finish in 6 weeks")
    pid = p["id"]
    up = client.post(f"/api/v1/projects/{pid}/images", files=[("files", ("kitchen.jpg", jpeg_bytes(), "image/jpeg"))], headers=auth)
    assert up.status_code == 201 and up.json()[0]["width"] == 800

    r = client.post(f"/api/v1/projects/{pid}/analyze", headers=auth)
    assert r.status_code == 202

    wf = client.get(f"/api/v1/projects/{pid}/workflow", headers=auth).json()
    assert wf["run"]["status"] == "waiting" and wf["run"]["waiting_for"]["type"] == "approval"
    nodes = [e["node"] for e in wf["events"]]
    for expected in ("intake", "vision", "requirements", "classify", "completeness", "retrieve", "plan_kitchen_renovation", "pricing",
                     "quote_reasoning", "validate", "save_quote", "approval_request"):
        assert expected in nodes, f"missing step {expected}: {nodes}"

    # vision output: structured, honest about measurements
    vis = client.get(f"/api/v1/projects/{pid}/vision", headers=auth).json()
    a = vis["items"][0]["analysis"]
    assert a["dimensions"]["provenance"] in ("unknown", "estimated")
    assert any("not measurements" in x or "measure" in x.lower() for x in a["limitations"])
    assert vis["items"][0]["cv"]["width"] == 800

    # requirements carry provenance
    req = client.get(f"/api/v1/projects/{pid}/requirements", headers=auth).json()["requirements"]
    assert req["budget"]["amount"] == 800000 and req["provenance"]["budget"] == "user_provided"

    # quote: three tiers, deterministic, reconciles
    q = client.get(f"/api/v1/projects/{pid}/quotes/1", headers=auth).json()
    opts = q["payload"]["options"]
    assert opts["budget"]["total"] < opts["standard"]["total"] < opts["premium"]["total"]
    for o in opts.values():
        parts = o["materials_subtotal"] + o["labor_subtotal"] + o["logistics"]
        assert abs(parts - o["subtotal"]) < 0.02 and abs(o["subtotal"] + o["contingency"] + o["tax"] - o["total"]) < 0.03
    assert q["status"] == "pending_approval" and q["payload"]["disclaimer"]
    assert q["payload"]["evidence"], "RAG evidence must be attached"

    # approval is required and listed
    ap = client.get("/api/v1/approvals?status=pending", headers=auth).json()
    assert len(ap) == 1 and ap[0]["reasons"]
    d = client.post(f"/api/v1/approvals/{ap[0]['id']}/decision", json={"decision": "approved", "note": "Looks right", "selected_tier": "standard"}, headers=auth)
    assert d.status_code == 202

    proj = client.get(f"/api/v1/projects/{pid}", headers=auth).json()
    assert proj["status"] == "approved"
    syncs = client.get("/api/v1/crm/syncs", headers=auth).json()
    assert syncs[0]["status"] == "synced" and syncs[0]["idempotency_key"] == f"{pid}:v1"
    tasks = client.get("/api/v1/tasks", headers=auth).json()
    assert any("Follow up" in t["title"] for t in tasks)

    # deciding twice is rejected
    again = client.post(f"/api/v1/approvals/{ap[0]['id']}/decision", json={"decision": "approved"}, headers=auth)
    assert again.status_code == 409

    # audit trail exists
    actions = [e["action"] for e in client.get(f"/api/v1/projects/{pid}/audit", headers=auth).json()]
    assert {"project.created", "images.uploaded", "quote.created", "approval.approved", "crm.synced"} <= set(actions)


def test_clarification_loop_pauses_and_resumes(client, auth):
    p = _create_project(client, auth, "Please redo my bathroom, modern style")
    pid = p["id"]
    client.post(f"/api/v1/projects/{pid}/analyze", headers=auth)
    wf = client.get(f"/api/v1/projects/{pid}/workflow", headers=auth).json()
    assert wf["run"]["waiting_for"]["type"] == "clarification" and wf["run"]["waiting_for"]["questions"]
    assert client.get(f"/api/v1/projects/{pid}", headers=auth).json()["status"] == "awaiting_clarification"
    # cannot restart while waiting
    assert client.post(f"/api/v1/projects/{pid}/analyze", headers=auth).status_code == 409

    r = client.post(f"/api/v1/projects/{pid}/clarifications", json={"answer": "It's about 45 sq ft in Mumbai, budget 3 lakh"}, headers=auth)
    assert r.status_code == 202
    wf = client.get(f"/api/v1/projects/{pid}/workflow", headers=auth).json()
    assert wf["run"]["waiting_for"]["type"] == "approval"
    q = client.get(f"/api/v1/projects/{pid}/quotes/1", headers=auth).json()
    assert q["payload"]["category"] == "bathroom_renovation"
    assert q["payload"]["pricing_params"]["params"]["region"] == "mumbai"


def test_negotiation_creates_new_version_and_keeps_history(client, auth):
    pid = _create_project(client, auth, "Modern kitchen in Chennai, 120 sq ft, budget 8 lakh")["id"]
    client.post(f"/api/v1/projects/{pid}/analyze", headers=auth)
    first = client.get(f"/api/v1/projects/{pid}/quotes/1", headers=auth).json()
    ap = client.get("/api/v1/approvals?status=pending", headers=auth).json()[0]
    client.post(f"/api/v1/approvals/{ap['id']}/decision", json={"decision": "approved"}, headers=auth)

    m = client.post(f"/api/v1/projects/{pid}/messages", json={"content": "That is too expensive, my budget is 4.5 lakh"}, headers=auth)
    assert m.status_code == 202 and m.json()["intent"] == "negotiate"

    quotes = client.get(f"/api/v1/projects/{pid}/quotes", headers=auth).json()
    assert [q["version"] for q in quotes] == [2, 1]
    v2 = client.get(f"/api/v1/projects/{pid}/quotes/2", headers=auth).json()
    v1 = client.get(f"/api/v1/projects/{pid}/quotes/1", headers=auth).json()
    assert v1["payload"] == first["payload"], "old version must be immutable"
    assert v1["status"] == "approved"
    assert v2["reason"] == "negotiation" and v2["parent_version"] == 1 and v2["selected_tier"] == "fitted"
    fitted = v2["payload"]["options"]["fitted"]
    assert fitted["total"] < v1["total"]
    assert fitted["total"] <= 450000 or fitted["achievable"] is False
    assert v2["payload"]["negotiation"]["steps"], "trade-offs must be recorded"
    assert v2["payload"]["tradeoffs"]


def test_negotiation_without_budget_asks_for_it(client, auth):
    pid = _create_project(client, auth, "Modern kitchen in Chennai, 120 sq ft")["id"]
    client.post(f"/api/v1/projects/{pid}/analyze", headers=auth)
    m = client.post(f"/api/v1/projects/{pid}/messages", json={"content": "this is too expensive"}, headers=auth).json()
    assert m["action"] == "revise_started"
    msgs = client.get(f"/api/v1/projects/{pid}/messages", headers=auth).json()
    assert any(x["meta"].get("type") == "ask_budget" for x in msgs)
    assert len(client.get(f"/api/v1/projects/{pid}/quotes", headers=auth).json()) == 1


def test_feedback_materials_analytics_and_system(client, auth):
    pid = _create_project(client, auth, "Modern kitchen in Chennai, 120 sq ft")["id"]
    assert client.post(f"/api/v1/projects/{pid}/feedback", json={"step": "quote", "rating": 1}, headers=auth).status_code == 201
    assert len(client.get("/api/v1/materials?group=kitchen_cabinets", headers=auth).json()) == 3
    cfg = client.get("/api/v1/system/config", headers=auth).json()
    assert cfg["mock_ai"] is True and cfg["llm"]["models"]["complex"]
    summary = client.get("/api/v1/analytics/summary", headers=auth).json()
    assert summary["mock_ai"] is True and summary["feedback"]["count"] == 1
    assert client.get("/health").json() == {"status": "ok"}
    ready = client.get("/ready")
    assert ready.status_code == 200 and ready.json()["checks"]["database"]["ok"]
    assert "renovai_http_requests_total" in client.get("/metrics").text
