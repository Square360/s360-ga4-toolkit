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
- `aborted` sites mean the sweep itself stopped on consecutive 503/504s:
  that's an outage at check time (local network or Google's API, which the
  check can't tell apart), so those errors collapse to one "re-run" line
  instead of listing properties.
- `--transient` asks only whether any error looks like a network/API blip
  (5xx, deadline, connect failure). The wrapper uses it to decide whether to
  wait for the network and re-run the sweep before classifying; it never
  touches the no_access state, so a retry doesn't count as a second run.

Exit codes: 0 = healthy, nothing to send; 10 = alert body on stdout, send it;
11 = (--transient only) transient errors present, re-run before alerting.
"""
import json
import os
import re
import sys

STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".no-access-state.json")
DNS_PATTERN = re.compile(r"dns|hostname lookup|address lookup|name resolution", re.I)
TRANSIENT_PATTERN = re.compile(
    r"^50[234]\b|deadline exceeded|failed to connect|no route to host|"
    r"can't assign requested address|connection (reset|refused)|timed out|unavailable",
    re.I,
)


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

    if "--transient" in sys.argv[1:]:
        transient = any(r["status"] == "aborted" for r in results) or any(
            r["status"] == "error"
            and (TRANSIENT_PATTERN.search(r["detail"] or "") or DNS_PATTERN.search(r["detail"] or ""))
            for r in results
        )
        sys.exit(11 if transient else 0)
    checked = [r for r in results if r["status"] != "skipped"]
    broken = [r for r in results if r["status"] in ("dead", "error")]
    aborted = [r for r in results if r["status"] == "aborted"]
    no_access_now = sorted(r["site"] for r in results if r["status"] == "no_access")

    prior_no_access = set(load_state().get("no_access", []))
    save_state({"no_access": no_access_now})
    # Alert only for sites no_access this run AND the previous run.
    no_access_alert = sorted(set(no_access_now) & prior_no_access)

    lines = []

    if aborted:
        # Collapse only the 503/504s; a dead site found before the outage still lists.
        net = [r for r in broken if r["status"] == "error" and TRANSIENT_PATTERN.search(r["detail"] or "")]
        lines.append(
            "Network error at check time: {e} properties in a row returned 503/504, "
            "so the sweep stopped with {a} of {n} unchecked. Either the local network "
            "dropped or Google's API is having an outage (https://status.cloud.google.com); "
            "the check can't tell which. Request a re-run: `ga4 health-check`.".format(
                e=len(net), a=len(aborted), n=len(checked)
            )
        )
        broken = [r for r in broken if r not in net]
    elif broken and len(broken) == len(checked) and all(
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
