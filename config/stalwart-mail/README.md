# Stalwart Mail Server for HomePBP

Local IMAP mail server with Authentik SSO, fetching inbound mail from Migadu.

## Architecture Decisions

### Why This Setup?

| Requirement | Solution |
|-------------|----------|
| No inbound ports (port 25) | Migadu receives mail, we fetch via IMAP |
| SSO with Authentik | Stalwart supports OIDC natively |
| Own storage & backups | Mail stored locally on Longhorn PVC |
| Choice of webmail | Roundcube (or any IMAP client) |
| Good deliverability | Migadu handles outbound reputation |

### The Flow

```
                              INTERNET
                                  │
                    ┌─────────────┴─────────────┐
                    │         MIGADU            │
                    │       ($19/year)          │
                    │                           │
          ┌─────────┤  INBOUND:                 │
          │         │  • MX records point here  │
          │         │  • Spam filtering         │
          │         │  • Your mailboxes          │
          │         │                           │
          │         │  OUTBOUND:                │◄──── mail-relay
          │         │  • SMTP relay             │
          │         │  • DKIM signing           │
          │         │  • Reputation             │
          │         └───────────────────────────┘
          │
     IMAP Fetch
     (outbound connection,
      no inbound ports needed)
          │
          ▼
┌─────────────────────────────────────────────────────────────────┐
│                         HOMELAB                                 │
│                                                                 │
│  ┌───────────────┐     ┌─────────────────┐     ┌─────────────┐ │
│  │   Fetchmail   │────▶│    Stalwart     │────▶│ Mail-Relay  │ │
│  │               │     │                 │     │  (Postfix)  │ │
│  │ Pulls from    │     │ • Local IMAP    │     │             │ │
│  │ Migadu for    │     │ • OIDC auth     │     │ → Migadu    │ │
│  │ each mailbox  │     │ • Mail storage  │     │   SMTP      │ │
│  │               │     │                 │     │             │ │
│  └───────────────┘     └────────┬────────┘     └─────────────┘ │
│                                 │                               │
│                          Authentik OIDC                         │
│                                 │                               │
│                                 ▼                               │
│                        ┌─────────────────┐                      │
│                        │    Roundcube    │                      │
│                        │    (Webmail)    │                      │
│                        │                 │                      │
│                        │ OIDC login via  │                      │
│                        │ Authentik       │                      │
│                        └─────────────────┘                      │
│                                                                 │
│  Storage: Longhorn PVC (included in backups)                    │
└─────────────────────────────────────────────────────────────────┘
```

## Adding Mailboxes

Each mailbox requires configuration in three places:

### 1. Create Mailbox in Migadu

1. Go to Migadu → **Domains** → `yourdomain.tld` → **Mailboxes**
2. Click **Add Mailbox**
3. Enter email address (e.g., `user@yourdomain.tld`)
4. Set a password (used for fetchmail authentication)

### 2. Add Fetchmail Entry to ConfigMap

Edit `config/stalwart-mail/manifests/fetchmail-configmap.yaml` and add a poll block:

```
poll imap.migadu.com
  protocol IMAP
  user "user@yourdomain.tld"
  password "FETCHMAIL_USER_PASSWORD"
  ssl
  sslcertck
  idle
  mda "/usr/local/bin/stalwart-cli import --account user"
  keep
```

> **Note**: Use a placeholder like `FETCHMAIL_USER_PASSWORD` — it will be replaced at runtime from the secret.

### 3. Add Password to Secret

The secret is created manually (not in git). Add the password that matches your placeholder:

```bash
kubectl create secret generic migadu-fetch-credentials \
  --namespace stalwart-mail \
  --from-literal=FETCHMAIL_USER_PASSWORD='actual-mailbox-password' \
  --dry-run=client -o yaml | kubectl apply -f -
```

The placeholder name in the ConfigMap must match the key name in the secret.

### Mailbox Features

