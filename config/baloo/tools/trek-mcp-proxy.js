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

// OpenClaw strips NODE_PATH from stdio MCP children for startup safety (it logs
// `env "NODE_PATH" is blocked for stdio startup safety and was ignored`), so we
// can't lean on it to locate the @modelcontextprotocol/sdk bundled in the
// openclaw image. Anchor our requires at the image's module dir explicitly.
const { createRequire } = require("module");
const req = createRequire(
  `${process.env.OPENCLAW_NODE_MODULES || "/app/node_modules"}/trek-mcp-proxy-anchor.js`
);

const {
  Client,
} = req("@modelcontextprotocol/sdk/client/index.js");
const {
  StreamableHTTPClientTransport,
} = req("@modelcontextprotocol/sdk/client/streamableHttp.js");
const {
  Server,
} = req("@modelcontextprotocol/sdk/server/index.js");
const {
  StdioServerTransport,
} = req("@modelcontextprotocol/sdk/server/stdio.js");
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
  ResultSchema,
} = req("@modelcontextprotocol/sdk/types.js");

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
function isStaleSessionError(error) {
  return error?.code === 404 && /session not found/i.test(error?.message || "");
}

function forwardRequest(local, upstreamManager, schema, method) {
  local.setRequestHandler(schema, async (req, extra) => {
    const params = req.params ?? {};
    const signal = extra?.signal;
    // The third arg is the *result* schema. It must be a real zod schema — the
    // SDK dereferences it internally (`._zod`), so passing `undefined` crashes
    // the response parse with "Cannot read properties of undefined (reading
    // '_zod')". `ResultSchema` is the SDK's passthrough base result, so it keeps
    // every upstream field (tools, contents, etc.) without re-validating the
    // full method-specific shape the request was already validated against.
    return await upstreamManager.request({ method, params }, ResultSchema, { signal });
  });
}

function forwardNotification(from, to, schema) {
  from.setNotificationHandler(schema, async (notif) => {
    await to.notification({ method: notif.method, params: notif.params });
  });
}

/*
 * Own the upstream Client/transport pair so a Trek restart does not poison the
 * long-lived stdio bridge. A missing server-side session is safe to retry: Trek
 * rejects it before executing the JSON-RPC request. Concurrent failures share
 * one reconnect, and each request is retried at most once.
 */
class UpstreamManager {
  constructor(authProvider) {
    this._authProvider = authProvider;
    this._client = undefined;
    this._transport = undefined;
    this._connectPromise = undefined;
    this._reconnectPromise = undefined;
    this._local = undefined;
    this._caps = undefined;
    this._closing = false;
  }

  async _connect() {
    const client = new Client(
      { name: "trek-mcp-proxy", version: "1.1.0" },
      { capabilities: {} }
    );
    const transport = new StreamableHTTPClientTransport(
      new URL(MCP_URL),
      { authProvider: this._authProvider }
    );

    client.onerror = (err) => log(`upstream error: ${err?.message || err}`);
    client.onclose = () => {
      if (this._client === client) {
        this._client = undefined;
        this._transport = undefined;
        if (!this._closing) log("upstream closed; next request will reconnect");
      }
    };

    log(`connecting to ${MCP_URL}`);
    await client.connect(transport);

    this._client = client;
    this._transport = transport;
    this._bindNotifications(client);
    log(`connected; session=${transport.sessionId || "(none)"}`);
    return client;
  }

  async getClient() {
    if (this._client) return this._client;
    if (!this._connectPromise) {
      this._connectPromise = this._connect().finally(() => {
        this._connectPromise = undefined;
      });
    }
    return await this._connectPromise;
  }

  bindLocal(local, caps) {
    this._local = local;
    this._caps = caps;
    if (this._client) this._bindNotifications(this._client);
  }

  _bindNotifications(client) {
    if (!this._local || !this._caps) return;
    const local = this._local;
    const caps = this._caps;

    forwardNotification(client, local, ProgressNotificationSchema);
    if (caps.tools?.listChanged) {
      forwardNotification(client, local, ToolListChangedNotificationSchema);
    }
    if (caps.resources?.listChanged) {
      forwardNotification(client, local, ResourceListChangedNotificationSchema);
    }
    if (caps.resources?.subscribe) {
      forwardNotification(client, local, ResourceUpdatedNotificationSchema);
    }
    if (caps.prompts?.listChanged) {
      forwardNotification(client, local, PromptListChangedNotificationSchema);
    }
    if (caps.logging) {
      forwardNotification(client, local, LoggingMessageNotificationSchema);
    }
  }

