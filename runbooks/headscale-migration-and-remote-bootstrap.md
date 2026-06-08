# Migrating off Headscale + Remote Bootstrap Access

Plan for two related changes that were paused on 2026-06-09:

1. Set up **Cloudflare Access SSH** as an independent path into the
   cluster from anywhere, so a broken VPN never locks us out again
   (and so we can bootstrap secrets while away).
2. **Tear out headscale + Pocket-ID OIDC** for VPN and replace with
   stock Tailscale, since Cloudflare Tunnel (free) cannot proxy
   headscale's TS2021 noise protocol.

These are sequenced: do step 1 first, because step 2 needs a
`kubectl create secret` for the Tailscale auth key and we can't run
that without cluster access.

---

## Why this plan exists

### The headscale problem

After a day of debugging (commits `f4fa194` → `5e78987`), we got the
nginx side of headscale clean and the noise upgrade returning HTTP 101
Switching Protocols correctly — for *both* the in-cluster subnet
router and the iPhone Tailscale app. But the iPhone still silently
hangs on "Log in" with the custom server.

Root cause confirmed via blog post + GitHub issues:

- Cloudflare Tunnel (free tier) only proxies HTTP/1.1, HTTP/2, and
  WebSockets cleanly.
- Headscale's TS2021 noise protocol does the initial HTTP/1.1
  Upgrade, gets a 101, then turns into a bidirectional binary
  stream framed as gRPC-over-HTTP/2. **Cloudflare Tunnel free
  doesn't proxy that bidirectional stream**, so no useful bytes
  flow after the upgrade.
