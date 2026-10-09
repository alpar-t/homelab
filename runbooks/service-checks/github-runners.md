# GitHub Actions runner functional checks

The collector samples ARC's three repository scale sets every 15 minutes:
`homelab-runners`, `newjoy-website-runners`, and `baloo-export-runners`.
Each stable check covers its Running reconciliation phase, the listener's current
EphemeralRunnerSet, and desired versus running capacity. Missing reconciliation
objects or capacity deficits receive a continuous 15-minute observation grace;
a current runner's creation time identifies registration stalled beyond that
window. The worker then applies the shared 30-minute failure grace and at least
two independent failed executions before confirming an incident. Recovery needs
two independent healthy executions. Cached snapshots never advance these counters;
failures retain the same 15-minute cadence. Referenced workload reboot grace and
notification timing are described in [the framework](../service-functional-checks.md).

Historical failed counters and terminal runners remain diagnostic counts and do
not cause an outage when current capacity is healthy. Retained prior runner sets
and deleting runners are ignored. A replacement that restores current capacity
can recover despite retained failures. Zero desired runners with Running sets and
a linked listener are healthy; long workflows do not cause queue-age alarms.
Details contain only booleans and counts, never workflow names, job identifiers,
status messages or log content. Sustained current-capacity failures page.

Four bounded inventory reads use five-second Kubernetes transport limits, a
30-second worker deadline and at most 500 objects per inventory; continuation
is rejected rather than silently truncating evidence.

Deploy the namespace-local `arc-readonly.yaml` Roles and bindings with the
collector module/config. Access is get/list of runner CRs in `arc-runners` and
listener CRs in `arc-systems`; there are no writes, Secret reads, PATs or GitHub
API calls. No destination network-policy change is required: requests use the
collector's existing Kubernetes API access. API denial, truncated inventories,
malformed counters or execution timeout produce functional-monitor unavailable.
No workflow dispatch, runner provisioning or test job is performed.

Semantics were verified against installed CRD schemas and live idle resource
status on 2026-10-08, and the deployed chart's official
[ARC 0.14.2 types](https://github.com/actions/actions-runner-controller/tree/gha-runner-scale-set-0.14.2/apis/actions.github.com/v1alpha1).
`EphemeralRunner.status.ready` means online; Failed means startup failed after
retries rather than a failed user workflow. AutoscalingRunnerSet Pending means
the listener has not started. The installed AutoscalingListener status schema
has no fields, and scale-set status exposes no heartbeat, observed generation,
or GitHub queue timestamp. Consequently passive CR checks cannot prove current
listener authentication, an unseen GitHub queue, or end-to-end execution while
idle. A stalled controller that leaves all old objects Running is also outside
this baseline. Existing workload readiness monitoring remains complementary.

For failures, inspect ARC reconciliation and listener diagnostics locally,
runner registration and repository credential validity, and pending scheduling.
Do not copy the ARC administration PAT into Zabbix. Resolve the underlying ARC
failure; no monitor state reset or workflow execution is needed for recovery.
