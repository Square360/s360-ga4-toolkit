#!/usr/bin/env python3
"""Format ga4 health-check JSON (stdin) as a Bear alert body (stdout).

Companion to health-check-alert.sh; no third-party imports so it runs on the
system Python.
"""
import json
import sys


def main() -> None:
    data = json.load(sys.stdin)
    lines = []
    for r in data["results"]:
        if r["status"] in ("dead", "error"):
            detail = " — " + r["detail"] if r["detail"] else ""
            lines.append("- **{site}** ({pid}): {status}{detail}".format(
                site=r["site"], pid=r["property_id"], status=r["status"], detail=detail
            ))
    print("\n".join(lines))

    no_access = [r["site"] for r in data["results"] if r["status"] == "no_access"]
    if no_access:
        print("\nUnverifiable (no access): " + ", ".join(no_access))
    print("\nWindow: last {} full days. Run `ga4 health-check` for the full table.".format(
        data["window_days"]
    ))


if __name__ == "__main__":
    main()
