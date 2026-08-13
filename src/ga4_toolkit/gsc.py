"""Search Console API queries — search performance and sitemap status.

Same service-account key as the GA4 side; the SA must be added as a user
(Restricted is enough) per Search Console property. A site's Search Console
property URL is `gsc_property` in sites.yaml when set, otherwise derived as
`https://{domain}/` (URL-prefix form). Domain properties use the
`sc-domain:example.org` form and must be set explicitly.

Deliberately excluded: the index-coverage report. Its findings on Drupal
sites are dominated by admin/login-side URLs that should never be indexed;
performance totals and sitemap health are the signals worth automating.
"""

from __future__ import annotations

import calendar
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

from google.oauth2 import service_account

from .config import SiteConfig

GSC_READONLY_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"


def build_gsc_service(service_account_path: str | Path) -> Any:
    """Build an authenticated Search Console API service (read-only scope)."""
    from googleapiclient.discovery import build

    path = Path(service_account_path).expanduser().resolve()
    credentials = service_account.Credentials.from_service_account_file(
        str(path),
        scopes=[GSC_READONLY_SCOPE],
    )
    return build("searchconsole", "v1", credentials=credentials, cache_discovery=False)


def gsc_property_for(site: SiteConfig) -> str:
    """The Search Console property URL for a site (explicit or derived URL-prefix)."""
    if site.gsc_property:
        return site.gsc_property
    return f"https://{site.domain}/"


def month_range(year: int, month: int) -> tuple[str, str]:
    last = calendar.monthrange(year, month)[1]
    return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{last:02d}"


def previous_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def default_report_month(today: date | None = None) -> tuple[int, int]:
    """The most recent complete month (what the monthly Google email covers)."""
    today = today or date.today()
    return previous_month(today.year, today.month)


@dataclass(frozen=True)
class SearchMonth:
    """One site's search performance for a month, with prior-month comparison."""

    site: str
    gsc_property: str
    status: str  # ok | no_access | error
    clicks: int = 0
    impressions: int = 0
    ctr: float = 0.0
    position: float = 0.0
    prev_clicks: int = 0
    prev_impressions: int = 0
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def clicks_delta_pct(self) -> float | None:
        if self.prev_clicks == 0:
            return None
        return (self.clicks - self.prev_clicks) / self.prev_clicks * 100


@dataclass(frozen=True)
class SitemapStatus:
    """One submitted sitemap's state, as Search Console sees it."""

    site: str
    path: str
    status: str  # ok | flagged
    last_downloaded: str = ""
    submitted_urls: int = 0
    errors: int = 0
    warnings: int = 0
    is_pending: bool = False
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _classify_http_error(exc: Exception) -> tuple[str, str]:
    text = str(exc)
    if "403" in text or "does not have sufficient permission" in text or "User does not" in text:
        return "no_access", "Service account is not a user on this Search Console property"
    return "error", text[:200]


def _month_totals(service: Any, prop: str, start: str, end: str) -> dict[str, Any]:
    resp = (
        service.searchanalytics()
        .query(siteUrl=prop, body={"startDate": start, "endDate": end, "rowLimit": 1})
        .execute()
    )
    rows = resp.get("rows") or [{}]
    r = rows[0]
    return {
        "clicks": int(r.get("clicks", 0)),
        "impressions": int(r.get("impressions", 0)),
        "ctr": float(r.get("ctr", 0.0)),
        "position": float(r.get("position", 0.0)),
    }


def search_month(
    service: Any, site: SiteConfig, year: int, month: int
) -> SearchMonth:
    """Search totals for a month plus the prior month, for one site."""
    prop = gsc_property_for(site)
    try:
        cur = _month_totals(service, prop, *month_range(year, month))
        prev = _month_totals(service, prop, *month_range(*previous_month(year, month)))
    except Exception as exc:  # HttpError, transport errors — classify, don't raise
        status, detail = _classify_http_error(exc)
        return SearchMonth(site=site.friendly_name, gsc_property=prop, status=status, detail=detail)
    return SearchMonth(
        site=site.friendly_name,
        gsc_property=prop,
        status="ok",
        clicks=cur["clicks"],
        impressions=cur["impressions"],
        ctr=cur["ctr"],
        position=cur["position"],
        prev_clicks=prev["clicks"],
        prev_impressions=prev["impressions"],
    )


def list_accessible_sites(service: Any) -> list[dict[str, str]]:
    """All Search Console properties the service account can see."""
    resp = service.sites().list().execute()
    return [
        {"siteUrl": e.get("siteUrl", ""), "permissionLevel": e.get("permissionLevel", "")}
        for e in resp.get("siteEntry", [])
    ]


STALE_DOWNLOAD_DAYS = 30


def sitemap_statuses(service: Any, site: SiteConfig) -> list[SitemapStatus]:
    """Submitted sitemaps for one site, flagged when Search Console reports trouble.

    Flag conditions: parse errors, warnings, still pending, never downloaded,
    or last download older than STALE_DOWNLOAD_DAYS. No submitted sitemap at
    all is reported as a single flagged row.
    """
    prop = gsc_property_for(site)
    try:
        resp = service.sitemaps().list(siteUrl=prop).execute()
    except Exception as exc:
        status, detail = _classify_http_error(exc)
        return [SitemapStatus(site=site.friendly_name, path="", status="flagged", detail=detail if status == "error" else "no_access")]

    entries = resp.get("sitemap", [])
    if not entries:
        return [
            SitemapStatus(
                site=site.friendly_name, path="", status="flagged",
                detail="No sitemap submitted to Search Console",
            )
        ]

    out: list[SitemapStatus] = []
    today = date.today()
    for e in entries:
        errors = int(e.get("errors", 0) or 0)
        warnings = int(e.get("warnings", 0) or 0)
        submitted = sum(int(c.get("submitted", 0) or 0) for c in e.get("contents", []))
        last_dl = (e.get("lastDownloaded") or "")[:10]
        pending = bool(e.get("isPending", False))
        problems = []
        if errors:
            problems.append(f"{errors} error(s)")
        if warnings:
            problems.append(f"{warnings} warning(s)")
        if pending:
            problems.append("pending (not yet processed)")
        if not last_dl:
            problems.append("never downloaded")
        else:
            try:
                age = (today - date.fromisoformat(last_dl)).days
                if age > STALE_DOWNLOAD_DAYS:
                    problems.append(f"last downloaded {age}d ago")
            except ValueError:
                pass
        out.append(
            SitemapStatus(
                site=site.friendly_name,
                path=e.get("path", ""),
                status="flagged" if problems else "ok",
                last_downloaded=last_dl,
                submitted_urls=submitted,
                errors=errors,
                warnings=warnings,
                is_pending=pending,
                detail="; ".join(problems),
            )
        )
    return out
