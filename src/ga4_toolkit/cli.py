"""Typer-based CLI.

Commands map 1:1 to the functions in queries.py. All business logic lives
in queries.py — this file is a presentation layer and parameter-parsing adapter.

Date-range handling: every command accepts either `--last NNd` (relative) or
`--start YYYY-MM-DD --end YYYY-MM-DD` (explicit). Output format defaults to a
rich-powered terminal table; `--format json` or `--format csv` opts out.
"""

from __future__ import annotations

import csv
import json
import logging
import re
import sys
from dataclasses import asdict
from datetime import date, timedelta
from enum import Enum
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from ga4_toolkit import __version__, queries
from ga4_toolkit.client import default_client
from ga4_toolkit.config import ConfigError, load_sites, load_toolkit_config, resolve_site

app = typer.Typer(
    name="ga4",
    help="Portable GA4 Data API toolkit. Read-only queries against any property you have Viewer access to.",
    no_args_is_help=True,
    add_completion=False,
)

console = Console()
err_console = Console(stderr=True)


class OutputFormat(str, Enum):
    TABLE = "table"
    JSON = "json"
    CSV = "csv"


# ---------------------------------------------------------------------------
# Shared option parsing
# ---------------------------------------------------------------------------


_RELATIVE_RE = re.compile(r"^(\d+)([dwmy])$")


def _parse_date_range(
    last: str | None,
    start: str | None,
    end: str | None,
    default_lookback_days: int,
) -> tuple[str, str]:
    """Resolve --last / --start --end into concrete ISO dates.

    Returns (start_date, end_date). If nothing is specified, uses
    default_lookback_days from config.
    """
    if last and (start or end):
        raise typer.BadParameter("Use either --last OR --start/--end, not both.")

    if last:
        match = _RELATIVE_RE.match(last)
        if not match:
            raise typer.BadParameter(f"--last must be like '30d' or '7d', got: {last!r}")
        value = int(match.group(1))
        unit = match.group(2)
        if unit == "d":
            days = value
        elif unit == "w":
            days = value * 7
        elif unit == "m":
            days = value * 30
        elif unit == "y":
            days = value * 365
        else:
            raise typer.BadParameter(f"Unknown time unit: {unit}")
        return queries.days_ago_range(days)

    if start and end:
        return start, end

    if start or end:
        raise typer.BadParameter("Provide both --start and --end, or use --last.")

    # Fall through to default lookback
    return queries.days_ago_range(default_lookback_days)


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _get_client() -> Any:
    try:
        config = load_toolkit_config()
    except ConfigError as e:
        err_console.print(f"[red]Config error:[/red] {e}")
        raise typer.Exit(code=2) from None
    _setup_logging(config.log_level)
    return default_client(config.service_account_path), config


def _render_pagestats(rows: list[queries.PageStat], fmt: OutputFormat, title: str) -> None:
    if fmt == OutputFormat.JSON:
        console.print_json(data=[r.to_dict() for r in rows])
    elif fmt == OutputFormat.CSV:
        writer = csv.DictWriter(sys.stdout, fieldnames=["path", "title", "pageviews", "active_users", "engagement_rate"])
        writer.writeheader()
        for r in rows:
            writer.writerow(r.to_dict())
    else:
        table = Table(title=title, show_lines=False, header_style="bold")
        table.add_column("#", justify="right", style="dim")
        table.add_column("Path", overflow="fold")
        table.add_column("Title", overflow="fold")
        table.add_column("Pageviews", justify="right")
        table.add_column("Active Users", justify="right")
        table.add_column("Engagement", justify="right")
        for i, r in enumerate(rows, 1):
            table.add_row(
                str(i),
                r.path,
                r.title or "—",
                f"{r.pageviews:,}",
                f"{r.active_users:,}",
                f"{r.engagement_rate:.1%}",
            )
        console.print(table)