- iOS Tailscale [silently hangs](https://github.com/tailscale/tailscale/issues/18494)
  in exactly this scenario (no error, no spinner).

So our nginx workaround (re-injecting the `Upgrade:
tailscale-control-protocol` header that Cloudflare strips on
HTTP/2-negotiated connections, for path `/ts2021`) is necessary but
not sufficient. The 101 succeeds; the noise channel does not.

Workarounds that don't require giving up Cloudflare for ingress:

- Pay for Cloudflare Zero Trust (gRPC support)
- Expose headscale directly (needs static IP / port forward)
- VPS as TCP relay

All rejected. Pragmatic answer: **drop headscale, use stock
Tailscale**, which avoids the noise-protocol-through-proxy problem
entirely (clients talk directly to controlplane.tailscale.com).

### The chicken-and-egg

We can't bootstrap a new Tailscale subnet router without creating a
k8s secret (`tailscale-auth`). We can't `kubectl create secret`
without cluster access. We don't have cluster access from off-LAN —
which is exactly the problem the VPN was supposed to solve.

Cloudflare Access SSH breaks the loop: it tunnels SSH through the
existing cloudflared infrastructure, gated by the same Google login
we already use for argocd.newjoy.ro, with no inbound ports and no
VPN.

---

## Part 1 — Cloudflare Access SSH (bootstrap unblock)

This gives us a permanent off-LAN escape hatch into the cluster,
independent of any VPN. It also makes future bootstrap problems
(creating any new secret, recovering a node, etc.) tractable from
anywhere.

### Cloudflare side (one-time, via dashboard)

1. **Zero Trust → Access → Applications → Add an application →
   Self-hosted**
   - Application name: `SSH (homelab nodes)`
   - Session duration: `24 hours` (matches argocd policy)
   - Public hostname: `ssh.newjoy.ro`
2. **Add policy**
   - Name: `Allow Me`
   - Action: `Allow`
   - Include: `Emails → alpar.torok@elastic.co` (or whichever Google
     identity already works for argocd.newjoy.ro)
3. **Additional settings → Browser rendering** off, **CORS** off,
   **HTTP only** off — defaults are fine for SSH.

### Cluster side (in this repo)

Add an ingress rule to cloudflared. Edit
`config/cloudflare-tunnel/manifests/configmap.yaml`:

```yaml
data:
  config.yaml: |
    tunnel: YOUR_TUNNEL_ID
    credentials-file: /etc/cloudflared/creds/credentials.json
    metrics: 0.0.0.0:2000
    no-autoupdate: true

    ingress:
      # SSH access via Cloudflare Access — gated by Google login.
      # Use `cloudflared access ssh --hostname ssh.newjoy.ro --user core`
      # from any workstation. See runbooks/headscale-migration-and-
      # remote-bootstrap.md.
      - hostname: ssh.newjoy.ro
        service: ssh://buksi.local:22

      # Route all other traffic to ingress-nginx
      - service: http://ingress-nginx-controller.ingress-nginx.svc.cluster.local:80
```

Notes:

- `buksi.local` resolves via mDNS *inside the cluster* (k3s nodes can
  resolve each other's `.local` names). If that turns out to be
  flaky, hardcode `192.168.1.174:22` instead.
- We pick a single node deliberately. Round-robin across multiple
  nodes would interact badly with SSH host-key pinning.
- Cloudflared will reload automatically (Reloader annotation already
  in place — added in commit `a26bef0`).

### Workstation side (any device, anywhere)

One-time install:

```bash
brew install cloudflared   # macOS
# or: see https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
```

Per-session:

```bash
cloudflared access ssh --hostname ssh.newjoy.ro --user core
```

First time this prompts for a Cloudflare Access login in the
browser; subsequent calls within the session duration are silent.
The SSH stream tunnels through Cloudflare, terminating at
buksi:22.

Optional — make it ergonomic by editing `~/.ssh/config`:

```
Host buksi-cf
    HostName ssh.newjoy.ro
    User core
    ProxyCommand cloudflared access ssh --hostname %h
```

Then just: `ssh buksi-cf`. Use this from anywhere, including from
the iPhone via Termius / Blink.

### Verification

```bash
ssh buksi-cf
# should land on buksi as core
sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml kubectl get nodes
# all three nodes Ready
```

---

## Part 2 — Tear out headscale, deploy stock Tailscale

Do this *after* Part 1 is verified working (you need SSH to create
the secret). Pocket-ID OIDC stays in place — it's still used by
every other app. We're only removing the headscale-specific OIDC
client.

### Pre-work: get a Tailscale auth key

1. Sign up at https://login.tailscale.com (free, picks any identity
   provider — Google is fine, can be the same Google account used for
   Pocket-ID).
2. **Admin console → Settings → Keys → Generate auth key**
   - Reusable: yes
   - Ephemeral: no
   - Pre-approved: yes (skip device approval on the subnet router)
   - Tags: `tag:k8s-subnet-router`
   - Expiration: 90 days (renewal calendar reminder needed; OAuth
     client credentials are the alternative if we want no-expiry)
3. Save the `tskey-auth-...` value somewhere temporarily (Bitwarden,
   not git).
4. **Admin console → Access controls → ACLs**, add the tag definition:
   ```json
   "tagOwners": {
     "tag:k8s-subnet-router": ["autogroup:admin"]
   },
   "autoApprovers": {
     "routes": {
       "192.168.1.0/24": ["tag:k8s-subnet-router"]
     }
   }
   ```
   (Same approach as we had in headscale — auto-approve the LAN route
   for the tagged subnet-router node.)

### Bootstrap the secret (via Part 1 SSH)

```bash
ssh buksi-cf
sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml kubectl create namespace tailscale
sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml kubectl create secret generic tailscale-auth \
  --namespace=tailscale \
  --from-literal=authkey=tskey-auth-XXXXXXXXXXXXXXXXX
```

### Repo changes

1. **Create `config/tailscale/manifests/`** with just the subnet
   router (deployment + serviceaccount, similar to today's
   `config/headscale/manifests/subnet-router.yaml`) but:
   - Namespace: `tailscale` (new)
   - No `TS_EXTRA_ARGS=--login-server=...` (default = stock
     Tailscale)
   - No `TS_KUBE_SECRET=""` (we want the default kube secret
     behavior; in fact for stock Tailscale you want this *enabled*
     for state, but only if RBAC permits — easier to keep
     emptyDir + `TS_STATE_DIR=/var/lib/tailscale`)
   - `TS_AUTHKEY` from the new `tailscale-auth` secret in the new
     namespace
   - `TS_ROUTES=192.168.1.0/24` (same as today)
   - `TS_HOSTNAME=k8s-subnet-router`
2. **Create `apps/tailscale.yaml`** ArgoCD Application pointing at
   `config/tailscale/manifests`.
3. **Delete `apps/headscale.yaml`** and `apps/homeassistant-db.yaml`
   is independent so leave it alone — only `apps/headscale.yaml`
   goes.
4. **Delete `config/headscale/`** entirely.
5. **Pocket-ID admin UI:** delete the `Headscale VPN` OIDC client
   (client ID `a3ffe55a-f7ba-4562-b8f9-87e6e62b5a03` per
   `config/headscale/README.md`). Don't touch any other clients.
6. **Cloudflare DNS / Tunnel:** the `vpn.newjoy.ro` hostname can
   either be deleted from the wildcard DNS (it's already covered)
   or repurposed. There's no per-hostname cloudflared rule for it,
   so nothing to delete in the configmap.
7. **CLAUDE.md:** remove the entry that says "headscale TODO" if
   any, and update `Plan.md` (see below).
8. **runbooks/** consider deleting this runbook once Part 2 is done,
   or repurposing it as a "stock Tailscale operational notes" file.

### Per-device setup

- **iPhone:** Install Tailscale from the App Store, sign in with the
  chosen identity provider. Done.
- **Mac / Linux:** `brew install tailscale && sudo tailscale up`.
- **GL.iNet GL-MT3000:** already on Tailscale per CLAUDE.md — verify
  it's on the same tailnet as the new one. If it's a separate
  account, decide whether to consolidate.

### What we lose vs headscale

- Control plane is hosted by Tailscale, not us. We accept this in
  exchange for "actually working on iOS through Cloudflare."
- Auth isn't through Pocket-ID anymore. Each user logs in with
  whatever identity provider they pick on tailscale.com. For a
  3-person max free-tier homelab, this is fine.
- No more `vpn.newjoy.ro` URL. Devices use Tailscale's MagicDNS for
  device-to-device names, and the existing `*.newjoy.ro` (via
  Cloudflare) for service access stays unchanged.

### Cleanup verification

```bash
# All from buksi-cf SSH (Part 1):
kubectl get pods -A | grep -E 'headscale|tailscale'
# expect: only tailscale-subnet-router pod, no headscale anything

kubectl get pvc -n headscale
# expect: namespace gone

kubectl get applications -n argocd
# expect: no `headscale` application

# From iPhone Tailscale, browse to a service on 192.168.1.x (e.g.,
# 192.168.1.202 for pihole) — should work via the subnet router.
```

---

## Open items for when we resume

- Decide whether to keep the nginx `/ts2021` Upgrade-injection
  snippet around in some form (it's correct and would matter if we
  ever go back to headscale). Currently it's in
  `config/headscale/manifests/ingress.yaml` which gets deleted as
  part of Part 2.
- The debug-level log on the current headscale deployment
  (`config/headscale/manifests/configmap.yaml`, `log.level: debug`)
  is moot once we delete it, but if we ever resurrect headscale for
  another reason, revert that to `info` first.
- The travel router setup (GL-MT3000 + Brovi SIM) is currently
  documented as "Connected to homelab via Tailscale" in CLAUDE.md.
  Verify which tailnet it's on once Part 2 is done.
