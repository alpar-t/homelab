# Pocket ID application access

Require explicit group membership for every Pocket ID OIDC client, including
mobile clients and unused duplicate registrations. Keep the authoritative
client-to-group mapping in `config/pocket-id/access-policy.json`. Pocket ID
stores the live policy in its backed-up database; it is not a Kubernetes setting.

Check the complete inventory and reconcile deliberate changes:

```bash
python3 scripts/reconcile-pocket-id-access.py
python3 scripts/reconcile-pocket-id-access.py --apply
scripts/test access-policy
scripts/test access-policy-live
```

The helper reads the existing API credential without printing it, rejects
unknown or missing clients before making changes, creates `kids` if necessary,
and verifies every applied group restriction. It preserves client registration,
credentials, and callbacks. Run the check after adding or editing clients. Add
new clients to the policy before reconciling; the shared OIDC provisioner creates
clients with group restrictions enabled and no allowed groups, so they deny
sign-in until deliberately granted access.

The `Check application access policy` GitHub workflow runs the local check on
pull requests and main pushes. It rejects new unclassified Ingress hosts,
enabled Helm ingresses without audited hosts, missing or mismatched proxy group
allowlists, and new shared-provisioner clients absent from the policy. Keep
endpoint authentication modes in `config/pocket-id/service-access-policy.json`;
public and independent-account exceptions are deliberately limited in the test.
Install `scripts/requirements-access-tests.txt` if PyYAML is unavailable locally.

The live test is opt-in because it requires administrator API access. It creates
temporary ordinary identities with non-deliverable email identifiers, exercises Pocket ID's
OIDC authorization preview for every client, and deletes the test users. It
checks both no-group denial and the kids group's restricted access. This tests
Pocket ID's authorization decision; it does not exercise every application's
existing sessions or independent authentication methods. UI-created clients
are covered by the live inventory audit, not by repository-only CI checks.

`pocket-id/pocket-id-access-check` runs a read-only audit daily at 06:00 Bucharest
time and fails if any live client disables group restrictions or has no allowed
groups. It has no Kubernetes API token and uses the existing Pocket ID API key
only for GET requests. Inspect its Job status and logs, or run it immediately:

```bash
kubectl -n pocket-id create job --from=cronjob/pocket-id-access-check pocket-id-access-check-manual
kubectl -n pocket-id logs job/pocket-id-access-check-manual
```

## Groups

- `kids`: portal, both Immich Photos clients, and shared media sign-in.
- `family_users`: household applications, including documents and budgets.
- `advanced_apps`: operations, website staging, and household applications.
- `opencloud_admin` and `opencloud_users_`: OpenCloud web and mobile/desktop clients.

Existing narrower client policies remain narrower: for example Docs, Webmail,
and Recipes allow `family_users`; Longhorn, Omada, Node-RED, and OTMonitor allow
`advanced_apps`. Do not attach `family_users` to a child who should not access
documents or budgets. An ordinary Pocket ID user with no groups must not be
allowed to sign in to any application client. Pocket ID's own account/passkey
settings remain available so the user can manage their identity.

The `kids` portal contains Immich, Emby, Radarr, Sonarr, Vaultwarden, and account
settings. Emby is available on the home network or travel WireGuard. The shared
Media client covers Radarr, Sonarr, Prowlarr, qBittorrent, and Maintainerr;
its group policy applies to all those public endpoints.

## Web proxies and sessions

Every managed oauth2-proxy requests `groups` and has explicit `--allowed-group`
arguments matching its client policy. This also rejects signed cookies whose
stored claims contain no allowed groups. Old cookies created without group
claims may require a new sign-in after deployment. Changes to membership are
not instant revocation of every application session: proxies and applications
may cache claims until refresh or session expiry. Check application sessions
separately when removing access from an existing user.

## Limits of SSO enforcement

Pocket ID group checks control SSO. They do not authorize independent accounts
or API keys in applications. In particular:

- Vaultwarden uses separate vault accounts; public signups are disabled and
  accounts must be invited. A Pocket ID group does not create a vault account.
- Emby and standalone Home Assistant use separate accounts.
- Actual keeps password authentication for Baloo's restricted BASIC identity;
  its internal MCP uses credentials, not Pocket ID. Do not remove password
  authentication without migrating that integration first.
- Native application logins, API keys, LAN/MetalLB endpoints, and established
  sessions must be audited separately before claiming all access requires a
  current Pocket ID group. Never place an interactive SSO proxy in front of a
  mobile/API service without verifying client compatibility.

Public landing pages, health endpoints, sign-in pages, and Pocket ID account
settings are intentionally reachable without application group membership.
The stale unmanaged Forecastle dashboard at `dashboard.newjoy.ro` is blocked by
an explicit Cloudflare Tunnel 404 rule before the wildcard ingress route.
