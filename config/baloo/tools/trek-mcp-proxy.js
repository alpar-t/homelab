#!/usr/bin/env node
"use strict";

/*
 * trek-mcp-proxy — stdio↔HTTP MCP bridge with in-process OAuth client_credentials.
 *
 * ──────────────────────────────────────────────────────────────────────────────
 * Why this exists (so future-us knows when to delete it):
 *
 *   OpenClaw 2026.6.10's MCP client (config in openclaw.json `mcp.servers.*`)
 *   supports exactly two HTTP auth modes — see /app/docs/cli/mcp.md inside the
 *   openclaw image:
 *
 *     1. Static `headers` — fixed Authorization header. No refresh, ever.
 *     2. `auth: "oauth"` — interactive authorization_code grant with
 *        Dynamic Client Registration and a localhost callback URL. Useless
 *        in a pod (no browser, no callback), and OpenClaw does not auto-
 *        refresh the resulting tokens. Previously needed a 30-min cron
 *        sidecar to keep the refresh_token alive (commit 8111e64, reverted
 *        in 8422f4e).
 *
 *   Trek's MCP server now offers OAuth `client_credentials` — machine-to-
 *   machine, no user flow, no refresh_token, just POST creds → 1h bearer.
 *   OpenClaw has no native config for this grant, so we run an in-process
 *   stdio↔HTTP bridge that handles the token lifecycle itself.
 *
 *   The `@modelcontextprotocol/sdk` client does support client_credentials
 *   via OAuthClientProvider.prepareTokenRequest(); we lean on that and add
 *   our own expiry-aware `tokens()` so refresh happens before requests fly
 *   instead of reacting to 401s.
 *
 * When to remove:
 *
 *   When OpenClaw gains first-class client_credentials support for HTTP MCP
 *   servers (e.g. `auth: "client_credentials"` with `clientId`/`clientSecret`
 *   fields on `mcp.servers.<name>`). At that point:
 *
 *     • Replace the openclaw.json entry with the native config.
 *     • Delete this file and the TREK_CLIENT_ID/TREK_CLIENT_SECRET env wiring
 *       from the openclaw container; keep them in baloo-secrets only.
 *
 *   Track upstream: https://github.com/openclaw/openclaw (search for
 *   "client_credentials" or "machine-to-machine"). The relevant docs file
 *   inside the running image is `/app/docs/cli/mcp.md` — diff it on upgrade.
 *
 * ──────────────────────────────────────────────────────────────────────────────
 * How it works:
 *
 *   • Spins up an upstream MCP Client over StreamableHTTPClientTransport
 *     pointed at Trek (TREK_MCP_URL), with our OAuthClientProvider that
 *     mints + refreshes Bearer tokens on demand.
 *   • Spins up a local MCP Server over StdioServerTransport, advertising
 *     the same capabilities + instructions that Trek announces upstream.
 *   • Forwards every request method Trek supports (tools, resources,
 *     prompts, completions, ping, logging) and every list-changed /
 *     update / log / progress notification in both directions.
 *
 *   Required env (set on the openclaw container; OpenClaw passes through
 *   to stdio MCP children):
 *     TREK_CLIENT_ID, TREK_CLIENT_SECRET
 *   Optional env (defaults are correct for travel.newjoy.ro):
 *     TREK_MCP_URL, TREK_TOKEN_URL
 */

const {
  Client,
} = require("@modelcontextprotocol/sdk/client/index.js");
const {
  StreamableHTTPClientTransport,
} = require("@modelcontextprotocol/sdk/client/streamableHttp.js");
const {
  Server,
} = require("@modelcontextprotocol/sdk/server/index.js");
const {
  StdioServerTransport,
} = require("@modelcontextprotocol/sdk/server/stdio.js");
const {
  CallToolRequestSchema,
  CompleteRequestSchema,
  GetPromptRequestSchema,
  ListPromptsRequestSchema,
  ListResourceTemplatesRequestSchema,
  ListResourcesRequestSchema,
  ListToolsRequestSchema,
  LoggingMessageNotificationSchema,
  PingRequestSchema,
  ProgressNotificationSchema,
  PromptListChangedNotificationSchema,
  ReadResourceRequestSchema,
  ResourceListChangedNotificationSchema,
  ResourceUpdatedNotificationSchema,
  SetLevelRequestSchema,
  SubscribeRequestSchema,
  ToolListChangedNotificationSchema,
  UnsubscribeRequestSchema,
} = require("@modelcontextprotocol/sdk/types.js");

