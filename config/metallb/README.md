# MetalLB - Bare Metal Load Balancer

MetalLB provides LoadBalancer service support for bare-metal Kubernetes clusters.

## Why MetalLB?

In cloud environments (AWS, GCP, Azure), Kubernetes `type: LoadBalancer` services automatically get external IPs. On bare metal, these services stay "Pending" forever. MetalLB fills this gap.

## How It Works (Layer 2 Mode)

```
┌─────────────────────────────────────────────────────────────────┐
│                        Your LAN                                 │
│                                                                 │
│   ┌──────────────┐                    ┌──────────────────────┐  │
│   │ Home         │     ARP: Who has   │ Kubernetes Cluster   │  │
│   │ Assistant    │     192.168.1.200? │                      │  │
│   │              │ ──────────────────►│ MetalLB: "I do!"     │  │
│   │              │                    │                      │  │
│   │              │ ◄──────────────────│ Routes to Service    │  │
│   │              │   Traffic flows    │                      │  │
│   └──────────────┘                    └──────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

1. You define a pool of IPs from your LAN (e.g., 192.168.1.200-220)
2. When a LoadBalancer service is created, MetalLB assigns an IP
3. MetalLB responds to ARP requests for that IP
4. Traffic is routed to the appropriate service

## Installation

MetalLB is installed via ArgoCD. See `apps/metallb.yaml`.

The ArgoCD application deploys:
1. MetalLB Helm chart (controller + speakers)
2. Configuration manifests from `config/metallb/manifests/`

## Configuration

### Files

```
config/metallb/
├── README.md
└── manifests/
    ├── ipaddresspool.yaml   # IP range for LoadBalancer services
    └── l2advertisement.yaml  # Enable Layer 2 mode
```

### IP Address Pool

Edit `manifests/ipaddresspool.yaml` to set your IP range:

```yaml
spec:
  addresses:
  - 192.168.1.200-192.168.1.220  # ← Adjust for your network!
```

**Important:** These IPs must be:
- On your LAN subnet
- Outside your MikroTik DHCP range
- Not used by other devices

### MikroTik DHCP Adjustment

If your DHCP pool is currently `192.168.1.100-254`, change it to end at `.199`:

```
/ip pool set [find name=dhcp_pool] ranges=192.168.1.100-192.168.1.199
```

Or via Winbox: IP → Pool → Edit your pool → Set range to end before MetalLB range

## Usage

Once configured, any LoadBalancer service gets an IP automatically:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: my-service
spec:
  type: LoadBalancer
  ports:
  - port: 5432
    targetPort: 5432
  selector:
    app: my-app
```

Check assigned IP:

```bash
kubectl get svc my-service
# NAME         TYPE           CLUSTER-IP     EXTERNAL-IP     PORT(S)
# my-service   LoadBalancer   10.43.x.x      192.168.1.200   5432:3xxxx/TCP
```

### Request Specific IP

```yaml
metadata:
  annotations:
    metallb.universe.tf/loadBalancerIPs: 192.168.1.205
```

## Current Usage

| Service | IP | Port | Purpose |
|---------|-----|------|---------|
| homeassistant-db-external | 192.168.1.200 | 5432 | PostgreSQL for HA Green |
| immich-server-lan | 192.168.1.203 | 2283 | Immich LAN access (bypasses Cloudflare 100MB limit) |

## IP Planning

Suggested allocation for your homelab:

| Range | Purpose |
|-------|---------|
| 192.168.1.1-199 | DHCP / Static devices |
| 192.168.1.200-220 | MetalLB pool |
| 192.168.1.200 | Home Assistant DB |
| 192.168.1.201 | Paperless FTP |
| 192.168.1.202 | Pi-hole DNS |
| 192.168.1.203 | Immich LAN (large uploads) |
| 192.168.1.204+ | (reserved for future) |

**Adjust based on your network configuration!**

## Troubleshooting

### Service Stuck in Pending

```bash
# Check MetalLB pods
kubectl get pods -n metallb-system

# Check for events
kubectl describe svc <service-name>

# Check IPAddressPool
kubectl get ipaddresspool -n metallb-system

# Check MetalLB speaker logs
kubectl logs -n metallb-system -l component=speaker
```

### IP Not Reachable

```bash
# Check L2Advertisement exists
kubectl get l2advertisement -n metallb-system

# Check which node is advertising the IP
kubectl logs -n metallb-system -l component=speaker | grep "announcing"

# Verify ARP from another machine
arp -a | grep 192.168.1.200
```

### IP Conflicts

If the IP was previously used by another device:
1. Clear ARP cache on your router/devices
2. Wait a few minutes for ARP to expire
3. Or choose a different IP

## Layer 2 vs BGP

| Mode | Use Case | Requirements |
|------|----------|--------------|
| **Layer 2** ✅ | Home networks, simple setup | Nothing special |
| **BGP** | Large networks, multi-router | BGP-capable router |

For homelabs, Layer 2 is the right choice.

## Limitations

- **Single node answers ARP**: Only one node handles traffic for a given IP at a time
- **Failover delay**: If that node dies, ~10 seconds for another to take over
- **Same subnet**: LoadBalancer IPs must be on the same subnet as nodes

These are fine for homelab use.

## Related Documentation

- [MetalLB Official Docs](https://metallb.io/)
- [MetalLB Layer 2 Mode](https://metallb.io/concepts/layer2/)