def _render_traffic(rows: list[queries.TrafficPoint], fmt: OutputFormat, title: str) -> None:
    if fmt == OutputFormat.JSON:
        console.print_json(data=[r.to_dict() for r in rows])
    elif fmt == OutputFormat.CSV:
        writer = csv.DictWriter(sys.stdout, fieldnames=["date", "sessions", "active_users", "pageviews"])
        writer.writeheader()
        for r in rows:
            writer.writerow(r.to_dict())
    else:
        table = Table(title=title, show_lines=False, header_style="bold")
        table.add_column("Date")
        table.add_column("Sessions", justify="right")
        table.add_column("Active Users", justify="right")
        table.add_column("Pageviews", justify="right")
        for r in rows:
            table.add_row(r.date, f"{r.sessions:,}", f"{r.active_users:,}", f"{r.pageviews:,}")
        console.print(table)


def _render_acquisition(
    rows: list[queries.AcquisitionStat],
    fmt: OutputFormat,
    title: str,
    primary_label: str,
    secondary_label: str,
    only_attributed: bool = False,
) -> None:
    """Render a list of AcquisitionStat rows.

    In TABLE mode, attributed rows appear on top, then a dim separator, then
    unattributed rows in dim styling, then a footer line with the unattributed
    session total and share. In JSON/CSV the raw list is emitted in the same
    order the query returned it (attributed first, unattributed last), with the
    `attributed` boolean preserved.
    """
    if only_attributed:
        rows = [r for r in rows if r.attributed]

    fieldnames = ["primary", "secondary", "sessions", "active_users", "engagement_rate", "attributed"]

    if fmt == OutputFormat.JSON:
        console.print_json(data=[r.to_dict() for r in rows])
        return
    if fmt == OutputFormat.CSV:
        writer = csv.DictWriter(sys.stdout, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r.to_dict())
        return

    attributed_rows = [r for r in rows if r.attributed]
    unattributed_rows = [r for r in rows if not r.attributed]

    table = Table(title=title, show_lines=False, header_style="bold")
    table.add_column("#", justify="right", style="dim")
    table.add_column(primary_label, overflow="fold")
    table.add_column(secondary_label, overflow="fold")
    table.add_column("Sessions", justify="right")
    table.add_column("Active Users", justify="right")
    table.add_column("Engagement", justify="right")

    i = 0
    for r in attributed_rows:
        i += 1
        table.add_row(
            str(i),
            r.primary or "—",
            r.secondary or "—",
            f"{r.sessions:,}",
            f"{r.active_users:,}",
            f"{r.engagement_rate:.1%}",
        )

    if unattributed_rows:
        table.add_row("", "[dim]─── unattributed ───[/dim]", "", "", "", "")
        for r in unattributed_rows:
            i += 1
            table.add_row(
                f"[dim]{i}[/dim]",
                f"[dim]{r.primary}[/dim]",
                f"[dim]{r.secondary or '—'}[/dim]",
                f"[dim]{r.sessions:,}[/dim]",
                f"[dim]{r.active_users:,}[/dim]",
                f"[dim]{r.engagement_rate:.1%}[/dim]",
            )

    console.print(table)

    # Footer: unattributed session share
    if unattributed_rows:
        unattrib_sessions = sum(r.sessions for r in unattributed_rows)
        total_sessions = sum(r.sessions for r in rows)
        if total_sessions > 0:
            share = unattrib_sessions / total_sessions
            console.print(
                f"[dim]Unattributed: {unattrib_sessions:,} sessions ({share:.1%} of total)[/dim]"
            )


def _render_summary(summary: queries.SiteSummary, fmt: OutputFormat, title: str) -> None:
    if fmt == OutputFormat.JSON:
        console.print_json(data=summary.to_dict())
        return
    if fmt == OutputFormat.CSV:
        # CSV for a summary is awkward; we emit two sections separated by a blank line
        writer = csv.writer(sys.stdout)
        writer.writerow(["metric", "value"])
        writer.writerow(["total_sessions", summary.total_sessions])
        writer.writerow(["total_active_users", summary.total_active_users])
        writer.writerow(["total_pageviews", summary.total_pageviews])
        sys.stdout.write("\n")
        writer.writerow(["category", "dimension", "sessions", "active_users", "pageviews"])
        for b in summary.by_device:
            writer.writerow(["device", b.dimension, b.sessions, b.active_users, b.pageviews])
        for b in summary.by_channel:
            writer.writerow(["channel", b.dimension, b.sessions, b.active_users, b.pageviews])
        return

    # Rich format
    console.print(f"[bold]{title}[/bold]")
    console.print(f"  Total sessions:     {summary.total_sessions:,}")
    console.print(f"  Total active users: {summary.total_active_users:,}")
    console.print(f"  Total pageviews:    {summary.total_pageviews:,}")
    console.print()

    for label, rows in (("By device", summary.by_device), ("By channel", summary.by_channel)):
        table = Table(title=label, show_lines=False, header_style="bold")
        table.add_column("Dimension")
        table.add_column("Sessions", justify="right")
        table.add_column("Active Users", justify="right")
        table.add_column("Pageviews", justify="right")
        for r in rows:
            table.add_row(r.dimension, f"{r.sessions:,}", f"{r.active_users:,}", f"{r.pageviews:,}")
        console.print(table)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@app.callback()
