# Stalwart Mail Server for HomePBP

Local IMAP mail server with Pocket ID SSO, fetching inbound mail from Migadu.

## Architecture Decisions

### Why This Setup?

| Requirement | Solution |
|-------------|----------|
| No inbound ports (port 25) | Migadu receives mail, we fetch via IMAP |
| SSO with Pocket ID | Stalwart supports OIDC natively |
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
          │         │  • Your mailboxes         │
          │         │                           │
          │         │  OUTBOUND:                │◄──── Stalwart (direct)
          │         │  • SMTP relay             │
          │         │  • DKIM signing           │
          │         │  • Reputation             │
          │         └───────────────────────────┘
          │                      ▲
     IMAP Fetch                  │ SMTP relay
     (outbound connection,       │ (port 465 TLS)
      no inbound ports needed)   │
          │                      │
          ▼                      │
┌─────────────────────────────────────────────────────────────────┐
│                         HOMELAB                                 │
│                                                                 │
│  ┌───────────────┐     ┌─────────────────┐                      │
│  │   Fetchmail   │────▶│    Stalwart     │──────────────────────┘
│  │               │     │                 │
│  │ Pulls from    │     │ • Local IMAP    │◄──── Pocket ID
│  │ Migadu for    │     │ • OIDC auth     │      (other apps)
│  │ each mailbox  │     │ • Mail storage  │
│  │               │     │ • Outbound SMTP │
│  └───────────────┘     └────────┬────────┘
│                                 │
│                          Pocket ID OIDC
│                                 │
│                                 ▼
│                        ┌─────────────────┐
│                        │    Roundcube    │
│                        │    (Webmail)    │
│                        │                 │
│                        │ OIDC login via  │
│                        │ Pocket ID       │
│                        └─────────────────┘
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
  is "user@yourdomain.tld" here
  nokeep
```

> **Note**: Use a placeholder like `FETCHMAIL_USER_PASSWORD` — it will be replaced at runtime from the secret. The `is ... here` line tells fetchmail to deliver to that local address via SMTP.

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
- Accessible via webmail (Roundcube) with Pocket ID SSO
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
User → Roundcube "Login with Pocket ID" → Pocket ID (OIDC) → Roundcube → Stalwart (OIDC token)
```

- ✅ True single sign-on
- ✅ No separate password needed
- ✅ Pocket ID session = mail access

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
| Webmail | ✅ | Pocket ID SSO |

## Prerequisites

Before deploying, ensure:

1. **Migadu account** with Micro plan ($19/year)
2. **Migadu mailboxes** created for each user
3. **DNS configured** for SPF, DKIM, DMARC (see Migadu DNS section below)
4. **Pocket ID running** with OIDC client configured

## Setup Guide

### 1. Configure Pocket ID OIDC Client

Create an OIDC client in Pocket ID for Stalwart:

1. Go to Pocket ID Admin → **OIDC Clients** → **Create**
2. Configure:

| Setting | Value |
|---------|-------|
| Name | `Stalwart Mail` |
| Redirect URIs | `https://mail.newjoy.ro/oauth/callback` |

3. Copy the **Client ID** and **Client Secret**

### 2. Create Secrets

> **⚠️ Never commit secrets to the repository!** Create secrets directly in the cluster.

You need to create **three secrets** in the `stalwart-mail` namespace:

#### Secret 1: Migadu Fetch Credentials

Contains passwords for fetchmail to pull mail from Migadu (one entry per mailbox):

```bash
kubectl create namespace stalwart-mail

# Add one --from-literal for each mailbox
# The key names must match placeholders in fetchmail-configmap.yaml
kubectl create secret generic migadu-fetch-credentials \
  --namespace stalwart-mail \
  --from-literal=FETCHMAIL_SERVICE_PASSWORD='<service mailbox migadu password>' \
  --from-literal=FETCHMAIL_KINGA_PASSWORD='<kinga mailbox migadu password>' \
  --from-literal=FETCHMAIL_ALPAR_PASSWORD='<alpar mailbox migadu password>'
```

#### Secret 2: Stalwart OIDC Credentials

Contains the Pocket ID OIDC client credentials:

```bash
kubectl create secret generic stalwart-oidc \
  --namespace stalwart-mail \
  --from-literal=client_id='<client-id-from-pocket-id>' \
  --from-literal=client_secret='<client-secret-from-pocket-id>'
```

#### Secret 3: Email Addresses

Contains email addresses to avoid checking them into git:

```bash
kubectl create secret generic stalwart-emails \
  --namespace stalwart-mail \
  --from-literal=SERVICE_EMAIL='<service email address>' \
  --from-literal=KINGA_EMAIL='<kinga email address>' \
  --from-literal=ALPAR_EMAIL='<alpar email address>'
```

#### Secret 4: Stalwart Admin Password

Admin password for Stalwart's fallback authentication:

```bash
kubectl create secret generic stalwart-admin \
  --namespace stalwart-mail \
  --from-literal=password='<generate-a-strong-password>'
```

#### Secret 5: Migadu SMTP Credentials

