"""Portable GA4 Data API toolkit — read-only query library.

Exports the core query functions so callers can write either:

    from ga4_toolkit import top_pages
    from ga4_toolkit.queries import top_pages

Both forms are supported. The CLI (`ga4`) and MCP server (`ga4-mcp`)
are thin wrappers over this same module.
"""

from ga4_toolkit.queries import (
    device_and_channel_breakdown,
    pageviews_for_paths,
    top_campaigns,
    top_channels,
    top_landing_pages,
    top_pages,
    top_sources,
    traffic_by_date,
)

__version__ = "0.3.0"

__all__ = [
    "__version__",
    "device_and_channel_breakdown",
    "pageviews_for_paths",
    "top_campaigns",
    "top_channels",
    "top_landing_pages",
    "top_pages",
    "top_sources",
    "traffic_by_date",
]
