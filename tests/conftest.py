"""Shared pytest fixtures.

The GA4 client is mocked at the boundary — we build fake response objects that
mirror the structure of `google.analytics.data_v1beta.types.RunReportResponse`
and feed them into a MagicMock standing in for `BetaAnalyticsDataClient`.

This means we never need the real Google client library installed to run tests
(though it's a dev dependency anyway for type-checking). Fixtures are composable:
each test builds only the response shape it needs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Fake GA4 response shapes — match the proto field names we care about
# ---------------------------------------------------------------------------


@dataclass
class FakeValue:
    value: str


@dataclass
class FakeRow:
    dimension_values: list[FakeValue] = field(default_factory=list)
    metric_values: list[FakeValue] = field(default_factory=list)


@dataclass
class FakeResponse:
    rows: list[FakeRow] = field(default_factory=list)


def make_row(dimensions: list[str], metrics: list[str | int | float]) -> FakeRow:
    """Build a FakeRow from plain Python values."""
    return FakeRow(
        dimension_values=[FakeValue(value=str(d)) for d in dimensions],
        metric_values=[FakeValue(value=str(m)) for m in metrics],
    )


# ---------------------------------------------------------------------------
# Client fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_client() -> MagicMock:
    """A bare mock client. Individual tests set `.run_report.return_value`."""
    client = MagicMock()
    return client


@pytest.fixture
def mock_client_queued() -> tuple[MagicMock, list[FakeResponse]]:
    """A mock client whose `run_report` pops from a queue on each call.

    Useful for tests that make multiple GA4 calls (e.g., device_and_channel_breakdown
    which issues three requests). Append FakeResponse objects to the returned list
    in the order the code will call them.
    """
    client = MagicMock()
    queue: list[FakeResponse] = []

    def _side_effect(*args: Any, **kwargs: Any) -> FakeResponse:
        if not queue:
            raise AssertionError("mock_client_queued called more times than responses queued")
        return queue.pop(0)

    client.run_report.side_effect = _side_effect
    return client, queue