Each mailbox:
- Receives mail via Migadu (spam-filtered)
- Is fetched to local Stalwart storage
- Accessible via webmail (Roundcube) with Authentik SSO
- Accessible via mobile apps (with app-specific passwords)

## Components

| Component | Purpose | Image |
|-----------|---------|-------|
| **Stalwart** | IMAP server, OIDC auth, mail storage | See `CLOUD.md` for pinned version |
| **Fetchmail** | Pulls mail from Migadu to Stalwart | See `CLOUD.md` for pinned version |
| **Roundcube** | Webmail UI | See `CLOUD.md` for pinned version |

> **Note**: Always use specific version tags with digests, never `latest`. See `/CLOUD.md` for current pinned versions.

## Authentication

### Webmail (Full SSO)

```
User → Roundcube "Login with Authentik" → Authentik (OIDC) → Roundcube → Stalwart (OIDC token)
```

- ✅ True single sign-on
- ✅ No separate password needed
- ✅ Authentik session = mail access

### Mobile/Desktop Apps (App Passwords)

```
User → Mail app → Stalwart (app password)
```

IMAP clients (iOS Mail, Thunderbird, etc.) don't support OIDC. Users generate app-specific passwords in Stalwart.

| Client | OIDC Support | Solution |
|--------|--------------|----------|
| iOS Mail | ❌ | App password |
| Gmail app | ❌ | App password |
| Thunderbird | ❌ | App password |
| K-9 Mail | ❌ | App password |
| Webmail | ✅ | Authentik SSO |

## Prerequisites

Before deploying, ensure:

1. **Migadu account** with Micro plan ($19/year)
2. **Migadu mailboxes** created for each user
3. **DNS configured** (see `config/mail-relay/README.md` for DNS setup)
4. **mail-relay deployed** and working
5. **Authentik running** with OIDC provider configured

## Setup Guide

### 1. Configure Authentik OIDC Provider

Create an OAuth2/OIDC provider in Authentik for Stalwart:

1. Go to Authentik Admin → **Applications** → **Providers** → **Create**
2. Choose **OAuth2/OpenID Provider**
3. Configure:

| Setting | Value |
|---------|-------|
| Name | `Stalwart Mail` |
| Authorization flow | default-provider-authorization-explicit-consent |
| Client ID | `stalwart` (auto-generated or custom) |
| Client Secret | (copy this for later) |
| Redirect URIs | `https://mail.newjoy.ro/oauth/callback` |
| Scopes | `openid email profile` |

4. Create an Application linking to this provider

### 2. Create Migadu Fetch Credentials Secret

Create a secret with credentials for fetching from Migadu (one entry per mailbox):

```bash
kubectl create namespace stalwart-mail

# Secret for fetchmail to pull from Migadu
# Add one --from-literal for each mailbox
kubectl create secret generic migadu-fetch-credentials \
  --namespace stalwart-mail \
  --from-literal=user1_password='USER1_MIGADU_PASSWORD' \
  --from-literal=user2_password='USER2_MIGADU_PASSWORD'
```

### 3. Create Authentik OIDC Secret

```bash
kubectl create secret generic stalwart-oidc \
  --namespace stalwart-mail \
  --from-literal=client_id='stalwart' \
  --from-literal=client_secret='YOUR_AUTHENTIK_CLIENT_SECRET'
```

### 4. Deploy Stalwart

```bash
kubectl apply -f apps/stalwart-mail.yaml
```

### 5. Configure Stalwart OIDC

Stalwart configuration for Authentik OIDC (in ConfigMap):

```toml
[authentication]
fallback-admin.user = "admin"
fallback-admin.secret = "%{env:ADMIN_SECRET}%"

[oauth]
oidc.issuer-url = "https://auth.newjoy.ro/application/o/stalwart/"
oidc.client-id = "%{env:OIDC_CLIENT_ID}%"
oidc.client-secret = "%{env:OIDC_CLIENT_SECRET}%"
oidc.scopes = ["openid", "email", "profile"]

# Map Authentik email to Stalwart account
[oauth.claims]
email = "email"
name = "name"
```