def root(
    version: bool = typer.Option(False, "--version", help="Print version and exit."),
) -> None:
    if version:
        typer.echo(f"ga4-toolkit {__version__}")
        raise typer.Exit()


@app.command(name="top-pages")
def top_pages_cmd(
    site: str = typer.Argument(..., help="Friendly site name (from sites.yaml) or numeric property ID."),
    last: str | None = typer.Option(None, "--last", help="Relative date range, e.g. '30d', '4w', '3m'."),
    start: str | None = typer.Option(None, "--start", help="Start date (YYYY-MM-DD). Use with --end."),
    end: str | None = typer.Option(None, "--end", help="End date (YYYY-MM-DD). Use with --start."),
    limit: int = typer.Option(25, "--limit", "-n", help="Max rows to return."),
    fmt: OutputFormat = typer.Option(OutputFormat.TABLE, "--format", "-f", help="Output format."),
) -> None:
    """Top pages by pageviews. Answers 'what are the most-visited pages?'"""
    client, config = _get_client()
    start_date, end_date = _parse_date_range(last, start, end, config.default_lookback_days)
    property_id = resolve_site(site)

    rows = queries.top_pages(client, property_id, start_date, end_date, limit=limit)
    _render_pagestats(rows, fmt, f"Top pages — {site} — {start_date} to {end_date}")


@app.command(name="traffic")
def traffic_cmd(
    site: str = typer.Argument(..., help="Friendly site name or numeric property ID."),
    last: str | None = typer.Option(None, "--last"),
    start: str | None = typer.Option(None, "--start"),
    end: str | None = typer.Option(None, "--end"),
    granularity: str = typer.Option("day", "--by", help="Time bucket: day, week, month."),
    fmt: OutputFormat = typer.Option(OutputFormat.TABLE, "--format", "-f"),
) -> None:
    """Traffic time series. Answers 'is traffic trending up/down?'"""
    if granularity not in ("day", "week", "month"):
        raise typer.BadParameter(f"--by must be day/week/month, got: {granularity!r}")
    client, config = _get_client()
    start_date, end_date = _parse_date_range(last, start, end, config.default_lookback_days)
    property_id = resolve_site(site)

    rows = queries.traffic_by_date(client, property_id, start_date, end_date, granularity=granularity)  # type: ignore[arg-type]
    _render_traffic(rows, fmt, f"Traffic by {granularity} — {site} — {start_date} to {end_date}")


@app.command(name="pages")
def pages_cmd(
    site: str = typer.Argument(..., help="Friendly site name or numeric property ID."),
    paths: list[str] = typer.Argument(..., help="One or more URL paths, e.g. /about /contact"),
    last: str | None = typer.Option(None, "--last"),
    start: str | None = typer.Option(None, "--start"),
    end: str | None = typer.Option(None, "--end"),
    fmt: OutputFormat = typer.Option(OutputFormat.TABLE, "--format", "-f"),
) -> None:
    """Pageviews for specific paths. Answers 'how does THIS page perform?'"""
    client, config = _get_client()
    start_date, end_date = _parse_date_range(last, start, end, config.default_lookback_days)
    property_id = resolve_site(site)

    rows = queries.pageviews_for_paths(client, property_id, paths, start_date, end_date)
    _render_pagestats(rows, fmt, f"Pageviews — {site} — {start_date} to {end_date}")


