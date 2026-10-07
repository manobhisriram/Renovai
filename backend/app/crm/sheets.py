"""Google Sheets as a lightweight CRM (service account). Free and human-friendly for small teams.

Share the spreadsheet with the service-account e-mail (Editor). Row layout (A..L):
Timestamp | Name | Email | Phone | Project | Category | Budget | Quote total | Currency | Tier/version | Status | IdempotencyKey
Not exercised against live Google APIs from this repository's CI (see docs/deployment.md).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx

from app.config import Settings
from app.crm.base import CRMContact, CRMLeadPayload, CRMWriteResult
from app.utils.errors import ExternalServiceError, ServiceNotConfigured

SCOPE = "https://www.googleapis.com/auth/spreadsheets"


def _default_token_provider(service_account_json: str) -> Callable[[], str]:
    import urllib3
    from google.auth.transport.urllib3 import Request
    from google.oauth2 import service_account

    creds = service_account.Credentials.from_service_account_info(json.loads(service_account_json), scopes=[SCOPE])
    transport = Request(urllib3.PoolManager())

    def token() -> str:
        if not creds.valid:
            creds.refresh(transport)
        return str(creds.token)

    return token


class GoogleSheetsCRM:
    name = "google_sheets"

    def __init__(self, settings: Settings, client: httpx.Client | None = None, token_provider: Callable[[], str] | None = None):
        if not (settings.google_sheets_spreadsheet_id and settings.google_service_account_json):
            raise ServiceNotConfigured("GOOGLE_SHEETS_SPREADSHEET_ID and GOOGLE_SERVICE_ACCOUNT_JSON are required.")
        self._sheet = settings.google_sheets_spreadsheet_id
        self._range = settings.google_sheets_range
        self._client = client or httpx.Client(timeout=httpx.Timeout(15.0, connect=5.0))
        self._token = token_provider or _default_token_provider(settings.google_service_account_json.get_secret_value())

    def _call(self, method: str, suffix: str, **kw: Any) -> dict[str, Any]:
        url = f"https://sheets.googleapis.com/v4/spreadsheets/{self._sheet}/values/{quote(self._range, safe='')}{suffix}"
        try:
            r = self._client.request(method, url, headers={"Authorization": f"Bearer {self._token()}"}, **kw)
        except httpx.HTTPError as exc:
            raise ExternalServiceError("Google Sheets is unreachable.") from exc
        if r.status_code >= 400:
            raise ExternalServiceError(f"Google Sheets rejected the request (HTTP {r.status_code}).", details={"status": r.status_code})
        return r.json() if r.content else {}

    def _rows(self) -> list[list[str]]:
        return list(self._call("GET", "").get("values", []))

    def lookup_contact(self, *, email: str | None = None, phone: str | None = None) -> CRMContact | None:
        for i, row in enumerate(self._rows()):
            row = row + [""] * (12 - len(row))
            if (email and row[2].lower() == email.lower()) or (phone and row[3] == phone):
                return CRMContact(str(i + 1), row[1], row[2] or None, row[3] or None, {"status": row[10]})
        return None

    def upsert_lead(self, payload: CRMLeadPayload) -> CRMWriteResult:
        for i, existing in enumerate(self._rows()):  # idempotent: skip if this key was already written
            if len(existing) >= 12 and existing[11] == payload.idempotency_key:
                return CRMWriteResult(str(i + 1), False)
        new_row: list[Any] = [datetime.now(UTC).isoformat(), payload.name, payload.email or "", payload.phone or "", payload.project_title,
               payload.category or "", payload.budget or "", payload.quote_total or "", payload.currency,
               f"{payload.selected_tier} v{payload.quote_version}", payload.status, payload.idempotency_key]
        data = self._call("POST", ":append", params={"valueInputOption": "USER_ENTERED", "insertDataOption": "INSERT_ROWS"},
                          json={"values": [new_row]})
        updated = (data.get("updates") or {}).get("updatedRange", "appended")
        return CRMWriteResult(str(updated), True)

    def healthy(self) -> bool:
        try:
            self._call("GET", "", params={"majorDimension": "ROWS"})
            return True
        except Exception:
            return False