const MCP_URL    = process.env.TREK_MCP_URL   || "https://travel.newjoy.ro/mcp";
const TOKEN_URL  = process.env.TREK_TOKEN_URL || "https://travel.newjoy.ro/oauth/token";
const CLIENT_ID  = process.env.TREK_CLIENT_ID;
const CLIENT_SEC = process.env.TREK_CLIENT_SECRET;
// Refresh this many seconds before the declared expiry. Keeps in-flight
// requests from racing a token rotation.
const REFRESH_SAFETY_SEC = 60;

if (!CLIENT_ID || !CLIENT_SEC) {
  process.stderr.write("trek-mcp-proxy: TREK_CLIENT_ID and TREK_CLIENT_SECRET are required\n");
  process.exit(1);
}

const log = (msg) => process.stderr.write(`trek-mcp-proxy: ${msg}\n`);

/*
 * OAuthClientProvider for the client_credentials grant.
 *
 * The SDK calls `tokens()` on every outbound request and `prepareTokenRequest()`
 * when it needs to mint a fresh token (initially or after a 401 / clear).
 * Returning a still-valid cached token from `tokens()` lets the SDK reuse it;
 * returning undefined forces the SDK into its `auth()` flow, which calls our
 * `prepareTokenRequest()` and POSTs to the token endpoint.
 */
class ClientCredentialsProvider {
  constructor({ clientId, clientSecret, tokenUrl }) {
    this._clientId     = clientId;
    this._clientSecret = clientSecret;
    this._tokenUrl     = tokenUrl;
    this._tokens       = undefined;
    this._expiresAt    = 0;
  }

  // Unused for client_credentials but required by the interface.
  get redirectUrl() { return ""; }

  get clientMetadata() {
    return {
      client_name:                "trek-mcp-proxy",
      redirect_uris:              [],
      grant_types:                ["client_credentials"],
      token_endpoint_auth_method: "client_secret_post",
    };
  }

  // Pre-registered static creds — no Dynamic Client Registration needed.
  clientInformation() {
    return { client_id: this._clientId, client_secret: this._clientSecret };
  }
  saveClientInformation() { /* static creds, nothing to persist */ }

  async tokens() {
    if (this._tokens && Date.now() < this._expiresAt) return this._tokens;
    return undefined;
  }

  async saveTokens(tokens) {
    this._tokens = tokens;
    const ttl = Math.max((tokens.expires_in ?? 3600) - REFRESH_SAFETY_SEC, 60);
    this._expiresAt = Date.now() + ttl * 1000;
    log(`token cached, will refresh in ${ttl}s`);
  }

  prepareTokenRequest() {
    return new URLSearchParams({ grant_type: "client_credentials" });
  }

  // The remaining methods exist only because the SDK type marks them
  // required for authorization_code flows. They should never be called
  // when grant_types = ["client_credentials"].
  redirectToAuthorization() {
    throw new Error("trek-mcp-proxy: client_credentials grant does not use authorization redirects");
  }
  saveCodeVerifier() { /* no PKCE for client_credentials */ }
  codeVerifier() {
    throw new Error("trek-mcp-proxy: client_credentials grant does not use PKCE");
  }
}

/*
 * Forward `method` on the local server through to upstream.
 *
 * Each handler just relays the request payload (sans the `method` field, which
 * the SDK adds back) and returns the upstream result unchanged. The upstream
 * Client's `request()` accepts a full JSON-RPC request object including
 * `method`, so we pass `{ method, params }`.
 */
function forwardRequest(local, upstream, schema, method) {
  local.setRequestHandler(schema, async (req, extra) => {
    const params = req.params ?? {};
    const signal = extra?.signal;
    // The third arg is the *result* schema; we don't validate here, the SDK
    // already validated the request against `schema` and the upstream response
    // shape is the same as what we'd return locally.
    return await upstream.request({ method, params }, undefined, { signal });
  });
}

