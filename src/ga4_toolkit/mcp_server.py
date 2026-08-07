"""MCP server exposing GA4 query functions as tools.

Same thin-wrapper pattern as the CLI: every MCP tool delegates to queries.py.
Adding a new query function in queries.py automatically shows up here and in
the CLI with no duplication.

Run directly:
    ga4-mcp
or:
    python -m ga4_toolkit.mcp_server
or via docker-compose (see docker-compose.yml).

Connect from an MCP client by configuring the command path and providing
GA4_SERVICE_ACCOUNT_PATH in the environment.
"""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

from ga4_toolkit import queries
from ga4_toolkit.client import default_client
from ga4_toolkit.config import ConfigError, load_sites, load_toolkit_config, resolve_site

logger = logging.getLogger("ga4_toolkit.mcp_server")

mcp = FastMCP("ga4-toolkit")


def _client_and_config() -> tuple[Any, Any]:
    """Load config and build/reuse a client. Errors become MCP tool errors."""
    config = load_toolkit_config()
    client = default_client(config.service_account_path)
    return client, config


def _resolve_dates(
    last: str | None,
    start_date: str | None,
    end_date: str | None,
    default_lookback_days: int,
) -> tuple[str, str]:
    """Translate the MCP tool's date parameters into (start, end) ISO dates."""
    if last:
        import re

        m = re.match(r"^(\d+)([dwmy])$", last)
        if not m:
            raise ValueError(f"'last' must be like '30d', '4w', '3m'; got {last!r}")
        value, unit = int(m.group(1)), m.group(2)
        days = {"d": value, "w": value * 7, "m": value * 30, "y": value * 365}[unit]
        return queries.days_ago_range(days)
    if start_date and end_date:
        return start_date, end_date
    if start_date or end_date:
        raise ValueError("Provide both start_date and end_date, or use 'last'.")
    return queries.days_ago_range(default_lookback_days)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def list_sites() -> list[dict[str, str]]:
    """List configured GA4 sites from sites.yaml.

    Returns a list of site entries with friendly_name, property_id, domain, and notes.
    Use the friendly_name as the `site` argument in other tools.
    """
    try:
        sites = load_sites()
    except ConfigError as e:
        return [{"error": str(e)}]
    return [
        {
            "friendly_name": s.friendly_name,
            "property_id": s.property_id,
            "domain": s.domain,
            "notes": s.notes,
        }
        for s in sites.values()
    ]


@mcp.tool()
def top_pages(
    site: str,
    last: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 25,
) -> list[dict[str, Any]]:
    """Return the top pages by pageviews for a site over a date range.

    Args:
        site: Friendly site name (from list_sites) or numeric GA4 property ID.
        last: Relative date range like '30d', '4w', '3m'. Mutually exclusive with start_date/end_date.
        start_date: Explicit start date in YYYY-MM-DD format. Requires end_date.
        end_date: Explicit end date in YYYY-MM-DD format. Requires start_date.
        limit: Maximum rows to return. Default 25.

    Returns a list of {path, title, pageviews, active_users, engagement_rate}.
    """
    client, config = _client_and_config()
    start, end = _resolve_dates(last, start_date, end_date, config.default_lookback_days)
    property_id = resolve_site(site)
    rows = queries.top_pages(client, property_id, start, end, limit=limit)
    return [r.to_dict() for r in rows]


@mcp.tool()
def traffic(
    site: str,
    last: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    granularity: str = "day",
) -> list[dict[str, Any]]:
    """Return traffic time series for a site over a date range.

    Args:
        site: Friendly site name or numeric property ID.
        last: Relative date range, e.g. '30d'.
        start_date / end_date: Explicit range, YYYY-MM-DD each.
        granularity: 'day', 'week', or 'month'.

    Returns a list of {date, sessions, active_users, pageviews}.
    """
    if granularity not in ("day", "week", "month"):
        raise ValueError(f"granularity must be day/week/month, got {granularity!r}")
    client, config = _client_and_config()
    start, end = _resolve_dates(last, start_date, end_date, config.default_lookback_days)
    property_id = resolve_site(site)
    rows = queries.traffic_by_date(client, property_id, start, end, granularity=granularity)  # type: ignore[arg-type]
    return [r.to_dict() for r in rows]


@mcp.tool()
def pageviews_for_paths(
    site: str,
    paths: list[str],
    last: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict[str, Any]]:
    """Return pageviews and users for specific URL paths on a site.

    Use this when you already know which pages you care about — faster and more
    targeted than top_pages.

    Args:
        site: Friendly site name or numeric property ID.
        paths: List of URL paths to query, e.g. ['/about', '/contact'].
        last: Relative date range, e.g. '30d'.
        start_date / end_date: Explicit range.

    Returns a list of {path, title, pageviews, active_users, engagement_rate}.
    """
    client, config = _client_and_config()
    start, end = _resolve_dates(last, start_date, end_date, config.default_lookback_days)
    property_id = resolve_site(site)
    rows = queries.pageviews_for_paths(client, property_id, paths, start, end)
    return [r.to_dict() for r in rows]


