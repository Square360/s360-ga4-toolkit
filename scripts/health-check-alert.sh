#!/bin/bash
# Daily GA4 health check with Bear alert + macOS notification on failure.
#
# Runs `ga4 health-check` across every site in config/sites.yaml and hands the
# JSON to health_alert.py, which decides whether an alert is due (dead/error
# sites; no_access on two consecutive runs; all-sites DNS failures collapse to
# a one-liner). A due alert becomes a Bear note tagged #squircle plus a macOS
# notification. Silence means healthy. Invoked by the LaunchAgent
# com.square360.ga4-health (daily, morning); safe to run by hand.
#
# Exit codes: 0 healthy or alert delivered, 1 alert could not be delivered.

set -u

TOOLKIT_DIR="/Volumes/Work/ClaudeCowork/WorkAreas/_code/s360-ga4-toolkit"
GA4="$TOOLKIT_DIR/.venv/bin/ga4"
BEARCLI="/Applications/Bear.app/Contents/MacOS/bearcli"
TODAY="$(date +%Y-%m-%d)"

cd "$TOOLKIT_DIR" || exit 1

json="$("$GA4" health-check --format json 2>/tmp/ga4-health-stderr.log)"
ga4_status=$?

if [ -n "$json" ]; then
    body="$(printf '%s' "$json" | python3 "$TOOLKIT_DIR/scripts/health_alert.py")"
    alert_status=$?
else
    # Config errors (exit 2) produce no JSON — report the stderr instead so
    # the alert still says something actionable.
    body="Health check failed to run (exit $ga4_status). stderr:

$(tail -5 /tmp/ga4-health-stderr.log)"
    alert_status=10
fi

if [ $alert_status -eq 0 ]; then
    echo "$TODAY healthy"
    exit 0
fi

# Body goes via stdin — bearcli misparses --content values that start with "-".
printf '%s\n' "$body" | "$BEARCLI" create "GA4 health alert — $TODAY" \
    --tags "squircle" \
    --if-not-exists >/dev/null

if [ $? -ne 0 ]; then
    echo "$TODAY ALERT DELIVERY FAILED" >&2
    exit 1
fi

osascript -e 'display notification "GA4 health alert filed in Bear (#squircle)" with title "GA4 Health" sound name "Basso"' >/dev/null 2>&1

echo "$TODAY alert created"
exit 0
