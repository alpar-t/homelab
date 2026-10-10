# Stalwart / fetchmail functional monitoring

## Polling and incident confirmation

Poll every 900 seconds (15 minutes); shared failure grace is 1800 seconds.
A problem needs both the elapsed grace and at least two independent failed
executions; recovery needs two independent healthy executions. At this cadence
and grace, ordinary continuous failure normally requires three failed runs.
Minute snapshots never count as new observations, and failures keep the same
slow cadence. Scheduling is staggered. Referenced workload reboot/rescheduling
grace and maintenance preserve confirmed state without declaring recovery.
Persistent ordinary outages page; module-specific advisories stay on the dashboard.
See [the shared framework](../service-functional-checks.md) for startup,
unknown/deferred observations and queue freshness.

Every 15 minutes, the collector performs anonymous protocol negotiations:

- Local SMTP port 25: valid 220 greeting, successful EHLO and QUIT, matching the fetchmail delivery listener.
- Local submission port 587: EHLO must advertise STARTTLS, upgrade with certificate verification, then repeat EHLO and QUIT.
- Local IMAPS port 993 and Migadu IMAPS port 993: verified TLS, OK greeting, CAPABILITY containing IMAP4rev1 or IMAP4rev2 and matching tagged OK completion.
- Migadu outbound relay port 465: verified implicit TLS, SMTP greeting, EHLO and QUIT.

Each endpoint has a five-second total socket-operation budget bounded by the runner's remaining 30-second deadline; responses are capped at 16 KiB total, 4 KiB buffered and 40 lines per response. Failures retry at the foundation's configured cadence and use its existing execution-based alert debounce. No AUTH, mailbox selection, message retrieval, MAIL/RCPT/DATA, synthetic delivery or credentials are used. Only static error classifications are reported.

The deployed v0.15.5 configuration explicitly distinguishes submission STARTTLS from IMAPS implicit TLS. SMTP reset/re-EHLO semantics follow [RFC 3207](https://www.rfc-editor.org/rfc/rfc3207); anonymous IMAP CAPABILITY/tagged completion follows [RFC 9051](https://www.rfc-editor.org/rfc/rfc9051). [Pinned v0.15.5 TLS resolver source](https://github.com/stalwartlabs/stalwart/blob/v0.15.5/crates/common/src/listener/tls.rs) confirms SNI certificate selection and self-signed fallback when no configured certificate exists. [Stalwart TLS certificate documentation](https://stalw.art/docs/server/tls/certificates/) describes certificate selection and self-signed fallback. Source-controlled listener and Migadu fetch/relay settings are in config/stalwart-mail/manifests/.

## Local TLS trust rollout prerequisite

A read-only live probe from the collector confirmed the local listener presents a self-signed certificate. Provision its authenticated public certificate/issuing CA PEM as the `stalwart_mail_ca` key in the optional `zabbix-functional-credentials` Secret in namespace `zabbix`. Obtain and verify it through a trusted administrator channel; do not blindly trust the certificate obtained over the monitored connection. For example, save the verified certificate to `/private/tmp/stalwart-mail-ca.pem`, then merge this key while preserving other service credentials:

```sh
kubectl -n zabbix create secret generic zabbix-functional-credentials --from-file=stalwart_mail_ca=/private/tmp/stalwart-mail-ca.pem --dry-run=client -o json | jq '{data: .data}' > /private/tmp/stalwart-mail-trust-patch.json
kubectl -n zabbix patch secret zabbix-functional-credentials --type=merge --patch-file=/private/tmp/stalwart-mail-trust-patch.json
```

Create the Secret first if it does not exist. Secret volume projection supplies updates without copying mailbox passwords. To revoke trust, remove only this key. Certificate renewal/rotation may require replacing the trusted self-signed certificate. The monitor retains normal chain, validity and hostname validation with TLS >=1.2; local SNI is `mail.newjoy.ro`, independently of the cluster DNS connection address. Migadu uses public system trust and its configured upstream hostname. A missing approved public CA reports deferred informational/dashboard coverage without connecting to those local TLS endpoints. Supplied invalid PEM, name mismatch, expiry or untrusted certificates remain real local TLS failures; no verification bypass exists. If the fallback certificate does not cover `mail.newjoy.ro`, install a correctly named certificate on Stalwart before rollout. No new NetworkPolicy or RBAC is required: the mail namespace has no ingress-restricting policy, collector egress is unrestricted, and probes use sockets only.

## Limits and existing passive receiving signal

These checks establish listener/protocol/TLS functionality and upstream availability, not mailbox authentication, durable ingestion, outbound relay authorization or end-to-end mail delivery. Closing an anonymous IMAP session after CAPABILITY touches no mailbox state. No mail or addresses enter monitoring output.

The existing incoming activity, fetchmail/Stalwart failure-log and TCP checks are untouched. In particular receiving activity remains 24/7 with the initial 24-hour silence threshold and exactly the existing adaptive-gap policy described in [Zabbix monitoring](../zabbix-monitoring.md#incoming-mail-activity). No new activity is generated and no absence-of-mail threshold changes.

Missing local public trust affects only the configured CA-dependent STARTTLS and
IMAPS observations. Plaintext SMTP and upstream Migadu probes continue unchanged.
The monitor does not obtain or trust a certificate from the monitored connection
to clear the advisory, and it provisions no credentials or CA material.
