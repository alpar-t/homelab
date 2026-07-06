#!/usr/bin/env node
"use strict";

/*
 * github-mcp-proxy — stdio↔stdio MCP bridge that keeps the stock GitHub MCP
 * server authenticated with a never-stale GitHub App installation token.
 *
 * ──────────────────────────────────────────────────────────────────────────────
 * Why this exists (so future-us knows when to delete it):
 *
 *   Baloo talks to GitHub through the stock `@modelcontextprotocol/server-github`,
 *   which reads its credential once from `GITHUB_PERSONAL_ACCESS_TOKEN` at startup
 *   and never re-reads it. We authenticate as a GitHub App, and App *installation
 *   tokens expire after exactly 1 hour* — there is no refresh, they just die.
 *
 *   The previous wrapper (`github-mcp-start.js`) minted one installation token and
 *   `exec`'d the stock server with it baked into the env. Its comment assumed the
 *   process "restarts per conversation", but OpenClaw stdio MCP children are
 *   *session*-scoped, reaped only after `mcp.sessionIdleTtlMs` of idle time
 *   (openclaw.json sets 1h). So any session that stayed warm longer than ~1h since
 *   the child spawned handed a dead token to the GitHub API → `Bad credentials`,
 *   which is exactly the intermittent PR-creation failure we saw.
 *
 *   This proxy fixes it the same way `trek-mcp-proxy.js` handles Trek's 1h bearer:
 *   an in-process MCP bridge that owns the token lifecycle. The difference is that
 *   Trek's upstream is HTTP (a refreshed token is just a new header on the next
 *   request), whereas the GitHub server's token is baked into a child process at
 *   spawn. So "refresh" here means *recycling the child*: we run a background timer
 *   that, shortly before the current token expires, spawns a fresh stock server
 *   with a newly minted token, swaps it in, and drains + retires the old one —
 *   all under a single stdio session with OpenClaw that never drops.
 *
 *   Timer (not lazy) refresh is deliberate: the token is always fresh *before* a
 *   tool call arrives, so PR creation never eats a token-mint + child-respawn on
 *   the request's critical path.
 *
 * When to remove:
 *
 *   When OpenClaw (or the stock GitHub MCP server) gains native GitHub App auth
 *   with automatic installation-token refresh. At that point wire the App creds
 *   directly and delete this file + its openclaw.json `github-life` entry.
 *
 * ──────────────────────────────────────────────────────────────────────────────
 * Required env (set on the openclaw container; OpenClaw passes through to stdio
 * MCP children):
 *     GITHUB_APP_ID, GITHUB_APP_INSTALLATION_ID, GITHUB_APP_PRIVATE_KEY_FILE
 */

const { createSign } = require("crypto");
const { readFileSync } = require("fs");
const { request } = require("https");

// OpenClaw strips NODE_PATH from stdio MCP children for startup safety, so we
// can't lean on it to locate the @modelcontextprotocol/sdk bundled in the
// openclaw image. Anchor our requires at the image's module dir explicitly
// (same trick as trek-mcp-proxy.js).
const { createRequire } = require("module");
const req = createRequire(
  `${process.env.OPENCLAW_NODE_MODULES || "/app/node_modules"}/github-mcp-proxy-anchor.js`
);

const { Client } = req("@modelcontextprotocol/sdk/client/index.js");
const { StdioClientTransport } = req("@modelcontextprotocol/sdk/client/stdio.js");
const { Server } = req("@modelcontextprotocol/sdk/server/index.js");
const { StdioServerTransport } = req("@modelcontextprotocol/sdk/server/stdio.js");
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

const APP_ID = process.env.GITHUB_APP_ID;
const INSTALL_ID = process.env.GITHUB_APP_INSTALLATION_ID;
const KEY_PATH = process.env.GITHUB_APP_PRIVATE_KEY_FILE;

// The stock GitHub MCP server to spawn as our upstream.
const UPSTREAM_CMD = process.env.GITHUB_MCP_COMMAND || "npx";
const UPSTREAM_ARGS = process.env.GITHUB_MCP_ARGS
  ? process.env.GITHUB_MCP_ARGS.split(" ")
  : ["-y", "@modelcontextprotocol/server-github"];

// Recycle the upstream this many ms before the installation token expires, so a
// fresh token is always in place before any request arrives. GitHub tokens last
// 1h; 5 min of headroom comfortably covers mint + child spawn + handshake.
const REFRESH_SAFETY_MS = 5 * 60 * 1000;
// If a scheduled refresh fails (transient GitHub/network error), retry soon
// rather than limping on toward expiry.
const REFRESH_RETRY_MS = 60 * 1000;