Contains the Migadu SMTP credentials for outbound mail relay:

```bash
kubectl create secret generic migadu-smtp-credentials \
  --namespace stalwart-mail \
  --from-literal=username='service@newjoy.ro' \
  --from-literal=password='<your-migadu-mailbox-password>'
```

> **Note**: Use the same Migadu mailbox credentials. With wildcard sending enabled in Migadu, this account can send as any `@newjoy.ro` address.

### 3. Verify Secrets

Confirm all secrets are created:

```bash
kubectl get secrets -n stalwart-mail
# Expected:
# migadu-fetch-credentials
# stalwart-oidc
# stalwart-emails
# stalwart-admin
# migadu-smtp-credentials
```

### 4. Deploy Stalwart

Stalwart is deployed via ArgoCD. The application is defined in `apps/stalwart-mail.yaml`:

```bash
# ArgoCD will automatically sync, or you can trigger manually:
kubectl apply -f apps/stalwart-mail.yaml
```

### 5. Create Stalwart Accounts

After Stalwart is running, you must create accounts for each mailbox. Stalwart won't accept mail for addresses it doesn't know about.

1. Go to the Stalwart webadmin at `https://mail.newjoy.ro`
2. Login with:
   - Username: `admin`
   - Password: (from your `stalwart-admin` secret)
3. Go to **Management** → **Accounts** → **Create Account**
4. Create an account for each mailbox:

| Account Name | Email Address | Description |
|--------------|---------------|-------------|
| `service` | (from SERVICE_EMAIL secret) | System/service emails |
| `kinga` | (from KINGA_EMAIL secret) | Personal mailbox |
| `alpar` | (from ALPAR_EMAIL secret) | Personal mailbox |

> **Important**: The account name must match the `is "..." here` mapping in fetchmail config. Stalwart will match incoming mail by email address to the correct account.

### 6. Configure Stalwart OIDC

Stalwart configuration for Pocket ID OIDC (in ConfigMap):

```toml
[authentication]
fallback-admin.user = "admin"
fallback-admin.secret = "%{env:ADMIN_PASSWORD}%"

[oauth]
oidc.issuer-url = "https://auth.newjoy.ro"
oidc.client-id = "%{env:OIDC_CLIENT_ID}%"
oidc.client-secret = "%{env:OIDC_CLIENT_SECRET}%"
oidc.scopes = ["openid", "email", "profile"]

# Map Pocket ID email to Stalwart account
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
    set smtp localhost/25
    
    # Service mailbox
    poll imap.migadu.com
      protocol IMAP
      user "SERVICE_EMAIL_PLACEHOLDER"
      password "FETCHMAIL_SERVICE_PASSWORD"
      ssl
      sslcertck
      is "SERVICE_EMAIL_PLACEHOLDER" here
      nokeep
    
    # Kinga mailbox
    poll imap.migadu.com
      protocol IMAP
      user "KINGA_EMAIL_PLACEHOLDER"
      password "FETCHMAIL_KINGA_PASSWORD"
      ssl
      sslcertck
      is "KINGA_EMAIL_PLACEHOLDER" here
      nokeep
    
    # Alpar mailbox
    poll imap.migadu.com
      protocol IMAP
      user "ALPAR_EMAIL_PLACEHOLDER"
      password "FETCHMAIL_ALPAR_PASSWORD"
      ssl
      sslcertck
      is "ALPAR_EMAIL_PLACEHOLDER" here
      nokeep
```

#### Secret (created manually, NOT in git)

See "Create Secrets" section above.

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
        # Replace email placeholders
        sed -i "s|SERVICE_EMAIL_PLACEHOLDER|$SERVICE_EMAIL|g" /config/fetchmailrc
        sed -i "s|KINGA_EMAIL_PLACEHOLDER|$KINGA_EMAIL|g" /config/fetchmailrc
        sed -i "s|ALPAR_EMAIL_PLACEHOLDER|$ALPAR_EMAIL|g" /config/fetchmailrc
        chmod 600 /config/fetchmailrc
    envFrom:
      - secretRef:
          name: migadu-fetch-credentials
      - secretRef:
          name: stalwart-emails
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
| `is ... here` | Deliver to this local email address via SMTP |
| `set smtp localhost/25` | Deliver via SMTP to Stalwart (same pod) |
| `nokeep` | Delete mail from Migadu after fetching; use `keep` to retain as backup |
| `set daemon 60` | Poll every 60 seconds |

### 7. Deploy Roundcube with OIDC

Roundcube supports OIDC via the `oauth2` plugin, enabling true SSO with Pocket ID.

**How it works:**
1. User visits `webmail.newjoy.ro`
2. Clicks "Login with Pocket ID"
3. Authenticates via Pocket ID OIDC
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
    value: "stalwart.stalwart-mail.svc.cluster.local"
  - name: ROUNDCUBEMAIL_SMTP_PORT
    value: "25"
  # Enable OIDC plugin
  - name: ROUNDCUBEMAIL_PLUGINS
    value: "oauth2"
