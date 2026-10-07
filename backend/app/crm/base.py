"""CRM provider abstraction. Add Salesforce/Zoho by implementing ``CRMProvider``."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class CRMContact:
    external_id: str
    name: str
    email: str | None = None
    phone: str | None = None
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class CRMLeadPayload:
    idempotency_key: str
    project_id: str
    name: str
    email: str | None
    phone: str | None
    project_title: str
    category: str | None
    budget: float | None
    quote_total: float | None
    currency: str
    quote_version: int
    selected_tier: str
    timeline_weeks: float | None
    follow_up_date: str | None
    status: str = "quoted"
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class CRMWriteResult:
    external_id: str
    created: bool


class CRMProvider(Protocol):
    name: str

    def lookup_contact(self, *, email: str | None = None, phone: str | None = None) -> CRMContact | None: ...
    def upsert_lead(self, payload: CRMLeadPayload) -> CRMWriteResult: ...
    def healthy(self) -> bool: ...
