# HomePBP

3-node k3s cluster on Odroid hardware. See [README.md](README.md) for the broader picture.

## OS

Nodes run **Fedora CoreOS** (immutable, ostree-based) — *not* Talos. The top-level `README.md`, `genesis/`, and `Plan.md` still contain Talos references; those are stale and should be cleaned up when convenient. When operating the cluster, use FCOS commands (`systemctl`, `rpm-ostree`), not `talosctl`.

## SSH access

```
ssh core@<node>.local        # e.g. core@buksi.local, core@pamacs.local, core@pufi.local
```

User `core` has sudo. Nodes: `buksi` (192.168.1.174), `pamacs` (192.168.1.173), `pufi`.

## Key paths on the nodes

- k3s systemd unit: `/etc/systemd/system/k3s.service` (server args baked into `ExecStart`)
- k3s config file (auto-read if present): `/etc/rancher/k3s/config.yaml`
- kubeconfig: `/etc/rancher/k3s/k3s.yaml`
- Longhorn replica dirs: `/var/lib/longhorn-ssd/replicas/`, `/var/lib/longhorn/replicas/`
- Root filesystem is composefs/ostree (read-only). `/var` is the only writeable bulk path.

## Longhorn recurring-job opt-out

To exclude a volume from a recurring job, **remove** the
`recurring-job-group.longhorn.io/<group>` label entirely. Setting it to
`=disabled` is silently ignored — the controller only honors `=enabled`.
This bit us in 2026-04: a `backup-exclusions` Job set
`recurring-job.longhorn.io/weekly-backup=disabled` on `media/movies-data`,
`media/tv-data`, etc., but Longhorn kept backing them up because
`recurring-job-group.longhorn.io/default=enabled` (auto-applied by the CSI
provisioner) still placed them in the group. ~5.5 TB of unwanted B2
storage before the bug was caught.

- Existing volume: `kubectl label volume <name> -n longhorn-system recurring-job-group.longhorn.io/default-`
- New volumes: set `parameters.recurringJobSelector: '[]'` on the StorageClass — the CSI provisioner uses that instead of defaulting to the `default` group.
- Always verify by waiting for the next scheduled run and checking `kubectl get backups.longhorn.io -n longhorn-system` for new entries — the label alone is not proof.

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
