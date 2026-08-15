# HomePBP

3-node k3s cluster on Intel x86_64 Odroid hardware (`amd64` in Kubernetes).
See [README.md](README.md) for the broader picture.

## Runbooks

Detailed operational knowledge — incident post-mortems, recovery procedures, and
non-obvious subsystem details — lives in `runbooks/`, not in this file. When
something is too long or too incident-specific to belong in AGENTS.md, write a
runbook and keep only a one-line pointer here. Check `runbooks/` before operating
or debugging a subsystem.

Baloo's source-controlled recurring jobs and reconciliation procedure:
`runbooks/baloo-recurring-jobs.md`.

Whole-cluster shutdown and startup for planned power maintenance:
`runbooks/cluster-power-maintenance.md`.

Vaultwarden client compatibility monitoring and safe upgrade procedure:
`runbooks/vaultwarden-maintenance.md`.

Baloo's read-only OpenCloud/Newjoy MCP credential setup and validation:
`runbooks/baloo-opencloud-mcp.md`.

Baloo's OLX account skill, credential isolation, and validation procedure:
`runbooks/baloo-olx-account.md`.

Baloo's Paperless document MCP account, credential, and validation procedure:
`runbooks/baloo-paperless-mcp.md`.

Longhorn minor-version upgrade procedure and validation gates:
`runbooks/longhorn-upgrade.md`.

CNPG database local-storage decision, inventory, and rolling migration:
`runbooks/migrate-postgres-to-local-storage.md`.

CNPG in-tree Barman backup to Barman Cloud Plugin migration and validation:
`runbooks/migrate-cnpg-to-barman-cloud-plugin.md`.

Newjoy portal architecture, image delivery, catalog policy, and operations:
`runbooks/newjoy-portal.md`.

Cloudflare Tunnel outage history, one-connector-per-node placement, and checks:
`runbooks/cloudflare-tunnel-availability.md`.

## Baloo agent tool access

OpenClaw's `mcp.servers` block is **gateway-global** — there is no per-agent MCP server config. Every agent can in principle reach every registered MCP server. The only access control is per-agent `tools.allow` and `tools.deny`.

**Hard rules — enforce these on every change:**

- Every agent in `openclaw.json` must have an explicit `tools.allow` listing exactly the tool namespaces it needs. This is a strict allowlist: tools not listed are unavailable to that agent.
- Every agent must also have an explicit `tools.deny` for any sensitive namespace available in `mcp.servers` that it does not need. At minimum, deny `hass__*` and `github-baloo__*` unless the agent explicitly requires them.
- Never add a new MCP server to `mcp.servers` without auditing every agent's `tools.deny` list to block it where it isn't needed.
- `openclaw.json` changes (tool policies, bindings) require a pod restart to take effect: `kubectl rollout restart deployment/openclaw -n baloo`. SOUL.md / AGENTS.md changes hot-reload without restart.

The trips channel (`Palkoek es Torokek`) must never have HA access — it is a shared family group with members outside the household.

### Read-only k8s access (`k8s__*`)

The `k8s` MCP server (`config/baloo/manifests/mcp-k8s.yaml`) gives the
`alpar` agent **read-only** cluster access so Alpar can ask about the
homelab and the `cluster-health` cron job can page on critical outages. It is
`flux159/mcp-server-kubernetes` in `ALLOW_ONLY_NON_DESTRUCTIVE_TOOLS` mode, but
the real guardrail is RBAC: the `mcp-k8s` ServiceAccount is bound to a
ClusterRole with only `get/list/watch` (no secrets, no configmaps, no write
verbs). It is `k8s__*` allowed **only on `alpar`** and explicitly
**denied on every other agent** (`kinga`, `cooking`, `garden`, `trips`,
`interior-designer`, `main`). If you
widen the ClusterRole, keep it read-only; never add write verbs or Secret read.

### Browser tool (`browser`)

The `browser` tool drives an **isolated headless Chromium** (Browserless v2) in
its own pod (`config/baloo/manifests/browser.yaml`), which OpenClaw attaches to
over remote CDP (`browser` block in `openclaw.json`, profile `cluster`,
`attachOnly`). The browser pod renders untrusted web content, so it is locked
down: no ServiceAccount token, non-root, and a **NetworkPolicy** that allows
ingress only from the openclaw pod and egress only to DNS + the public internet
(every private range — cluster, LAN incl. HA `192.168.x`, link-local, tailnet —
is blocked). Because that NetworkPolicy caps the blast radius to the public
internet regardless of caller, `browser` is allowed **wherever `web_fetch` +
`searxng__*` are** (the conversational agents: `alpar`, `kinga`, `cooking`,
`garden`, `trips`) — it is just a JS-capable fetch with the same reach. It is
denied only on `main` (the auth root, which has no web tools). Attaching to the
pod's private CDP address relies on `browser.ssrfPolicy.allowedHostnames` (do
**not** enable `dangerouslyAllowPrivateNetwork` — that would weaken navigation
SSRF).

