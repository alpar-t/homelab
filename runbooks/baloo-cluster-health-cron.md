# Baloo cluster-health cron (outage pager)

The 24/7 homelab outage check is an **isolated cron job** named `cluster-health`
on the `alpar` agent — *not* a heartbeat task.

## Why it's a cron job, not a heartbeat

Heartbeats have no per-run reasoning or tool override: the check was firing every
15m on the full DM context (~316K input tokens, `thinking=medium`)
and dominated OpenAI usage (the ChatGPT-plan / Codex auth, which has a multi-day
usage window rather than per-token billing). Cron jobs *do* support per-job
overrides, so moving the check there lets it run cheap without lowering the
reasoning of interactive DM conversations (a per-agent `thinkingDefault` would
have dropped those too).

## Current configuration

- **Schedule:** every 15m (isolated session, fresh each run)
- **Model:** default `openai/gpt-5.5` (in-plan) → fallback
  `anthropic/claude-sonnet-4-6` (pay-per-use, only on spillover)
- **`thinking: low`**, **`lightContext: true`**
- **Scoped tools:** `k8s__kubectl_get,k8s__kubectl_describe` only — this is the
  biggest lever; the unscoped agent loads ~200 trek tools + maps/hass/browser/
  searxng schemas on every run.
- **Delivery:** `announce` on WhatsApp to `${BALOO_OWNER_PHONE}`.
- **All-clear token:** the run replies the cron silent token `NO_REPLY` (not
  `HEARTBEAT_OK`) so nothing is delivered; a real problem returns one terse line.

Per-run cost after these changes: ~95K input / ~650 output tokens (~3× cheaper
than the old heartbeat). The remaining ~95K is mostly verbose `kubectl get`
output — tune the probe prompt to request narrower/filtered queries if it needs
to go lower.

## Source-controlled reconciliation

The job payload now lives in `openclaw/cron-jobs.json` in the private
`alpar-t/baloo` repository. The `cron-sync`
sidecar creates or updates it in OpenClaw's SQLite-backed cron store after the
gateway becomes ready. A state-PVC rebuild therefore recreates the health check
automatically.

The full reconciliation and verification procedure is in
`runbooks/baloo-recurring-jobs.md`.

## Managing the job

```bash
kubectl -n baloo exec deployment/openclaw -c openclaw -- openclaw cron list --all
kubectl -n baloo exec deployment/openclaw -c openclaw -- openclaw cron run <id> --wait   # test-run now
kubectl -n baloo exec deployment/openclaw -c openclaw -- openclaw cron edit <id> --tools <list>
```
