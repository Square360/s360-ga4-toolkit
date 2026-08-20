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
