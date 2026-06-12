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
