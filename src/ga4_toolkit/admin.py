"""GA4 Admin API — property inventory and data-retention audit.

Same service-account key as the Data API side. Unlike the other modules this
sweeps every property the SA can see (via accountSummaries), not just the
ones in sites.yaml, so a newly granted property shows up without config.

Why this exists: GA4 defaults *event* data retention to 2 months. Standard
reports don't care, but Explorations and any event-level question ("who
clicked this download link in March?") silently lose history past the
window. User data retention is a separate setting and is usually already
at 14 months, which hides the problem. Retention changes are forward-only,
so the audit is worth running on a schedule, not once.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from google.oauth2 import service_account

from .config import SiteConfig

ANALYTICS_READONLY_SCOPE = "https://www.googleapis.com/auth/analytics.readonly"
TARGET_RETENTION = "FOURTEEN_MONTHS"


def build_admin_service(service_account_path: str | Path) -> Any:
    """Build an authenticated GA4 Admin API (v1beta) service, read-only scope."""
    from googleapiclient.discovery import build

    path = Path(service_account_path).expanduser().resolve()
    credentials = service_account.Credentials.from_service_account_file(
        str(path),
        scopes=[ANALYTICS_READONLY_SCOPE],
    )
    return build("analyticsadmin", "v1beta", credentials=credentials, cache_discovery=False)


@dataclass
class RetentionResult:
    """Retention settings for one property.

    status values:
      ok    — both event and user retention at TARGET_RETENTION
      short — at least one setting below target (the actionable case)
      error — the Admin API call failed (detail carries the message)
    """

    account: str
    property_name: str
    property_id: str
    site: str  # friendly name from sites.yaml, or "-" when unmapped
    event_retention: str
    user_retention: str
    status: str
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def list_properties(service: Any) -> list[tuple[str, str, str]]:
    """Every (account_name, property_name, property_id) the SA can see."""
    out: list[tuple[str, str, str]] = []
    req = service.accountSummaries().list(pageSize=200)
    while req is not None:
        resp = req.execute()
        for acct in resp.get("accountSummaries", []):
            for prop in acct.get("propertySummaries", []):
                out.append((acct["displayName"], prop["displayName"], prop["property"].split("/")[1]))
        req = service.accountSummaries().list_next(req, resp)
    return out


def get_retention(service: Any, property_id: str) -> tuple[str, str]:
    """(event_retention, user_retention) enum strings for a property."""
    resp = (
        service.properties()
        .getDataRetentionSettings(name=f"properties/{property_id}/dataRetentionSettings")
        .execute()
    )
    return resp.get("eventDataRetention", "?"), resp.get("userDataRetention", "?")


def retention_audit(
    service: Any,
    sites: dict[str, SiteConfig] | None = None,
    target: str = TARGET_RETENTION,
) -> list[RetentionResult]:
    """Audit every visible property's retention settings against `target`."""
    known = {cfg.property_id: name for name, cfg in (sites or {}).items()}
    results: list[RetentionResult] = []
    for account, prop_name, pid in list_properties(service):
        site = known.get(pid, "-")
        try:
            event, user = get_retention(service, pid)
        except Exception as exc:  # googleapiclient raises HttpError; keep the audit going
            results.append(RetentionResult(account, prop_name, pid, site, "?", "?", "error", str(exc)[:200]))
            continue
        status = "ok" if (event == target and user == target) else "short"
        results.append(RetentionResult(account, prop_name, pid, site, event, user, status))
    return sorted(results, key=lambda r: (r.status == "ok", r.account, r.property_name))
