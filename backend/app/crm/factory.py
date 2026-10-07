from __future__ import annotations

from app.config import Settings
from app.crm.base import CRMProvider
from app.crm.internal import InternalCRM
from app.database import SessionFactory


def build_crm(settings: Settings, session_factory: SessionFactory) -> CRMProvider:
    if settings.crm_provider == "hubspot":
        from app.crm.hubspot import HubSpotCRM

        return HubSpotCRM(settings)
    if settings.crm_provider == "google_sheets":
        from app.crm.sheets import GoogleSheetsCRM

        return GoogleSheetsCRM(settings)
    return InternalCRM(session_factory)
