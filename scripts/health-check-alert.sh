#!/bin/bash
# Daily GA4 health check with a console alert file + macOS notification on failure.
#
# Runs `ga4 health-check` across every site in config/sites.yaml and hands the
# JSON to health_alert.py, which decides whether an alert is due (dead/error
# sites; no_access on two consecutive runs; all-sites DNS failures collapse to
# a one-liner). A due alert becomes an alert file, a macOS notification and a
# post to the ClickUp Development chat. Alerts are Markdown files in the ga4-analytics-tools project's
# outputs/alerts/ (Squircle Console); Bear retired 2026-09-18. Silence means healthy. Invoked by the LaunchAgent
# com.square360.ga4-health (daily, morning); safe to run by hand.
#
# Exit codes: 0 healthy or alert delivered, 1 alert could not be delivered.

set -u

TOOLKIT_DIR="/Volumes/Work/ClaudeCowork/WorkAreas/_code/s360-ga4-toolkit"
GA4="$TOOLKIT_DIR/.venv/bin/ga4"
TODAY="$(date +%Y-%m-%d)"
PROJECT_SLUG="ga4-analytics-tools-project"
ALERT_DIR="/Volumes/Work/ClaudeCowork/WorkAreas/Infrastructure/$PROJECT_SLUG/outputs/alerts"
NOTIFY="/Volumes/Work/ClaudeCowork/.claude/tools/clickup-chat-notify.py"

# ── wait for network (2026-09-18): the Mac dark-wakes at 07:00 and this job
# ran at 08:05 (moved to 09:30 on 2026-09-18), sometimes before networking is back. Probe up to 10 minutes.
wait_for_network() {
    local i
    for i in $(seq 1 40); do
        nc -z -w 3 1.1.1.1 443 >/dev/null 2>&1 && return 0
        sleep 15
    done
    return 1
}

# ── alert file (2026-09-18): Markdown with frontmatter in the project's
# outputs/alerts/, where the Squircle Console lists it. Bear step retired.
write_alert() {  # $1 title  $2 slug  $3 description ; body on stdin
    local dir="$ALERT_DIR" file="$ALERT_DIR/${TODAY}_$2_Alert_v1.md" n=1
    mkdir -p "$dir" || return 1
    while [ -e "$file" ]; do n=$((n+1)); file="$dir/${TODAY}_$2_Alert_v$n.md"; done
    {
        printf -- '---\nname: %s\ndescription: %s\ntype: alert\nproject: %s\ncreated: %s\n---\n\n# %s\n\n' "$1" "$3" "$PROJECT_SLUG" "$TODAY" "$1"
        cat
    } > "$file"
}

cd "$TOOLKIT_DIR" || exit 1

if ! wait_for_network; then
    printf '%s\n' "Network never came up within 10 minutes; health check not run." | write_alert "GA4 health check could not run" "GA4-Health" "The daily GA4 health check found no network for 10 minutes after 08:05 and did not run."
    echo "$TODAY no network" >&2
    exit 1
fi

json="$("$GA4" health-check --format json 2>/tmp/ga4-health-stderr.log)"
ga4_status=$?

# ── transient retry (2026-10-07): a network drop mid-sweep (laptop closed,
# Wi-Fi gone) or a one-off 504 errors the remaining properties. If any error
# looks transient, wait a minute, wait for the network, and re-run the whole
# sweep; only the second run's result is classified and can alert.
if [ -n "$json" ]; then
    printf '%s' "$json" | python3 "$TOOLKIT_DIR/scripts/health_alert.py" --transient
    if [ $? -eq 11 ]; then
        echo "$TODAY transient errors; retrying" >&2
        sleep 60
        if wait_for_network; then
            json="$("$GA4" health-check --format json 2>/tmp/ga4-health-stderr.log)"
            ga4_status=$?
        fi
    fi
fi

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

printf '%s\n' "$body" | write_alert "GA4 health alert" "GA4-Health" "Daily GA4 health check: one or more site properties dead or erroring. Details inside."

if [ $? -ne 0 ]; then
    echo "$TODAY ALERT DELIVERY FAILED" >&2
    exit 1
fi

osascript -e 'display notification "GA4 health alert filed in the console (ga4-analytics-tools outputs/alerts)" with title "GA4 Health" sound name "Basso"' >/dev/null 2>&1

# ── team ping (2026-10-10): the alert also goes to the ClickUp Development chat
# as Grimbert, so it reaches the team when George is away. The alert file stays
# the record; a failed post is logged, not fatal. GA4_ALERT_CHANNEL=sandbox to test.
printf '%s\n\n%s\n' "$body" "Please check the affected properties to confirm GA4 and GTM connectivity." | python3 "$NOTIFY" --channel "${GA4_ALERT_CHANNEL:-development}" \
    --title "GA4 health alert $TODAY" \
    --source "Daily GA4 health check. Full record: $PROJECT_SLUG/outputs/alerts/" \
    || echo "$TODAY ClickUp chat post failed (alert file written)" >&2

echo "$TODAY alert created"
exit 0
