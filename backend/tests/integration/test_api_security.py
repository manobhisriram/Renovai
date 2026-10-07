from __future__ import annotations

import io

import pytest
from PIL import Image

from tests.conftest import jpeg_bytes, login


def mk_project(client, auth):
    r = client.post("/api/v1/projects", json={"lead": {"name": "A B", "email": "ab@example.com"}, "title": "T", "request_text": "kitchen 100 sq ft"}, headers=auth)
    return r.json()["id"]


@pytest.mark.parametrize("method,path", [
    ("get", "/api/v1/projects"), ("post", "/api/v1/projects"), ("get", "/api/v1/approvals"), ("get", "/api/v1/analytics/summary"),
    ("get", "/api/v1/materials"), ("post", "/api/v1/rag/search"), ("get", "/api/v1/system/config"), ("get", "/api/v1/auth/me"), ("get", "/api/v1/audit"),
])
def test_endpoints_require_authentication(client, method, path):
    r = getattr(client, method)(path)
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"


def test_garbage_and_forged_tokens_rejected(client):
    for tok in ("garbage", "Bearer x.y.z"):
        assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok}"}).status_code == 401


def test_role_boundaries(client, auth):
    client.post("/api/v1/auth/admin/users", json={"email": "sales@example.com", "full_name": "Sam Sales", "password": "Sales-pass-12345", "role": "sales"}, headers=auth)
    client.post("/api/v1/auth/admin/users", json={"email": "rev@example.com", "full_name": "Rae Rev", "password": "Review-pass-12345", "role": "reviewer"}, headers=auth)
    sales, rev = login(client, "sales@example.com", "Sales-pass-12345"), login(client, "rev@example.com", "Review-pass-12345")
    pid = mk_project(client, sales)
    client.post(f"/api/v1/projects/{pid}/analyze", headers=sales)
    ap = client.get("/api/v1/approvals?status=pending", headers=sales).json()[0]
    assert client.post(f"/api/v1/approvals/{ap['id']}/decision", json={"decision": "approved"}, headers=sales).status_code == 403
    assert client.put("/api/v1/materials/KITCHEN_CABINETS-STA", json={"unit_price": 1}, headers=rev).status_code == 403
    assert client.get("/api/v1/audit", headers=sales).status_code == 403
    assert client.post("/api/v1/auth/admin/users", json={"email": "x@example.com", "full_name": "X Y", "password": "Pass-word-123456"}, headers=sales).status_code == 403
    assert client.post(f"/api/v1/approvals/{ap['id']}/decision", json={"decision": "approved"}, headers=rev).status_code == 202


def test_login_errors_are_generic_and_rate_limited(client):
    wrong_pw = client.post("/api/v1/auth/login", json={"email": "admin@renovai.local", "password": "nope"})
    wrong_user = client.post("/api/v1/auth/login", json={"email": "ghost@example.com", "password": "nope"})
    assert wrong_pw.status_code == wrong_user.status_code == 401 and wrong_pw.json()["error"]["message"] == wrong_user.json()["error"]["message"]
    codes = [client.post("/api/v1/auth/login", json={"email": "ghost@example.com", "password": "x"}).status_code for _ in range(14)]
    assert 429 in codes


def test_registration_closed_when_users_exist(client):
    r = client.post("/api/v1/auth/register", json={"email": "new@example.com", "full_name": "New User", "password": "A-long-password-1"})
    assert r.status_code == 403


def test_upload_attacks_rejected(client, auth):
    pid = mk_project(client, auth)
    up = lambda name, data, ct="image/jpeg": client.post(f"/api/v1/projects/{pid}/images", files=[("files", (name, data, ct))], headers=auth)
    assert up("shell.php.jpg", b"<?php system($_GET[1]);?>").status_code == 422
    assert up("x.svg", b"<svg><script>alert(1)</script></svg>", "image/svg+xml").status_code == 422
    assert up("../../etc/passwd", b"root:x:0:0").status_code == 422
    big = io.BytesIO()
    Image.new("RGB", (100, 100)).save(big, "JPEG")
    ok = up("../../../evil name.jpg", jpeg_bytes())
    assert ok.status_code == 201 and ok.json()[0]["filename"] == "evil name.jpg"
    assert up("dup.jpg", jpeg_bytes()).status_code == 422, "same content twice must be refused"
    img_id = ok.json()[0]["id"]
    served = client.get(f"/api/v1/projects/{pid}/images/{img_id}/content", headers=auth)
    assert served.status_code == 200 and served.headers["content-type"] == "image/jpeg" and served.headers["x-content-type-options"] == "nosniff"
    assert client.get(f"/api/v1/projects/{pid}/images/{img_id}/content").status_code == 401
    other = mk_project(client, auth)
    assert client.get(f"/api/v1/projects/{other}/images/{img_id}/content", headers=auth).status_code == 404


