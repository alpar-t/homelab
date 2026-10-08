# Cluster support controllers

The functional baseline reads the node API every five minutes and verifies
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
The framework retries failures after one minute and uses the existing three
failing-sample debounce. No credentials, extra RBAC or NetworkPolicy are needed;
the collector already has node get/list access. One API request uses the existing
15-second Kubernetes client timeout within a 20-second worker deadline.

Keep expected nodes, selector and capacity synchronized with intentional plugin
placement or sharing changes. This verifies kubelet registration, not a working
GPU kernel or a successful workload execution; no device is allocated or used.

The remaining inventory deliberately relies on existing infrastructure checks.
Support-controller Deployments are not in the current expected-deployment list:
pod checks detect unready discovered pods, but do not prove that a deleted
controller still exists. DaemonSet discovery has the same deletion limitation:

| Component | Existing coverage and passive limit |
| --- | --- |
| k3s local-path provisioner | Discovered pod readiness; workload/DB readiness exposes unusable existing storage. No synthetic PVC or proof of future provisioning. |
| Stakater Reloader | Discovered pod and managed workload readiness. No synthetic Secret/ConfigMap changes; idle reconciliation is normal. |
| system-upgrade controller | Discovered pod and node readiness. No synthetic upgrade, cordon or reboot; completion of an intended upgrade still needs operator verification. |
| Multus | DaemonSet readiness and Longhorn workload/volume health. No synthetic network attachment. |
| Whereabouts | CRDs installed by its ArgoCD app; IPAM is invoked by CNI rather than an independently monitored Deployment here. Longhorn health exposes downstream failures; no synthetic allocations or claim that readiness proves IPAM correctness. |
| node-config | DaemonSet readiness; dedicated node-storage-health readiness/events retain disk quarantine and latched errors. Host configuration parity is not inferred from a sleeping pod. |

Validate with `scripts/test zabbix` and
`kubectl kustomize config/zabbix/manifests`. This PR depends on the functional
runner foundation; no production mutation is required to validate this check.
