"""Configuration loader for ga4_toolkit.

Two inputs:
  1. sites.yaml — friendly-name → property mapping (committed-example, gitignored-real)
  2. .env / environment variables — service-account path, defaults, log level

Both are loaded lazily. Callers that only use the library (not the CLI/MCP)
can pass explicit values and skip the file-based config entirely.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

# Load .env once at import time. Callers can also set env vars directly; os.environ wins.
load_dotenv()


class ConfigError(ValueError):
    """Raised when configuration is missing or malformed."""


@dataclass(frozen=True)
class SiteConfig:
    """A single site entry from sites.yaml."""

    friendly_name: str
    property_id: str
    domain: str
    notes: str = ""
    skip_health_check: bool = False


@dataclass(frozen=True)
class ToolkitConfig:
    """Top-level runtime config."""

    service_account_path: Path
    default_lookback_days: int = 30
    log_level: str = "INFO"
    sites_config_path: Path | None = None


def load_toolkit_config(
    *,
    service_account_path: str | Path | None = None,
    sites_config_path: str | Path | None = None,
    default_lookback_days: int | None = None,
    log_level: str | None = None,
) -> ToolkitConfig:
    """Load toolkit config, with explicit arguments overriding environment variables.

    Explicit arguments take precedence over env vars, which take precedence over defaults.
    Raises ConfigError if the service-account path is missing or the file does not exist.
    """
    sa_path = service_account_path or os.environ.get("GA4_SERVICE_ACCOUNT_PATH")
    if not sa_path:
        raise ConfigError(
            "No service-account path configured. Set GA4_SERVICE_ACCOUNT_PATH in .env "
            "or pass service_account_path explicitly."
        )
    sa_path = Path(sa_path).expanduser().resolve()
    if not sa_path.is_file():
        raise ConfigError(f"Service-account file does not exist: {sa_path}")

    sites_path_raw = sites_config_path or os.environ.get("GA4_SITES_CONFIG")
    sites_path = Path(sites_path_raw).expanduser().resolve() if sites_path_raw else None

    lookback = default_lookback_days
    if lookback is None:
        env_val = os.environ.get("GA4_DEFAULT_LOOKBACK_DAYS")
        lookback = int(env_val) if env_val else 30

    level = log_level or os.environ.get("GA4_LOG_LEVEL", "INFO")

    return ToolkitConfig(
        service_account_path=sa_path,
        default_lookback_days=lookback,
        log_level=level.upper(),
        sites_config_path=sites_path,
    )


def load_sites(sites_path: str | Path | None = None) -> dict[str, SiteConfig]:
    """Load the site friendly-name → SiteConfig mapping from a YAML file.

    If `sites_path` is explicitly provided, it must exist or ConfigError is raised —
    no silent fallback, since an explicit path mis-specified is almost always a bug.

    If `sites_path` is None, auto-discovery order:
      1. GA4_SITES_CONFIG environment variable
      2. ./config/sites.yaml relative to the current working directory
      3. ./config/sites.example.yaml as a fallback
    """
    chosen: Path | None = None

    if sites_path:
        explicit = Path(sites_path).expanduser().resolve()
        if not explicit.is_file():
            raise ConfigError(f"Sites config file does not exist: {explicit}")
        chosen = explicit
    else:
        candidates: list[Path] = []
        env_path = os.environ.get("GA4_SITES_CONFIG")
        if env_path:
            candidates.append(Path(env_path).expanduser().resolve())
        candidates.append(Path("config/sites.yaml").resolve())
        candidates.append(Path("config/sites.example.yaml").resolve())

        for candidate in candidates:
            if candidate.is_file():
                chosen = candidate
                break

    if chosen is None:
        raise ConfigError(
            "No sites config found. Create config/sites.yaml from the example, "
            "or set GA4_SITES_CONFIG to point at your config file."
        )

    with chosen.open("r") as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    sites_section = raw.get("sites", {})
    if not isinstance(sites_section, dict):
        raise ConfigError(f"Malformed sites config at {chosen}: 'sites' must be a mapping.")

    result: dict[str, SiteConfig] = {}
    for friendly_name, entry in sites_section.items():
        if not isinstance(entry, dict):
            raise ConfigError(
                f"Malformed site entry '{friendly_name}' in {chosen}: expected a mapping."
            )
        property_id = entry.get("property_id")
        if not property_id or property_id == "000000000":
            # Skip placeholder entries silently — they're scaffolding, not errors.
            continue
        result[friendly_name] = SiteConfig(
            friendly_name=friendly_name,
            property_id=str(property_id),
            domain=str(entry.get("domain", "")),
            notes=str(entry.get("notes", "")),
            skip_health_check=bool(entry.get("skip_health_check", False)),
        )

    return result


def resolve_site(name_or_id: str, sites: dict[str, SiteConfig] | None = None) -> str:
    """Resolve a friendly site name to a GA4 property ID.

    If `name_or_id` is numeric, it's returned as-is (assumed to be a property ID).
    Otherwise, looked up in the sites mapping. If no mapping is provided, loads the default.
    """
    if name_or_id.isdigit():
        return name_or_id

    if sites is None:
        sites = load_sites()

    if name_or_id not in sites:
        known = ", ".join(sorted(sites.keys())) or "(none)"
        raise ConfigError(
            f"Unknown site '{name_or_id}'. Known sites: {known}. "
            f"Either add it to sites.yaml or pass a numeric property ID directly."
        )
    return sites[name_or_id].property_id
