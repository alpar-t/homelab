# Portal functional checks

The collector samples every 10 minutes with a 30-second deadline and three-second
HTTP timeouts. Three failed samples trigger the existing Zabbix alert debounce.
No credentials or additional Kubernetes permissions are required. The portal has
no destination NetworkPolicy restricting the collector; no access policy changes
are introduced.

- `entry_assets`: internal shell semantic marker and its required theme script,
  application script and stylesheet must be nonempty and have expected MIME types.
- `catalog_contract`: internal `/catalog.json` requests use synthetic trusted-backend
  group headers for admin, family and kids. Validate sections/cards, capability
  policy coverage, referenced SVG icons. Direct
  backing-catalog access must remain 404. This deliberately exercises the backend
  contract; headers never go to the public endpoint. Catalog contents, link URLs,
  and response bodies are never reported.
- `public_signin_gate`: anonymous public entry must redirect to the same portal's
  `/oauth2/start` with its root return URL. Redirects are not followed.

Failures mean the shipped site/catalog/assets are unusable, inconsistent, or the
public authentication entry gate changed. This does not perform a user login or
prove OIDC group enforcement, correct role membership, JavaScript execution,
linked-service functionality or successful Pocket ID authorization. Asset requests
are tiny read-only operations; catalog links are never visited. Fixed asset paths
match the shipped portal contract, so an intentional frontend contract change
requires updating this monitor. No deployment was performed as part of validation.
