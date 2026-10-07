# Toolkit to-do

Small items queued for the next working session in this repo.

- **Health-check: don't alert on transient API errors first strike** (2026-08-20).
  The 07:52 sweep alerted on econ-egc (377910938) with `504 Deadline Exceeded`;
  a manual re-query minutes later showed the property fully healthy (613 users /
  1,738 pageviews over 3 days). Fix in `health_alert.py` + the check itself:
  retry a property once within the run on 5xx/DeadlineExceeded, and treat a
  persisting `error` like `no_access` — alert only after two consecutive runs
  (same rule added 2026-08-13 for no_access). George's ruling: fix next time
  we're in here, no ticket.
  - **Retry: done 2026-10-07.** The wrapper re-runs the sweep once after a
    transient error (5xx, deadline, connect failure), following a network wait.
    Trigger: a laptop network drop mid-sweep errored 7 properties.
  - **Two-run rule: still open, deliberately.** George 2026-10-07: an alert he
    questions and we re-check is the system working. Deferring persistent errors
    a day would hide a real outage, so this stays unbuilt unless false alarms
    keep getting through the retry.