if (!APP_ID || !INSTALL_ID || !KEY_PATH) {
  process.stderr.write(
    "github-mcp-proxy: GITHUB_APP_ID, GITHUB_APP_INSTALLATION_ID, GITHUB_APP_PRIVATE_KEY_FILE are required\n"
  );
  process.exit(1);
}

const privateKey = readFileSync(KEY_PATH, "utf8");
const log = (msg) => process.stderr.write(`github-mcp-proxy: ${msg}\n`);

// ── GitHub App auth: JWT → installation access token ────────────────────────

function b64url(buf) {
  return buf.toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function makeJwt() {
  const now = Math.floor(Date.now() / 1000);
  const hdr = b64url(Buffer.from(JSON.stringify({ alg: "RS256", typ: "JWT" })));
  const pay = b64url(Buffer.from(JSON.stringify({ iat: now - 60, exp: now + 600, iss: APP_ID })));
  const sig = b64url(createSign("RSA-SHA256").update(`${hdr}.${pay}`).sign(privateKey));
  return `${hdr}.${pay}.${sig}`;
}

function ghPost(path, bearer) {
  return new Promise((resolve, reject) => {
    const r = request(
      {
        hostname: "api.github.com",
        path,
        method: "POST",
        headers: {
          Authorization: `Bearer ${bearer}`,
          "User-Agent": "baloo-mcp-auth/1",
          Accept: "application/vnd.github+json",
          "X-GitHub-Api-Version": "2022-11-28",
          "Content-Length": "0",
        },
      },
      (res) => {
        const chunks = [];
        res.on("data", (c) => chunks.push(c));
        res.on("end", () => {
          const body = Buffer.concat(chunks).toString();
          if (res.statusCode >= 400) return reject(new Error(`GitHub ${res.statusCode}: ${body}`));
          resolve(JSON.parse(body));
        });
      }
    );
    r.on("error", reject);
    r.end();
  });
}

// Returns { token, expiresAt } — expiresAt is epoch-ms from GitHub's `expires_at`
// (falls back to now + 1h if the field is ever missing).
async function mintToken() {
  const data = await ghPost(`/app/installations/${INSTALL_ID}/access_tokens`, makeJwt());
  const expiresAt = data.expires_at ? Date.parse(data.expires_at) : Date.now() + 3600 * 1000;
  return { token: data.token, expiresAt };
}

// ── Upstream (stock GitHub MCP server) lifecycle ────────────────────────────

// Spawn the stock server with a fresh token and complete the MCP handshake.
// The transport merges getDefaultEnvironment() (PATH/HOME/etc.) with our env,
// so we only inject the token. Track in-flight requests on the client so a
// recycled upstream is closed only after its outstanding calls drain.
async function spawnUpstream(token) {
  const transport = new StdioClientTransport({
    command: UPSTREAM_CMD,
    args: UPSTREAM_ARGS,
    env: { GITHUB_PERSONAL_ACCESS_TOKEN: token },
    stderr: "inherit",
  });
  const client = new Client({ name: "github-mcp-proxy", version: "1.0.0" }, { capabilities: {} });
  client.__inflight = 0;
  client.__retiring = false;
  await client.connect(transport);
  return client;
}

// Close an upstream once it has no in-flight requests (called during recycle).
function retire(client) {
  client.__retiring = true;
  if (client.__inflight === 0) {
    client.close().catch((e) => log(`error closing retired upstream: ${e?.message || e}`));
  }
}

(async () => {
  let refreshTimer = null;

  // Initial upstream: mint a token, spawn the stock server, arm the refresh
  // timer for shortly before this token's expiry.
  const first = await mintToken();
  let upstream = await spawnUpstream(first.token);
  scheduleRefresh(first.expiresAt);

  function scheduleRefresh(expiresAt) {
    if (refreshTimer) clearTimeout(refreshTimer);
    const delay = Math.max(expiresAt - Date.now() - REFRESH_SAFETY_MS, 1000);
    log(`token valid until ${new Date(expiresAt).toISOString()}; refreshing in ${Math.round(delay / 1000)}s`);
    refreshTimer = setTimeout(recycle, delay);
    refreshTimer.unref?.();
  }

  async function recycle() {
    try {
      const { token, expiresAt } = await mintToken();
      const next = await spawnUpstream(token);
      wireNotifications(next);
      watchClose(next);
      const prev = upstream;
      upstream = next; // atomic swap: new requests go to the fresh child
      retire(prev); // drain + close the old child
      scheduleRefresh(expiresAt);
      log("upstream recycled with fresh token");
    } catch (err) {
      log(`refresh failed (${err?.message || err}); retrying in ${REFRESH_RETRY_MS / 1000}s`);
      if (refreshTimer) clearTimeout(refreshTimer);
      refreshTimer = setTimeout(recycle, REFRESH_RETRY_MS);
      refreshTimer.unref?.();
    }
  }

  // If the *active* upstream dies unexpectedly (not one we're retiring), we
  // can't serve requests — exit so OpenClaw respawns the whole proxy fresh.
  // Bind each handler to its specific child: a retired child closing after a
  // swap must not be mistaken for the current one dying.
  function onUpstreamClose(client) {
    if (client === upstream && !client.__retiring) {
      log("active upstream closed unexpectedly; exiting for respawn");
      process.exit(0);
    }
  }
  function watchClose(client) {
    client.onclose = () => onUpstreamClose(client);
  }
  watchClose(upstream);

  // ── Build the local server from the upstream's advertised capabilities ────
  const caps = upstream.getServerCapabilities() ?? {};
  const serverInfo = upstream.getServerVersion() ?? { name: "github", version: "1.0.0" };
  const instructions = upstream.getInstructions();
  log(`upstream connected; capabilities: ${Object.keys(caps).join(", ") || "(none)"}`);

  const local = new Server(
    { name: serverInfo.name || "github", version: serverInfo.version || "1.0.0" },
    { capabilities: caps, instructions }
  );

  // Forward a request method through to whatever upstream is current, tracking
  // in-flight count so a retiring child stays alive until its calls finish.
  function forwardRequest(schema, method) {
    local.setRequestHandler(schema, async (r, extra) => {
      const params = r.params ?? {};
      const signal = extra?.signal;
      const u = upstream; // capture: this call belongs to the current child
      u.__inflight++;
      try {
        // ResultSchema is the SDK's passthrough base result — keeps every
        // upstream field without re-validating the method-specific shape.
        return await u.request({ method, params }, ResultSchema, { signal });
      } finally {
        u.__inflight--;
        if (u.__retiring && u.__inflight === 0) {
          u.close().catch((e) => log(`error closing drained upstream: ${e?.message || e}`));
        }
      }
    });
  }

  // Wire server→client notifications from a given upstream to the local server.
  // Re-applied to each freshly spawned child on recycle.
  function wireNotifications(client) {
    const fwd = (schema) =>
      client.setNotificationHandler(schema, async (n) => {
        await local.notification({ method: n.method, params: n.params });
      });
    fwd(ProgressNotificationSchema);
    if (caps.tools?.listChanged) fwd(ToolListChangedNotificationSchema);
    if (caps.resources?.listChanged) fwd(ResourceListChangedNotificationSchema);
    if (caps.resources?.subscribe) fwd(ResourceUpdatedNotificationSchema);
    if (caps.prompts?.listChanged) fwd(PromptListChangedNotificationSchema);
    if (caps.logging) fwd(LoggingMessageNotificationSchema);
  }

  // Request handlers — forward what the upstream advertises. ping is mandatory.
  forwardRequest(PingRequestSchema, "ping");
  if (caps.tools) {
    forwardRequest(ListToolsRequestSchema, "tools/list");
    forwardRequest(CallToolRequestSchema, "tools/call");
  }
  if (caps.resources) {
    forwardRequest(ListResourcesRequestSchema, "resources/list");
    forwardRequest(ListResourceTemplatesRequestSchema, "resources/templates/list");
    forwardRequest(ReadResourceRequestSchema, "resources/read");
    if (caps.resources.subscribe) {
      forwardRequest(SubscribeRequestSchema, "resources/subscribe");
      forwardRequest(UnsubscribeRequestSchema, "resources/unsubscribe");
    }
  }
  if (caps.prompts) {
    forwardRequest(ListPromptsRequestSchema, "prompts/list");
    forwardRequest(GetPromptRequestSchema, "prompts/get");
  }
  if (caps.completions) {
    forwardRequest(CompleteRequestSchema, "completion/complete");
  }
  if (caps.logging) {
    forwardRequest(SetLevelRequestSchema, "logging/setLevel");
  }

  wireNotifications(upstream);

  await local.connect(new StdioServerTransport());
  log("stdio bridge ready");
})().catch((err) => {
  log(`fatal: ${err?.stack || err?.message || err}`);
  process.exit(1);
});