@app.command(name="landing-pages")
def landing_pages_cmd(
    site: str = typer.Argument(...),
    last: str | None = typer.Option(None, "--last"),
    start: str | None = typer.Option(None, "--start"),
    end: str | None = typer.Option(None, "--end"),
    limit: int = typer.Option(25, "--limit", "-n"),
    fmt: OutputFormat = typer.Option(OutputFormat.TABLE, "--format", "-f"),
) -> None:
    """Top landing pages. Answers 'what are people arriving at?'"""
    client, config = _get_client()
    start_date, end_date = _parse_date_range(last, start, end, config.default_lookback_days)
    property_id = resolve_site(site)

    rows = queries.top_landing_pages(client, property_id, start_date, end_date, limit=limit)
    _render_pagestats(rows, fmt, f"Top landing pages — {site} — {start_date} to {end_date}")


@app.command(name="campaigns")
def campaigns_cmd(
    site: str = typer.Argument(..., help="Friendly site name or numeric property ID."),
    last: str | None = typer.Option(None, "--last", help="Relative date range, e.g. '30d', '4w', '3m'."),
    start: str | None = typer.Option(None, "--start", help="Start date (YYYY-MM-DD). Use with --end."),
    end: str | None = typer.Option(None, "--end", help="End date (YYYY-MM-DD). Use with --start."),
    limit: int = typer.Option(25, "--limit", "-n", help="Max rows to return."),
    only_attributed: bool = typer.Option(
        False, "--only-attributed", "-a",
        help="Hide '(not set)' / '(not provided)' rows entirely.",
    ),
    fmt: OutputFormat = typer.Option(OutputFormat.TABLE, "--format", "-f", help="Output format."),
) -> None:
    """Top UTM campaigns by sessions. Answers 'which campaigns drove traffic?'"""
    client, config = _get_client()
    start_date, end_date = _parse_date_range(last, start, end, config.default_lookback_days)
    property_id = resolve_site(site)

    rows = queries.top_campaigns(client, property_id, start_date, end_date, limit=limit)
    _render_acquisition(
        rows, fmt,
        title=f"Top campaigns — {site} — {start_date} to {end_date}",
        primary_label="Campaign",
        secondary_label="Source / Medium",
        only_attributed=only_attributed,
    )


@app.command(name="sources")
def sources_cmd(
    site: str = typer.Argument(..., help="Friendly site name or numeric property ID."),
    last: str | None = typer.Option(None, "--last"),
    start: str | None = typer.Option(None, "--start"),
    end: str | None = typer.Option(None, "--end"),
    limit: int = typer.Option(25, "--limit", "-n"),
    only_attributed: bool = typer.Option(
        False, "--only-attributed", "-a",
        help="Hide '(not set)' / '(not provided)' rows entirely.",
    ),
    fmt: OutputFormat = typer.Option(OutputFormat.TABLE, "--format", "-f"),
) -> None:
    """Top traffic sources by sessions. Answers 'where is traffic coming from?'"""
    client, config = _get_client()
    start_date, end_date = _parse_date_range(last, start, end, config.default_lookback_days)
    property_id = resolve_site(site)

    rows = queries.top_sources(client, property_id, start_date, end_date, limit=limit)
    _render_acquisition(
        rows, fmt,
        title=f"Top sources — {site} — {start_date} to {end_date}",
        primary_label="Source",
        secondary_label="Medium",
        only_attributed=only_attributed,
    )


@app.command(name="channels")
def channels_cmd(
    site: str = typer.Argument(..., help="Friendly site name or numeric property ID."),
    last: str | None = typer.Option(None, "--last"),
    start: str | None = typer.Option(None, "--start"),
    end: str | None = typer.Option(None, "--end"),
    limit: int = typer.Option(25, "--limit", "-n"),
    only_attributed: bool = typer.Option(
        False, "--only-attributed", "-a",
        help="Hide '(not set)' / '(not provided)' rows entirely.",
    ),
    fmt: OutputFormat = typer.Option(OutputFormat.TABLE, "--format", "-f"),
) -> None:
    """Top default channel groupings. Answers 'what's the organic/paid/social split?'"""
    client, config = _get_client()
    start_date, end_date = _parse_date_range(last, start, end, config.default_lookback_days)
    property_id = resolve_site(site)

    rows = queries.top_channels(client, property_id, start_date, end_date, limit=limit)
    _render_acquisition(
        rows, fmt,
        title=f"Top channels — {site} — {start_date} to {end_date}",
        primary_label="Channel",
        secondary_label="Source",
        only_attributed=only_attributed,
    )


