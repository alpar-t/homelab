# Cloudflare Tunnel + Access Setup

This guide sets up:
- **Ingress Controller** - Routes traffic inside the cluster
- **Cloudflare Tunnel** - Exposes services to internet without opening ports
- **Cloudflare Access** - SSO/auth for internal apps (Google login)

## Prerequisites

- Domain you control (e.g., `newjoy.ro`)
- Cloudflare account (free tier works)

---

## Part 1: Cloudflare Account Setup

### 1.1 Create Cloudflare Account

1. Go to https://dash.cloudflare.com/sign-up
2. Create account with your email
3. Verify email

### 1.2 Add Your Domain

1. In Cloudflare dashboard, click **Add a Site**
2. Enter your domain (e.g., `newjoy.ro`)
3. Select **Free** plan
4. Cloudflare will scan existing DNS records
5. Update your domain registrar's nameservers to Cloudflare's (shown after scan)
   - Usually something like `ada.ns.cloudflare.com` and `bob.ns.cloudflare.com`
6. Wait for nameserver propagation (can take up to 24h, usually faster)

### 1.3 Create API Token

1. Go to **My Profile** → **API Tokens** (https://dash.cloudflare.com/profile/api-tokens)
2. Click **Create Token**
3. Use **Create Custom Token**:
   - Token name: `homelab-tunnel`
   - Permissions:
     - Account → Cloudflare Tunnel → Edit
     - Account → Access: Apps and Policies → Edit
     - Zone → DNS → Edit
   - Account Resources: Include → Your account
   - Zone Resources: Include → Specific zone → `newjoy.ro`
4. Click **Continue to summary** → **Create Token**
5. **Save the token** - you won't see it again!

---

## Part 2: Create Cloudflare Tunnel

### 2.1 Install cloudflared CLI (on your workstation)

```bash
# macOS
brew install cloudflared

# Linux
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o cloudflared
chmod +x cloudflared
sudo mv cloudflared /usr/local/bin/
```

### 2.2 Authenticate cloudflared

```bash
cloudflared tunnel login
```

This opens a browser - select your domain and authorize.

### 2.3 Create the Tunnel

```bash
# Create tunnel
cloudflared tunnel create homelab

# Note the Tunnel ID and credentials file path shown
# e.g., Tunnel credentials written to /Users/you/.cloudflared/abc123.json
```

### 2.4 Get Tunnel Credentials

```bash
# Show your tunnel ID
cloudflared tunnel list

# The credentials file is at ~/.cloudflared/<TUNNEL_ID>.json
cat ~/.cloudflared/<TUNNEL_ID>.json
```

### 2.5 Create Kubernetes Secret

```bash
# Create namespace first
kubectl create namespace cloudflared

# Create secret from credentials file
kubectl create secret generic tunnel-credentials \
  --namespace=cloudflared \
  --from-file=credentials.json=$HOME/.cloudflared/<TUNNEL_ID>.json
```

### 2.6 Configure DNS

Route your domains through the tunnel:

```bash
# For internal apps
cloudflared tunnel route dns homelab internal.newjoy.ro
cloudflared tunnel route dns homelab argocd.internal.newjoy.ro
cloudflared tunnel route dns homelab longhorn.internal.newjoy.ro

# For public apps (add as needed)
cloudflared tunnel route dns homelab newjoy.ro
```

This creates CNAME records pointing to your tunnel.

---

## Part 3: Deploy Ingress Controller

We use **ingress-nginx** for routing inside the cluster.

The ArgoCD application is at `apps/ingress-nginx.yaml`.

After ArgoCD syncs, verify:

```bash
kubectl get pods -n ingress-nginx
kubectl get svc -n ingress-nginx
```

---

## Part 4: Deploy Cloudflare Tunnel

### 4.1 Update Configuration

Edit `config/cloudflare-tunnel/values.yaml`:
- Set your `TUNNEL_ID` (from step 2.3)

### 4.2 Deploy via ArgoCD

The ArgoCD application is at `apps/cloudflare-tunnel.yaml`.

After sync:

```bash
kubectl get pods -n cloudflared
kubectl logs -n cloudflared deploy/cloudflared
```

You should see "Connection established" messages.

---

## Part 5: Configure Cloudflare Access (SSO)

### 5.1 Set Up Identity Provider (Google)

1. **Google Cloud Console** (https://console.cloud.google.com):
   - Create new project or use existing
   - Go to **APIs & Services** → **Credentials**
   - Click **Create Credentials** → **OAuth client ID**
   - Application type: **Web application**
   - Name: `Cloudflare Access`
   - Authorized redirect URIs: `https://<your-team-name>.cloudflareaccess.com/cdn-cgi/access/callback`
     (You'll get the team name in the next step)
   - Save **Client ID** and **Client Secret**

2. **Cloudflare Zero Trust Dashboard** (https://one.dash.cloudflare.com):
   - First time: Create a team name (e.g., `newjoy`)
   - Go to **Settings** → **Authentication** → **Login methods**
   - Click **Add new** → **Google**
   - Enter Client ID and Client Secret from Google
   - Save

### 5.2 Create Access Application (Protect Internal Apps)

1. In Zero Trust dashboard, go to **Access** → **Applications**
2. Click **Add an application** → **Self-hosted**
3. Configure:
   - Application name: `Internal Apps`
   - Session duration: `24 hours` (or your preference)
   - Subdomain: `*.internal` 
   - Domain: `newjoy.ro`
   - (This protects all `*.internal.newjoy.ro` subdomains)
4. Click **Next**
5. Add policy:
   - Policy name: `Allow Google Users`
   - Action: **Allow**
   - Include: **Emails ending in** → `@gmail.com` (or your domain)
   - Or: **Login Methods** → **Google**
6. Click **Next** → **Add application**

### 5.3 Test Access

1. Open `https://argocd.internal.newjoy.ro` in browser
2. You should see Cloudflare Access login page
3. Click "Sign in with Google"
4. After auth, you're redirected to the app

---

## Part 6: Adding New Apps

Each app defines its own Ingress resource. Cloudflared routes all traffic to ingress-nginx, which then routes based on hostname.

**To add a new app:**

1. Create the app's deployment/service
2. Add an Ingress resource:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: my-app
  namespace: my-app
spec:
  ingressClassName: nginx
  rules:
    - host: my-app.internal.newjoy.ro  # or my-app.newjoy.ro for public
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: my-app
                port:
                  number: 80
```

3. Add DNS route (one-time per hostname):
```bash
cloudflared tunnel route dns homelab my-app.internal.newjoy.ro
```

4. If internal, add to Cloudflare Access policy (already covered by `*.internal.newjoy.ro` wildcard)

**No need to update cloudflared config** - just add Ingress resources!

---

## Summary

Traffic flow:
```
User → Cloudflare Access (auth) → Cloudflare Tunnel → cloudflared pod → Ingress Controller → App
```

**Domains:**
- `*.internal.newjoy.ro` - Protected by Cloudflare Access (Google login)
- `newjoy.ro`, other subdomains - Public (add Access policies as needed)

**No inbound ports needed** - tunnel connects outbound to Cloudflare.

