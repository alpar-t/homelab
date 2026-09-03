# Actual Budget

[Actual Budget](https://actualbudget.org/) replaces Sure at
<https://finance.newjoy.ro>. It is the household expense and tracking-budget
ledger; trip-level expenses remain in TREK and are rolled up separately.

## Deployment shape

- `actual-budget` is the official sync server and web client.
- `actual-budget-data` contains the server files and is in Longhorn's
  `critical` recurring backup group.
- `actual-budget-mcp` is the unmodified community
  `agigante80/actual-mcp-server` v0.9.6 image. It tracks Actual 26.8's API,
  exposes split-transaction writes, and supports authenticated HTTP transport.
- The MCP has no Ingress. It is reachable only inside the cluster.
- The MCP is activated after the first budget supplies a Sync ID.
- MCP connections remain idle for 15 minutes. This exceeds Baloo's 9-minute
  MCP runtime lifetime, preventing Baloo from reusing a session after the
  community server has evicted it.
- Password is the primary server login method so headless API clients can
  authenticate; Pocket ID remains an allowed web login method.
- Baloo uses Actual's local password identity, not the Pocket ID user. The
  identity is named `Baloo`, has the `BASIC` role, is not an owner, and is
  granted access only to the configured household budget.

## First-run setup

1. Wait for the ArgoCD application to become Healthy and open
   <https://finance.newjoy.ro>.
2. Read the generated one-time server password:

   ```bash
   kubectl get secret actual-mcp-credentials -n actual-budget \
     -o jsonpath='{.data.server_password}' | base64 -d; echo
   ```

3. Log in, create the household budget, switch it to Tracking Budget, and set
   RON as its canonical currency.
4. In Settings -> Advanced, copy the budget Sync ID into the existing Secret:

   ```bash
   kubectl patch secret actual-mcp-credentials -n actual-budget \
     --type merge \
     -p '{"stringData":{"budget_sync_id":"REPLACE_WITH_SYNC_ID"}}'
   ```

5. Enable Pocket ID from Actual's settings. The `actual` client and callback
   `https://finance.newjoy.ro/openid/callback` are already provisioned.

The private Baloo repo already contains the disabled `actual` MCP definition
and explicit policies: only the `alpar` agent allows `actual__*`; every other
agent denies it. To finish MCP activation:

1. Copy `mcp_api_key` from `actual-budget/actual-mcp-credentials` into the
   `ACTUAL_MCP_API_KEY` key of `baloo/baloo-secrets`.
2. Expose that Secret key as `ACTUAL_MCP_API_KEY` on OpenClaw's
   `render-config` init container.
3. Change the MCP Deployment in `deployment.yaml` to one replica.
4. Change `mcp.servers.actual.enabled` to `true` in Baloo's `openclaw.json`.
5. Because this activation also changes a secret-backed environment value,
   wait for the Reloader rollout (or roll out OpenClaw once). The subsequent
   `openclaw.json` enablement itself hot-reloads and does not require a restart.

## Recovery

The server PVC is backed up by Longhorn. Once the first budget exists, add a
scheduled application-level Actual ZIP export as a second recovery path.

Sure's former CNPG backups remain in B2 under
`s3://homelab-longhorn-backup/cnpg/sure-db` for their configured retention
window, but the live Sure namespace and PVCs are pruned when this change is
synced.
