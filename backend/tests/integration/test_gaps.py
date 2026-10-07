"""Covers production-only adapters and conversation paths that the main flows do not reach."""

from __future__ import annotations

import io
import json
import smtplib

import httpx
import pytest
from PIL import Image

from app.services.notify import LogNotifier, SmtpNotifier, build_notifier
from app.storage.s3 import S3Storage
from app.utils.errors import ExternalServiceError, ServiceNotConfigured
from app.viz.providers import NoVisualization, OpenAIImages, build_prompt, build_viz_provider
from tests.conftest import make_settings


class FakeS3:
    """Minimal boto3-client double that records calls and can be told to fail."""

    def __init__(self):
        self.objects: dict[tuple[str, str], dict] = {}
        self.fail = False

    def put_object(self, **kw):
        if self.fail:
            raise RuntimeError("boom")
        self.objects[(kw["Bucket"], kw["Key"])] = kw

    def get_object(self, Bucket, Key):
        if self.fail:
            raise RuntimeError("boom")
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)]["Body"])}

    def delete_object(self, Bucket, Key):
        if self.fail:
            raise RuntimeError("boom")
        self.objects.pop((Bucket, Key), None)

    def head_bucket(self, Bucket):
        if self.fail:
            raise RuntimeError("no bucket")


def test_s3_storage_roundtrip_encryption_and_key_validation(tmp_path):
    fake = FakeS3()
    st = S3Storage(make_settings(tmp_path, storage_backend="s3", s3_bucket="b", s3_region="ap-south-1"), client=fake)
    st.put("projects/p1/a.jpg", b"img", "image/jpeg")
    sent = fake.objects[("b", "projects/p1/a.jpg")]
    assert sent["ServerSideEncryption"] == "AES256" and sent["ContentType"] == "image/jpeg"
    assert st.get("projects/p1/a.jpg") == b"img" and st.healthy()
    st.delete("projects/p1/a.jpg")
    assert ("b", "projects/p1/a.jpg") not in fake.objects
    for bad in ("../x.jpg", "/abs.jpg", "a//b.jpg"):
        with pytest.raises(ValueError):
            st.put(bad, b"x", "image/jpeg")


def test_s3_failures_become_typed_errors_and_health_reports_false(tmp_path):
    fake = FakeS3()
    st = S3Storage(make_settings(tmp_path, storage_backend="s3", s3_bucket="b", s3_region="r"), client=fake)
    fake.fail = True
    with pytest.raises(ExternalServiceError, match="write"):
        st.put("projects/p/a.jpg", b"x", "image/jpeg")
    with pytest.raises(ExternalServiceError, match="read"):
        st.get("projects/p/a.jpg")
    with pytest.raises(ExternalServiceError, match="delete"):
        st.delete("projects/p/a.jpg")
    assert st.healthy() is False


def test_smtp_notifier_sends_and_contains_failures(tmp_path, monkeypatch):
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            sent["host"], sent["port"] = host, port

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            sent["tls"] = True

        def login(self, u, p):
            sent["login"] = (u, p)

        def send_message(self, msg):
            sent["subject"], sent["to"] = msg["Subject"], msg["To"]

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    s = make_settings(tmp_path, smtp_host="smtp.example.com", smtp_username="u", smtp_password="pw-123456")
    assert isinstance(build_notifier(s), SmtpNotifier) and isinstance(build_notifier(make_settings(tmp_path)), LogNotifier)
    assert SmtpNotifier(s).send("rev@example.com", "Quote waiting", "body") is True
    assert sent["tls"] and sent["login"] == ("u", "pw-123456") and sent["to"] == "rev@example.com"
    monkeypatch.setattr(smtplib, "SMTP", lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
    assert SmtpNotifier(s).send("x@example.com", "s", "b") is False  # never raises into the workflow
    assert LogNotifier().send("x@example.com", "s", "b") is True


def test_openai_images_edit_and_generate_paths(tmp_path):
    import base64

    png = io.BytesIO()
    Image.new("RGB", (8, 8), (1, 2, 3)).save(png, "PNG")
    seen = []

    def handler(req: httpx.Request):
        seen.append(req.url.path)
        return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(png.getvalue()).decode()}]})

    s = make_settings(tmp_path, viz_provider="openai_images", openai_api_key="sk-openai-test-123456")
    prov = OpenAIImages(s, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert prov.generate("p", b"srcimage") and prov.generate("p", None)
    assert seen == ["/v1/images/edits", "/v1/images/generations"]
    bad = OpenAIImages(s, client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))))
    with pytest.raises(ExternalServiceError):
        bad.generate("p", None)
    empty = OpenAIImages(s, client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"data": []}))))
    with pytest.raises(ExternalServiceError, match="no image"):
        empty.generate("p", None)
    with pytest.raises(ServiceNotConfigured):
        NoVisualization().generate("p", None)
    with pytest.raises(ServiceNotConfigured):
        OpenAIImages(make_settings(tmp_path))
    assert isinstance(build_viz_provider(make_settings(tmp_path)), NoVisualization)


def test_viz_prompt_carries_project_constraints_and_safety_suffix():
    p = build_prompt("show a modern version", style="minimalist", category="kitchen_renovation", constraints=["keep the window", "no wall removal"])
    assert "minimalist" in p and "kitchen renovation" in p and "keep the window" in p and "Do not add text" in p


# ------------------------------------------------------------------ chat intents not covered by the main flows
def _project(client, auth, text="Modern kitchen in Chennai, 120 sq ft, budget 8 lakh"):
    r = client.post("/api/v1/projects", json={"lead": {"name": "C D", "email": "cd@example.com"}, "title": "T", "request_text": text}, headers=auth)
    return r.json()["id"]


