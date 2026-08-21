# Baloo — household WhatsApp assistant

Baloo is an OpenClaw-based assistant deployed in the `baloo` namespace. Static
WhatsApp bindings route each DM or group to an agent with its own prompt
workspace and explicit tool policy.

## Current agents

| Agent | Audience | Main capabilities |
| --- | --- | --- |
| `alpar` | Alpar DM | Web, images, Maps/timezones, TREK, HA control, GitHub, read-only k8s, reminders |
| `kinga` | Kinga DM | Web, images, Maps/timezones, TREK, HA control, GitHub, reminders |
| `cooking` | Baloo Shef group | Cookbook reads/PRs, web research, native image understanding, read-only HA context |
| `garden` | Garden group | Garden journal reads/PRs, web research, native image understanding, read-only HA context, morning heartbeat |
| `trips` | Palkoek es Torokek group | Shared-trip editing, expenses, Maps/timezones, web research, native image understanding |
| `main` | No channel binding | Reserved model-auth root; no tools |

There is currently no kids agent or binding.

## Prompt layout

Each configured workspace under the private `alpar-t/baloo` repository's
`openclaw/agents/` directory contains:

- `SOUL.md` — identity, voice, and conversational boundaries.
- `AGENTS.md` — operational rules and tool workflows.
- `HEARTBEAT.md` — only where an actual heartbeat remains enabled.

OpenClaw reads these files from `/git/link/openclaw/agents/<id>`. Git-sync
updates the checkout every 60 seconds; prompt changes apply on a new session
without restarting the pod.

`agents.defaults.skipBootstrap: true` prevents OpenClaw from creating memory or
bootstrap files in these read-only workspaces. Baloo does not autonomously edit
its own prompts.

Alpar and Kinga have separate workspaces and `USER.md` context. Both can load
the shared `trips` skill on demand from `openclaw/skills/trips/`; other agents
explicitly receive no shared skills.

## Images and voice

The primary conversational model understands inbound WhatsApp image
attachments directly. The prompts therefore tell agents to inspect attached
images without calling a separate `image` tool. Only the DM agent has
`image_generate`, and only for explicit image creation/editing requests.

Voice messages are transcribed locally by
`openclaw/whisper-transcribe.py` in the private repo; the transcript is echoed and interpreted
by the receiving agent.

## Tool policy

`openclaw/openclaw.json` in the private repo is the enforcement layer. Every agent has explicit
`tools.allow` and `tools.deny` lists.

- The trips group never receives HA, GitHub, image-generation, or k8s tools.
- The trips agent keeps broad TREK editing and expense support, but cannot
  create or delete a trip. Participant and itinerary edits remain available;
  trip creation is a DM workflow.
- Cooking and garden receive only `hass__GetDateTime` and
  `hass__GetLiveContext`; DM receives the full HA surface for state and control.
- `google-timezone__lookup` is available only to DM and trips; all other agents
  explicitly deny the namespace.
- K8s is limited to three read tools on DM. The MCP server's read-only RBAC is
  the independent hard guardrail.
- GitHub write access in cooking/garden is limited to branch, file, and PR
  creation in support of their review workflows.

Validate prompt references and policy consistency with:

```bash
python3 scripts/audit-baloo-prompts.py
```

## Scheduled work

Operator-managed recurring jobs live in the private repo's
`openclaw/cron-jobs.json` and are
reconciled by the `cron-sync` sidecar. This includes cluster health, DM
`@remind` tags, and scheduled trips briefings.

Fixed-time work uses cron expressions rather than 24-hour heartbeat tasks, so a
morning or evening task cannot become anchored to the wrong part of the day.
User-created one-shot reminders remain unmanaged and are never touched by the
reconciler.

See `runbooks/baloo-recurring-jobs.md`.

The garden agent retains one light-context heartbeat because its checks share a
short 08:00–10:00 window.

## Configuration delivery

- Source config: `alpar-t/baloo:openclaw/openclaw.json`
- Rendered config: `/rendered/openclaw.json`
- Workspaces and cron declarations: `/git/link/openclaw/`
- Writable state: `/state` Longhorn PVC
- Deployment: `config/baloo/manifests/openclaw.yaml`

The `render-config` init container creates the first secret-backed config before
startup. A companion sidecar then watches the git-synced source, validates JSON,
and atomically replaces `/rendered/openclaw.json`. OpenClaw hot-reloads supported
changes to bindings, tools, models, and MCP servers without restarting the pod.

Deployment changes and settings OpenClaw explicitly reports as
restart-required still require:

```bash
kubectl rollout restart deployment/openclaw -n baloo
```

Prompt, helper, source-config, and managed-cron changes are picked up from git
without a restart. Render and cron synchronization status are visible with:

```bash
kubectl -n baloo logs deployment/openclaw -c cron-sync --tail=100
kubectl -n baloo logs deployment/openclaw -c render-config --tail=100
```

## Trip group model

The current shared group uses a simple prompt mapping:

- Visible trips contain Lenny.
- Alpar/Kinga senders map to payer Alpar.
- Other current group senders map to payer Lenny.
- Expenses split between Alpar and Lenny.

This intentionally favors household simplicity over server-side trip ACLs.
Before adding several friend groups, move the per-group participant and payer
mapping into one declarative configuration consumed by the TREK proxy or a
binding-context hook. That will let multiple WhatsApp groups reuse the trips
agent without duplicating prompts or manually maintaining TREK access rules.

## Timezone lookup

`openclaw/tools/google-timezone-mcp.js` in the private repo exposes one read-only MCP tool
backed by the Google Maps Time Zone API:

```text
google-timezone__lookup(latitude, longitude, timestamp)
→ { timeZoneId, timeZoneName, rawOffset, dstOffset }
```

It reuses `GOOGLE_MAPS_API_KEY`. Enable **Time Zone API** in the key's Google
Cloud project and include it in the key's API restrictions; otherwise calls
return `REQUEST_DENIED`. The trips agent prefers a timezone already stored in
TREK and uses this tool after geocoding when one is absent.

Google Cloud setup:

1. Enable the
   [Time Zone API](https://console.cloud.google.com/apis/library/timezone-backend.googleapis.com)
   in the project that owns `GOOGLE_MAPS_API_KEY`; Maps Platform billing must
   be active.
2. If the key has API restrictions, add **Time Zone API** to its allowed APIs.
3. After deploying and restarting OpenClaw, verify discovery with
   `openclaw mcp probe google-timezone`.

Run the deterministic wrapper tests with:

```bash
node --test openclaw/tools/google-timezone-mcp.test.js
```
