# Pi-hole DNS Redundancy

This runbook documents options for making DNS resilient in the homelab.

## The Problem

Pi-hole runs as a single instance:

```yaml
# config/pihole/manifests/deployment.yaml
replicas: 1
```

If the Pi-hole pod fails, restarts, or the node goes down:
- **All DNS resolution fails** for devices on the network
- Smart home devices, phones, laptops lose internet access
- Recovery requires pod to reschedule and start (30s-2min)

---

## Options

### Option 1: Fallback DNS in DHCP (Simplest) ✅ Recommended

Configure your DHCP server to provide two DNS servers:
1. **Primary**: Pi-hole (e.g., `192.168.1.53`)
2. **Secondary**: Public DNS (e.g., `1.1.1.1` or `8.8.8.8`)

**How it works:**
- Clients try primary first
- If primary times out (~5s), clients fall back to secondary
- No Pi-hole filtering during fallback, but internet works

**Implementation (Omada Controller):**

1. Go to **Settings → Wired Networks → LAN → DHCP Server**
2. Set:
   - Primary DNS: `192.168.1.53` (Pi-hole)
   - Secondary DNS: `1.1.1.1` (Cloudflare)
3. Save and wait for DHCP leases to renew

**Pros:**
- Zero additional infrastructure
- Simple to implement
- Works immediately

**Cons:**
- Fallback DNS has no ad-blocking
- ~5s delay before failover on each DNS query
- Some devices may prefer secondary DNS (bypassing Pi-hole)

---

### Option 2: Two Pi-hole Instances with Gravity Sync

Run two Pi-hole instances that sync their configuration.

**Architecture:**
```
┌─────────────────┐     ┌─────────────────┐
│  Pi-hole #1     │────▶│  Pi-hole #2     │
│  192.168.1.53   │◀────│  192.168.1.54   │
│  (Primary)      │sync │  (Secondary)    │
└─────────────────┘     └─────────────────┘
         │                      │
         └──────────┬───────────┘
                    │
              DHCP provides both
```

**Tools for syncing:**
- [Gravity Sync](https://github.com/vmstan/gravity-sync) - Bash script, syncs via SSH
- [Orbital Sync](https://github.com/mattwebbio/orbital-sync) - Docker container, syncs via API

**Implementation with Orbital Sync:**

1. **Create second Pi-hole deployment:**

```yaml
# config/pihole/manifests/deployment-secondary.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: pihole-secondary
  namespace: pihole
spec:
  replicas: 1
  # ... same config as primary but different name ...
```

2. **Create LoadBalancer service for secondary:**

```yaml
apiVersion: v1
kind: Service
metadata:
  name: pihole-dns-secondary
  namespace: pihole
spec:
  type: LoadBalancer
  loadBalancerIP: 192.168.1.54  # Different IP from primary
  selector:
    app: pihole-secondary
  ports:
    - name: dns-tcp
      port: 53
      targetPort: 53
      protocol: TCP
    - name: dns-udp
      port: 53
      targetPort: 53
      protocol: UDP
```

3. **Deploy Orbital Sync:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: orbital-sync
  namespace: pihole
spec:
  replicas: 1
  selector:
    matchLabels:
      app: orbital-sync
  template:
    metadata:
      labels:
        app: orbital-sync
    spec:
      containers:
        - name: orbital-sync
          image: mattwebbio/orbital-sync:latest
          env:
            - name: PRIMARY_HOST_BASE_URL
              value: "http://pihole.pihole.svc.cluster.local"
            - name: PRIMARY_HOST_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: pihole-password
                  key: password
            - name: SECONDARY_HOST_1_BASE_URL
              value: "http://pihole-secondary.pihole.svc.cluster.local"
            - name: SECONDARY_HOST_1_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: pihole-password
                  key: password
            - name: INTERVAL_MINUTES
              value: "30"
```

4. **Update DHCP to provide both IPs**

**Pros:**
- True redundancy with ad-blocking on both
- Automatic failover
- Configuration stays in sync

**Cons:**
- More resources (2 Pi-hole pods + sync pod)
- More complexity to manage
- Need second MetalLB IP

---

### Option 3: Pi-hole with Pod Anti-Affinity + Fast Restart

Keep single instance but ensure fast recovery:

1. **Add pod disruption budget:**

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: pihole
  namespace: pihole
spec:
  minAvailable: 1
  selector:
    matchLabels:
      app: pihole
```

2. **Reduce startup time:**
   - Use smaller PVC (already 1Gi ✅)
   - Ensure node has capacity

3. **Add priority class:**

```yaml
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: dns-critical
value: 1000000
globalDefault: false
description: "Critical DNS services"
---
# In deployment:
spec:
  template:
    spec:
      priorityClassName: dns-critical
```

**Pros:**
- Simple, single instance
- Pi-hole gets scheduling priority

**Cons:**
- Still has downtime during node failure
- Not true redundancy

---

## Recommendation

For a homelab, **Option 1 (Fallback DNS in DHCP)** is the best trade-off:

| Factor | Option 1 | Option 2 | Option 3 |
|--------|----------|----------|----------|
| Complexity | Low | High | Low |
| Resources | None | +2 pods | None |
| True HA | No | Yes | No |
| Ad-blocking during failure | No | Yes | No |
| Implementation time | 5 min | 1-2 hours | 15 min |

**Downtime impact with Option 1:**
- Pi-hole failure: 5-second delay per DNS query, then public DNS used
- This is acceptable for most home use cases

---

## Implementation Checklist

### For Option 1 (Recommended):

- [ ] Log into Omada Controller
- [ ] Navigate to Settings → Wired Networks → LAN
- [ ] Edit DHCP settings
- [ ] Set Secondary DNS to `1.1.1.1` or `8.8.8.8`
- [ ] Save and apply
- [ ] Test: Stop Pi-hole pod, verify DNS still works (with delay)
- [ ] Restart Pi-hole pod

### Verification:

```bash
# On a client machine after DHCP renewal
cat /etc/resolv.conf
# Should show both DNS servers

# Test failover
kubectl scale deployment pihole -n pihole --replicas=0
# Wait 10s, then try DNS resolution - should work via fallback

kubectl scale deployment pihole -n pihole --replicas=1
```

---

## Related

- [config/pihole/README.md](../config/pihole/README.md) - Pi-hole configuration
- [config/metallb/README.md](../config/metallb/README.md) - LoadBalancer IPs




