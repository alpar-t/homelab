# Node memory OOM incident, 2026-10-19

## What happened

At 17:00 UTC Pufi's kernel reported a **system OOM** and killed Omada's Java
process while it was below its 2560 MiB container limit. At 17:24 UTC Pamacs
reported a system OOM and killed a Longhorn instance manager; Pamacs then
restarted k3s. Buksi had no recorded `SystemOOM` event, but after workloads
rescheduled to it, memory pressure stalls became severe and k3s exited at
17:42 UTC, then restarted. All three nodes subsequently reported Ready. A
Ready node is not proof of memory headroom: Buksi had under 1 GiB available
and spent more than 20% of wall time in full memory stalls during the incident.

Pod memory limits protect against a *single* pod growing without bound. They
do not reserve the sum of those limits on a node. Scheduling uses requests;
several measured heavy workloads requested much less memory than they used.
Longhorn instance managers have no memory request in this deployment and used
roughly 1–3 GiB per node. k3s and the OS also need room. The live Buksi
kubelet reported no `KubeReserved` or `SystemReserved` memory. Its default
`evictionHard` contained only the two disk thresholds, so kubelet had no memory
threshold at which to evict a pod before the kernel OOM. The node budget must
explicitly leave room for k3s, Longhorn, and the OS.

## Source changes and rollout

- Raise requests for Immich Server to 2560 MiB, Immich ML to 2560 MiB,
  Frigate to 2 GiB, and Omada to 1536 MiB. Keep their existing hard limits.
- Run one Immich ML replica at ordinal 2, preserving its model-cache PVC.
  Prefer Pamacs with soft node affinity; the pod can run on a 16 GiB node if
  Pamacs is unavailable. The idle cache PVCs for ordinals 0 and 1 are retained.
  This reduces parallel ML capacity, so check Immich's ML jobs after rollout.
- Softly prefer Pamacs for the Interior Designer UI, which was stranded on
  Buksi after the Pamacs reboot. Its RWO PVC must be healthy before rollout.
- Softly prefer Pufi for Frigate after removing its ML replica. The Immich
  Server rollout also preferred Pamacs, so moving Frigate's 2 GiB request to
  Pufi brings Pamacs below 85% of its new allocatable memory. Frigate remains
  movable if Pufi is unavailable; verify the iGPU and RWO volumes after moving.
- Zabbix warns at 85% node memory use and discovers recent Kubernetes
  `SystemOOM` node events through read-only Event access in `default`.
- `config/node-config/k3s-memory.yaml` adds `memory.available<1Gi` to each
  node's kubelet hard eviction thresholds while retaining K3s's existing
  `imagefs.available<5%` and `nodefs.available<5%` thresholds. The Ignition
  template carries the same setting for replacement nodes.

Do not restart PVC-backed workloads while Longhorn volumes are degraded after
an OOM/reboot. Before applying the workload changes, verify all three nodes
are Ready, Longhorn volumes used by the affected pods are healthy, and at least
2 GiB of host memory is available on each node. Check projected memory requests
after the change as well: keep each node below 85% of allocatable so k3s,
Longhorn, and the OS retain space. A two-replica ML request increase would
leave Buksi near 97% with the incident's pod placement; one replica on Pamacs
plus the Interior Designer move keeps all three nodes within the admission
budget on Buksi. Tandoor was stranded on Pufi with a 512 MiB request; after
its PVC is healthy, recreate that pod so its existing soft preference moves
it to Pamacs. This brings Pufi below 85% of its post-eviction allocatable
memory. The StatefulSet template
change restarts the retained ML pod; verify it is Ready on Pamacs. Check
scheduling failures, ML job throughput, and node memory after each rollout.
Stop if a node OOM recurs.

Pamacs's soft placement preference does not move pods back automatically after
it recovers. If heavy movable pods are stranded on Buksi or Pufi, move them
back in a controlled rollout after their PVCs are healthy. Do not hard pin
them: they must still run when Pamacs is unavailable. Check GPU allocation
before moving Whisper, Frigate, or Immich ML.

Install the kubelet setting one node at a time after Longhorn is healthy. The
K3s configuration is absent on all three existing nodes, so do not overwrite
other server flags or the cluster token in the systemd unit. Copy the YAML to
`/etc/rancher/k3s/config.yaml` on Pufi, then Pamacs, then Buksi, restarting
`k3s` on each and verifying `Ready`, application pods, and Longhorn robustness
before continuing. Buksi serves the workstation's API endpoint, so do it last.
After each restart, check k3s startup logs for `evictionHard` containing the
1 GiB memory threshold and confirm node allocatable memory fell by 1 GiB.
Stop if node readiness, storage, or API health degrades. Kubelet eviction is a
last resort; raising pod requests and reducing the ML footprint remain necessary
to avoid routine evictions.

Useful checks:

```bash
kubectl top nodes
kubectl describe nodes
kubectl get events -A --field-selector reason=SystemOOM -o wide
kubectl -n longhorn-system get volumes.longhorn.io
kubectl -n immich get pods -o wide
```
