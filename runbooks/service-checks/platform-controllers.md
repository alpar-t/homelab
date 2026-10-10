# Cluster support controllers

## Polling and incident confirmation

Poll every 600 seconds (10 minutes); shared failure grace is 900 seconds.
A problem needs both the elapsed grace and at least two independent failed
executions; recovery needs two independent healthy executions. At this cadence
and grace, ordinary continuous failure normally requires three failed runs.
Minute snapshots never count as new observations, and failures keep the same
slow cadence. Scheduling is staggered. Referenced workload reboot/rescheduling
grace and maintenance preserve confirmed state without declaring recovery.
Persistent ordinary outages page; module-specific advisories stay on the dashboard.
See [the shared framework](../service-functional-checks.md) for startup,
unknown/deferred observations and queue freshness.

The functional baseline reads the node API every 10 minutes and verifies
`gpu.intel.com/i915` allocatable remains at least 10 on buksi, pamacs and pufi.
The Intel GPU plugin source selects amd64 nodes and configures
`-shared-dev-num=10`; live read-only validation on 2026-10-08 confirmed 10 on
each node. Allocatable means total schedulable device capacity, not free slots:
ordinary workload allocation does not reduce it. Missing registration or
reduced healthy-device capacity therefore fails even if the plugin pod is Ready.

Nodes outside the configured plugin selector are explicitly skipped. Not-Ready
nodes rely on infrastructure availability checks; newly Ready nodes receive ten
minutes to register devices. Missing expected nodes fail. Malformed, incomplete,
unauthorized or timed-out API reads become framework monitoring failures.
The framework retains the configured polling interval and uses the existing execution-based confirmation. No credentials, extra RBAC or NetworkPolicy are needed;
the collector already has node get/list access. One API request uses the existing
five-second timeout within a 20-second worker deadline.

Keep expected nodes, selector and capacity synchronized with intentional plugin
placement or sharing changes. This verifies kubelet registration, not a working
GPU kernel or a successful workload execution; no device is allocated or used.

The remaining inventory deliberately relies on existing infrastructure checks.
The expected-deployment inventory now explicitly includes the live-verified
`kube-system/local-path-provisioner`, `reloader/reloader-reloader` and
`system-upgrade/system-upgrade-controller`. Existing checks detect missing or
unavailable Deployments without adding competing functional readiness records.
Dynamic DaemonSet discovery still does not detect a deleted DaemonSet:

| Component | Existing coverage and passive limit |
| --- | --- |
| k3s local-path provisioner | Expected Deployment presence/readiness; workload/DB readiness exposes unusable existing storage. No synthetic PVC or proof of future provisioning. |
| Stakater Reloader | Expected Deployment presence/readiness and managed workload readiness. No synthetic Secret/ConfigMap changes; idle reconciliation is normal. |
| system-upgrade controller | Expected Deployment presence/readiness and node readiness. No synthetic upgrade, cordon or reboot; completion of an intended upgrade still needs operator verification. |
| Multus | DaemonSet readiness and Longhorn workload/volume health. No synthetic network attachment. |
| Whereabouts | CRDs installed by its ArgoCD app; IPAM is invoked by CNI rather than an independently monitored Deployment here. Longhorn health exposes downstream failures; no synthetic allocations or claim that readiness proves IPAM correctness. |
| node-config | DaemonSet readiness; dedicated node-storage-health readiness/events retain disk quarantine and latched errors. Host configuration parity is not inferred from a sleeping pod. |

Validate with `scripts/test zabbix` and
`kubectl kustomize config/zabbix/manifests`. This PR depends on the functional
runner foundation; no production mutation is required to validate this check.

Not-Ready nodes and registration startup grace produce unknown observations,
so an older GPU registration incident cannot recover until fresh registration
is observed. Infrastructure node availability remains the outage signal.
