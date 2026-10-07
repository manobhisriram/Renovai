from __future__ import annotations

import json

import httpx
import pytest

from app.crm.base import CRMLeadPayload
from app.crm.hubspot import HubSpotCRM
from app.crm.internal import InternalCRM
from app.crm.sheets import GoogleSheetsCRM
from app.utils.errors import ExternalServiceError, ServiceNotConfigured
from tests.conftest import make_settings

PAYLOAD = CRMLeadPayload(idempotency_key="p1:v1", project_id="p1", name="Meera Iyer", email="Meera@Example.com", phone="+919800000000",
                         project_title="Kitchen", category="kitchen_renovation", budget=800000, quote_total=663775.02, currency="INR",
                         quote_version=1, selected_tier="standard", timeline_weeks=6, follow_up_date="2026-10-10")


def hubspot(tmp_path, handler):
    s = make_settings(tmp_path, crm_provider="hubspot", hubspot_access_token="pat-test-token-123456")
    return HubSpotCRM(s, client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_hubspot_creates_contact_then_attaches_note(tmp_path):
    calls = []

    def handler(req):
        calls.append((req.method, req.url.path, json.loads(req.content) if req.content else None, req.headers["authorization"]))
        if req.url.path.endswith("/search"):
            return httpx.Response(200, json={"results": []})
        if req.url.path == "/crm/v3/objects/contacts":
            return httpx.Response(201, json={"id": "501"})
        return httpx.Response(201, json={"id": "9"})

    res = hubspot(tmp_path, handler).upsert_lead(PAYLOAD)
    assert res.external_id == "501" and res.created
    assert [c[1] for c in calls] == ["/crm/v3/objects/contacts/search", "/crm/v3/objects/contacts", "/crm/v3/objects/notes"]
    assert calls[0][2]["filterGroups"][0]["filters"][0]["value"] == "meera@example.com"
    assert calls[1][2]["properties"]["firstname"] == "Meera" and calls[2][2]["associations"][0]["to"]["id"] == "501"
    assert "p1:v1" in calls[2][2]["properties"]["hs_note_body"] and calls[0][3] == "Bearer pat-test-token-123456"


def test_hubspot_updates_existing_contact(tmp_path):
    seen = []

    def handler(req):
        seen.append(req.method + " " + req.url.path)
        if req.url.path.endswith("/search"):
            return httpx.Response(200, json={"results": [{"id": "77", "properties": {"email": "meera@example.com", "firstname": "Meera"}}]})
        return httpx.Response(200, json={"id": "77"})

    res = hubspot(tmp_path, handler).upsert_lead(PAYLOAD)
    assert not res.created and res.external_id == "77" and "PATCH /crm/v3/objects/contacts/77" in seen


def test_hubspot_errors_are_typed(tmp_path):
    with pytest.raises(ExternalServiceError, match="temporarily"):
        hubspot(tmp_path, lambda r: httpx.Response(429)).lookup_contact(email="a@b.co")
    with pytest.raises(ExternalServiceError, match="rejected"):
        hubspot(tmp_path, lambda r: httpx.Response(401)).lookup_contact(email="a@b.co")
    with pytest.raises(ServiceNotConfigured):
        HubSpotCRM(make_settings(tmp_path))


def sheets(tmp_path, handler):
    s = make_settings(tmp_path, crm_provider="google_sheets", google_sheets_spreadsheet_id="sheet123", google_service_account_json='{"x":1}')
    return GoogleSheetsCRM(s, client=httpx.Client(transport=httpx.MockTransport(handler)), token_provider=lambda: "tok")


def test_sheets_appends_row_and_is_idempotent(tmp_path):
    store: list[list[str]] = []
    appends = []

    def handler(req):
        assert req.headers["authorization"] == "Bearer tok"
        if req.method == "POST":
            row = json.loads(req.content)["values"][0]
            appends.append(row)
            store.append(row)
            return httpx.Response(200, json={"updates": {"updatedRange": "Leads!A2:L2"}})
        return httpx.Response(200, json={"values": store})

    crm = sheets(tmp_path, handler)
    first = crm.upsert_lead(PAYLOAD)
    second = crm.upsert_lead(PAYLOAD)
    assert first.created and not second.created and len(appends) == 1
    assert appends[0][1] == "Meera Iyer" and appends[0][11] == "p1:v1" and appends[0][9] == "standard v1"
    assert crm.lookup_contact(email="meera@example.com").name == "Meera Iyer"


def test_sheets_error_is_typed(tmp_path):
    with pytest.raises(ExternalServiceError):
        sheets(tmp_path, lambda r: httpx.Response(403)).upsert_lead(PAYLOAD)


def test_internal_crm_lookup_and_upsert(container):
    from app.database.models import Project
    from app.services.projects import get_or_create_lead

    crm = InternalCRM(container.session_factory)
    assert crm.lookup_contact(email="priya.nair@example.com").name == "Priya Nair"
    assert crm.lookup_contact(email="ghost@example.com") is None and crm.lookup_contact() is None
    with container.session_factory() as s:
        lead, _ = get_or_create_lead(s, name="Zed", email="zed@example.com", phone=None)
        p = Project(lead_id=lead.id, title="t", request_text="x")
        s.add(p)
        s.commit()
        pid = p.id
    from dataclasses import replace

    p1 = replace(PAYLOAD, project_id=pid)
    assert crm.upsert_lead(p1).created and not crm.upsert_lead(p1).created  # one open follow-up task, not duplicates
