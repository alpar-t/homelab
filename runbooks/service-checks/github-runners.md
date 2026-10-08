# GitHub Actions runner functional checks

The collector samples ARC's three repository scale sets every five minutes:
`homelab-runners`, `newjoy-website-runners`, and `baloo-export-runners`.
One stable check per set covers its Running reconciliation phase, linked
EphemeralRunnerSet and AutoscalingListener, failed runner startup, and runners
that have not become online within 15 minutes of creation. It also catches a
continuous desired/current replica deficit when no runner is running. Missing
or outdated reconciliation objects and replica deficits receive a continuous
15-minute observation grace. The foundation preserves that bounded in-memory
window across polls; collector restart or module update resets it. Native runner
creation timestamps preserve registration-age evidence across those resets.
Normal startup remains healthy during grace. Explicit failed startup is bad
immediately, followed by Zabbix's existing three-failing-sample debounce.

Zero desired/current runners with Running sets and a linked listener is healthy.
Long workflows and a busy one-runner capacity do not trigger a queue-age alarm.
Succeeded ephemeral runners are ignored. Details contain only booleans and
counts, never workflow names, job identifiers, status messages or log content.

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
