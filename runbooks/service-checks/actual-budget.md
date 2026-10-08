# Actual Budget functional baseline

Every five minutes, bounded by a 30-second worker deadline, the collector checks three contracts. Existing Zabbix discovery and three-failure debounce apply.

- `/info` must return the Actual sync-server build name and a version, and `/account/needs-bootstrap` must report a bootstrapped server with password login available. This exercises the account database and headless login configuration beyond `/health`.
- A dedicated BASIC session must validate through `/account/validate`, then return an empty `/sync/list-user-files` listing. Missing/expired credentials, an elevated role, malformed responses, or any budget access fail. Budget identifiers, names, account details, and tokens never enter result output.
- An anonymous JSON-RPC `tools/list` POST to MCP `/http` must return its deployed JSON 401 missing-authorization error. This detects a broken transport or accidentally unprotected endpoint; it does not prove authenticated catalog or Actual connectivity.

## Credential prerequisite

Before rollout, use Actual's administrator UI to create a dedicated `Zabbix monitor` BASIC user with no owned/shared budgets. Use its dedicated authentication identity to obtain a session token once via the supported Actual login workflow. Store only that token in `zabbix/zabbix-functional-credentials`, key `actual_budget_monitor_session`, using a local file and `kubectl create secret generic ... --from-file=actual_budget_monitor_session=/secure/path/token --dry-run=client -o yaml | kubectl apply -f -` (preserve other service keys when updating an existing Secret). Do not place passwords/tokens in command arguments, git, or logs. Sessions can expire; rotate via the same dedicated workflow. Revoke the session in Actual's user/session administration and remove the Secret key to retire it. No Secret API read RBAC is added.

Actual 26.8 has BASIC/ADMIN roles, not a read-only financial token scope. No household budget access is granted, and Baloo's password/session/MCP bearer is not copied. The monitor uses GET only on authenticated Actual endpoints. The MCP bearer grants broad financial operations; authenticated catalog coverage is deferred until the adapter offers a separately scoped catalog-only identity. No tools are called, no budgets downloaded, and no financial mutations, syncs or bank requests occur.

Source semantics were verified from the running Actual 26.8.0 application source maps (`app-account`, `app-sync`, `validate-user`, `app.ts`) and MCP 0.9.6 `dist/src/server/httpServer.js`. API source was inspected live; HTTP behavior was validated with fixtures only. No destination ingress NetworkPolicy currently isolates Actual pods, so no access policy expansion is required. This baseline cannot prove household budget sync, bank integration, or MCP tool execution.
