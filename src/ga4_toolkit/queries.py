"""Core GA4 query functions.

Every function is a pure adapter over the GA4 Data API's `run_report` endpoint.
Return types are plain dataclasses — easy to serialize to JSON, tabulate, or
pass through an MCP response envelope.

Design principles:
  1. All queries take a `client` argument so tests can inject a mock.
  2. Date ranges are ISO strings ("YYYY-MM-DD") or GA4 relative strings ("30daysAgo").
  3. Property IDs are numeric strings — the GA4 Data API requires the
     "properties/<id>" URI prefix, which is built inside each function.
  4. No function hides an error; we let the underlying client exceptions propagate.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from google.analytics.data_v1beta import BetaAnalyticsDataClient


# ---------------------------------------------------------------------------
# Return type dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PageStat:
    """A single page's aggregate statistics over a date range."""

    path: str
    title: str
    pageviews: int
    active_users: int
    engagement_rate: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TrafficPoint:
    """A single time-series point."""

    date: str  # YYYY-MM-DD
    sessions: int
    active_users: int
    pageviews: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ChannelBreakdown:
    """One row of the channel/device summary."""

    dimension: str  # channel name or device category
    sessions: int
    active_users: int
    pageviews: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SiteSummary:
    """Aggregate summary from device_and_channel_breakdown."""

    total_sessions: int
    total_active_users: int
    total_pageviews: int
    by_device: list[ChannelBreakdown]
    by_channel: list[ChannelBreakdown]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_sessions": self.total_sessions,
            "total_active_users": self.total_active_users,
            "total_pageviews": self.total_pageviews,
            "by_device": [b.to_dict() for b in self.by_device],
            "by_channel": [b.to_dict() for b in self.by_channel],
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _property(property_id: str) -> str:
    """Return the GA4 property URI for the run_report call."""
    return f"properties/{property_id}"


def _normalize_date(d: str | date | datetime) -> str:
    """Accept ISO dates, date objects, or GA4 relative strings; return whatever GA4 accepts."""
    if isinstance(d, str):
        return d
    if isinstance(d, datetime):
        return d.date().isoformat()
    if isinstance(d, date):
        return d.isoformat()
    raise TypeError(f"Unsupported date type: {type(d)!r}")


def _int(value: str | None) -> int:
    """Safely coerce a GA4 metric string to int."""
    if value is None or value == "":
        return 0
    try:
        return int(float(value))  # metrics sometimes come back as "1.0"
    except (ValueError, TypeError):
        return 0


def _float(value: str | None) -> float:
    if value is None or value == "":
        return 0.0
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


def days_ago_range(days: int) -> tuple[str, str]:
    """Return (start, end) as ISO dates spanning the last `days` days, ending yesterday."""
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    return start.isoformat(), end.isoformat()


# ---------------------------------------------------------------------------
# Query functions — the v0.1 five
# ---------------------------------------------------------------------------


def top_pages(
    client: BetaAnalyticsDataClient,
    property_id: str,
    start_date: str | date,
    end_date: str | date,
    limit: int = 25,
) -> list[PageStat]:
    """Top pages by pageviews over a date range.

    Answers: "What are the most-visited pages on this site?"
    First consumer: Yale Budget Lab VRT config.
    """
    from google.analytics.data_v1beta.types import (
        DateRange,
        Dimension,
        Metric,
        OrderBy,
        RunReportRequest,
    )

    request = RunReportRequest(
        property=_property(property_id),
        date_ranges=[DateRange(start_date=_normalize_date(start_date), end_date=_normalize_date(end_date))],
        dimensions=[Dimension(name="pagePath"), Dimension(name="pageTitle")],
        metrics=[
            Metric(name="screenPageViews"),
            Metric(name="activeUsers"),
            Metric(name="engagementRate"),
        ],
        order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="screenPageViews"), desc=True)],
        limit=limit,
    )
    response = client.run_report(request)

    return [
        PageStat(
            path=row.dimension_values[0].value,
            title=row.dimension_values[1].value,
            pageviews=_int(row.metric_values[0].value),
            active_users=_int(row.metric_values[1].value),
            engagement_rate=_float(row.metric_values[2].value),
        )
        for row in response.rows
    ]


def traffic_by_date(
    client: BetaAnalyticsDataClient,
    property_id: str,
    start_date: str | date,
    end_date: str | date,
    granularity: Literal["day", "week", "month"] = "day",
) -> list[TrafficPoint]:
    """Time-series traffic counts over a date range.

    Answers: "Is traffic trending up/down? Any spikes or dips?"
    """
    from google.analytics.data_v1beta.types import (
        DateRange,
        Dimension,
        Metric,
        OrderBy,
        RunReportRequest,
    )

    dimension_name = {"day": "date", "week": "yearWeek", "month": "yearMonth"}[granularity]

    request = RunReportRequest(
        property=_property(property_id),
        date_ranges=[DateRange(start_date=_normalize_date(start_date), end_date=_normalize_date(end_date))],
        dimensions=[Dimension(name=dimension_name)],
        metrics=[
            Metric(name="sessions"),
            Metric(name="activeUsers"),
            Metric(name="screenPageViews"),
        ],
        order_bys=[OrderBy(dimension=OrderBy.DimensionOrderBy(dimension_name=dimension_name))],
    )
    response = client.run_report(request)

    return [
        TrafficPoint(
            date=_format_date_dim(row.dimension_values[0].value, granularity),
            sessions=_int(row.metric_values[0].value),
            active_users=_int(row.metric_values[1].value),
            pageviews=_int(row.metric_values[2].value),
        )
        for row in response.rows
    ]