### 6. Configure Fetchmail (GitOps)

Fetchmail configuration is split into two parts for GitOps:

1. **ConfigMap** (committed to git) — contains the fetchmailrc template with password placeholders
2. **Secret** (NOT in git) — contains actual passwords

An init container substitutes placeholders with real passwords at startup.

#### ConfigMap (`config/stalwart-mail/manifests/fetchmail-configmap.yaml`)

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: fetchmail-config
  namespace: stalwart-mail
data:
  fetchmailrc.template: |
    set daemon 60
    set syslog
    
    # Add one poll block per mailbox
    # Use FETCHMAIL_<USERNAME>_PASSWORD as placeholder
    
    poll imap.migadu.com
      protocol IMAP
      user "user1@yourdomain.tld"
      password "FETCHMAIL_USER1_PASSWORD"
      ssl
      sslcertck
      mda "/usr/local/bin/stalwart-cli import --account user1"
      keep
    
    poll imap.migadu.com
      protocol IMAP
      user "user2@yourdomain.tld"
      password "FETCHMAIL_USER2_PASSWORD"
      ssl
      sslcertck
      mda "/usr/local/bin/stalwart-cli import --account user2"
      keep
```

#### Secret (created manually, NOT in git)

```bash
kubectl create secret generic migadu-fetch-credentials \
  --namespace stalwart-mail \
  --from-literal=FETCHMAIL_USER1_PASSWORD='actual-password-1' \
  --from-literal=FETCHMAIL_USER2_PASSWORD='actual-password-2'
```

#### Init Container (substitutes passwords)

The deployment includes an init container that replaces placeholders:

```yaml
initContainers:
  - name: fetchmail-config-init
    image: alpine:3.19
    command:
      - sh
      - -c
      - |
        cp /config-template/fetchmailrc.template /config/fetchmailrc
        # Replace each placeholder with actual password from env
        for var in $(env | grep '^FETCHMAIL_' | cut -d= -f1); do
          value=$(eval echo \$$var)
          sed -i "s|$var|$value|g" /config/fetchmailrc
        done
        chmod 600 /config/fetchmailrc
    envFrom:
      - secretRef:
          name: migadu-fetch-credentials
    volumeMounts:
      - name: fetchmail-config-template
        mountPath: /config-template
      - name: fetchmail-config
        mountPath: /config
```

#### Fetchmail Options

| Option | Description |
|--------|-------------|
| `user` | Full email address in Migadu |
| `password` | Placeholder replaced at runtime from secret |
| `mda --account` | Local Stalwart account name (usually the part before @) |
| `keep` | Retain mail on Migadu as backup; use `nokeep` to delete after fetch |
| `set daemon 60` | Poll every 60 seconds (IDLE not used for simplicity) |

### 7. Deploy Roundcube with OIDC

Roundcube supports OIDC via the `oauth2` plugin, enabling true SSO with Authentik.

**How it works:**
1. User visits `webmail.newjoy.ro`
2. Clicks "Login with Authentik"
3. Authenticates via Authentik OIDC
4. Roundcube receives token with user's email
5. Connects to Stalwart IMAP (Stalwart also validates the OIDC token)
6. User sees their mailbox

All users share the **same Roundcube instance** — each sees their own mailbox after login.

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: roundcube
spec:
  rules:
    - host: webmail.newjoy.ro
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: roundcube
                port:
                  number: 80
```

Roundcube configuration:

```yaml
env:
  # IMAP/SMTP settings
  - name: ROUNDCUBEMAIL_DEFAULT_HOST
    value: "ssl://stalwart.stalwart-mail.svc.cluster.local"
  - name: ROUNDCUBEMAIL_DEFAULT_PORT
    value: "993"
  - name: ROUNDCUBEMAIL_SMTP_SERVER
    value: "mail-relay.mail-relay.svc.cluster.local"
  - name: ROUNDCUBEMAIL_SMTP_PORT
    value: "25"
  # Enable OIDC plugin
  - name: ROUNDCUBEMAIL_PLUGINS
    value: "oauth2"
```

