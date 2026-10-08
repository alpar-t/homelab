# ArgoCD reconciliation monitoring

The collector reads only Application CRs in `argocd`, every five minutes, with
three-failure Zabbix debounce. It needs the included namespace Role/RoleBinding
granting only `list applications.argoproj.io`; no ArgoCD credentials, public
endpoint, network-policy changes or Secret reads are required. Private admin
access remains as described in [argocd-access](../argocd-access.md).

Three aggregate checks report inventory availability, persistent repository /
comparison / specification / sync errors, and reconciliation progress. Progress
catches unsynced, degraded, missing, unknown or persistently progressing apps,
failed operations on unsynced apps, and stale/missing `status.reconciledAt`.
Completed historical failed operations on now-Synced applications do not alert.
Counts are emitted; Application names, repository addresses and CR error messages
are never copied into monitoring output.

Each continuous unhealthy period gets 30 minutes of grace, resetting on recovery.
Reconciliation timestamps become stale after 30 minutes; the subsequent grace
means a stopped controller is detected after roughly 60 minutes plus debounce.
The timestamps tracked in memory reset on collector restart. A healthy idle app
needs no new deployment or operation; regular controller comparison suffices.

Applications with automation absent/null or `automated.enabled: false`, deletion
in progress, `argocd.argoproj.io/skip-reconcile: "true"`, or
`monitoring.homepbp.io/maintenance: "true"` annotations are counted as paused
and excluded from error/progress checks. Healthy `Suspended` resource health is
also accepted. For staged work follow [argocd-staged-changes](../argocd-staged-changes.md)
and suspend both root and affected child; suspending only the root does not pause
monitoring of other active children. Keep intentional maintenance annotations in
the authoritative Application manifests where applicable. Remove them when done.
No maximum pause duration is enforced. AppProject sync windows are not evaluated;
use the explicit maintenance marker for long deliberate blocked sync periods.

The API call uses one list page capped at 500 Applications, a 15-second client
timeout, and requires at least 16 seconds remaining in the 30-second worker
budget. Empty, truncated, unauthorized, malformed or inaccessible inventories
fail closed. The shared client does not enforce a byte cap on Kubernetes JSON;
this check never paginates and bounds evaluation to 500 Applications.

This passive baseline verifies controller-reported convergence, not an actual new
Git commit, repo-server synthetic generation or application business workflows.
Inspect the private ArgoCD UI and affected Application CR for detailed failures.
Independent service checks remain necessary even when ArgoCD reports Healthy.

Policy references: [automated sync](https://argo-cd.readthedocs.io/en/stable/user-guide/auto_sync/)
and [skip reconciliation](https://argo-cd.readthedocs.io/en/stable/user-guide/skip_reconcile/).
