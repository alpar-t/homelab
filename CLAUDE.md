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
`0 15 3 * * *` for daily at 03:15.
