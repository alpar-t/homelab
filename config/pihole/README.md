# Pi-hole - Network-wide Ad Blocking

Pi-hole deployed as a DaemonSet for high availability DNS across all nodes.

## Architecture

```
Local Network:
  Devices → Router DNS (node IPs:30053) → Pi-hole DaemonSet

Web UI:
  Browser → pihole.newjoy.ro → Authentik SSO → Pi-hole Admin
```

## Components

| Component | Purpose | HA Strategy |
|-----------|---------|-------------|
| Pi-hole DaemonSet | DNS + Ad blocking | Runs on every node |
| DNS Service (NodePort 30053) | Local network DNS | Available on all nodes |
| Web UI Ingress | Admin interface | Via Authentik SSO |

## Access

- **Web UI:** https://pihole.newjoy.ro (protected by Authentik SSO)
- **Local DNS:** Any node IP on port 30053

## Setup

### 1. Configure Authentik (Required for Web UI)

1. **Create Provider** in Authentik Admin:
   - Go to: Applications → Providers → Create
   - Type: **Proxy Provider**
   - Name: `pihole-proxy`
   - Mode: **Proxy**
   - External host: `https://pihole.newjoy.ro`
   - Internal host: `http://pihole-web.pihole.svc.cluster.local:80`

2. **Create Application**:
   - Go to: Applications → Applications → Create
   - Name: `Pi-hole`
   - Slug: `pihole`
   - Provider: select `pihole-proxy`
   - Icon (optional): `https://pi-hole.net/wp-content/uploads/2016/12/Vortex-R.png`

3. **Add to Outpost**:
   - Go to: Applications → Outposts → authentik Embedded Outpost
   - Add `Pi-hole` to Applications
   - Click Update

Pi-hole has no internal password - Authentik handles all authentication.

### 2. Configure Local Network DNS

Configure your router to use Pi-hole as DNS. For HA, add all node IPs:

```
Primary DNS:   192.168.x.10:30053  (node 1)
Secondary DNS: 192.168.x.11:30053  (node 2)
Tertiary DNS:  192.168.x.12:30053  (node 3)
```

Replace with your actual node IPs. Most routers only support 2 DNS servers.

**Note:** If your router doesn't support custom ports, you may need to run Pi-hole on port 53 using `hostNetwork: true` (edit the DaemonSet).

## Mobile Access (Future)

For iOS/Android access outside the home network, consider:
- **WireGuard VPN** - Route all traffic through homelab (most secure)
- **Tailscale** - Easier setup, mesh VPN

These options route DNS through Pi-hole without exposing it publicly.

## Troubleshooting

### Check Pi-hole pods

```bash
kubectl get pods -n pihole -o wide
kubectl logs -n pihole -l app=pihole
```

### Test DNS resolution

```bash
# From a node
dig @localhost -p 30053 google.com

# Or using node IP from your workstation
dig @<node-ip> -p 30053 google.com
```

### Check query logs

Access the web UI at https://pihole.newjoy.ro and check Query Log.

## Notes

- Pi-hole runs on every node as a DaemonSet for high availability
- DNS is exposed via NodePort 30053 - configure your router to use node IPs
- Web UI is SSO-protected via Authentik - no separate Pi-hole password
- Data is ephemeral (emptyDir) - custom blocklists need reconfiguration after pod restart

## Adding Custom Blocklists

Via the web UI:
1. Go to https://pihole.newjoy.ro
2. Settings → Adlists → Add new
3. Popular lists: https://firebog.net/