@mcp.tool()
def top_landing_pages(
    site: str,
    last: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 25,
) -> list[dict[str, Any]]:
    """Return the top pages where sessions begin (entry points) for a site.

    Different signal than top_pages — these are the first pages in a session,
    useful for understanding where traffic is arriving rather than what gets read.
    """
    client, config = _client_and_config()
    start, end = _resolve_dates(last, start_date, end_date, config.default_lookback_days)
    property_id = resolve_site(site)
    rows = queries.top_landing_pages(client, property_id, start, end, limit=limit)
    return [r.to_dict() for r in rows]


@mcp.tool()
def site_summary(
    site: str,
    last: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """One-call site summary: totals plus device and channel breakdowns.

    Good starting query for any site investigation. Surfaces whether mobile/desktop
    or paid/organic is the meaningful axis before you go deeper.

    Returns {total_sessions, total_active_users, total_pageviews, by_device, by_channel}.
    """
    client, config = _client_and_config()
    start, end = _resolve_dates(last, start_date, end_date, config.default_lookback_days)
    property_id = resolve_site(site)
    summary = queries.device_and_channel_breakdown(client, property_id, start, end)
    return summary.to_dict()


@mcp.tool()
def health_check(days: int = 3) -> dict[str, Any]:
    """Check every configured site is still receiving GA4 data.

    Window is `days` full days ending yesterday (GA4 processing lags 24-48h).
    A site is dead when it shows zero active users AND zero pageviews across
    the whole window — stray bot sessions don't count as alive. Sites marked
    skip_health_check in sites.yaml report as skipped; 403s as no_access.

    Returns {window_days, healthy, results: [{site, property_id, status,
    active_users, pageviews, detail}]}.
    """
    client, _config = _client_and_config()
    sites = load_sites()
    results = []
    for name, cfg in sites.items():
        if cfg.skip_health_check:
            results.append(
                queries.HealthResult(name, cfg.property_id, "skipped", 0, 0, detail="skip_health_check")
            )
            continue
        results.append(queries.health_check_site(client, name, cfg.property_id, window_days=days))
    return {
        "window_days": days,
        "healthy": all(r.status in ("ok", "skipped", "no_access") for r in results),
        "results": [r.to_dict() for r in results],
    }


@mcp.tool()
def top_campaigns(
    site: str,
    last: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 25,
    only_attributed: bool = False,
) -> list[dict[str, Any]]:
    """Return the top UTM campaigns by sessions for a site, with source/medium breakdown.

    Session-scoped — answers "which campaigns drove traffic in this period?"

    Args:
        site: Friendly site name (from list_sites) or numeric GA4 property ID.
        last: Relative date range like '30d'. Mutually exclusive with start/end.
        start_date / end_date: Explicit YYYY-MM-DD range.
        limit: Max rows to return. Default 25.
        only_attributed: If True, filter out "(not set)" / "(not provided)" rows.

    Returns a list of {primary (campaign), secondary (source/medium), sessions,
    active_users, engagement_rate, attributed}. Unattributed rows appear at the
    end with attributed=False — callers that want clean data can filter those out
    (or pass only_attributed=True).
    """
    client, config = _client_and_config()
    start, end = _resolve_dates(last, start_date, end_date, config.default_lookback_days)
    property_id = resolve_site(site)
    rows = queries.top_campaigns(client, property_id, start, end, limit=limit)
    if only_attributed:
        rows = [r for r in rows if r.attributed]
    return [r.to_dict() for r in rows]


@mcp.tool()
def top_sources(
    site: str,
    last: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 25,
    only_attributed: bool = False,
) -> list[dict[str, Any]]:
    """Return the top traffic sources by sessions for a site, with medium breakdown.

    Session-scoped — answers "where is traffic coming from?"

    "(direct)" traffic IS included (typed URLs, bookmarks, app links — real
    traffic with no referrer). "(not set)" / "(not provided)" rows are
    partitioned at the end with attributed=False.

    Args / Returns: same shape as top_campaigns.
    """
    client, config = _client_and_config()
    start, end = _resolve_dates(last, start_date, end_date, config.default_lookback_days)
    property_id = resolve_site(site)
    rows = queries.top_sources(client, property_id, start, end, limit=limit)
    if only_attributed:
        rows = [r for r in rows if r.attributed]
    return [r.to_dict() for r in rows]


@mcp.tool()
def top_channels(
    site: str,
    last: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 25,
    only_attributed: bool = False,
) -> list[dict[str, Any]]:
    """Return the top default channel groupings by sessions, with source breakdown.

    Uses GA4's `sessionDefaultChannelGroup` (Organic Search, Paid Search, Social,
    Direct, Referral, Email, Display, etc.) — answers "what's the organic/paid/
    social/direct split?"

    Args / Returns: same shape as top_campaigns.
    """
    client, config = _client_and_config()
    start, end = _resolve_dates(last, start_date, end_date, config.default_lookback_days)
    property_id = resolve_site(site)
    rows = queries.top_channels(client, property_id, start, end, limit=limit)
    if only_attributed:
        rows = [r for r in rows if r.attributed]
    return [r.to_dict() for r in rows]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the MCP server on stdio transport (default for MCP clients)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger.info("Starting ga4-toolkit MCP server")
    mcp.run()


if __name__ == "__main__":
    main()
