"""Tests for the config loader."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import yaml

from ga4_toolkit.config import (
    ConfigError,
    SiteConfig,
    load_sites,
    load_toolkit_config,
    resolve_site,
)


def _write_sites_file(path: Path, data: dict[str, Any]) -> None:
    with path.open("w") as f:
        yaml.safe_dump(data, f)


# ---------------------------------------------------------------------------
# load_sites
# ---------------------------------------------------------------------------


def test_load_sites_parses_valid_yaml(tmp_path: Path) -> None:
    sites_file = tmp_path / "sites.yaml"
    _write_sites_file(
        sites_file,
        {
            "sites": {
                "budget-lab": {
                    "property_id": "123456789",
                    "domain": "budgetlab.yale.edu",
                    "notes": "first consumer",
                },
                "square360": {
                    "property_id": "987654321",
                    "domain": "square360.com",
                },
            }
        },
    )

    sites = load_sites(sites_file)

    assert len(sites) == 2
    assert sites["budget-lab"] == SiteConfig(
        friendly_name="budget-lab",
        property_id="123456789",
        domain="budgetlab.yale.edu",
        notes="first consumer",
    )
    assert sites["square360"].property_id == "987654321"
    assert sites["square360"].notes == ""


def test_load_sites_skips_placeholder_entries(tmp_path: Path) -> None:
    sites_file = tmp_path / "sites.yaml"
    _write_sites_file(
        sites_file,
        {
            "sites": {
                "budget-lab": {"property_id": "000000000", "domain": "budgetlab.yale.edu"},
                "square360": {"property_id": "987654321", "domain": "square360.com"},
            }
        },
    )

    sites = load_sites(sites_file)

    # Placeholder "000000000" should be silently dropped
    assert "budget-lab" not in sites
    assert "square360" in sites


def test_load_sites_raises_on_explicit_missing_file(tmp_path: Path) -> None:
    # Explicit path that doesn't exist should raise, not silently fall back
    with pytest.raises(ConfigError, match="Sites config file does not exist"):
        load_sites(tmp_path / "nonexistent.yaml")


def test_load_sites_auto_discovery_raises_when_nothing_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # No explicit path, no env var, and cwd has no config/ — should raise
    monkeypatch.delenv("GA4_SITES_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigError, match="No sites config found"):
        load_sites()


def test_load_sites_raises_on_malformed_yaml(tmp_path: Path) -> None:
    sites_file = tmp_path / "sites.yaml"
    _write_sites_file(sites_file, {"sites": "this should be a mapping"})

    with pytest.raises(ConfigError, match="'sites' must be a mapping"):
        load_sites(sites_file)


# ---------------------------------------------------------------------------
# resolve_site
# ---------------------------------------------------------------------------


def test_resolve_site_returns_numeric_id_unchanged() -> None:
    # No sites mapping needed when input is already a property ID
    assert resolve_site("123456789", sites={}) == "123456789"


def test_resolve_site_looks_up_friendly_name() -> None:
    sites = {
        "budget-lab": SiteConfig("budget-lab", "123456789", "budgetlab.yale.edu"),
    }
    assert resolve_site("budget-lab", sites=sites) == "123456789"


def test_resolve_site_raises_on_unknown_name() -> None:
    sites = {
        "budget-lab": SiteConfig("budget-lab", "123456789", "budgetlab.yale.edu"),
    }
    with pytest.raises(ConfigError, match="Unknown site 'cases-som'"):
        resolve_site("cases-som", sites=sites)


# ---------------------------------------------------------------------------
# load_toolkit_config
# ---------------------------------------------------------------------------


def test_load_toolkit_config_requires_service_account(tmp_path: Path) -> None:
    with patch.dict(os.environ, {"GA4_SERVICE_ACCOUNT_PATH": ""}, clear=False):
        with pytest.raises(ConfigError, match="No service-account path"):
            load_toolkit_config()


def test_load_toolkit_config_validates_file_exists(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="does not exist"):
        load_toolkit_config(service_account_path=tmp_path / "nope.json")


def test_load_toolkit_config_uses_explicit_args(tmp_path: Path) -> None:
    sa = tmp_path / "fake-sa.json"
    sa.write_text("{}")

    config = load_toolkit_config(
        service_account_path=sa,
        default_lookback_days=90,
        log_level="debug",
    )

    assert config.service_account_path == sa.resolve()
    assert config.default_lookback_days == 90
    assert config.log_level == "DEBUG"  # normalized to uppercase