function forwardNotification(from, to, schema) {
  from.setNotificationHandler(schema, async (notif) => {
    await to.notification({ method: notif.method, params: notif.params });
  });
}

(async () => {
  const authProvider = new ClientCredentialsProvider({
    clientId:     CLIENT_ID,
    clientSecret: CLIENT_SEC,
    tokenUrl:     TOKEN_URL,
  });

  // Note: we declare client capabilities matching what we'll proxy back to
  // OpenClaw. Trek only consults the *server* capabilities it advertises;
  // these client caps mostly affect notification routing.
  const upstream = new Client(
    { name: "trek-mcp-proxy", version: "1.0.0" },
    { capabilities: { } }
  );

  const upstreamTransport = new StreamableHTTPClientTransport(
    new URL(MCP_URL),
    { authProvider }
  );

  log(`connecting to ${MCP_URL}`);
  await upstream.connect(upstreamTransport);

  const caps         = upstream.getServerCapabilities() ?? {};
  const serverInfo   = upstream.getServerVersion()      ?? { name: "trek", version: "1.0.0" };
  const instructions = upstream.getInstructions();
  log(`connected; capabilities: ${Object.keys(caps).join(", ") || "(none)"}`);

  const local = new Server(
    { name: serverInfo.name || "trek", version: serverInfo.version || "1.0.0" },
    { capabilities: caps, instructions }
  );

  // Request handlers — forward what the upstream advertises.
  // Always-on: ping. The MCP spec mandates ping support.
  forwardRequest(local, upstream, PingRequestSchema, "ping");

  if (caps.tools) {
    forwardRequest(local, upstream, ListToolsRequestSchema, "tools/list");
    forwardRequest(local, upstream, CallToolRequestSchema,  "tools/call");
  }
  if (caps.resources) {
    forwardRequest(local, upstream, ListResourcesRequestSchema,        "resources/list");
    forwardRequest(local, upstream, ListResourceTemplatesRequestSchema,"resources/templates/list");
    forwardRequest(local, upstream, ReadResourceRequestSchema,         "resources/read");
    if (caps.resources.subscribe) {
      forwardRequest(local, upstream, SubscribeRequestSchema,   "resources/subscribe");
      forwardRequest(local, upstream, UnsubscribeRequestSchema, "resources/unsubscribe");
    }
  }
  if (caps.prompts) {
    forwardRequest(local, upstream, ListPromptsRequestSchema, "prompts/list");
    forwardRequest(local, upstream, GetPromptRequestSchema,   "prompts/get");
  }
  if (caps.completions) {
    forwardRequest(local, upstream, CompleteRequestSchema, "completion/complete");
  }
  if (caps.logging) {
    forwardRequest(local, upstream, SetLevelRequestSchema, "logging/setLevel");
  }

  // Notifications — server→client only (these are the ones Trek may emit).
  forwardNotification(upstream, local, ProgressNotificationSchema);
  if (caps.tools?.listChanged) {
    forwardNotification(upstream, local, ToolListChangedNotificationSchema);
  }
  if (caps.resources?.listChanged) {
    forwardNotification(upstream, local, ResourceListChangedNotificationSchema);
  }
  if (caps.resources?.subscribe) {
    forwardNotification(upstream, local, ResourceUpdatedNotificationSchema);
  }
  if (caps.prompts?.listChanged) {
    forwardNotification(upstream, local, PromptListChangedNotificationSchema);
  }
  if (caps.logging) {
    forwardNotification(upstream, local, LoggingMessageNotificationSchema);
  }

  // Connection lifecycle — if upstream drops, exit so OpenClaw respawns us.
  upstream.onclose = () => { log("upstream closed; exiting"); process.exit(0); };
  upstream.onerror = (err) => log(`upstream error: ${err?.message || err}`);

  await local.connect(new StdioServerTransport());
  log("stdio bridge ready");
})().catch((err) => {
  log(`fatal: ${err?.stack || err?.message || err}`);
  process.exit(1);
});
