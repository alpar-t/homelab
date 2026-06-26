#!/usr/bin/env node
"use strict";

// Auth bridge: exchanges GitHub App credentials for a short-lived installation
// token, then starts the standard @modelcontextprotocol/server-github with
// GITHUB_PERSONAL_ACCESS_TOKEN set. Installation tokens are API-identical to
// PATs and expire in 1 hour — fine since this process restarts per conversation.

const { createSign } = require("crypto");
const { readFileSync } = require("fs");
const { request }    = require("https");
const { spawn }      = require("child_process");

const APP_ID     = process.env.GITHUB_APP_ID;
const INSTALL_ID = process.env.GITHUB_APP_INSTALLATION_ID;
const KEY_PATH   = process.env.GITHUB_APP_PRIVATE_KEY_FILE;

if (!APP_ID || !INSTALL_ID || !KEY_PATH) {
  process.stderr.write("Required: GITHUB_APP_ID, GITHUB_APP_INSTALLATION_ID, GITHUB_APP_PRIVATE_KEY_FILE\n");
  process.exit(1);
}

const privateKey = readFileSync(KEY_PATH, "utf8");

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

function post(path, bearer) {
  return new Promise((resolve, reject) => {
    const req = request(
      {
        hostname: "api.github.com", path, method: "POST",
        headers: {
          Authorization:          `Bearer ${bearer}`,
          "User-Agent":           "baloo-mcp-auth/1",
          Accept:                 "application/vnd.github+json",
          "X-GitHub-Api-Version": "2022-11-28",
          "Content-Length":       "0",
        },
      },
      res => {
        const chunks = [];
        res.on("data", c => chunks.push(c));
        res.on("end", () => {
          const body = Buffer.concat(chunks).toString();
          if (res.statusCode >= 400) return reject(new Error(`GitHub ${res.statusCode}: ${body}`));
          resolve(JSON.parse(body));
        });
      },
    );
    req.on("error", reject);
    req.end();
  });
}

(async () => {
  const data  = await post(`/app/installations/${INSTALL_ID}/access_tokens`, makeJwt());
  const child = spawn("npx", ["-y", "@modelcontextprotocol/server-github"], {
    stdio: "inherit",
    env:   { ...process.env, GITHUB_PERSONAL_ACCESS_TOKEN: data.token },
  });
  child.on("exit", code => process.exit(code ?? 0));
})().catch(err => {
  process.stderr.write(`github-mcp-start: ${err.message}\n`);
  process.exit(1);
});