@app.command(name="summary")
def summary_cmd(
    site: str = typer.Argument(...),
    last: str | None = typer.Option(None, "--last"),
    start: str | None = typer.Option(None, "--start"),
    end: str | None = typer.Option(None, "--end"),
    fmt: OutputFormat = typer.Option(OutputFormat.TABLE, "--format", "-f"),
) -> None:
    """Site summary: totals + device + channel breakdown. One-call triage view."""
    client, config = _get_client()
    start_date, end_date = _parse_date_range(last, start, end, config.default_lookback_days)
    property_id = resolve_site(site)

    summary = queries.device_and_channel_breakdown(client, property_id, start_date, end_date)
    _render_summary(summary, fmt, f"Summary — {site} — {start_date} to {end_date}")


@app.command(name="sites")
def sites_cmd() -> None:
    """List configured sites from sites.yaml."""
    try:
        sites = load_sites()
    except ConfigError as e:
        err_console.print(f"[red]Config error:[/red] {e}")
        raise typer.Exit(code=2) from None

    if not sites:
        console.print("[yellow]No sites configured.[/yellow] Add entries to config/sites.yaml.")
        return

    table = Table(title="Configured sites", header_style="bold")
    table.add_column("Friendly name")
    table.add_column("Property ID")
    table.add_column("Domain")
    table.add_column("Notes", overflow="fold")
    for name, cfg in sites.items():
        table.add_row(name, cfg.property_id, cfg.domain, cfg.notes)
    console.print(table)


@app.command(name="health-check")
def health_check_cmd(
    days: int = typer.Option(3, "--days", help="Window of full days ending yesterday."),
    fmt: OutputFormat = typer.Option(OutputFormat.TABLE, "--format", "-f"),
    fail_on_no_access: bool = typer.Option(
        False,
        "--fail-on-no-access",
        help="Also exit non-zero when a property returns 403 (default: report only).",
    ),
) -> None:
    """Check every configured site is still receiving data.

    Exits 1 if any site is dead or errored (plus no-access sites with
    --fail-on-no-access), 0 when everything is ok/skipped. Designed for
    scheduled runs: `--format json` + exit code is the whole contract.
    """
    client, _config = _get_client()
    try:
        sites = load_sites()
    except ConfigError as e:
        err_console.print(f"[red]Config error:[/red] {e}")
        raise typer.Exit(code=2) from None

    results: list[queries.HealthResult] = []
    for name, cfg in sites.items():
        if cfg.skip_health_check:
            results.append(
                queries.HealthResult(name, cfg.property_id, "skipped", 0, 0, detail="skip_health_check")
            )
            continue
        results.append(queries.health_check_site(client, name, cfg.property_id, window_days=days))

    bad_statuses = {"dead", "error"} | ({"no_access"} if fail_on_no_access else set())
    failures = [r for r in results if r.status in bad_statuses]

    if fmt == OutputFormat.JSON:
        console.print_json(
            data={
                "window_days": days,
                "healthy": not failures,
                "results": [r.to_dict() for r in results],
            }
        )
    elif fmt == OutputFormat.CSV:
        writer = csv.DictWriter(
            sys.stdout, fieldnames=["site", "property_id", "status", "active_users", "pageviews", "detail"]
        )
        writer.writeheader()
        for r in results:
            writer.writerow(r.to_dict())
    else:
        style = {"ok": "green", "dead": "red bold", "no_access": "yellow", "error": "red", "skipped": "dim"}
        table = Table(title=f"GA4 health check — last {days} full days", header_style="bold")
        table.add_column("Site")
        table.add_column("Status")
        table.add_column("Active Users", justify="right")
        table.add_column("Pageviews", justify="right")
        table.add_column("Detail", overflow="fold", style="dim")
        for r in sorted(results, key=lambda r: (r.status == "ok", r.site)):
            table.add_row(
                r.site,
                f"[{style[r.status]}]{r.status}[/{style[r.status]}]",
                f"{r.active_users:,}",
                f"{r.pageviews:,}",
                r.detail,
            )
        console.print(table)

    if failures:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
