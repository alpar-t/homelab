# Mail Relay for HomePBP

A lightweight Postfix-based SMTP relay that forwards all outbound email through Migadu.

## Why a Local Relay?

- **Single configuration point**: All apps use `smtp://mail-relay.mail-relay:25`
- **Email queuing**: Emails are queued locally if Migadu is unreachable
- **Automatic retry**: Failed sends are retried automatically
- **Simplified app config**: Apps don't need Migadu credentials

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Authentik  │────▶│             │     │             │
├─────────────┤     │ Mail Relay  │────▶│   Migadu    │────▶ Recipients
│  Grafana    │────▶│  (Postfix)  │     │    SMTP     │
├─────────────┤     │             │     │             │
│  Stalwart   │────▶│             │     │             │
└─────────────┘     └─────────────┘     └─────────────┘
     Internal           Queue              External
```

## Why Migadu?

| Feature | Migadu Micro | Mailgun Free |
|---------|--------------|--------------|
| Price | $19/year | $0 (100/day limit) |
| Emails/day | 200 | 100 |
| Dedicated reputation | ✅ Yes | ❌ Shared IP pool |
| Privacy | 🇨🇭 Swiss | 🇺🇸 US (Sinch) |
| Inbound mailboxes | ✅ Included | ❌ Separate |

We use Migadu because:
1. **Better deliverability** - own IP reputation, not shared with spammers
2. **Combined solution** - same provider handles inbound mail (see `config/stalwart-mail`)
3. **Simple pricing** - flat yearly fee, no surprises
4. **Privacy-focused** - Swiss company, GDPR compliant

## Migadu Setup Guide

### 1. Create Migadu Account

1. Go to [https://www.migadu.com](https://www.migadu.com)
2. Sign up for the **Micro** plan ($19/year)
3. Verify your email address

### 2. Add Your Domain

1. Navigate to **Domains** → **Add Domain**
2. Enter your domain: `newjoy.ro`
3. Choose your admin email address

### 3. Configure DNS Records for Outbound Mail

For **outbound email only**, you need SPF, DKIM, and DMARC records. These tell receiving mail servers that Migadu is authorized to send on behalf of your domain.

> **Note**: MX records (for inbound mail) are configured separately in `config/stalwart-mail/README.md`.

1. Go to [Cloudflare Dashboard](https://dash.cloudflare.com) → **newjoy.ro** → **DNS** → **Records**

2. **Add/Update your SPF record**:

   Find your current TXT record for `newjoy.ro` that starts with `v=spf1`, or create one:
   ```
   v=spf1 include:spf.migadu.com -all
   ```

   > ⚠️ **Important**: A domain can only have ONE SPF record. If you have an existing one, edit it to include Migadu.

| Type | Name | Content | TTL |
|------|------|---------|-----|
| TXT | @ | `v=spf1 include:spf.migadu.com -all` | Auto |

3. **Add DKIM records** (Migadu provides 3 CNAME records):

| Type | Name | Content | TTL |
|------|------|---------|-----|
| CNAME | `key1._domainkey` | `key1.newjoy.ro._domainkey.migadu.com` | Auto |
| CNAME | `key2._domainkey` | `key2.newjoy.ro._domainkey.migadu.com` | Auto |
| CNAME | `key3._domainkey` | `key3.newjoy.ro._domainkey.migadu.com` | Auto |

4. **Add DMARC record**:

| Type | Name | Content | TTL |
|------|------|---------|-----|
| TXT | `_dmarc` | `v=DMARC1; p=quarantine; rua=mailto:dmarc@newjoy.ro` | Auto |

5. **Add domain verification TXT record** (Migadu will provide the exact value):

| Type | Name | Content | TTL |
|------|------|---------|-----|
| TXT | @ | `hosted-email-verify=xxxxxxxx` | Auto |

### 4. Verify DNS in Migadu

1. Go back to Migadu → **Domains** → `newjoy.ro`
2. Click **Verify DNS**
3. Cloudflare propagates quickly - usually verifies within minutes
4. Expected results:
   - ✅ SPF - should pass
   - ✅ DKIM - should pass
   - ✅ DMARC - should pass
   - ⚠️ MX - may show warning if not yet configured (that's fine for outbound-only)

### 5. Create SMTP Credentials

For the mail-relay, create a dedicated sending identity:

1. Go to **Domains** → `newjoy.ro` → **Mailboxes**
2. Create a mailbox for SMTP authentication (e.g., `service@newjoy.ro`)
3. Note down the SMTP credentials:
   - **SMTP Server**: `smtp.migadu.com`
   - **Port**: `587` (STARTTLS) or `465` (SSL)
   - **Username**: `service@newjoy.ro`
   - **Password**: The mailbox password

> **Important**: The SMTP username is only for **authentication**. Your services can still send from any `@newjoy.ro` address (e.g., `service.authentik@newjoy.ro`, `alerts@newjoy.ro`). The "From" address is independent of the login credentials.

### 6. Create Kubernetes Secret

> **⚠️ Never commit secrets to the repository!** Create secrets directly in the cluster.

Create the namespace and secret with your Migadu credentials:

```bash
# Create namespace first
kubectl create namespace mail-relay

