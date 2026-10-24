# Tandoor 2.7.1 migration and email-address sequence

On 2026-10-24, Tandoor moved from `2.6.13` to `2.7.1` through GitOps commit
`34105aa7`. The new image reduced Trivy's distinct critical advisory count
from 8 to 1 and includes application security fixes. The database upgrade
encountered an existing PostgreSQL sequence mismatch during
`cookbook.0243_auto_20261018_1149`.

## What happened

Migration 0243 creates a verified fallback email address for any superuser
without one. Its first insert failed with a duplicate primary key on
`account_emailaddress.id=2`. On the **current primary** `tandoor-db-2`, the
table had three rows with `max(id)=3`, while
`account_emailaddress_id_seq.last_value=2`. The failed insert advanced the
sequence to 2 even though the transaction rolled back. The migration was
unapplied. A standby's sequence value appeared higher; use the CNPG current
primary for this check.

The container's startup script continued to collect static files and start
Gunicorn despite the migration failure, so Pod readiness alone did not prove
that migrations succeeded. A backup taken just before the image change
(`tandoor-db-pre-v271-20261024-1606`) completed at 16:06:22 UTC. Because
the app remained live for about an hour, a second backup immediately before
repair (`tandoor-db-pre-v271-repair-20261024-1709`) completed at 17:09:40 UTC.

After confirming that backup and the primary, we advanced only the affected
sequence to the table's maximum ID. A manual `manage.py migrate` using the
container's virtualenv Python then exhausted the app container's 1 GiB limit
while Gunicorn was also running; the exec exited 137 and the container
restarted once. The startup path completed migration 0243 and the remaining
OAuth provider migrations. Final checks: Tandoor 1/1 Ready, CNPG 2/2 healthy,
ArgoCD Synced/Healthy, `https://food.newjoy.ro/` redirected to the login
page, and the running digest's Trivy report contained one critical ID with no
scan error. The migration record was present, the sequence reached 4, and no
superuser lacked a verified email.

## If this recurs

1. Take a fresh on-demand CNPG backup and wait for its `status.phase` to be
   `completed`. Keep the application image and database restore point paired.
2. Identify the current primary with
   `kubectl -n tandoor get cluster tandoor-db -o jsonpath='{.status.currentPrimary}'`.
   Query that pod, not a standby. Check `max(id)` in
   `account_emailaddress`, `last_value` and `is_called` in
   `account_emailaddress_id_seq`, and the `django_migrations` row for
   `cookbook.0243_auto_20261018_1149`.
3. If the migration is still unapplied and the sequence is behind the table,
   advance only this sequence on the primary after the backup:

   ```sql
   SELECT setval(
     pg_get_serial_sequence('account_emailaddress', 'id'),
     (SELECT max(id) FROM account_emailaddress),
     true
   );
   ```

4. Let Tandoor's startup migration run and inspect its logs. Do not run a
   second migration process inside the 1 GiB app container while Gunicorn is
   active. If startup cannot complete, plan an isolated one-off migration Job
   with enough memory and the same image, database environment, and Secrets.
   Use `/opt/recipes/venv/bin/python`; the image's system `python` lacks
   application dependencies.
5. Confirm the migration record, table and sequence state, Pod and CNPG
   readiness, ArgoCD health, login redirect, and scanner coverage. Do not
   rerun a migration once its record is present.

The local startup error log was preserved at
`/private/tmp/tandoor-v271-startup-20261024.log` during the incident; this
temporary file is not a durable backup.

## Memory follow-up

After recovery, `kubectl top` showed about 830 MiB of Tandoor working-set
memory. Its cgroup held about 944 MiB against the 1 GiB limit, with a 945 MiB
peak since restart and no new cgroup OOM. Pamacs had about 58% actual memory
use but memory requests already consumed 85% of allocatable; the 2026-10-19
node OOM runbook uses 85% as its request-budget ceiling. The observed OOM
occurred only when a second management process ran alongside Gunicorn. Watch
normal-use memory and OOM events before changing the limit or its 512 MiB
request, and review placement plus fallback-node headroom before raising the
request. Avoid running management commands inside the live container while
Gunicorn is serving.
