"""Unit tests for the query functions, using mocked GA4 responses."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest

from ga4_toolkit.queries import (
    AcquisitionStat,
    health_check_site,
    ChannelBreakdown,
    PageStat,
    SiteSummary,
    TrafficPoint,
    days_ago_range,
    device_and_channel_breakdown,
    pageviews_for_paths,
    top_campaigns,
    top_channels,
    top_landing_pages,
    top_pages,
    top_sources,
    traffic_by_date,
)

from tests.conftest import FakeResponse, make_row

# Importing from conftest works because of `pythonpath = ["src"]` in pyproject.
# Fixtures are resolved automatically via conftest.py discovery.


# ---------------------------------------------------------------------------
# top_pages
# ---------------------------------------------------------------------------


def test_top_pages_parses_response(mock_client: MagicMock) -> None:
    mock_client.run_report.return_value = FakeResponse(
        rows=[
            make_row(["/", "Home"], ["4200", "1800", "0.62"]),
            make_row(["/about", "About Us"], ["900", "550", "0.71"]),
            make_row(["/research/topic-ai", "Topic: AI"], ["600", "410", "0.58"]),
        ]
    )

    result = top_pages(mock_client, "123456", "2026-03-01", "2026-03-31", limit=10)

    assert len(result) == 3
    assert result[0] == PageStat(path="/", title="Home", pageviews=4200, active_users=1800, engagement_rate=0.62)
    assert result[1].path == "/about"
    assert result[2].pageviews == 600


def test_top_pages_empty_response(mock_client: MagicMock) -> None:
    mock_client.run_report.return_value = FakeResponse(rows=[])
    result = top_pages(mock_client, "123456", "2026-03-01", "2026-03-31")
    assert result == []


def test_top_pages_handles_date_objects(mock_client: MagicMock) -> None:
    mock_client.run_report.return_value = FakeResponse(rows=[])
    # Just verifying no TypeError on date inputs
    top_pages(mock_client, "123456", date(2026, 3, 1), date(2026, 3, 31))
    assert mock_client.run_report.called


def test_top_pages_coerces_numeric_strings(mock_client: MagicMock) -> None:
    # GA4 sometimes returns metrics as "1.0" instead of "1"
    mock_client.run_report.return_value = FakeResponse(
        rows=[make_row(["/", "Home"], ["100.0", "50.0", "0.5"])]
    )
    result = top_pages(mock_client, "123456", "2026-03-01", "2026-03-31")
    assert result[0].pageviews == 100
    assert result[0].active_users == 50


# ---------------------------------------------------------------------------
# traffic_by_date
# ---------------------------------------------------------------------------


def test_traffic_by_date_normalizes_day_format(mock_client: MagicMock) -> None:
    mock_client.run_report.return_value = FakeResponse(
        rows=[
            make_row(["20260301"], ["250", "180", "520"]),
            make_row(["20260302"], ["300", "210", "610"]),
        ]
    )

    result = traffic_by_date(mock_client, "123456", "2026-03-01", "2026-03-02")

    assert len(result) == 2
    assert result[0] == TrafficPoint(date="2026-03-01", sessions=250, active_users=180, pageviews=520)
    assert result[1].date == "2026-03-02"


def test_traffic_by_date_month_granularity(mock_client: MagicMock) -> None:
    mock_client.run_report.return_value = FakeResponse(
        rows=[make_row(["202603"], ["8000", "5400", "15000"])]
    )
    result = traffic_by_date(mock_client, "123456", "2026-03-01", "2026-03-31", granularity="month")
    assert result[0].date == "2026-03"


def test_traffic_by_date_week_granularity(mock_client: MagicMock) -> None:
    mock_client.run_report.return_value = FakeResponse(
        rows=[make_row(["202610"], ["1200", "800", "2400"])]
    )
    result = traffic_by_date(mock_client, "123456", "2026-03-01", "2026-03-07", granularity="week")
    assert result[0].date == "2026-W10"


# ---------------------------------------------------------------------------
# pageviews_for_paths
# ---------------------------------------------------------------------------


def test_pageviews_for_paths_returns_requested_paths(mock_client: MagicMock) -> None:
    mock_client.run_report.return_value = FakeResponse(
        rows=[
            make_row(["/about", "About Us"], ["900", "550", "0.71"]),
            make_row(["/contact", "Contact"], ["300", "220", "0.65"]),
        ]
    )

    result = pageviews_for_paths(
        mock_client,
        "123456",
        paths=["/about", "/contact"],
        start_date="2026-03-01",
        end_date="2026-03-31",
    )

    assert len(result) == 2
    assert {r.path for r in result} == {"/about", "/contact"}


def test_pageviews_for_paths_empty_list_still_valid(mock_client: MagicMock) -> None:
    # GA4 would return no rows for a zero-length filter; test our handling
    mock_client.run_report.return_value = FakeResponse(rows=[])
    result = pageviews_for_paths(mock_client, "123456", paths=[], start_date="2026-03-01", end_date="2026-03-31")
    assert result == []


# ---------------------------------------------------------------------------
# top_landing_pages
# ---------------------------------------------------------------------------


def test_top_landing_pages_parses_response(mock_client: MagicMock) -> None:
    mock_client.run_report.return_value = FakeResponse(
        rows=[
            make_row(["/", "Home"], ["1500", "1200", "0.58"]),
            make_row(["/research", "Research"], ["600", "500", "0.72"]),
        ]
    )

    result = top_landing_pages(mock_client, "123456", "2026-03-01", "2026-03-31")

    assert len(result) == 2
    assert result[0].path == "/"
    assert result[0].pageviews == 1500  # sessions, reused as the "count" slot
    assert result[0].title == "Home"


# ---------------------------------------------------------------------------
# device_and_channel_breakdown
# ---------------------------------------------------------------------------


def test_device_and_channel_breakdown_combines_three_calls(
    mock_client_queued: tuple[MagicMock, list[FakeResponse]],
) -> None:
    client, queue = mock_client_queued

    # Call 1: totals (no dimension, one row)
    queue.append(FakeResponse(rows=[make_row([], ["10000", "6500", "22000"])]))
    # Call 2: by device
    queue.append(
        FakeResponse(
            rows=[
                make_row(["mobile"], ["6000", "4000", "12000"]),
                make_row(["desktop"], ["3500", "2200", "9000"]),
                make_row(["tablet"], ["500", "300", "1000"]),
            ]
        )
    )
    # Call 3: by channel
    queue.append(
        FakeResponse(
            rows=[
                make_row(["Organic Search"], ["5000", "3300", "11000"]),
                make_row(["Direct"], ["3000", "2000", "7000"]),
                make_row(["Referral"], ["2000", "1200", "4000"]),
            ]
        )
    )

    result = device_and_channel_breakdown(client, "123456", "2026-03-01", "2026-03-31")

    assert isinstance(result, SiteSummary)
    assert result.total_sessions == 10000
    assert result.total_active_users == 6500
    assert result.total_pageviews == 22000

    assert len(result.by_device) == 3
    assert result.by_device[0] == ChannelBreakdown(
        dimension="mobile", sessions=6000, active_users=4000, pageviews=12000
    )

    assert len(result.by_channel) == 3
    assert {c.dimension for c in result.by_channel} == {"Organic Search", "Direct", "Referral"}


def test_device_and_channel_breakdown_empty_property(
    mock_client_queued: tuple[MagicMock, list[FakeResponse]],
) -> None:
    client, queue = mock_client_queued
    queue.append(FakeResponse(rows=[]))  # totals: no rows at all
    queue.append(FakeResponse(rows=[]))  # by device
    queue.append(FakeResponse(rows=[]))  # by channel

    result = device_and_channel_breakdown(client, "123456", "2026-03-01", "2026-03-31")

    assert result.total_sessions == 0
    assert result.total_active_users == 0
    assert result.total_pageviews == 0
    assert result.by_device == []
    assert result.by_channel == []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_days_ago_range_produces_iso_dates() -> None:
    start, end = days_ago_range(7)
    # Both must be ISO format (YYYY-MM-DD); sanity-check structure without hardcoding dates.
    assert len(start) == 10 and start[4] == "-" and start[7] == "-"
    assert len(end) == 10
    # End is strictly after start
    assert start < end


def test_days_ago_range_is_inclusive() -> None:
    start, end = days_ago_range(1)
    # "last 1 day" means a single day — start == end
    assert start == end


@pytest.mark.parametrize(
    "date_input,expected",
    [
        ("2026-03-01", "2026-03-01"),
        ("30daysAgo", "30daysAgo"),  # GA4 relative strings pass through
        (date(2026, 3, 15), "2026-03-15"),
    ],
)
def test_normalize_date_accepts_multiple_forms(date_input: object, expected: str) -> None:
    from ga4_toolkit.queries import _normalize_date

    assert _normalize_date(date_input) == expected


# ---------------------------------------------------------------------------
# top_campaigns / top_sources / top_channels — v0.2 acquisition queries
# ---------------------------------------------------------------------------


def test_top_campaigns_parses_and_partitions(mock_client: MagicMock) -> None:
    """Attributed rows first (order preserved), unattributed last with attributed=False."""
    mock_client.run_report.return_value = FakeResponse(
        rows=[
            make_row(["spring-sale", "google / cpc"], ["1200", "900", "0.65"]),
            make_row(["(not set)", "(direct) / (none)"], ["800", "600", "0.55"]),
            make_row(["newsletter-april", "email / email"], ["400", "350", "0.72"]),
        ]
    )

    result = top_campaigns(mock_client, "123456", "2026-03-01", "2026-03-31")

    assert len(result) == 3
    # Attributed rows first, unattributed last
    assert [r.primary for r in result] == ["spring-sale", "newsletter-april", "(not set)"]
    assert [r.attributed for r in result] == [True, True, False]
    assert result[0] == AcquisitionStat(
        primary="spring-sale",
        secondary="google / cpc",
        sessions=1200,
        active_users=900,
        engagement_rate=0.65,
        attributed=True,
    )


def test_top_sources_keeps_direct_traffic_as_attributed(mock_client: MagicMock) -> None:
    """(direct) / (none) is real traffic and must NOT be treated as unattributed."""
    mock_client.run_report.return_value = FakeResponse(
        rows=[
            make_row(["google", "organic"], ["5000", "3800", "0.68"]),
            make_row(["(direct)", "(none)"], ["3000", "2500", "0.60"]),
            make_row(["(not set)", "(not set)"], ["200", "180", "0.45"]),
        ]
    )

    result = top_sources(mock_client, "123456", "2026-03-01", "2026-03-31")

    assert result[0].primary == "google"
    assert result[0].attributed is True
    # (direct) stays attributed — it's real traffic with no referrer
    assert result[1].primary == "(direct)"
    assert result[1].attributed is True
    # (not set) goes to the bottom, flagged unattributed
    assert result[2].primary == "(not set)"
    assert result[2].attributed is False


def test_top_channels_handles_not_provided_placeholder(mock_client: MagicMock) -> None:
    """Both '(not set)' and '(not provided)' count as unattributed."""
    mock_client.run_report.return_value = FakeResponse(
        rows=[
            make_row(["Organic Search", "google"], ["4000", "3100", "0.70"]),
            make_row(["(not provided)", "(not set)"], ["100", "80", "0.30"]),
            make_row(["Direct", "(direct)"], ["2000", "1600", "0.58"]),
        ]
    )

    result = top_channels(mock_client, "123456", "2026-03-01", "2026-03-31")

    # Attributed first (Organic, Direct), then unattributed (not provided)
    assert [r.primary for r in result] == ["Organic Search", "Direct", "(not provided)"]
    assert [r.attributed for r in result] == [True, True, False]


# ---------------------------------------------------------------------------
# health_check_site
# ---------------------------------------------------------------------------


def test_health_check_ok_with_real_traffic(mock_client: MagicMock) -> None:
    mock_client.run_report.return_value = FakeResponse(
        rows=[make_row(["20260805"], [40, 35, 90])]
    )
    result = health_check_site(mock_client, "example", "123456")
    assert result.status == "ok"
    assert result.active_users == 35
    assert result.pageviews == 90


def test_health_check_dead_when_no_rows(mock_client: MagicMock) -> None:
    mock_client.run_report.return_value = FakeResponse(rows=[])
    result = health_check_site(mock_client, "example", "123456")
    assert result.status == "dead"


def test_health_check_stray_sessions_are_not_alive(mock_client: MagicMock) -> None:
    # A dead property still logs occasional bot sessions with zero users and
    # zero pageviews — those must not count as signs of life.
    mock_client.run_report.return_value = FakeResponse(
        rows=[make_row(["20260805"], [1, 0, 0]), make_row(["20260806"], [2, 0, 0])]
    )
    result = health_check_site(mock_client, "example", "123456")
    assert result.status == "dead"


def test_health_check_no_access_on_403(mock_client: MagicMock) -> None:
    from google.api_core import exceptions as gexc

    mock_client.run_report.side_effect = gexc.PermissionDenied("no viewer role")
    result = health_check_site(mock_client, "example", "123456")
    assert result.status == "no_access"
