# Mail Relay for HomePBP

A lightweight Postfix-based SMTP relay that forwards all outbound email through Mailgun.

## Why a Local Relay?

- **Single configuration point**: All apps use `smtp://mail-relay.mail-relay:25`
- **Email queuing**: Emails are queued locally if Mailgun is unreachable
- **Automatic retry**: Failed sends are retried automatically
- **Simplified app config**: Apps don't need Mailgun credentials

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Authentik  │────▶│             │     │             │
├─────────────┤     │ Mail Relay  │────▶│   Mailgun   │────▶ Recipients
│  Grafana    │────▶│  (Postfix)  │     │    SMTP     │
├─────────────┤     │             │     │             │
│  Nextcloud  │────▶│             │     │             │
└─────────────┘     └─────────────┘     └─────────────┘
     Internal           Queue              External
```

## Mailgun Setup Guide

### 1. Create Mailgun Account

1. Go to [https://www.mailgun.com](https://www.mailgun.com)
2. Sign up for an account (free tier: 5,000 emails/month for 3 months, then pay-as-you-go)
3. Verify your email address

### 2. Add Your Domain

1. Navigate to **Sending** → **Domains** → **Add New Domain**
2. Enter your main domain: `newjoy.ro`
3. Select your region (EU recommended for GDPR)

> **Note**: We use the main domain (not a subdomain) so services can send from `service.authentik@newjoy.ro`. Gmail/Google Workspace continues to handle inbound email.

### 3. Configure DNS Records in Cloudflare

Mailgun will provide DNS records. Add them in Cloudflare **alongside your existing Google Workspace records**:

1. Go to [Cloudflare Dashboard](https://dash.cloudflare.com) → **newjoy.ro** → **DNS** → **Records**

2. **Update your existing SPF record** (don't create a new one!):

   Find your current TXT record for `newjoy.ro` that starts with `v=spf1`. It probably looks like:
   ```
   v=spf1 include:_spf.google.com ~all
   ```
   
   **Edit it** to add Mailgun:
   ```
   v=spf1 include:_spf.google.com include:mailgun.org ~all
   ```

   > ⚠️ **Important**: A domain can only have ONE SPF record. Don't create a second one - edit the existing one.

3. **Add DKIM record** (new TXT record):

| Type | Name | Content | TTL |
|------|------|---------|-----|
| TXT | `smtp._domainkey` | (long string from Mailgun - starts with `k=rsa; p=...`) | Auto |

   > The exact name might vary - Mailgun will tell you. Common patterns: `smtp._domainkey`, `k1._domainkey`, `mg._domainkey`

4. **Do NOT change MX records** - keep them pointing to Google:

   Your existing MX records should remain:
   ```
   newjoy.ro  MX  1   aspmx.l.google.com
   newjoy.ro  MX  5   alt1.aspmx.l.google.com
   ...
   ```
   
   This ensures inbound email continues going to Gmail.

### 4. Verify DNS in Mailgun

1. Go back to Mailgun → **Sending** → **Domains** → `newjoy.ro`
2. Click **Verify DNS Settings**
3. Cloudflare propagates quickly - usually verifies within minutes
4. Expected results:
   - ✅ SPF - should pass (includes mailgun.org)
   - ✅ DKIM - should pass (your new TXT record)
   - ⚠️ MX - will show warning (pointing to Google, not Mailgun) - **this is expected and correct!**

> **MX Warning is OK!** We intentionally keep MX pointing to Google Workspace. Mailgun only needs SPF and DKIM to send outbound email.

### 5. Get SMTP Credentials

1. Go to **Sending** → **Domain settings** → **SMTP credentials**
2. Create new SMTP user or use the default one
3. Note down:
   - **SMTP Server**: `smtp.eu.mailgun.org` (EU region)
   - **Port**: `587` (TLS)
   - **Username**: `postmaster@newjoy.ro`
   - **Password**: Generate/copy the SMTP password

### 6. Create Kubernetes Secret

> **⚠️ Never commit secrets to the repository!** Create secrets directly in the cluster.

Create the namespace and secret with your Mailgun credentials:

```bash
# Create namespace first
kubectl create namespace mail-relay

