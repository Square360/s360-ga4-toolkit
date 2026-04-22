"""GA4 Data API client factory.

Builds an authenticated `BetaAnalyticsDataClient` from a service-account JSON file.
Kept deliberately thin so queries.py can accept either a real client (production)
or a mock (tests) without caring which.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from google.oauth2 import service_account

if TYPE_CHECKING:
    from google.analytics.data_v1beta import BetaAnalyticsDataClient


GA4_READONLY_SCOPE = "https://www.googleapis.com/auth/analytics.readonly"


def build_client(service_account_path: str | Path) -> BetaAnalyticsDataClient:
    """Build an authenticated GA4 Data API client from a service-account JSON file.

    The client is read-only by scope. Even if the service account's IAM grant were
    misconfigured, the analytics.readonly scope limits what this client can do.
    """
    # Imported here so consumers that only use queries via mocks don't pay the
    # import cost of the Google client library.
    from google.analytics.data_v1beta import BetaAnalyticsDataClient

    path = Path(service_account_path).expanduser().resolve()
    credentials = service_account.Credentials.from_service_account_file(
        str(path),
        scopes=[GA4_READONLY_SCOPE],
    )
    return BetaAnalyticsDataClient(credentials=credentials)


@lru_cache(maxsize=4)
def default_client(service_account_path: str | Path) -> BetaAnalyticsDataClient:
    """Cached client factory keyed on service-account path.

    Reuses the same client across calls in a single process. Useful for the CLI
    and MCP server where multiple queries hit the same property in one session.
    """
    return build_client(service_account_path)
