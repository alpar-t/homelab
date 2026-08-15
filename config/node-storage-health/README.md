# Node storage health

The `node-storage-health` DaemonSet runs one collector on every node. Its single
readiness signal covers the physical storage conditions that can endanger CNPG
local PVCs or Longhorn data:

- `/var` block usage, absolute free space, and inode usage;
- NVMe SMART critical warnings, temperature, available spare, wear, media
  errors, and error-log entries;
- SATA SMART overall health, temperature, pending sectors, reallocated sectors,
  uncorrectable errors, reported errors, and interface CRC errors.

The collector uses `smartctl` from the pinned
`prometheuscommunity/smartctl-exporter` image but does not require Prometheus.
It ignores Longhorn's `VIRTUAL-DISK` devices and checks the host's physical
NVMe/SATA devices directly.

SMART counters are cumulative. On first observation their current values are
stored under `/var/lib/node-storage-health/`; only later increases cause an
alert. An increased counter remains latched until it has been investigated and
its corresponding `*.baseline` file is removed. The next check adopts the new
value as its baseline.

Inspect health with:

```bash
kubectl -n node-config get daemonset/node-storage-health
kubectl -n node-config get pods -l app.kubernetes.io/name=node-storage-health -o wide
kubectl -n node-config logs -l app.kubernetes.io/name=node-storage-health --tail=20
kubectl -n node-config describe pod <unready-pod>
```

Thresholds are intentionally conservative:

| Signal | Warning | Critical |
|---|---:|---:|
| `/var` or inode usage | 75% | 85% |
| `/var` absolute free space | 100 GiB | 50 GiB |
| Physical-drive temperature | 65 C | 75 C |
| NVMe percentage used | 80% | 95% |

Any NVMe critical-warning bit, SMART overall-health failure, current pending
sector, unreadable physical drive, or increase in NVMe media errors is critical.
Other newly increased SMART error counters are warnings. Both warning and
critical states make that node's collector pod NotReady so the Baloo
`cluster-health` job can page with the probe's exact status.