# Create the secret (replace with your actual credentials)
kubectl create secret generic mailgun-credentials \
  --namespace mail-relay \
  --from-literal=username='postmaster@newjoy.ro' \
  --from-literal=password='YOUR_MAILGUN_SMTP_PASSWORD'
```

Verify the secret was created:

```bash
kubectl get secret -n mail-relay mailgun-credentials
```

### 7. Deploy via ArgoCD

Once the secret exists, the mail-relay application will sync automatically.

If you haven't added it yet, add to `root-application.yaml` or apply directly:

```bash
kubectl apply -f apps/mail-relay.yaml
```

## Configuration

### Sender Addresses

The relay allows sending from any `@newjoy.ro` address. Use the `service.<app>@` convention:

| Service | From Address |
|---------|-------------|
| Authentik | `service.authentik@newjoy.ro` |
| Grafana | `service.grafana@newjoy.ro` |
| Nextcloud | `service.nextcloud@newjoy.ro` |
| Alerts | `service.alerts@newjoy.ro` |

> **Note on replies**: If someone replies to these addresses, the email goes to Google Workspace. You can optionally create aliases in Google Admin to route them to `admin@newjoy.ro`.

### App Configuration

Configure your apps to use the relay:

| Setting | Value |
|---------|-------|
| SMTP Host | `mail-relay.mail-relay.svc.cluster.local` |
| SMTP Port | `25` |
| TLS/SSL | None (internal traffic) |
| Authentication | None (internal traffic) |

## Testing

Send a test email from inside the cluster:

```bash
# Create a test pod
kubectl run --rm -it mail-test --image=busybox --restart=Never -- sh

# Install mailx and send test
apk add mailx
echo "Test from homelab" | mail -s "Test Email" \
  -S smtp=mail-relay.mail-relay:25 \
  -S from="test@newjoy.ro" \
  your-email@example.com
```

Or check the relay logs:

```bash
kubectl logs -n mail-relay -l app=mail-relay -f
```

## Troubleshooting

### Emails Not Sending

1. Check pod logs: `kubectl logs -n mail-relay deployment/mail-relay`
2. Verify secret exists: `kubectl get secret -n mail-relay mailgun-credentials`
3. Test Mailgun credentials manually
4. Check Mailgun dashboard for rejected emails

### DNS Issues

1. Verify domain is active in Mailgun dashboard
2. Check SPF record includes Mailgun: `dig TXT newjoy.ro`
3. Check DKIM record: `dig TXT smtp._domainkey.newjoy.ro`
4. Use [MXToolbox SPF checker](https://mxtoolbox.com/spf.aspx) to validate

### Queue Issues

Check mail queue inside the relay:

```bash
kubectl exec -n mail-relay deployment/mail-relay -- postqueue -p
```

Flush the queue:

```bash
kubectl exec -n mail-relay deployment/mail-relay -- postqueue -f
```

---

## Future: Inbound Email Migration

Currently, inbound email (`*@newjoy.ro`) is handled by Google Workspace. To migrate to self-hosted inbound:

### Phase 1 (Current)
- ✅ Outbound: Mailgun via mail-relay
- ✅ Inbound: Google Workspace (MX → Google)

### Phase 2 (Future)
- Outbound: Mailgun via mail-relay (unchanged)
- Inbound: Self-hosted (Mailu, Mailcow, or similar)

### Migration Steps (when ready)
1. Deploy Mailu/Mailcow in the cluster
2. Configure Mailgun to receive and forward to your cluster (or use Cloudflare Email Routing)
3. Test with a subdomain first (e.g., `test.newjoy.ro`)
4. Update MX records to point to your mail server
5. Gradually migrate mailboxes from Google Workspace

> **Tip**: Keep Google Workspace as a backup MX during migration.