  async reconnect(reason, failedClient) {
    if (this._reconnectPromise) return await this._reconnectPromise;
    if (this._client && this._client !== failedClient) return this._client;

    this._reconnectPromise = (async () => {
      log(`${reason}; recreating upstream MCP session`);
      const oldClient = this._client;
      this._client = undefined;
      this._transport = undefined;
      if (oldClient) {
        try {
          await oldClient.close();
        } catch (error) {
          log(`old upstream close failed: ${error?.message || error}`);
        }
      }
      return await this.getClient();
    })().finally(() => {
      this._reconnectPromise = undefined;
    });

    return await this._reconnectPromise;
  }

  async request(message, resultSchema, options) {
    const client = await this.getClient();
    try {
      return await client.request(message, resultSchema, options);
    } catch (error) {
      if (!isStaleSessionError(error)) throw error;
      const replacement = await this.reconnect("Trek rejected stale session", client);
      return await replacement.request(message, resultSchema, options);
    }
  }

  async shutdown() {
    if (this._closing) return;
    this._closing = true;
    const client = this._client;
    const transport = this._transport;
    this._client = undefined;
    this._transport = undefined;

    if (transport?.sessionId) {
      try {
        await transport.terminateSession();
        log("upstream session terminated");
      } catch (error) {
        log(`upstream session termination failed: ${error?.message || error}`);
      }
    }
    if (client) {
      try {
        await client.close();
      } catch (error) {
        log(`upstream close failed: ${error?.message || error}`);
      }
    }
  }
}

(async () => {
  const authProvider = new ClientCredentialsProvider({
    clientId:     CLIENT_ID,
    clientSecret: CLIENT_SEC,
    tokenUrl:     TOKEN_URL,
  });

  const upstreamManager = new UpstreamManager(authProvider);
  const upstream = await upstreamManager.getClient();

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
  forwardRequest(local, upstreamManager, PingRequestSchema, "ping");

  if (caps.tools) {
    forwardRequest(local, upstreamManager, ListToolsRequestSchema, "tools/list");
    forwardRequest(local, upstreamManager, CallToolRequestSchema,  "tools/call");
  }
  if (caps.resources) {
    forwardRequest(local, upstreamManager, ListResourcesRequestSchema,         "resources/list");
    forwardRequest(local, upstreamManager, ListResourceTemplatesRequestSchema, "resources/templates/list");
    forwardRequest(local, upstreamManager, ReadResourceRequestSchema,          "resources/read");
    if (caps.resources.subscribe) {
      forwardRequest(local, upstreamManager, SubscribeRequestSchema,   "resources/subscribe");
      forwardRequest(local, upstreamManager, UnsubscribeRequestSchema, "resources/unsubscribe");
    }
  }
  if (caps.prompts) {
    forwardRequest(local, upstreamManager, ListPromptsRequestSchema, "prompts/list");
    forwardRequest(local, upstreamManager, GetPromptRequestSchema,   "prompts/get");
  }
  if (caps.completions) {
    forwardRequest(local, upstreamManager, CompleteRequestSchema, "completion/complete");
  }
  if (caps.logging) {
    forwardRequest(local, upstreamManager, SetLevelRequestSchema, "logging/setLevel");
  }

  upstreamManager.bindLocal(local, caps);

  const localTransport = new StdioServerTransport();
  let stopping = false;
  const stop = async (reason, exitCode) => {
    if (stopping) return;
    stopping = true;
    log(`${reason}; shutting down`);
    await upstreamManager.shutdown();
    process.exit(exitCode);
  };
  local.onclose = () => { void stop("stdio closed", 0); };
  process.once("SIGTERM", () => { void stop("SIGTERM", 0); });
  process.once("SIGINT",  () => { void stop("SIGINT",  0); });

  await local.connect(localTransport);
  log("stdio bridge ready");
})().catch((err) => {
  log(`fatal: ${err?.stack || err?.message || err}`);
  process.exit(1);
});