def say(client, auth, pid, text):
    r = client.post(f"/api/v1/projects/{pid}/messages", json={"content": text}, headers=auth)
    assert r.status_code == 202, r.text
    return r.json()


def test_chat_suggest_question_visualize_replan_and_ack(client, auth):
    pid = _project(client, auth)
    assert say(client, auth, pid, "make it cheaper")["action"] == "no_quote"
    client.post(f"/api/v1/projects/{pid}/analyze", headers=auth)
    s = say(client, auth, pid, "I'm not sure what to do, any ideas?")
    assert s["intent"] == "suggest" and s["action"] == "suggestions" and "Layered lighting" in s["reply"]
    q = say(client, auth, pid, "how long will it take?")
    assert q["intent"] == "question" and q["action"] == "answer"
    v = say(client, auth, pid, "can you show me what it would look like?")
    assert v["action"] == "visualize_hint" and "not configured" in v["reply"]
    assert say(client, auth, pid, "thanks")["action"] == "ack"
    r = say(client, auth, pid, "also include a pantry unit instead of the tv area")
    assert r["action"] == "replan_started"
    assert len(client.get(f"/api/v1/projects/{pid}/quotes", headers=auth).json()) == 2
    sug = client.post(f"/api/v1/projects/{pid}/suggestions", headers=auth).json()
    assert sug["available"] and sug["items"]


def test_manual_revise_endpoint_and_validation(client, auth):
    pid = _project(client, auth)
    assert client.post(f"/api/v1/projects/{pid}/quotes/revise", json={"budget": 400000}, headers=auth).status_code == 404
    client.post(f"/api/v1/projects/{pid}/analyze", headers=auth)
    assert client.post(f"/api/v1/projects/{pid}/quotes/revise", json={}, headers=auth).status_code == 422
    assert client.post(f"/api/v1/projects/{pid}/quotes/revise", json={"budget": 450000, "message": "keep the cabinets"}, headers=auth).status_code == 202
    quotes = client.get(f"/api/v1/projects/{pid}/quotes", headers=auth).json()
    assert [x["version"] for x in quotes] == [2, 1] and quotes[0]["selected_tier"] == "fitted"


def test_crm_leads_tasks_materials_and_requirements_endpoints(client, auth):
    leads = client.get("/api/v1/leads?q=Priya", headers=auth).json()
    assert leads and leads[0]["name"] == "Priya Nair"
    upd = client.patch(f"/api/v1/leads/{leads[0]['id']}", json={"status": "contacted", "notes": "called"}, headers=auth)
    assert upd.status_code == 200 and upd.json()["status"] == "contacted"
    assert client.patch("/api/v1/leads/nope", json={"status": "won"}, headers=auth).status_code == 404
    assert client.get("/api/v1/crm/status", headers=auth).json() == {"provider": "internal", "healthy": True}
    pid = _project(client, auth)
    client.post(f"/api/v1/projects/{pid}/analyze", headers=auth)
    ap = client.get("/api/v1/approvals?status=pending", headers=auth).json()[0]
    client.post(f"/api/v1/approvals/{ap['id']}/decision", json={"decision": "approved"}, headers=auth)
    tasks = client.get("/api/v1/tasks", headers=auth).json()
    done = client.patch(f"/api/v1/tasks/{tasks[0]['id']}", json={"status": "done"}, headers=auth)
    assert done.json()["status"] == "done"
    sync = client.get("/api/v1/crm/syncs", headers=auth).json()[0]
    assert client.post(f"/api/v1/crm/syncs/{sync['id']}/retry", headers=auth).json()["status"] == "synced"
    assert client.post("/api/v1/crm/syncs/nope/retry", headers=auth).status_code == 404
    # editing a price marks it as no-longer-sample and is audited
    m = client.put("/api/v1/materials/FLOOR_TILES-STA", json={"unit_price": 125}, headers=auth).json()
    assert m["unit_price"] == 125 and m["is_sample"] is False
    cfg = client.get("/api/v1/pricing/config", headers=auth).json()
    assert len(cfg["categories"]) == 7 and cfg["regions"]
    r = client.patch(f"/api/v1/projects/{pid}/requirements", json={"area_sqm": 15, "budget_amount": 700000}, headers=auth).json()["requirements"]
    assert r["area_sqm"] == 15 and r["provenance"]["area_sqm"] == "user_provided" and r["budget"]["amount"] == 700000
    assert any(e["action"] == "requirements.edited" for e in client.get(f"/api/v1/projects/{pid}/audit", headers=auth).json())
    assert client.get("/api/v1/audit", headers=auth).status_code == 200
    json.dumps(client.get("/api/v1/analytics/summary", headers=auth).json())


def test_cancel_workflow_unblocks_a_waiting_project(client, auth):
    pid = _project(client, auth, "please redo my kitchen")
    client.post(f"/api/v1/projects/{pid}/analyze", headers=auth)
    assert client.post(f"/api/v1/projects/{pid}/clarifications", json={"answer": "x"}, headers=auth).status_code in (202, 404)
    st = client.get(f"/api/v1/projects/{pid}/workflow", headers=auth).json()["run"]["status"]
    if st == "waiting":
        assert client.post(f"/api/v1/projects/{pid}/workflow/cancel", headers=auth).json()["cancelled_runs"] == 1
    assert client.post(f"/api/v1/projects/{pid}/analyze", headers=auth).status_code == 202
    assert client.post(f"/api/v1/projects/{pid}/clarifications", json={"answer": "x"}, headers=auth).status_code in (202, 404)
    assert client.post("/api/v1/projects/nope/analyze", headers=auth).status_code == 404
