# HomePBP

3-node k3s cluster on Odroid hardware. See [README.md](README.md) for the broader picture.

## Baloo agent tool access

OpenClaw's `mcp.servers` block is **gateway-global** — there is no per-agent MCP server config. Every agent can in principle reach every registered MCP server. The only access control is per-agent `tools.allow` and `tools.deny`.

**Hard rules — enforce these on every change:**

- Every agent in `openclaw.json` must have an explicit `tools.allow` listing exactly the tool namespaces it needs. This is a strict allowlist: tools not listed are unavailable to that agent.
- Every agent must also have an explicit `tools.deny` for any sensitive namespace available in `mcp.servers` that it does not need. At minimum, deny `hass__*` and `github-life__*` unless the agent explicitly requires them.
- Never add a new MCP server to `mcp.servers` without auditing every agent's `tools.deny` list to block it where it isn't needed.
- `openclaw.json` changes (tool policies, bindings) require a pod restart to take effect: `kubectl rollout restart deployment/openclaw -n baloo`. SOUL.md / AGENTS.md changes hot-reload without restart.

The trips channel (`Palkoek es Torokek`) must never have HA access — it is a shared family group with members outside the household.

### Read-only k8s access (`k8s__*`)

The `k8s` MCP server (`config/baloo/manifests/mcp-k8s.yaml`) gives the
`direct-message` agent **read-only** cluster access so Alpar can ask about the
homelab and the DM heartbeat can page on critical outages. It is
`flux159/mcp-server-kubernetes` in `ALLOW_ONLY_NON_DESTRUCTIVE_TOOLS` mode, but
the real guardrail is RBAC: the `mcp-k8s` ServiceAccount is bound to a
ClusterRole with only `get/list/watch` (no secrets, no configmaps, no write
verbs). It is `k8s__*` allowed **only on `direct-message`** and explicitly
**denied on every other agent** (`cooking`, `garden`, `trips`, `main`). If you
widen the ClusterRole, keep it read-only; never add write verbs or Secret read.

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

When editing anything in `config/baloo/agents/*/SOUL.md` or `AGENTS.md`, or when authoring a new Claude Code skill, first load Anthropic's skill-creator guidance for review principles:

- https://raw.githubusercontent.com/anthropics/skills/main/skills/skill-creator/SKILL.md

Key points to apply: imperative tone with the *why*, keep files lean, avoid rigid ALL-CAPS rules, put "when to use" details in the description (for skills) or in the first paragraph (for agents), specify output formats with concrete examples where they aren't obvious.

## Container image references

Always verify image references against the actual registry before writing them into manifests. Do not guess or infer from the GitHub repo name — published image names often differ (e.g. the `rhasspy/wyoming-faster-whisper` repo publishes as `rhasspy/wyoming-whisper` on Docker Hub). Verify by fetching the GitHub README or the registry page directly.

**Lookup workflow — always use these commands, not WebFetch to Docker Hub UI (which is unreliable):**

```bash
# 1. registry.k8s.io images (kubectl, coredns, git-sync, etc.)
curl -s "https://europe-west10-docker.pkg.dev/v2/k8s-artifacts-prod/images/<name>/tags/list" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); \
    tags=[t for t in d.get('tags',[]) if not any(x in t for x in ['alpha','beta','rc','sha'])]; \
    print('\n'.join(sorted(tags)[-10:]))"
# Then get digest:
docker manifest inspect --verbose registry.k8s.io/<name>:<tag> \
  | python3 -c "import sys,json; d=json.load(sys.stdin); \
    print(d[0].get('Descriptor',{}).get('digest','') if isinstance(d,list) else '')"

# 2. Docker Hub / ghcr.io images — use Hub REST API, not the web UI:
curl -s "https://registry.hub.docker.com/v2/repositories/<org>/<image>/tags/?page_size=20&ordering=last_updated" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); \
    [print(t['name']) for t in d.get('results',[]) \
      if not any(x in t['name'] for x in ['sha256','sig','att','metadata'])]"
# Then get manifest-list digest:
docker manifest inspect --verbose <image>:<tag> \
  | python3 -c "import sys,json; d=json.load(sys.stdin); \
    print(d[0].get('Descriptor',{}).get('digest','') if isinstance(d,list) else '')"
```

Always write image refs as `<registry>/<image>:<tag>@<digest>` for reproducibility.

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
  mirror of the live HA `/config/` directory. Edit files here, then `scp`
  or `rsync` to the device. Packages live under
  `config/homeassistant/ha/packages/` (e.g. `pool.yaml`, etc.).
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

## Travel network / backup uplink

Portable kit for travel and homelab failover:

- **GL.iNet GL-MT3000 (Beryl AX)** — travel router/Mifi. Default admin: `192.168.8.1` (may renumber to `192.168.9.1` when Brovi is the WAN to avoid subnet conflict). Connected to homelab via Tailscale.
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

## Buksi i915 freeze fix (2026-04-12)

Buksi was hard-freezing every 8–15 days (3 crashes since Jan 2026).
Root cause: i915 GPU display core power states (DC5/DC6) on a headless
Alder Lake-N. `intel_idle.max_cstate=1` (already in place) only covers
CPU idle, not GPU display power. Added `i915.enable_dc=0` via
`rpm-ostree kargs` on all 3 nodes and to `genesis/ignition-template.bu`
for re-provisioning. Buksi rebooted with the fix on 2026-04-12;
pufi/pamacs were staged for next Zincati reboot. If buksi crashes
again past mid-May 2026, re-evaluate — the fix may be insufficient.

## TREK app

`apps/trek.yaml` and `config/trek/` deploy TREK
(github.com/mauriceboe/TREK) — a **holiday/trip planner**, not a Star
Trek LCARS-style dashboard. The name is misleading; mention "trip
planner" when describing it.