For an authenticated browser workflow, create a dedicated named browser
profile and require its skill to specify that profile on every browser call.
This separates tabs and session state from unrelated browsing, but it is not an
authorization boundary: browser profiles are gateway-global and any agent with
the generic `browser` tool can select them. When the workflow needs access
isolation, use a separately allowlisted tool namespace and browser service
instead of relying on the profile name. With Browserless, do not use its
`trackingId` query parameter as the OpenClaw profile identity: `trackingId`
rejects later connections while the first session is alive, breaking
multi-command flows. Let OpenClaw own the live connection for each named
profile through a normal Browserless CDP URL. Give profiles on the same
Browserless service distinct, behavior-neutral CDP URLs (for example an
explicit request timeout equal to the server default); OpenClaw may reuse the
same controller when two profiles have byte-for-byte identical URLs, which
mixes their tabs.

Prereq: create the `BROWSER_CDP_TOKEN` key in the `baloo-secrets` Secret (used
by both the browser pod's `TOKEN` and the CDP URL). The key is wired as
`optional`, so until it exists the attach will fail but nothing crash-loops.

### OpenClaw docs lookup

The OpenClaw image ships its full documentation at `/app/docs/` and `/app/qa/`. Read it from the running pod instead of guessing or web-searching:

```bash
# List doc topics
kubectl -n baloo exec deployment/openclaw -c openclaw -- ls /app/docs
# Read a specific page (MCP config, channels, gateway, etc.)
kubectl -n baloo exec deployment/openclaw -c openclaw -- cat /app/docs/cli/mcp.md
# Find anything across docs
kubectl -n baloo exec deployment/openclaw -c openclaw -- grep -rln '<term>' /app/docs
```

These are authoritative for the deployed version — version-correct, no drift from upstream docs sites.

## Writing skills or Baloo agent files

Baloo's OpenClaw configuration, agent workspaces, and shared skills live in the
private `alpar-t/baloo` repository under `openclaw/`; only its Kubernetes
manifests remain under `config/baloo/manifests/` here. Expect that repository to
be checked out at the sibling path `../baloo`, and operate there for Baloo source
changes instead of searching for those files here. Identify the coding agent
performing the change. When editing anything in `openclaw/agents/*/SOUL.md` or
`AGENTS.md`, or when authoring a new skill, first load that coding agent's native
skill-creator guidance:

- Claude Code: load Anthropic's guidance from
  https://raw.githubusercontent.com/anthropics/skills/main/skills/skill-creator/SKILL.md
- Codex: load its installed `skill-creator` skill from the session's available
  skills catalog; do not hard-code a local installation path.
- Another coding agent: use its native equivalent when available. Otherwise,
  fall back to Anthropic's guidance above and state that fallback.

Do not direct one coding agent to use another agent's installation paths or
agent-specific tools.

Key points to apply: imperative tone with the *why*, keep files lean, avoid rigid ALL-CAPS rules, put "when to use" details in the description (for skills) or in the first paragraph (for agents), specify output formats with concrete examples where they aren't obvious.

## Container image references

Always verify image references against the actual registry before writing them
into manifests. Do not guess or infer from the GitHub repo name — published
image names often differ (e.g. the `rhasspy/wyoming-faster-whisper` repo
publishes as `rhasspy/wyoming-whisper` on Docker Hub).

**Lookup workflow — always use `scripts/resolve-container-image.py`, not ad-hoc
`curl`, Docker Hub UI, or `docker manifest` commands.** The helper queries the
registry with `skopeo`, verifies that the tag has a Linux `amd64` image, and
returns the manifest-list digest. With no tag it selects the highest stable
version-like tag; pass an explicit tag when a project uses non-version tags.

```bash
# Inspect the newest stable version-like tags.
scripts/resolve-container-image.py registry.k8s.io/kubectl --list

# Select the highest stable version-like tag and resolve it.
scripts/resolve-container-image.py prometheuscommunity/smartctl-exporter

# Resolve a deliberately selected tag.
scripts/resolve-container-image.py registry.k8s.io/kubectl v1.34.6
```

Copy the helper's `reference=` value into the manifest. Always write image refs
as `<registry>/<image>:<tag>@<digest>` for reproducibility.

**`registry.k8s.io/kubectl` is distroless** — no shell, no `cp`, no standard Unix tools.
To get kubectl into a volume, use an Alpine init container that `wget`s the binary:
```yaml
image: alpine:3.21@sha256:...
command: ["sh", "-c", "wget -qO /tools/kubectl https://dl.k8s.io/release/v<ver>/bin/linux/amd64/kubectl && chmod +x /tools/kubectl"]
```

## OS

Nodes run **Fedora CoreOS** (immutable, ostree-based) — *not* Talos. The top-level `README.md`, `genesis/`, and `Plan.md` still contain Talos references; those are stale and should be cleaned up when convenient. When operating the cluster, use FCOS commands (`systemctl`, `rpm-ostree`), not `talosctl`.

## SSH access

```
ssh core@<node>.local        # e.g. core@buksi.local, core@pamacs.local, core@pufi.local
```

User `core` has sudo. Nodes: `buksi` (192.168.1.174), `pamacs` (192.168.1.173), `pufi`.

## Home Assistant lives outside the cluster

Home Assistant runs on a **dedicated Home Assistant OS device at
`192.168.1.102`** — not in k3s. The `config/homeassistant/` manifests and
`apps/homeassistant-db.yaml` only deploy the **Postgres recorder DB** (CNPG)
that HA writes to; the HA app itself is on the standalone box.

Access from this workstation:

- **Local config mirror**: `config/homeassistant/ha/` in this repo is a
  mirror of the live HA `/config/` directory. Edit files here, then deploy
  with `scripts/deploy-ha.sh` (copies automations/scripts/scenes/packages/
  dashboards and reloads HA — do not use raw `scp`/`rsync` directly).
  Packages live under `config/homeassistant/ha/packages/` (e.g. `pool.yaml`, etc.).
  **All automations are synced here** — `config/homeassistant/ha/automations.yaml`
  is the source of truth for every automation on the device. To read or grep
  an automation's config, use this file; no need to query the live HA
  instance. Use `hass-mcp` only for *runtime* state (last_triggered, whether
  it fired, current entity values), not to discover the automation itself.
- **Shell / file edits**: `ssh hass` (configured in `~/.ssh/config` → port
  22222, root, key `~/.ssh/id_ed25519_hass`). Lands in the "Terminal & SSH"
  addon container, where `/config/*` is the HA config dir
  (`configuration.yaml`, `automations.yaml`, `scripts.yaml`,
  `custom_components/`, etc.). Use this for any YAML/file work.
- **Runtime API (entities, services, history, templates)**: via the
  `hass-mcp` MCP server (user-scope, registered with Claude Code).
- **Web UI**: `http://192.168.1.102:8123`.

When the user asks anything HA-related, default to these — do not look in
the k3s cluster (it only has the DB).

## Tailscale remote access

Stock Tailscale (controlplane.tailscale.com) provides remote access to the LAN
(`192.168.1.0/24`) via a subnet router pod in the `tailscale` namespace.

- **Subnet router is pinned to buksi** (`nodeSelector: kubernetes.io/hostname: buksi`).
  This is not optional — see the co-location constraint below.
- **Auth key** lives in the `tailscale-auth` secret (break-glass only; the node
  identity persists in `tailscale-state` across pod restarts).
- **DNS**: Tailscale admin → DNS → global nameserver `192.168.1.202` (Pi-hole),
  "Override local DNS" on. Without this, tailnet devices use carrier/WiFi DNS.
- **ACL**: `config/tailscale/` — allow-all with `autoApprovers` for the subnet route.

### MetalLB + Tailscale co-location constraint

kube-proxy drops forwarded traffic in nftables FILTER FORWARD for
`externalTrafficPolicy: Local` services when no local pod exists on the
forwarding node. Because Tailscale's iptables-legacy MASQUERADE only fires when
traffic goes via the cluster overlay (cni0/flannel), cross-node MetalLB traffic
going out the physical NIC (enp2s0) is dropped before POSTROUTING is reached.

**Rule**: the subnet router must run on the same node as any MetalLB service
with `externalTrafficPolicy: Local` that you want reachable via Tailscale.
Emby, Immich, and arr-stack are all on buksi — hence the pin. Services with
`externalTrafficPolicy: Cluster` (whisper, homeassistant-db, paperless-ftp)
work from any node because kube-proxy DNAT routes them via flannel regardless.

If you ever move Emby or other Local-policy services to a different node, move
the subnet router nodeSelector with them.

## Node workload placement (`workload/cpu-intensive`)

The three nodes are unequal: **pamacs has 32Gi RAM, buksi and pufi have 16Gi
each.** To keep memory-heavy but *movable* workloads off the small nodes (so a
memory spike can't OOM them and fault single-replica Longhorn volumes — see the
2026-07-06 OnlyOffice incident), pamacs carries the label
`workload/cpu-intensive=true`, and heavy movable Deployments set a **soft**
`preferredDuringSchedulingIgnoredDuringExecution` nodeAffinity toward it
(weight 100). This is a preference, not a hard pin — if pamacs is down they
schedule anywhere.

- Apps using it: `immich`, `tandoor`, `paperless-ngx`, `baloo/whisper`.
- **Do not** use hard `nodeSelector`/hostname pins for this — the default
  scheduler never migrates pods back after a node outage >~6min (freeze →
  watchdog reboot), so the soft affinity is what pulls them back to the big
  node on reschedule. A descheduler was considered and rejected (most heavy
  pods are hard-pinned anyway, and evicting Longhorn RWO pods causes
  detach/reattach churn).
- The label was applied imperatively (`kubectl label node pamacs
  workload/cpu-intensive=true`); it survives reboots/k3s restarts but not a node
  re-provision — re-apply it if pamacs is rebuilt.
- **Genuinely pinned, do not add this to them:** arr-stack/emby (MetalLB
  `Local` + Tailscale, buksi), opencloud core (local-ssd PVC on pufi),
  omada-controller (`hostNetwork` — moving it changes the controller IP and
  disrupts AP/switch adoption).

## Travel network / backup uplink

Portable kit for travel and homelab failover:

- **GL.iNet GL-MT3000 (Beryl AX)** — travel router/Mifi. Default admin: `192.168.8.1` (may renumber to `192.168.9.1` when Brovi is the WAN to avoid subnet conflict). Connected to homelab via Tailscale. SSH access + a Tailscale-stall post-mortem: `runbooks/travel-router.md`.
- **Brovi E3372 USB Surf Stick** — LTE modem plugged into the GL's USB port as WAN uplink. HiLink web UI (SMS inbox, signal) reachable at `192.168.8.1` from the GL's WAN side. Carries a dedicated SIM with its own mobile number and data plan.
- **WhatsApp Business** — registered on the Brovi SIM number (iPhone, separate from personal WhatsApp). Intended as the interface for an **OpenClaw** AI agent (open-source LLM agent framework, supports WhatsApp).

To read SMS on the Brovi (e.g. OTP codes): connect to GL network → open `http://192.168.8.1` → Messages.

## Key paths on the nodes

- k3s systemd unit: `/etc/systemd/system/k3s.service` (server args baked into `ExecStart`)
- k3s config file (auto-read if present): `/etc/rancher/k3s/config.yaml`
- kubeconfig: `/etc/rancher/k3s/k3s.yaml`
- Longhorn replica dirs: `/var/lib/longhorn-ssd/replicas/`, `/var/lib/longhorn/replicas/`
- Root filesystem is composefs/ostree (read-only). `/var` is the only writeable bulk path.

## Longhorn recurring-job opt-out

Per Longhorn's
[label-driven recurring job design](https://github.com/longhorn/longhorn/blob/master/enhancements/20210624-label-driven-recurring-job.md),
the controller "labels with `default` job-group if no other recurring job
label exists." So:

- `=disabled` on a label is **not** a recognized opt-out — it has no
  semantic meaning, but it does count as "another recurring-job label,"
  which incidentally suppresses the default auto-add.
- Removing the `default` group label alone does **not** work — the
  controller re-adds it within milliseconds because the volume is now
  unlabeled.

The supported way to opt a volume out is to **give it some other
recurring-job-group label**. We use a marker group called `excluded`
that has no associated `RecurringJob`, so nothing fires:

- Existing volumes: the `apps/longhorn-storage` PostSync hook
  (`config/longhorn/manifests/backup-exclusions.yaml`) labels each PVC
  in the inclusion-of-exclusions ConfigMap with
  `recurring-job-group.longhorn.io/excluded=enabled` and removes the
  `default` label.
- Future noreplica volumes: the `longhorn-{ssd,hdd}-noreplica`
  StorageClasses set
  `recurringJobSelector: '[{"name":"excluded","isGroup":true}]'`, so
  the CSI provisioner stamps the marker at creation.

This bit us in 2026-04. The original exclusion Job set
`recurring-job.longhorn.io/weekly-backup=disabled` on PVCs like
`media/movies-data`, but those volumes had already been auto-stamped
into `default` at creation time — the `=disabled` label was added on
top and didn't change anything. `media/movies-data`, `media/tv-data`
etc. kept being backed up to B2 weekly (~5.5 TB of waste). Then a
"fix" attempt that removed all recurring-job labels backfired: the
auto-add re-fired immediately because the volume was now unlabeled,
restoring `default`. The marker-label approach above is what actually
sticks.

Always verify by waiting for the next scheduled run and checking
`kubectl get backups.longhorn.io -n longhorn-system` for new entries —
labels alone are not proof.

## CNPG cron schedules need 6 fields

`postgresql.cnpg.io/v1` `ScheduledBackup` parses crons with a leading
seconds field. A 5-field cron is silently misread (`15 3 * * *` becomes
hourly, not daily) — there's no validation error. Always write 6-field:
`0 15 3 * * *` for daily at 03:15. First seen 2026-04-12 when weekly
backups for homeassistant/tandoor/roundcube hadn't run for two months
because `0 4 * * 7` was being misinterpreted.

## ArgoCD selfHeal races dynamic PVC provisioning

When swapping a PV for an ArgoCD-managed PVC whose Helm template has no
`volumeName`, ArgoCD's selfHeal recreates the PVC instantly and the
StorageClass dynamic provisioner binds a fresh empty volume before any
manual `kubectl apply` of a `volumeName`-pinned PVC can win. Scaling
replicas to 0 via `kubectl` doesn't help either — selfHeal reverts it.
Removing `spec.syncPolicy.automated` via merge patch also gets
reverted.

To swap a PV under an ArgoCD-managed app:

1. Pin replicas via `spec.sources[].helm.parameters` (ArgoCD respects
   its own parameter overrides).
2. Add the PVC to `spec.ignoreDifferences` with a JSON pointer to
   `/spec/volumeName`, plus `RespectIgnoreDifferences=true` in
   `syncOptions`. Persist this in the Application YAML in git.
3. Strip PV finalizers before deleting old PVs during a restore — they
   block deletion indefinitely otherwise.

Live example: `apps/opencloud.yaml` ignores `volumeName` on
`opencloud-opencloud-posixfs` because that PVC was manually bound to
the restored volume on 2026-03-31. Don't remove that block.

**Why patching `syncPolicy.automated` off a child app doesn't stick:** the
root **app-of-apps `homelab`** (path `apps/`) manages every child Application
and has its own selfHeal, so it re-adds `automated` to the child within
seconds and the child re-syncs to git. For a **controlled manual staged
change** (scale down → SQL → swap image → SQL → scale up, as in a DB
migration), suspend `homelab` *first*, then the child, do the work, push the
end-state to `main`, then re-enable (child then root). Exact procedure:
`runbooks/argocd-staged-changes.md`. Motivating example (Immich
pgvecto.rs→VectorChord, incl. the 10Gi-PVC-full and startup-probe-crashloop
gotchas): `runbooks/immich-vectorchord-migration.md`.

## Buksi i915 freeze fix (2026-04-12)

Buksi was hard-freezing every 8–15 days (3 crashes since Jan 2026).
Root cause: i915 GPU display core power states (DC5/DC6) on a headless
Alder Lake-N. `intel_idle.max_cstate=1` (already in place) only covers
CPU idle, not GPU display power. Added `i915.enable_dc=0` via
`rpm-ostree kargs` on all 3 nodes and to `genesis/ignition-template.bu`
for re-provisioning. Buksi rebooted with the fix on 2026-04-12;
pufi/pamacs were staged for next Zincati reboot. If buksi crashes
again past mid-May 2026, re-evaluate — the fix may be insufficient.

The fix proved **insufficient**: pamacs froze again on 2026-07-04 with
the karg active; the cause is now believed to be unit-specific hardware.
All nodes now arm the iTCO watchdog so a freeze auto-reboots instead of
needing a power-cycle. Full analysis + diagnostics:
`runbooks/node-freeze-hardware-watchdog.md`.

## TREK app

`apps/trek.yaml` and `config/trek/` deploy TREK
(github.com/mauriceboe/TREK) — a **holiday/trip planner**, not a Star
Trek LCARS-style dashboard. The name is misleading; mention "trip
planner" when describing it.
