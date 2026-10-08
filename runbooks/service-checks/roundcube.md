# Roundcube functional baseline

Depends on the shared functional-check runner (foundation PR #124). Every five
minutes, within a 25-second worker deadline, two checks run:

- **Roundcube OAuth bootstrap** requests the internal service anonymously with
  the configured public Host and HTTPS proxy header. It requires a Roundcube
  session cookie and a 302 authorization-code redirect to the configured Pocket
  ID endpoint, with the exact callback, scopes, client ID, state, nonce and S256
  PKCE challenge. A generic 200 login/error page is a failure. It never follows
  the authorization redirect or supplies household credentials.
- **Roundcube IMAP OAuth capability** connects to the configured Stalwart IMAP
  service on port 143, checks the greeting, sends only `CAPABILITY`, and requires
  tagged success, IMAP4rev1 or IMAP4rev2, and `AUTH=OAUTHBEARER`. This checks the
  actual configured mail protocol rather than duplicating the existing TCP probe.

The runner applies existing three-failure alert debounce and stale-result checks.
HTTP is capped at 32 KiB/6 seconds; IMAP at twelve response lines, 4096 bytes per
line and four seconds per operation, additionally bounded by remaining time.
Output contains only fixed descriptions, never cookies, redirect parameters,
mailbox identifiers, protocol banners or exception text.

No credentials, additional RBAC, or NetworkPolicies are required: neither
Roundcube nor Stalwart currently has restrictive ingress policy, and collector
egress is unrestricted. If ingress isolation is introduced, permit only the
Zabbix collector namespace/pod on Roundcube TCP 80 and Stalwart TCP 143. Keep the
HTTP callback/host and IMAP destination in sync with Roundcube configuration.

This proves anonymous application/session bootstrap and backend compatibility.
It does not prove Pocket ID token exchange, authenticated session persistence,
user-specific IMAP access, mailbox reads, SMTP sending, or external ingress.
The session cookie is created during normal anonymous login bootstrap; no login
attempt, mailbox access, email send, or user modification occurs. No dedicated
account is provisioned: full OAuth mailbox testing would require an interactive
identity/token lifecycle and is outside this baseline. Existing Stalwart mail
activity and failure checks remain unchanged.

Validation on 2026-10-08 read the deployed Roundcube OAuth implementation and
requested its loopback entrypoint with these proxy headers: it returned the
expected session cookie and PKCE authorization redirect. A CAPABILITY request
from the Roundcube pod to its configured backend completed successfully and
advertised IMAP4rev1, IMAP4rev2 and AUTH=OAUTHBEARER. These observations establish
protocol semantics; the collector module has not been deployed or live-run.