```

Roundcube OIDC config (`oauth2.inc.php`):

```php
$config['oauth_provider'] = 'generic';
$config['oauth_provider_name'] = 'Pocket ID';
$config['oauth_client_id'] = 'roundcube';
$config['oauth_client_secret'] = 'YOUR_CLIENT_SECRET';
$config['oauth_auth_uri'] = 'https://auth.newjoy.ro/authorize';
$config['oauth_token_uri'] = 'https://auth.newjoy.ro/api/oidc/token';
$config['oauth_identity_uri'] = 'https://auth.newjoy.ro/api/oidc/userinfo';
$config['oauth_scope'] = 'openid email profile';
$config['oauth_identity_fields'] = ['email'];
```

## Client Configuration

### Webmail

| Setting | Value |
|---------|-------|
| URL | `https://webmail.newjoy.ro` |
| Login | Via Pocket ID SSO |

### Mobile/Desktop Apps

| Setting | Value |
|---------|-------|
| IMAP Server | `mail.newjoy.ro` |
| IMAP Port | `993` (SSL) |
| SMTP Server | `mail.newjoy.ro` |
| SMTP Port | `587` (STARTTLS) |
| Username | Your full email address |
| Password | App-specific password from Stalwart |

#### iPhone Mail Setup

1. Go to **Settings** → **Mail** → **Accounts** → **Add Account** → **Other** → **Add Mail Account**
2. Enter:
   - **Name**: Your name
   - **Email**: your-email@newjoy.ro
   - **Password**: Your Stalwart password (or app password)
   - **Description**: Newjoy Mail
3. Tap **Next**, select **IMAP**
4. Configure incoming server:
   - **Host Name**: `mail.newjoy.ro`
   - **User Name**: your-email@newjoy.ro
   - **Password**: (same as above)
5. Configure outgoing server:
   - **Host Name**: `mail.newjoy.ro`
   - **User Name**: your-email@newjoy.ro
   - **Password**: (same as above)
6. Tap **Save**

> **Note**: If authentication fails, you may need to set a password in Stalwart first (OIDC accounts don't have passwords by default).

#### Setting a Password for IMAP Access

If you logged into Stalwart via OIDC and need a password for mobile apps:

1. Ask your admin to set a password via Stalwart admin panel at https://mail.newjoy.ro
2. Or generate an app-specific password (see below)

#### Generating App Passwords

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

1. Check Pocket ID client configuration
2. Verify redirect URI matches exactly
3. Check Stalwart logs:
   ```bash
   kubectl logs -n stalwart-mail deployment/stalwart -c stalwart
   ```

### Mail Not Sending

Outbound mail goes directly from Stalwart to Migadu:

1. Check Stalwart logs: `kubectl logs -n stalwart-mail deployment/stalwart -c stalwart`
2. Verify Migadu SMTP credentials in the `migadu-smtp-credentials` secret
3. Ensure wildcard sending is enabled for the Migadu mailbox
4. Check Migadu dashboard for sending statistics and errors

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

## Secrets Summary

Before deploying, create these secrets manually:

| Secret Name | Namespace | Keys | Purpose |
|-------------|-----------|------|---------|
| `migadu-fetch-credentials` | stalwart-mail | `FETCHMAIL_SERVICE_PASSWORD`, `FETCHMAIL_KINGA_PASSWORD`, `FETCHMAIL_ALPAR_PASSWORD` | Migadu mailbox passwords for fetchmail |
| `stalwart-oidc` | stalwart-mail | `client_id`, `client_secret` | Pocket ID OIDC credentials |
| `stalwart-emails` | stalwart-mail | `SERVICE_EMAIL`, `KINGA_EMAIL`, `ALPAR_EMAIL` | Email addresses (kept out of git) |
| `stalwart-admin` | stalwart-mail | `password` | Stalwart admin fallback password |
| `migadu-smtp-credentials` | stalwart-mail | `username`, `password` | Migadu SMTP credentials for outbound relay |

## Outbound Mail & DNS Setup

Stalwart relays outbound mail directly through Migadu. Configure these DNS records for proper email deliverability:

### SPF Record
```
v=spf1 include:spf.migadu.com -all
```

### DKIM Records (CNAME)
| Name | Target |
|------|--------|
| `key1._domainkey` | `key1.newjoy.ro._domainkey.migadu.com` |
| `key2._domainkey` | `key2.newjoy.ro._domainkey.migadu.com` |
| `key3._domainkey` | `key3.newjoy.ro._domainkey.migadu.com` |

### DMARC Record
```
v=DMARC1; p=quarantine; rua=mailto:dmarc@newjoy.ro
```

### Internal Apps Using Stalwart as SMTP Relay

Other apps in the cluster can send mail through Stalwart:

| Setting | Value |
|---------|-------|
| SMTP Host | `stalwart.stalwart-mail.svc.cluster.local` |
| SMTP Port | `25` |
| TLS/SSL | None (internal traffic) |
| Authentication | None (internal traffic) |

---

## Related

- **Pocket ID**: OIDC provider configuration for SSO
