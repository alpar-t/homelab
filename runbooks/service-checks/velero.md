# Velero resource-backup functional checks

The collector reads Velero CRs every five minutes. It checks `default` storage
availability and a validation timestamp within 15 minutes, then verifies the
expected `velero-daily-resources` schedule and its completed Kubernetes-resource
backup. The live inventory on 2026-10-08 confirmed `Enabled`, daily `0 4 * * *`
and a completed 04:00 UTC backup; storage validation was fresh and Available.

Daily schedules use UTC, matching Velero's default cron timezone. At 06:00 UTC
(two hours after the 04:00 run), today's backup must have started and completed;
until then yesterday's completion suffices. A latest Failed, PartiallyFailed,
or FailedValidation backup fails immediately. An unfinished backup older than
two hours also fails. Later successful completion recovers the check. Expired,
future-dated, missing, or malformed completion evidence cannot pass. Merely
advancing `Schedule.status.lastBackup` does not prove successful completion.

`spec.paused: true` suspends schedule completion checks. A new schedule waits
until its first required daily run. Missing expected schedules fail. For an
intentional retirement, remove the corresponding `daily_schedules` entry from
`service_velero.json`; an empty map explicitly means no expected schedules.
Unknown unconfigured schedules and manual backups do not establish success or
create alerts. Keep the hour/minute/grace policy in sync with Helm values;
non-daily or timezone-prefixed cron expressions fail as unsupported rather than
silently applying the wrong deadline. Update this module before adopting those
cadences. Storage availability remains monitored while schedules are paused.

The namespace-local `zabbix-velero-readonly` Role grants only get/list on
backupstoragelocations, schedules and backups in `velero` to `zabbix/collector`.
There are no credentials to provision, Secret reads, writes, backup creation,
restores, or direct B2 traffic. Sync the Role/RoleBinding together with the
collector ConfigMap. Reads use the shared Kubernetes client's fixed 15-second
request timeout and the runner's 30-second deadline; each request checks the
remaining deadline. Lists stop at one 500-object page, failing visibly if more
pages exist instead of looping indefinitely. API errors report only exception
class through the runner, without storage errors, private paths or object data.
The existing three-sample Zabbix debounce applies; failed checks retry after
60 seconds.

These checks prove controller-reported resource backup completion and storage
validation, not restorability, object integrity or volume/database protection.
Longhorn and CNPG retain their existing independent data-backup checks. No
production backups or restores are initiated to validate monitoring.

Field semantics: [Schedule API](https://velero.io/docs/v1.16/api-types/schedule/),
[Backup API](https://velero.io/docs/v1.16/api-types/backup/), and
[BackupStorageLocation API](https://velero.io/docs/v1.16/api-types/backupstoragelocation/).
