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

- `cluster-health` — disabled legacy LLM outage probe, retained for rollback.
- `managed: monitoring-watchdog` — disabled legacy deterministic probe;
  retained for rollback. The active digest below checks monitoring freshness.
- `managed: zabbix-digest` — deterministic command every minute; reads Zabbix
  problem/recovery state and delivers only eligible notifications to WhatsApp.
  Raw image CVE findings are dashboard-only; a reviewed urgent CVE uses a
  separate paging check. See [Zabbix monitoring](zabbix-monitoring.md).
- `managed: security-image-review` — queue-driven isolated Baloo reviewer.
  A deterministic stream checks the bounded review queue every minute and
  wakes the reviewer on new pending work or at least every five minutes while
  work remains. Each run takes at most 25 findings and rotates its offset
  across a larger backlog. The reviewer writes structured evidence through a
  constrained controller, with no direct WhatsApp delivery or Zabbix
  operations token.
  Keep this job disabled until the [vulnerability-review cutover](vulnerability-scanning.md#cutover-validation-and-rollback)
  passes its notification and write-boundary checks.
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
   require a pod restart. The config-renderer also applies tool-policy and
   other supported `openclaw.json` changes without a restart.

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

After an `openclaw.json` change, verify the renderer and OpenClaw's reload log;
do not restart the pod:

```bash
kubectl -n baloo logs deployment/openclaw -c config-renderer --tail=100
kubectl -n baloo logs deployment/openclaw -c openclaw --tail=200 | grep '\[reload\]'
```

Only Deployment changes, secret-backed environment changes, and settings that
OpenClaw explicitly marks restart-required need a rollout.

### Gateway token exposure during HOME-107 cutover

The `OPENCLAW_GATEWAY_TOKEN` value appeared in this session's tool transcript
because cron reconciliation and session cleanup passed it in process arguments.
There is no evidence it reached pod logs. Baloo commits `169c94f` and
`150c95e` removed those argument paths. On 2026-10-25 the
`baloo/baloo-secrets` key was replaced through stdin-only Secret creation,
and a credential-bearing last-applied annotation was removed. All four
dependent Deployments restarted and reached 1/1 Ready; OpenClaw `/readyz`
returned 200. For future rotations, avoid printing the value, restart its
consumers so they load the new environment value, and verify cron
reconciliation and session cleanup. Do not include the token or process
arguments containing it in diagnostic output.

Removing `--token` exposed an OpenClaw CLI quirk: an explicit `--url` also
stops the CLI from using `OPENCLAW_GATEWAY_TOKEN` from its environment. Baloo
commit `08ae29e` supplies both `OPENCLAW_GATEWAY_URL` and the token through
the scoped child-process environment for cron reconciliation and session
cleanup, keeping credentials out of process arguments. An isolated `cron-sync`
sidecar restart loaded the fix; it reconciled jobs without authentication
errors, and the reviewer stream had one active child after a one-shot
disable/enable rearm. The Gateway remained Ready throughout.

`newjoy-organizer` initially had one active project and cached the older
`baloo-agent-client` module. Once idle, its isolated restart loaded the fix:
restart count became 1 and `/health` returned 200 with `running=false` and
`activeProjects=0`. The Gateway stayed Ready without a further restart.
Verify the env-based session-cleanup path on its next use.

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
