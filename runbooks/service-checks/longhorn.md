# Longhorn functional baseline

The `functional/longhorn` check reads the named `default` BackupTarget CR
through the Kubernetes API every five minutes. It requires a parseable,
timezone-aware `status.lastSyncedAt` and a nonempty controller `ownerID`.
Synchronization older than two hours fails, allowing four missed configured
30-minute polls; timestamps more than five minutes in the future also fail.
Missing resources, unauthorized requests, malformed metadata and timeouts
fail with generic evidence, without storage URLs or credentials.

This detects stalled backup-store reconciliation even when cached
`status.available` remains true. Existing collector checks continue to cover
target availability, volume robustness and completed-backup freshness.
Normal idle storage passes because the controller polls the backup store even
without new backups. The target's existing `pollInterval: 30m0s` must stay
enabled; review this two-hour policy if changing the polling interval.
The deployed-version [Longhorn v1.11.3 controller source](https://github.com/longhorn/longhorn-manager/blob/v1.11.3/controller/backup_target_controller.go)
confirms the timer advances `spec.syncRequestedAt` and reconciliation updates
`status.lastSyncedAt`; failure to create a backup client leaves it unchanged.

The worker deadline is 30 seconds with one existing Kubernetes-client GET
bounded to 15 seconds. Standard Zabbix three-failure debounce applies to
cached samples; it does not imply three distinct five-minute executions.
Existing collector `get` permission on `backuptargets.longhorn.io` suffices.
No new credential, network access, RBAC, or application sign-in is required.

This is passive controller evidence. It cannot prove that a new backup can
be uploaded, restored, mounted, or read correctly, and does not exercise the
Longhorn manager's UI API or data plane. It never triggers synchronization,
backup, volume operations, or mounts. It does not inspect volume backup groups
or impose backup expectations on excluded volumes: the `excluded` marker and
all existing backup-selection semantics remain untouched. No per-volume stale
backup-store metadata is checked, including the known excluded-volume warning
documented in [the upgrade runbook](../longhorn-upgrade.md).

Validation on 2026-10-08 used a bounded read-only live BackupTarget GET:
`available=true`, a populated owner, `lastSyncedAt` at 18:04:57 UTC and
`pollInterval=30m0s`. Unit fixtures cover fresh/idle, stale cached-available,
future timestamps, malformed/ownerless status, authorization and timeout
failures. No production storage operations were performed.
