#!/bin/bash
# Daily GA4 health check with Bear alert on failure.
#
# Runs `ga4 health-check` across every site in config/sites.yaml and, when any
# property is dead or errored, drops a Bear note tagged #squircle so it lands
# in George's inbox. Silence means healthy. Invoked by the LaunchAgent
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
status=$?

if [ $status -eq 0 ]; then
    echo "$TODAY healthy"
    exit 0
fi

# Build the alert body. Config errors (exit 2) produce no JSON — report the
# stderr instead so the alert still says something actionable.
if [ -n "$json" ]; then
    body="$(printf '%s' "$json" | python3 "$TOOLKIT_DIR/scripts/format_alert.py")"
else
    body="Health check failed to run (exit $status). stderr:

$(tail -5 /tmp/ga4-health-stderr.log)"
fi

# Body goes via stdin — bearcli misparses --content values that start with "-".
printf '%s\n' "$body" | "$BEARCLI" create "GA4 health alert — $TODAY" \
    --tags "squircle" \
    --if-not-exists >/dev/null

if [ $? -ne 0 ]; then
    echo "$TODAY ALERT DELIVERY FAILED" >&2
    exit 1
fi
echo "$TODAY alert created"
exit 0