def _format_date_dim(raw: str, granularity: str) -> str:
    """GA4 returns 'YYYYMMDD' for day, 'YYYYWW' for week, 'YYYYMM' for month. Normalize."""
    if granularity == "day" and len(raw) == 8:
        return f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"
    if granularity == "month" and len(raw) == 6:
        return f"{raw[0:4]}-{raw[4:6]}"
    if granularity == "week" and len(raw) == 6:
        return f"{raw[0:4]}-W{raw[4:6]}"
    return raw


def pageviews_for_paths(
    client: BetaAnalyticsDataClient,
    property_id: str,
    paths: list[str],
    start_date: str | date,
    end_date: str | date,
) -> list[PageStat]:
    """Pageviews and users for a specific list of URL paths.

    Answers: "How does THIS page perform?" Useful when you already know which
    pages you care about (e.g., landing pages, investigation targets).

    Uses an `inListFilter` on pagePath so GA4 only returns rows for the requested paths.
    """
    from google.analytics.data_v1beta.types import (
        DateRange,
        Dimension,
        Filter,
        FilterExpression,
        Metric,
        RunReportRequest,
    )

    path_filter = FilterExpression(
        filter=Filter(
            field_name="pagePath",
            in_list_filter=Filter.InListFilter(values=list(paths)),
        )
    )

    request = RunReportRequest(
        property=_property(property_id),
        date_ranges=[DateRange(start_date=_normalize_date(start_date), end_date=_normalize_date(end_date))],
        dimensions=[Dimension(name="pagePath"), Dimension(name="pageTitle")],
        metrics=[
            Metric(name="screenPageViews"),
            Metric(name="activeUsers"),
            Metric(name="engagementRate"),
        ],
        dimension_filter=path_filter,
    )
    response = client.run_report(request)

    return [
        PageStat(
            path=row.dimension_values[0].value,
            title=row.dimension_values[1].value,
            pageviews=_int(row.metric_values[0].value),
            active_users=_int(row.metric_values[1].value),
            engagement_rate=_float(row.metric_values[2].value),
        )
        for row in response.rows
    ]


def top_landing_pages(
    client: BetaAnalyticsDataClient,
    property_id: str,
    start_date: str | date,
    end_date: str | date,
    limit: int = 25,
) -> list[PageStat]:
    """Top pages where sessions begin — different signal than top-overall.

    Answers: "What are people arriving at?" (vs. "What pages are getting viewed at all?")
    """
    from google.analytics.data_v1beta.types import (
        DateRange,
        Dimension,
        Metric,
        OrderBy,
        RunReportRequest,
    )

    request = RunReportRequest(
        property=_property(property_id),
        date_ranges=[DateRange(start_date=_normalize_date(start_date), end_date=_normalize_date(end_date))],
        dimensions=[Dimension(name="landingPage"), Dimension(name="pageTitle")],
        metrics=[
            Metric(name="sessions"),
            Metric(name="activeUsers"),
            Metric(name="engagementRate"),
        ],
        order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="sessions"), desc=True)],
        limit=limit,
    )
    response = client.run_report(request)

    return [
        PageStat(
            path=row.dimension_values[0].value,
            title=row.dimension_values[1].value,
            pageviews=_int(row.metric_values[0].value),  # sessions, reused as the "count" slot
            active_users=_int(row.metric_values[1].value),
            engagement_rate=_float(row.metric_values[2].value),
        )
        for row in response.rows
    ]


def device_and_channel_breakdown(
    client: BetaAnalyticsDataClient,
    property_id: str,
    start_date: str | date,
    end_date: str | date,
) -> SiteSummary:
    """One-call summary: totals + device split + channel split.

    Answers: "Give me a quick pulse of this site." Good starting query for any
    investigation; surfaces whether to go deeper on mobile/desktop or paid/organic.
    """
    from google.analytics.data_v1beta.types import (
        DateRange,
        Dimension,
        Metric,
        RunReportRequest,
    )

    date_range = DateRange(start_date=_normalize_date(start_date), end_date=_normalize_date(end_date))
    metrics = [
        Metric(name="sessions"),
        Metric(name="activeUsers"),
        Metric(name="screenPageViews"),
    ]

    # Totals query — no dimension
    totals_req = RunReportRequest(
        property=_property(property_id),
        date_ranges=[date_range],
        metrics=metrics,
    )
    totals_resp = client.run_report(totals_req)
    if totals_resp.rows:
        row = totals_resp.rows[0]
        total_sessions = _int(row.metric_values[0].value)
        total_users = _int(row.metric_values[1].value)
        total_pageviews = _int(row.metric_values[2].value)
    else:
        total_sessions = total_users = total_pageviews = 0

    # By device
    by_device = _breakdown_query(client, property_id, date_range, "deviceCategory", metrics)
    # By channel
    by_channel = _breakdown_query(client, property_id, date_range, "sessionDefaultChannelGroup", metrics)

    return SiteSummary(
        total_sessions=total_sessions,
        total_active_users=total_users,
        total_pageviews=total_pageviews,
        by_device=by_device,
        by_channel=by_channel,
    )


def _breakdown_query(
    client: BetaAnalyticsDataClient,
    property_id: str,
    date_range: Any,
    dimension_name: str,
    metrics: list[Any],
) -> list[ChannelBreakdown]:
    from google.analytics.data_v1beta.types import Dimension, OrderBy, RunReportRequest

    request = RunReportRequest(
        property=_property(property_id),
        date_ranges=[date_range],
        dimensions=[Dimension(name=dimension_name)],
        metrics=metrics,
        order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="sessions"), desc=True)],
    )
    response = client.run_report(request)
    return [
        ChannelBreakdown(
            dimension=row.dimension_values[0].value,
            sessions=_int(row.metric_values[0].value),
            active_users=_int(row.metric_values[1].value),
            pageviews=_int(row.metric_values[2].value),
        )
        for row in response.rows
    ]