def test_image_count_limit(client, auth, container):
    container.settings.max_images_per_project = 2
    pid = mk_project(client, auth)
    files = [("files", (f"{i}.jpg", jpeg_bytes(color=(10 * i + 50, 90, 120)), "image/jpeg")) for i in range(3)]
    r = client.post(f"/api/v1/projects/{pid}/images", files=files, headers=auth)
    assert r.status_code == 422 and "at most 2" in r.json()["error"]["message"]


def test_validation_errors_are_structured_and_headers_hardened(client, auth):
    r = client.post("/api/v1/projects", json={"lead": {"name": ""}, "title": "", "area_sqm": -5}, headers=auth)
    body = r.json()["error"]
    assert r.status_code == 422 and body["code"] == "validation_failed" and body["details"]["fields"] and body["request_id"]
    h = client.get("/health").headers
    assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY" and h["x-request-id"] and h["referrer-policy"] == "no-referrer"
    assert client.get("/api/v1/projects/does-not-exist", headers=auth).json()["error"]["code"] == "not_found"


def test_cors_is_restricted_to_configured_origins(client):
    ok = client.options("/api/v1/projects", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})
    bad = client.options("/api/v1/projects", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "access-control-allow-origin" not in bad.headers


def test_sql_injection_strings_are_inert(client, auth):
    mk_project(client, auth)
    r = client.get("/api/v1/projects", params={"q": "'; DROP TABLE projects; --"}, headers=auth)
    assert r.status_code == 200 and r.json() == []
    assert len(client.get("/api/v1/projects", headers=auth).json()) == 1


def test_visualization_not_configured_is_a_clear_error_and_never_fakes_an_image(client, auth):
    pid = mk_project(client, auth)
    st = client.get(f"/api/v1/projects/{pid}/visualizations", headers=auth).json()
    assert st["enabled"] is False
    r = client.post(f"/api/v1/projects/{pid}/visualizations", json={"prompt": "modern minimalist version"}, headers=auth)
    assert r.status_code == 503 and r.json()["error"]["code"] == "service_not_configured"


def test_visualization_with_a_provider_stamps_disclaimer(client, auth, container):
    from app.viz.providers import DISCLAIMER

    class Fake:
        name = "test-double"

        def generate(self, prompt, source):
            b = io.BytesIO()
            Image.new("RGB", (400, 300), (90, 120, 150)).save(b, "PNG")
            self.prompt = prompt
            return b.getvalue()

    container.viz = fake = Fake()
    pid = mk_project(client, auth)
    r = client.post(f"/api/v1/projects/{pid}/visualizations", json={"prompt": "show a modern minimalist version"}, headers=auth)
    assert r.status_code == 201 and r.json()["disclaimer"] == DISCLAIMER
    assert "Do not add text" in fake.prompt and "Keep the room's layout" in fake.prompt
    img = client.get(f"/api/v1/projects/{pid}/visualizations/{r.json()['id']}/content", headers=auth)
    assert img.status_code == 200 and Image.open(io.BytesIO(img.content)).getpixel((5, 295)) == (20, 20, 20)


def test_rag_admin_only_upload_and_search_for_staff(client, auth):
    client.post("/api/v1/auth/admin/users", json={"email": "s2@example.com", "full_name": "S Two", "password": "Sales-pass-12345"}, headers=auth)
    sales = login(client, "s2@example.com", "Sales-pass-12345")
    f = {"file": ("note.md", b"# Note\nTile guidance for bathrooms.", "text/markdown")}
    assert client.post("/api/v1/rag/documents", files=f, data={"doc_type": "faq"}, headers=sales).status_code == 403
    up = client.post("/api/v1/rag/documents", files=f, data={"doc_type": "faq", "category": "bathroom_renovation"}, headers=auth)
    assert up.status_code == 201 and up.json()["chunk_count"] >= 1
    hits = client.post("/api/v1/rag/search", json={"query": "tile guidance bathrooms", "doc_type": "faq"}, headers=sales).json()
    assert hits["evidence"] and hits["degraded"] is None
    assert client.delete(f"/api/v1/rag/documents/{up.json()['id']}", headers=auth).status_code == 204


def test_ready_reports_503_when_a_critical_dependency_is_down(client, container, monkeypatch):
    monkeypatch.setattr(container.store, "healthy", lambda: False)
    r = client.get("/ready")
    assert r.status_code == 503 and r.json()["checks"]["vector_db"]["ok"] is False and r.json()["status"] == "degraded"


def test_metrics_token_protects_metrics(client, container):
    from pydantic import SecretStr

    container.settings.metrics_token = SecretStr("m-token-123456")
    assert client.get("/metrics").status_code == 403
    assert client.get("/metrics", headers={"X-Metrics-Token": "m-token-123456"}).status_code == 200
