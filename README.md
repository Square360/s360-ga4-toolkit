# s360-ga4-toolkit

Portable Google Analytics 4 toolkit: Python CLI + MCP server, single codebase. Read-only, service-account authenticated, works against any GA4 property you have Viewer access to.

Built at [Square360](https://square360.com) and released under MIT so anyone on the team — or off it — can clone, configure, and run it against their own properties.

> **Just want to use it?** See [`docs/getting-started.md`](docs/getting-started.md) — a step-by-step install guide covering the CLI, Claude Code MCP, and GitHub Copilot integration. Install once, use from any repo.
>
> The rest of this README is reference material: what the toolkit does, how to develop against it, what the tools expose.

## What's in the box

Eight query functions, exposed identically through a CLI and an MCP server:

**Content performance**
- `top_pages` — top pages by pageviews, with active users and engagement rate
- `top_landing_pages` — entry-point pages for the period
- `pageviews_for_paths` — pageviews + users for a specific list of URL paths

**Traffic patterns**
- `traffic_by_date` — sessions / users / pageviews time series, day/week/month granularity
- `device_and_channel_breakdown` — totals + device (mobile/desktop/tablet) + channel grouping split

**Acquisition / attribution (v0.2)**
- `top_campaigns` — top UTM campaigns by sessions, with source/medium breakdown
- `top_sources` — top traffic sources by sessions, with medium breakdown
- `top_channels` — top default channel groupings (Organic Search, Paid Search, Social, Direct, etc.) with source breakdown
- `health_check` — sweep every configured site for signs of life over the last N full days (default 3, ending yesterday to absorb GA4's 24-48h processing lag). A site is `dead` only when active users AND pageviews are both zero across the window — stray bot sessions don't count as alive. Mark expected-dead sites `skip_health_check: true` in `sites.yaml`. The CLI exits 1 on any dead/errored site; `scripts/health-check-alert.sh` wraps it for a scheduled run that creates a Bear alert note on failure (loaded on the work Mac as LaunchAgent `com.square360.ga4-health`, daily 07:52).

The three acquisition queries partition unattributed rows (`(not set)` / `(not provided)`) to the bottom of results and flag them with `attributed=False`. `(direct)` / `(none)` stays as attributed traffic — it's real, just unreferred. Use the CLI's `--only-attributed` flag (or the MCP tool's `only_attributed=True`) to drop unattributed rows entirely.

Add a new function in `src/ga4_toolkit/queries.py` and it becomes available in both surfaces with no duplication.

## Requirements

- Python 3.11 or newer (the CLI is installable with `uv` or `pip`).
- A Google Cloud project with the Google Analytics Data API enabled.
- A service-account JSON key with the **Viewer** role on each GA4 property you want to query. Add the service-account email under Admin → Property access management in GA4.
- Docker (optional) if you want to run the MCP server through `docker compose` instead of natively.

The repo includes a step-by-step GCP + GA4 setup runbook if you're doing this for the first time — see the Square360 internal project folder, or adapt the same steps against any GCP org.

## Install

### Native (uv or pip)

```bash
git clone https://github.com/square360/s360-ga4-toolkit.git
cd s360-ga4-toolkit

# Using uv (recommended — fastest, handles the venv):
uv venv
uv pip install -e .

# Or plain pip:
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .
```

This installs two console scripts:

- `ga4` — the CLI.
- `ga4-mcp` — the MCP server (stdio transport).

### Via Docker

```bash
cp .env.example .env
# Edit .env, set GA4_SERVICE_ACCOUNT_PATH_HOST to the absolute path of your JSON key
cp config/sites.example.yaml config/sites.yaml
# Edit sites.yaml, add your properties
docker compose build
```

Then wire `docker compose run --rm ga4-mcp` into your MCP client (see below).

## Configure

### 1. Service-account JSON

Download the JSON key from GCP and keep it out of version control. Point the toolkit at it via one of:

- Environment variable: `GA4_SERVICE_ACCOUNT_PATH=/absolute/path/to/service-account.json`
- `.env` file in the repo root (copy `.env.example` and edit — `.gitignore` excludes it).

The service account needs **Viewer** access on every GA4 property you plan to query. Grant it in GA4: Admin → Property access management → add the service-account email.

### 2. `sites.yaml` — friendly names for properties

Copy `config/sites.example.yaml` to `config/sites.yaml` and add your properties. Example:

```yaml
sites:
  - friendly_name: yale-budget-lab
    property_id: "123456789"
    domain: budgetlab.yale.edu
    notes: Yale Budget Lab — VRT config test target

  - friendly_name: square360
    property_id: "987654321"
    domain: square360.com
    notes: Agency site
```

`property_id` must be quoted — GA4 IDs start with digits but aren't integers. Once sites are defined, every CLI and MCP call accepts the friendly name instead of the raw ID.

If `config/sites.yaml` doesn't exist the toolkit falls back to `config/sites.example.yaml`, and if neither exists it raises a clear error.

### 3. Environment variables (all optional)

| Variable | Default | Purpose |
|---|---|---|
| `GA4_SERVICE_ACCOUNT_PATH` | _(required)_ | Absolute path to the service-account JSON. |
| `GA4_DEFAULT_LOOKBACK_DAYS` | `30` | Default window when neither `--last` nor `--start/--end` is given. |
| `GA4_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, or `ERROR`. |
| `GA4_SITES_CONFIG` | `./config/sites.yaml` | Override if your sites config lives elsewhere. |
| `GA4_SERVICE_ACCOUNT_PATH_HOST` | — | Docker-compose only. Absolute host path; mounted into the container. |
| `GA4_SITES_CONFIG_HOST` | `./config/sites.yaml` | Docker-compose only. |

## CLI usage

All commands accept either a friendly name (from `sites.yaml`) or a raw numeric property ID.

Date range is specified one of three ways:

- `--last 30d` (also `4w`, `3m`, `1y`)
- `--start 2026-03-01 --end 2026-03-31`
- Nothing — falls back to `GA4_DEFAULT_LOOKBACK_DAYS`.

```bash
# List the sites the toolkit knows about
ga4 sites

# Top 25 pages over the last 30 days
ga4 top-pages yale-budget-lab --last 30d

# Traffic time series by week, explicit range, JSON output
ga4 traffic yale-budget-lab --start 2026-01-01 --end 2026-03-31 --granularity week --format json

# Pageviews for a specific set of paths
ga4 pages yale-budget-lab /publications /about --last 90d

# Top landing pages, CSV output for pasting into a sheet
ga4 landing-pages yale-budget-lab --last 30d --format csv

# One-call site summary — totals, device breakdown, channel breakdown
ga4 summary yale-budget-lab --last 30d
```

Every command supports `--format table|json|csv`. Table is the default and renders via `rich`.

## MCP server

The MCP server exposes the same five query functions as tools plus a `list_sites` tool. It speaks stdio, so it's configured like any other stdio MCP server.

### Native

Configure your MCP client to run `ga4-mcp` (or `uv run ga4-mcp` from inside the repo) with `GA4_SERVICE_ACCOUNT_PATH` set in the environment.

Example Claude Desktop / Claude Code config (`~/.config/claude/mcp.json` or equivalent):

```json
{
  "mcpServers": {
    "ga4": {
      "command": "ga4-mcp",
      "env": {
        "GA4_SERVICE_ACCOUNT_PATH": "/Users/george/.config/s360-ga4-toolkit/service-account.json",
        "GA4_SITES_CONFIG": "/Users/george/code/s360-ga4-toolkit/config/sites.yaml"
      }
    }
  }
}
```

### Via docker-compose

```json
{
  "mcpServers": {
    "ga4": {
      "command": "docker",
      "args": ["compose", "-f", "/absolute/path/to/s360-ga4-toolkit/docker-compose.yml", "run", "--rm", "-T", "ga4-mcp"]
    }
  }
}
```

The `-T` disables pseudo-TTY allocation — some MCP clients prefer that. If yours wants a TTY, drop it.

### GitHub Copilot in VSCode

Copilot agent mode reads MCP config from `.vscode/mcp.json` at the workspace root. A ready-to-go template ships in this repo — no editing required as long as you've done the three prereqs below.

**One-time setup per developer:**

1. Clone the repo and install the toolkit:
   ```bash
   uv venv
   uv pip install -e .
   ```
2. Copy the env template and set your service-account path:
   ```bash
   cp .env.example .env
   # Edit .env: set GA4_SERVICE_ACCOUNT_PATH to the absolute path of your JSON key.
   ```
3. Copy the sites config template and add the property IDs you have Viewer access to:
   ```bash
   cp config/sites.example.yaml config/sites.yaml
   ```

After that, open this repo in VSCode and Copilot's agent mode should pick up the `ga4` server automatically. The committed `.vscode/mcp.json` uses `${workspaceFolder}/.venv/bin/ga4-mcp` for the command and `envFile: ${workspaceFolder}/.env` so it reads your `GA4_SERVICE_ACCOUNT_PATH` straight from the `.env` you already created — no shell config needed.

**Using `ga4` from other repos:** the workspace config above only activates inside this repo. If you want the GA4 tools available from any repo, add a user-level MCP config in VSCode instead. Command Palette → "MCP: Open User Configuration" and paste:

```json
{
  "servers": {
    "ga4": {
      "type": "stdio",
      "command": "/absolute/path/to/s360-ga4-toolkit/.venv/bin/ga4-mcp",
      "env": {
        "GA4_SERVICE_ACCOUNT_PATH": "/absolute/path/to/your/service-account.json",
        "GA4_SITES_CONFIG": "/absolute/path/to/s360-ga4-toolkit/config/sites.yaml"
      }
    }
  }
}
```

Absolute paths only here — user-level config has no `${workspaceFolder}` context.

### Tools exposed

- `list_sites()` — list sites from `sites.yaml`.
- `top_pages(site, last?, start_date?, end_date?, limit=25)`
- `traffic(site, last?, start_date?, end_date?, granularity='day')`
- `pageviews_for_paths(site, paths, last?, start_date?, end_date?)`
- `top_landing_pages(site, last?, start_date?, end_date?, limit=25)`
- `site_summary(site, last?, start_date?, end_date?)`

## Development

```bash
uv venv
uv pip install -e ".[dev]"

# Run tests (GA4 responses are mocked — no network, no credentials needed)
pytest

# Lint + format
ruff check .
ruff format .

# Type check
mypy src
```

The test suite mocks `BetaAnalyticsDataClient.run_report` via fixtures in `tests/conftest.py`, so the full suite runs offline. `test_queries.py` covers query shaping and response parsing; `test_config.py` covers sites.yaml loading, friendly-name resolution, and error modes.

### Project layout

```
src/ga4_toolkit/
  client.py       # service-account auth + cached BetaAnalyticsDataClient
  config.py       # ToolkitConfig, SiteConfig, sites.yaml loading
  queries.py      # five query functions + dataclass return types
  cli.py          # Typer CLI
  mcp_server.py   # FastMCP server
tests/
  conftest.py     # FakeResponse / FakeRow / FakeValue fixtures
  test_queries.py
  test_config.py
config/
  sites.example.yaml
```

To add a new query:

1. Add the function in `queries.py`, returning a frozen dataclass with `to_dict()`.
2. Add tests in `test_queries.py` using the `mock_client` fixture.
3. Add a CLI command in `cli.py` and an MCP tool in `mcp_server.py`. Both are thin wrappers — CLI handles arg parsing and output formatting, MCP handles the JSON contract.

## License

MIT. See `LICENSE`.

## Credits

Built by the team at [Square360](https://square360.com). Contributions welcome — open an issue or PR.
