#!/usr/bin/env python3
"""Classify ga4 health-check JSON (stdin) and emit an alert body when one is due.

Supersedes format_alert.py. Companion to health-check-alert.sh; no third-party
imports so it runs on the system Python.

Decisions made here, not in the shell:
- dead/error sites always alert — except when EVERY checked site failed with
  the same DNS/hostname-lookup error, which is the laptop's resolver (VPN DNS
  scoping, network blip) rather than GA4: that collapses to a one-line alert.
- no_access alerts only on the second consecutive run a site reports it
  (permission revocations persist; API hiccups don't). State lives in
  .no-access-state.json beside this script (gitignored).

Exit codes: 0 = healthy, nothing to send; 10 = alert body on stdout, send it.
"""
import json
import os
import re
import sys

STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".no-access-state.json")
DNS_PATTERN = re.compile(r"dns|hostname lookup|address lookup|name resolution", re.I)


def load_state() -> dict:
    try:
        with open(STATE_PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)
        f.write("\n")


def main() -> None:
    data = json.load(sys.stdin)
    results = data["results"]
    checked = [r for r in results if r["status"] != "skipped"]
    broken = [r for r in results if r["status"] in ("dead", "error")]
    no_access_now = sorted(r["site"] for r in results if r["status"] == "no_access")

    prior_no_access = set(load_state().get("no_access", []))
    save_state({"no_access": no_access_now})
    # Alert only for sites no_access this run AND the previous run.
    no_access_alert = sorted(set(no_access_now) & prior_no_access)

    lines = []

    if broken and len(broken) == len(checked) and all(
        DNS_PATTERN.search(r["detail"] or "") for r in broken
    ):
        lines.append(
            "Local DNS/network failure at check time — all {n} property checks "
            "failed to resolve the Analytics API host. GA4 itself is not "
            "implicated; re-run `ga4 health-check` off VPN to confirm.".format(n=len(broken))
        )
        broken = []

    for r in broken:
        detail = " — " + r["detail"] if r["detail"] else ""
        lines.append("- **{site}** ({pid}): {status}{detail}".format(
            site=r["site"], pid=r["property_id"], status=r["status"], detail=detail
        ))

    if no_access_alert:
        lines.append(
            "\n**Access revoked** (no_access two runs in a row — service account "
            "likely removed from the property): " + ", ".join(no_access_alert)
        )
    elif no_access_now:
        # First sighting: stay quiet, but note it if an alert is going out anyway.
        if lines:
            lines.append("\nUnverifiable this run (no access, first sighting): "
                         + ", ".join(no_access_now))

    if not lines:
        sys.exit(0)

    lines.append("\nWindow: last {} full days. Run `ga4 health-check` for the full table.".format(
        data["window_days"]
    ))
    print("\n".join(lines))
    sys.exit(10)


if __name__ == "__main__":
    main()
