# Baloo recurring jobs

Baloo's operator-managed recurring jobs are declared in
`openclaw/cron-jobs.json` in the private `alpar-t/baloo` repository. The
`cron-sync` sidecar in
`config/baloo/manifests/openclaw.yaml` reconciles them into OpenClaw's
SQLite-backed cron store after the gateway becomes ready.

This closes the old reproducibility gap where `cluster-health` existed only in
the state PVC. One-shot reminders created by people in chat are not managed by
this file and are never edited or deleted by the reconciler.

## Managed jobs

- `cluster-health` — read-only outage probe every 15 minutes.
- `managed: dm-due-reminders` — checks explicit `@remind` tags in
  `life/TODO.md` hourly from 08:00 through 22:00 Europe/Bucharest.
- `managed: trips-morning-briefing` — 08:00 Europe/Bucharest.
- `managed: trips-evening-checkin` — 19:00 Europe/Bucharest.
- `managed: trips-countdown` — 08:15 Europe/Bucharest.

Fixed wall-clock tasks use cron expressions instead of heartbeat `interval`
tasks. A 24-hour heartbeat task can become anchored outside its own time gate:
an evening task evaluated at 08:00 replies `HEARTBEAT_OK`, advances its
last-run timestamp, and remains an 08:00 task.

## Reconciliation behavior

`openclaw/tools/sync-cron-jobs.js` in the private repository:

1. Waits for the local OpenClaw gateway readiness endpoint.
2. Reads the source-controlled job file.
3. Creates missing jobs and updates existing jobs with the same name.
4. Disables a `managed:` job removed from the file. The pre-existing
   `cluster-health` name is treated as managed too, so adopting it does not
   create a duplicate.
5. Leaves all other jobs, including user-created reminders, alone.
6. Re-reads the file every 60 seconds, so git-sync prompt/job changes do not
   require a pod restart. A manifest or tool-policy change still does.

If an optional delivery environment variable such as
`BALOO_TRIPS_PALKOEK_GROUP` is absent, the corresponding managed jobs are
disabled instead of sending to a stale destination.

## Validate before deploying

```bash
python3 openclaw/scripts/audit-baloo-prompts.py
node --check openclaw/tools/sync-cron-jobs.js
node openclaw/tools/sync-cron-jobs.js \
  --validate openclaw/cron-jobs.json
```

The audit checks that every cron tool is allowed by its target agent.

## Deploy and verify

Changes to `openclaw.json` or the Deployment require a restart:

```bash
kubectl rollout restart deployment/openclaw -n baloo
kubectl -n baloo rollout status deployment/openclaw
```

Inspect the reconciler and resulting jobs:

```bash
kubectl -n baloo logs deployment/openclaw -c cron-sync --tail=100
kubectl -n baloo exec deployment/openclaw -c openclaw -- \
  openclaw cron list --all
```

Test one job without waiting for its schedule:

```bash
kubectl -n baloo exec deployment/openclaw -c openclaw -- \
  openclaw cron run <job-id> --wait
```

An all-clear agent job replies `NO_REPLY`, which suppresses delivery. Heartbeat
jobs use `HEARTBEAT_OK`; do not interchange the tokens.
