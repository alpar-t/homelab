# Tailscale remote access

Stock Tailscale subnet router giving off-LAN access to `192.168.1.0/24`.
Replaced headscale on 2026-06-11 (headscale's TS2021 noise protocol can't be
proxied by free Cloudflare Tunnel after the HTTP 101 upgrade).

## What's deployed

- **Namespace**: `tailscale`
- **Manifests**: `config/tailscale/manifests/`
- **Pod**: single `Deployment`, pinned to buksi via `nodeSelector`
- **State**: persisted in `tailscale-state` kube secret (managed by Tailscale itself)
- **Auth key**: `tailscale-auth` secret — only consulted on first registration or
  if `tailscale-state` is wiped. After first run, disable key expiry on the
  device in the Tailscale admin console.

## Tailscale admin console

- **Machines**: `k8s-subnet-router` — should show "Expiry disabled" and "Subnets"
- **Subnet routes**: `192.168.1.0/24` must be approved (blue checkmark)
- **DNS**: global nameserver `192.168.1.202` (Pi-hole), "Override local DNS" on
- **ACL**: allow-all `{"action":"accept","src":["*"],"dst":["*:*"]}` plus
  `autoApprovers` for the subnet route via `tag:k8s-subnet-router`

## Co-location constraint (important)

The subnet router **must** run on the same node as MetalLB services with
`externalTrafficPolicy: Local` that you want reachable via Tailscale.

**Why**: kube-proxy (nftables) drops forwarded traffic in FILTER FORWARD for
Local-policy services when no local pod exists on that node. This happens
before iptables POSTROUTING runs, so Tailscale's MASQUERADE never fires.
Traffic with `externalTrafficPolicy: Cluster` works from any node (kube-proxy
DNAT routes via flannel overlay, where MASQUERADE does fire).

Currently pinned to **buksi** because Emby, Immich, and arr-stack all run
there with Local policy. If those pods move, update the `nodeSelector` in
`config/tailscale/manifests/subnet-router.yaml`.

Services on other nodes (whisper on pamacs, homeassistant-db on pamacs) use
`externalTrafficPolicy: Cluster` and work regardless of subnet router placement.

## Auth key renewal

The auth key in `tailscale-auth` has a 90-day expiry but is only consulted at
first registration. The node identity in `tailscale-state` survives indefinitely
as long as key expiry is disabled in the admin console (Machines →
k8s-subnet-router → ⋯ → Disable key expiry).

If you ever need to re-register from scratch (e.g. `tailscale-state` was
deleted):
```bash
# Via cloudflare-access-ssh.md
ssh buksi-cf
kubectl delete secret tailscale-state -n tailscale  # wipe old state
kubectl rollout restart deployment/tailscale-subnet-router -n tailscale
# New auth key may be needed if old one expired — generate in admin console
# and update the tailscale-auth secret
```

## GL-MT3000 travel router (LAN client gateway)

The GL-MT3000 (Tailscale IP `100.96.142.22`) lets devices on its WiFi reach
`192.168.1.0/24` without installing Tailscale on each device. The GL acts as a
transparent gateway — LAN clients (192.168.80.0/24) use MASQUERADE through
the GL's Tailscale tunnel to reach the home network via `k8s-subnet-router`.

### Required setup (not provided by GL.iNet's built-in Tailscale UI)

**1. Tailscale flags** — persist in `/etc/tailscale/tailscaled.state`, apply once:
```bash
tailscale up \
  --accept-routes \
  --advertise-routes=192.168.8.0/24,192.168.80.0/24 \
  --accept-dns=false
```
- `--accept-routes`: pull in `192.168.1.0/24` from k8s-subnet-router
- `--advertise-routes`: expose GL's LAN subnets to tailnet
- `--accept-dns=false`: prevent Tailscale overwriting GL's dnsmasq config

**2. MASQUERADE rule** — add to `/etc/firewall.user` (re-applied on every
firewall reload):
```bash
iptables -t nat -C postrouting_tailscale0_rule -j MASQUERADE 2>/dev/null || \
    iptables -t nat -A postrouting_tailscale0_rule -j MASQUERADE 2>/dev/null
```
Without this, LAN client source IPs (192.168.80.x) reach k8s-subnet-router
with no route back, so all connections time out.

**3. Route to home LAN** — GL.iNet's Tailscale 1.80.3 (OpenWrt) does not
auto-install kernel routes even with `--accept-routes`. Add to `/etc/rc.local`
before `exit 0`:
```bash
i=0; while [ $i -lt 60 ] && ! ip link show tailscale0 >/dev/null 2>&1; \
  do sleep 1; i=$((i+1)); done
ip route add 192.168.1.0/24 dev tailscale0 2>/dev/null || true
```

**4. DNS for LAN clients** — in GL admin → Network → DHCP → DNS server,
set `192.168.1.202` (Pi-hole). This pushes Pi-hole to clients via DHCP
option 6; clients reach it through the MASQUERADE path.

Do **not** set GL admin → Network → DNS to Pi-hole — that changes the GL
router's own upstream resolver, which cannot reach Pi-hole (the GL's own
traffic bypasses MASQUERADE and the tailscale0 zone has OUTPUT restrictions).

### Troubleshooting

```bash
# Verify route is installed on GL
ip route | grep 192.168.1

# Verify MASQUERADE rule is active
iptables -t nat -L postrouting_tailscale0_rule -n -v

# Test connectivity from GL itself (use TCP, not ping — MetalLB IPs don't respond to ICMP)
curl -sv http://192.168.1.204:8096 -o /dev/null 2>&1 | grep "< HTTP\|Connected"

# If route is missing after reboot, re-add manually
ip route add 192.168.1.0/24 dev tailscale0
```

### GL.iNet Tailscale UI limitations

- **Allow Remote Access LAN**: lets remote Tailscale peers reach GL's LAN — not the reverse.
- **Allow Remote Access WAN**: lets remote peers use GL's WAN uplink as exit node.
- Neither enables LAN clients to access remote Tailscale subnets — the MASQUERADE rule above is required for that.

## Debugging

```bash
# Status
kubectl exec -n tailscale deployment/tailscale-subnet-router -- tailscale status

# Ping a tailnet peer
kubectl exec -n tailscale deployment/tailscale-subnet-router -- tailscale ping <ip>

# Check subnet routing is advertised
kubectl exec -n tailscale deployment/tailscale-subnet-router -- ip route show table 52

# Pod logs
kubectl logs -n tailscale deployment/tailscale-subnet-router --tail=50
```
