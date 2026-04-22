# Getting started

Install the toolkit once on your machine, then use it from any repo. Covers the CLI, Claude Code MCP integration, and GitHub Copilot in VSCode.

If you want to *contribute* to the toolkit itself (add a query, fix a bug), read the "Development" section in the main README instead — that path clones the repo and uses an editable install.

## Before you start

You'll need:

- **macOS or Linux.** Windows via WSL should work but is untested.
- **Python 3.11 or newer.** Check with `python3 --version`. If it's older, install a newer Python — `brew install python@3.12` on macOS works.
- **[`uv`](https://github.com/astral-sh/uv).** Install via `curl -LsSf https://astral.sh/uv/install.sh | sh` or `brew install uv`.
- **A Google service-account JSON key.** Either Square360's shared key (ask George) or one you create yourself against your own GCP project. The JSON needs Viewer access on every GA4 property you want to query — granted in GA4's Admin → Property access management screen.

## Step 1 — Install the CLI

```bash
uv tool install git+https://github.com/square360/s360-ga4-toolkit.git
```

This installs `ga4` (the CLI) and `ga4-mcp` (the MCP server) as global tools in an isolated venv managed by `uv`. Both end up on your `$PATH`.

If the first time you run `ga4` your shell says "command not found", run:

```bash
uv tool update-shell
```

and restart your terminal. That fixes the PATH.

Verify:

```bash
ga4 --version
```

To upgrade later:

```bash
uv tool upgrade s360-ga4-toolkit
```

## Step 2 — Put the service-account JSON somewhere safe

The canonical location is `~/.config/s360-ga4-toolkit/`. Create it and drop the JSON there:

```bash
mkdir -p ~/.config/s360-ga4-toolkit
cp /path/to/your/service-account.json ~/.config/s360-ga4-toolkit/service-account.json
chmod 600 ~/.config/s360-ga4-toolkit/service-account.json
```

The `chmod 600` makes sure only you can read the file. Treat this JSON like a password — anyone with the file can read any GA4 property the service account has Viewer on.

**Square360 note:** if George shared the existing `s360-analytics-tools` key, use that. If you need Viewer on a property it doesn't yet have access to, ping George to grant the service-account email (`ga4-toolkit-reader@s360-analytics-tools.iam.gserviceaccount.com`) in that property's GA4 Admin screen.

## Step 3 — Create your sites.yaml

This file gives friendly names to GA4 property IDs so you can type `ga4 top-pages square360` instead of `ga4 top-pages 123456789`.

```bash
cat > ~/.config/s360-ga4-toolkit/sites.yaml <<'EOF'
sites:
  budget-lab:
    property_id: "435742842"
    domain: "budgetlab.yale.edu"
    notes: "Yale Budget Lab"

  # Add more sites as you get Viewer access granted:
  # square360:
  #   property_id: "000000000"
  #   domain: "square360.com"
EOF
```

Add entries for every property you have Viewer access to. `property_id` must be quoted (YAML otherwise reads it as an integer).

## Step 4 — Tell the toolkit where to find those files

Add to your shell rc file — `~/.zshrc` on macOS (default), `~/.bashrc` on Linux:

```bash
export GA4_SERVICE_ACCOUNT_PATH="$HOME/.config/s360-ga4-toolkit/service-account.json"
export GA4_SITES_CONFIG="$HOME/.config/s360-ga4-toolkit/sites.yaml"
```

Reload your shell:

```bash
source ~/.zshrc
```

## Step 5 — Smoke test the CLI

```bash
ga4 sites
```

You should see a table listing your configured sites. Then:

```bash
ga4 summary budget-lab --last 30d
```

You should see totals plus device and channel breakdowns. If that returns real numbers, your auth is working.

If you get an error about the service-account file, re-check the path in `GA4_SERVICE_ACCOUNT_PATH`. If you get a 403 from Google, the service account isn't a Viewer on that property yet.

## Step 6 — Wire up Claude Code

This makes the `ga4` tools available inside any Claude Code session, from any repo.

```bash
claude mcp add ga4 --scope user \
  -e GA4_SERVICE_ACCOUNT_PATH="$HOME/.config/s360-ga4-toolkit/service-account.json" \
  -e GA4_SITES_CONFIG="$HOME/.config/s360-ga4-toolkit/sites.yaml" \
  -- "$(which ga4-mcp)"
```

The `--scope user` is important — it means "available from any directory" rather than only inside one specific repo. The `$(which ga4-mcp)` bakes in the absolute path to the installed binary.

Verify:

```bash
claude mcp list
```

Then start a Claude Code session from anywhere and type `/mcp`. You should see `ga4` listed as connected with six tools. Ask Claude something like "use the ga4 mcp to get the top 10 pages on budget-lab last 30 days" — it should call `top_pages` and return real data.

## Step 7 — Wire up GitHub Copilot in VSCode

This makes the `ga4` tools available in Copilot agent mode, from any workspace.

Open VSCode, run Command Palette ("Cmd+Shift+P"), type "MCP: Open User Configuration". This opens `~/Library/Application Support/Code/User/mcp.json` on macOS. Paste:

```json
{
  "servers": {
    "ga4": {
      "type": "stdio",
      "command": "/path/to/ga4-mcp",
      "env": {
        "GA4_SERVICE_ACCOUNT_PATH": "/Users/yourname/.config/s360-ga4-toolkit/service-account.json",
        "GA4_SITES_CONFIG": "/Users/yourname/.config/s360-ga4-toolkit/sites.yaml"
      }
    }
  }
}
```

Replace `/path/to/ga4-mcp` with the output of `which ga4-mcp` and swap `yourname` for your macOS user. Absolute paths only — VSCode user-level MCP config has no `${workspaceFolder}` or `$HOME` interpolation.

Save. Restart VSCode. Open any workspace, enable Copilot agent mode, and the `ga4` tools should be available.

## Step 8 — You're done

The CLI works from any terminal. Claude Code sees the tools from any repo. Copilot sees them from any workspace. No per-project setup needed from here on.

To query a new property, grant the service-account email Viewer on it in GA4, then add an entry to `~/.config/s360-ga4-toolkit/sites.yaml`. No restart required for the CLI; Claude Code and VSCode may need a reload to re-read the sites file.

## Troubleshooting

**`command not found: ga4`** — `uv tool update-shell`, restart terminal.

**`ConfigError: No service-account path configured`** — `GA4_SERVICE_ACCOUNT_PATH` isn't set in the shell you're running from, or isn't passed through to the MCP server. Check `echo $GA4_SERVICE_ACCOUNT_PATH`; for MCP, check the `env` block in your MCP config.

**`ConfigError: Service-account file does not exist`** — Wrong path. `ls -la` the file to make sure it's there and readable.

**HTTP 403 from Google on a query** — The service account isn't a Viewer on that property. Grant it in GA4 Admin → Property access management.

**CLI works but MCP doesn't** — Almost always an env issue. The CLI picks env from your shell; the MCP server is launched by Claude Code or VSCode with a fresh environment that only has what's in the `env`/`envFile` block of the config. Double-check that block has the paths.

**I want to try a query before adding a property to sites.yaml** — Pass the numeric property ID directly: `ga4 summary 435742842 --last 30d`. All commands accept a numeric ID in place of a friendly name.
