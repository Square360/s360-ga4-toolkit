"""Unit tests for the Admin API retention audit, using a mocked service."""

from __future__ import annotations

from unittest.mock import MagicMock

from ga4_toolkit.admin import retention_audit
from ga4_toolkit.config import SiteConfig


def _service(summaries: list[dict], retention: dict[str, dict]) -> MagicMock:
    svc = MagicMock()
    req = MagicMock()
    req.execute.return_value = {"accountSummaries": summaries}
    svc.accountSummaries.return_value.list.return_value = req
    svc.accountSummaries.return_value.list_next.return_value = None

    def _get(name: str) -> MagicMock:
        pid = name.split("/")[1]
        call = MagicMock()
        if pid not in retention:
            call.execute.side_effect = RuntimeError("403 forbidden")
        else:
            call.execute.return_value = retention[pid]
        return call

    svc.properties.return_value.getDataRetentionSettings.side_effect = _get
    return svc


def test_retention_audit_flags_short_and_errors() -> None:
    summaries = [
        {
            "displayName": "Acct",
            "propertySummaries": [
                {"property": "properties/1", "displayName": "Good"},
                {"property": "properties/2", "displayName": "Short"},
                {"property": "properties/3", "displayName": "Broken"},
            ],
        }
    ]
    retention = {
        "1": {"eventDataRetention": "FOURTEEN_MONTHS", "userDataRetention": "FOURTEEN_MONTHS"},
        "2": {"eventDataRetention": "TWO_MONTHS", "userDataRetention": "FOURTEEN_MONTHS"},
    }
    sites = {"good": SiteConfig(friendly_name="good", property_id="1", domain="good.example")}

    results = retention_audit(_service(summaries, retention), sites)

    by_id = {r.property_id: r for r in results}
    assert by_id["1"].status == "ok" and by_id["1"].site == "good"
    assert by_id["2"].status == "short" and by_id["2"].event_retention == "TWO_MONTHS"
    assert by_id["3"].status == "error" and "403" in by_id["3"].detail
    # non-ok rows sort first
    assert results[-1].property_id == "1"