# Create the secret (replace with your actual credentials)
kubectl create secret generic migadu-credentials \
  --namespace mail-relay \
  --from-literal=username='service@newjoy.ro' \
  --from-literal=password='YOUR_MIGADU_MAILBOX_PASSWORD'
```

Verify the secret was created:

```bash
kubectl get secret -n mail-relay migadu-credentials
```

### 7. Deploy via ArgoCD

Once the secret exists, the mail-relay application will sync automatically.

If you haven't added it yet, add to `root-application.yaml` or apply directly:

```bash
kubectl apply -f apps/mail-relay.yaml
```

## Configuration

### Sender Addresses

The relay allows sending from any `@newjoy.ro` address. Use these conventions:

| Type | From Address | Purpose |
|------|--------------|---------|
| Authentik | `service.authentik@newjoy.ro` | Password resets, 2FA |
| Grafana | `service.grafana@newjoy.ro` | Alerts |
| Stalwart | `service.mail@newjoy.ro` | Outbound relay |
| Generic | `noreply@newjoy.ro` | System notifications |

> **Note on replies**: Replies to service addresses go to Migadu. Create appropriate mailboxes or aliases to handle them.

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
kubectl run --rm -it mail-test --image=alpine --restart=Never -- sh

# Install mailx and send test
apk add --no-cache mailx
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
2. Verify secret exists: `kubectl get secret -n mail-relay migadu-credentials`
3. Test Migadu credentials manually:
   ```bash
   # Test SMTP connection
   openssl s_client -connect smtp.migadu.com:587 -starttls smtp
   ```
4. Check Migadu dashboard for sending statistics

### DNS Issues

1. Verify domain is active in Migadu dashboard
2. Check SPF record: `dig TXT newjoy.ro`
3. Check DKIM records: `dig CNAME key1._domainkey.newjoy.ro`
4. Check DMARC record: `dig TXT _dmarc.newjoy.ro`
5. Use [MXToolbox](https://mxtoolbox.com/) to validate all records

### Queue Issues

Check mail queue inside the relay:

```bash
kubectl exec -n mail-relay deployment/mail-relay -- postqueue -p
```

Flush the queue:

```bash
kubectl exec -n mail-relay deployment/mail-relay -- postqueue -f
```

### Migadu Rate Limits

Migadu Micro allows 200 emails/day. If you hit limits:

1. Check current usage in Migadu dashboard
2. Review which service is sending too many emails
3. Consider upgrading to Migadu Mini ($9/month) for 1000/day

---

## Related

- **Inbound Mail**: See `config/stalwart-mail/README.md` for the inbound mail setup with Stalwart
- **Authentication**: Stalwart integrates with Authentik for SSO (webmail only)
