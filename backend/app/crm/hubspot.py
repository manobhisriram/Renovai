"""HubSpot CRM provider (private-app token).

Upserts a contact by email and attaches a Note with the quote summary. Written against HubSpot's public
CRM v3 API; it has not been exercised against a live HubSpot portal from this repository's CI, so run the
checklist in docs/deployment.md (section 'CRM verification') before relying on it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from app.config import Settings
from app.crm.base import CRMContact, CRMLeadPayload, CRMWriteResult
from app.utils.errors import ExternalServiceError, ServiceNotConfigured

NOTE_TO_CONTACT = 202  # HubSpot-defined association type id (note -> contact)


class HubSpotCRM:
    name = "hubspot"

    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        if settings.hubspot_access_token is None:
            raise ServiceNotConfigured("HUBSPOT_ACCESS_TOKEN is not set.")
        self._base = settings.hubspot_base_url.rstrip("/")
        self._token = settings.hubspot_access_token.get_secret_value()
        self._client = client or httpx.Client(timeout=httpx.Timeout(15.0, connect=5.0))

    def _req(self, method: str, path: str, **kw: Any) -> dict[str, Any]:
        try:
            r = self._client.request(method, self._base + path, headers={"Authorization": f"Bearer {self._token}"}, **kw)
        except httpx.HTTPError as exc:
            raise ExternalServiceError("HubSpot is unreachable.") from exc
        if r.status_code == 429 or r.status_code >= 500:
            raise ExternalServiceError(f"HubSpot temporarily unavailable (HTTP {r.status_code}).")
        if r.status_code >= 400:
            raise ExternalServiceError(f"HubSpot rejected the request (HTTP {r.status_code}).", details={"status": r.status_code})
        return r.json() if r.content else {}

    def lookup_contact(self, *, email: str | None = None, phone: str | None = None) -> CRMContact | None:
        if not email:
            return None
        data = self._req("POST", "/crm/v3/objects/contacts/search", json={
            "filterGroups": [{"filters": [{"propertyName": "email", "operator": "EQ", "value": email.lower()}]}],
            "properties": ["email", "firstname", "lastname", "phone"], "limit": 1})
        results = data.get("results") or []
        if not results:
            return None
        p = results[0].get("properties", {})
        return CRMContact(results[0]["id"], f"{p.get('firstname') or ''} {p.get('lastname') or ''}".strip(), p.get("email"), p.get("phone"), p)

    def upsert_lead(self, payload: CRMLeadPayload) -> CRMWriteResult:
        first, _, last = payload.name.partition(" ")
        props = {k: v for k, v in {"email": payload.email, "firstname": first, "lastname": last or None,
                                   "phone": payload.phone, "lifecyclestage": "lead"}.items() if v}
        existing = self.lookup_contact(email=payload.email)
        if existing:
            self._req("PATCH", f"/crm/v3/objects/contacts/{existing.external_id}", json={"properties": props})
            contact_id, created = existing.external_id, False
        else:
            contact_id = self._req("POST", "/crm/v3/objects/contacts", json={"properties": props})["id"]
            created = True
        body = (f"RenovAI quote v{payload.quote_version} ({payload.selected_tier}) for '{payload.project_title}'. "
                f"Category: {payload.category or 'n/a'}. Estimated total: {payload.currency} {payload.quote_total:,.2f}. "
                f"Client budget: {payload.budget or 'not stated'}. Timeline (weeks): {payload.timeline_weeks or 'n/a'}. "
                f"Ref: {payload.idempotency_key}. {payload.notes}")[:1900]
        self._req("POST", "/crm/v3/objects/notes", json={
            "properties": {"hs_note_body": body, "hs_timestamp": datetime.now(UTC).isoformat()},
            "associations": [{"to": {"id": contact_id}, "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": NOTE_TO_CONTACT}]}],
        })
        return CRMWriteResult(str(contact_id), created)

    def healthy(self) -> bool:
        try:
            self._req("GET", "/crm/v3/objects/contacts", params={"limit": 1})
            return True
        except Exception:
            return False
