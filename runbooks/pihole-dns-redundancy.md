# Pi-hole DNS Redundancy

Operational runbook for the Pi-hole hot-spare DNS setup. Architecture
is documented in [config/pihole/README.md](../config/pihole/README.md);
this file covers verification, failover testing, and recovery.

## Current setup (as deployed)

Two Pi-hole Deployments share one MetalLB LoadBalancer IP:

- `pihole` and `pihole-2` in namespace `pihole`, each `replicas: 1`
- Pod anti-affinity (`topologyKey: kubernetes.io/hostname`) keeps them
  on different nodes
- Service `pihole-dns` exposes `192.168.1.202` with
  `externalTrafficPolicy: Local`, so MetalLB only routes traffic to
  the node currently hosting a ready pod — the other instance sits as
  a hot spare
- Each instance has its own `local-ssd` PVC; data (blocklists, query
  logs) is rebuildable, no sync required
- Custom DNS entries and dnsmasq config live in shared ConfigMaps
  (`pihole-custom-dns`, `pihole-dnsmasq`) so both instances stay
  configuration-aligned via GitOps

DHCP on the Omada controller hands out `192.168.1.202` as the
primary DNS. No public-DNS fallback is configured — failover is
handled inside the cluster by MetalLB rerouting to the standby.

## Verify the setup is healthy

```bash
# Both pods Running on different nodes
kubectl get pods -n pihole -o wide -l app=pihole

# Service has both pods as endpoints
kubectl get endpoints pihole-dns -n pihole

# DNS resolves via the LB IP
dig @192.168.1.202 google.com +short
```

If only one endpoint is listed, the standby is unhealthy — check pod
status and node scheduling before relying on failover.

## Test failover

```bash
# Identify the active pod (the one on the MetalLB-announcing node;
# easiest signal is which one has recent query log activity)
kubectl logs -n pihole -l app=pihole --tail=20 --prefix

# Kill the active pod
kubectl delete pod -n pihole <active-pod-name>

# DNS should keep resolving immediately (standby takes over)
dig @192.168.1.202 google.com +short
```

Expected: brief blip (sub-second to a few seconds depending on which
node MetalLB picks next), then resolution continues. If `dig` hangs
for more than ~10s, the standby isn't picking up traffic — check
`externalTrafficPolicy` on the service and that the standby pod is
`Ready`.

## Both instances down (recovery)

If both nodes hosting Pi-hole are unhealthy, DNS resolution stops for
the LAN. Quick recovery options, in order of preference:

1. **Reschedule:** `kubectl get pods -n pihole -o wide` — if pods are
   `Pending`, a node is unschedulable. Cordon/uncordon or fix the
   node and pods will start.
2. **Temporary public DNS on the router:** in Omada, set primary DNS
   to `1.1.1.1` (you'll lose ad-blocking until Pi-hole is back). Roll
   back once `kubectl get endpoints pihole-dns -n pihole` shows
   endpoints again.
3. **Direct dig from a workstation:** `dig @1.1.1.1 ...` will work
   even if LAN DNS is broken.

## Adding/changing custom DNS entries

Edit `config/pihole/manifests/custom-dns-configmap.yaml`, push to git,
ArgoCD syncs the ConfigMap, Reloader restarts both Pi-holes.
ConfigMap is shared → both instances get the change.

## Why this design (decision log)

- **One IP, hot spare via `externalTrafficPolicy: Local`** rather
  than two IPs + sync (Gravity Sync / Orbital Sync): no second IP for
  DHCP to manage, real client IPs preserved in query logs, no sync
  daemon to fail. Trade-off: standby's query log is empty until
  failover, and downloaded blocklists are duplicated per instance.
- **Local SSD storage** rather than Longhorn: faster restarts, no
  attach/detach overhead. Data is rebuildable so per-instance loss
  is fine.
- **No public-DNS fallback in DHCP**: would defeat ad-blocking on
  every query (clients prefer whichever responds faster). Cluster
  failover is fast enough that we don't need it.

## Related

- [config/pihole/README.md](../config/pihole/README.md) — architecture
  diagram, components, mobile/VPN access
- [config/metallb/README.md](../config/metallb/README.md) —
  LoadBalancer IP allocation