Roundcube OIDC config (`oauth2.inc.php`):

```php
$config['oauth_provider'] = 'generic';
$config['oauth_provider_name'] = 'Authentik';
$config['oauth_client_id'] = 'roundcube';
$config['oauth_client_secret'] = 'YOUR_CLIENT_SECRET';
$config['oauth_auth_uri'] = 'https://auth.newjoy.ro/application/o/authorize/';
$config['oauth_token_uri'] = 'https://auth.newjoy.ro/application/o/token/';
$config['oauth_identity_uri'] = 'https://auth.newjoy.ro/application/o/userinfo/';
$config['oauth_scope'] = 'openid email profile';
$config['oauth_identity_fields'] = ['email'];
```

## Client Configuration

### Webmail

| Setting | Value |
|---------|-------|
| URL | `https://webmail.newjoy.ro` |
| Login | Via Authentik SSO |

### Mobile/Desktop Apps

| Setting | Value |
|---------|-------|
| IMAP Server | `mail.newjoy.ro` |
| IMAP Port | `993` (SSL) |
| SMTP Server | `mail.newjoy.ro` |
| SMTP Port | `587` (STARTTLS) |
| Username | Your full email address |
| Password | App-specific password from Stalwart |

To generate app password:
1. Login to Stalwart admin or webmail
2. Go to Settings → Security → App Passwords
3. Generate new password for each device

## Storage & Backup

Mail is stored locally on Longhorn:

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: stalwart-data
  namespace: stalwart-mail
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: longhorn-ssd
  resources:
    requests:
      storage: 10Gi
```

Mail directory structure:
```
/opt/stalwart-mail/
├── data/           # Mail storage (Maildir format)
├── queue/          # Outbound queue
└── reports/        # DMARC/delivery reports
```

**Backup**: Longhorn snapshots include all mail data automatically.

## Troubleshooting

### Fetchmail Not Pulling Mail

```bash
# Check fetchmail logs
kubectl logs -n stalwart-mail deployment/stalwart -c fetchmail

# Test Migadu IMAP connection manually
kubectl exec -n stalwart-mail deployment/stalwart -c fetchmail -- \
  openssl s_client -connect imap.migadu.com:993
```

### OIDC Login Failing

1. Check Authentik provider configuration
2. Verify redirect URI matches exactly
3. Check Stalwart logs:
   ```bash
   kubectl logs -n stalwart-mail deployment/stalwart -c stalwart
   ```

### Mail Not Sending

Outbound mail goes through mail-relay, not directly from Stalwart:

1. Check Stalwart is configured to relay through mail-relay
2. Check mail-relay logs: `kubectl logs -n mail-relay deployment/mail-relay`
3. Verify Migadu SMTP credentials

### App Password Not Working

1. Ensure app password was generated correctly
2. Check Stalwart allows app passwords for the account
3. Verify IMAP port (993) and SMTP port (587) are correct

## Migration from Google Workspace

### Phase 1: Setup (Current)
- [ ] Deploy Stalwart with OIDC
- [ ] Configure fetchmail for each mailbox
- [ ] Deploy Roundcube
- [ ] Test sending/receiving

### Phase 2: Parallel Run
- [ ] Keep Google Workspace active
- [ ] Forward copies to Migadu for testing
- [ ] Verify all mail arrives correctly

### Phase 3: Migration
- [ ] Export mail from Google (Google Takeout)
- [ ] Import to Stalwart
- [ ] Update MX to Migadu
- [ ] Monitor for 1 week

### Phase 4: Cleanup
- [ ] Cancel Google Workspace subscription
- [ ] Remove old DNS records
- [ ] Celebrate saving $72/year! 🎉

---

## Related

- **Outbound Mail**: See `config/mail-relay/README.md` for SMTP relay configuration
- **DNS Setup**: Migadu DNS records are documented in mail-relay README
- **Authentik**: OIDC provider configuration for SSO

