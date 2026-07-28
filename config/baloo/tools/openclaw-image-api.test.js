"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const { createImageApiServer } = require("./openclaw-image-api.js");

async function listen(server) {
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  return `http://127.0.0.1:${server.address().port}`;
}

async function close(server) {
  await new Promise((resolve) => server.close(resolve));
}

async function fixture() {
  const workRoot = await fs.mkdtemp(path.join(os.tmpdir(), "openclaw-image-api-test-"));
  const calls = [];
  const execute = async (_node, args) => {
    calls.push(args);
    const outputIndex = args.indexOf("--output");
    assert.notEqual(outputIndex, -1);
    const outputPath = `${args[outputIndex + 1]}.png`;
    await fs.writeFile(outputPath, Buffer.from("generated-image"));
    return {
      stdout: JSON.stringify({
        ok: true,
        capability: args.includes("edit") ? "image.edit" : "image.generate",
        provider: "openai",
        model: "gpt-image-2",
        outputs: [
          {
            path: outputPath,
            mimeType: "image/png",
            size: 15,
            revisedPrompt: "revised",
          },
        ],
      }),
      stderr: "",
    };
  };

  const env = {
    IMAGE_API_TOKEN: "test-token",
    OPENCLAW_IMAGE_MODEL: "openai/gpt-image-2",
    IMAGE_API_WORK_ROOT: workRoot,
  };
  const server = createImageApiServer({ env, execute });
  const baseUrl = await listen(server);
  return { server, baseUrl, calls, workRoot };
}

test("health does not require authentication", async (t) => {
  const ctx = await fixture();
  t.after(async () => {
    await close(ctx.server);
    await fs.rm(ctx.workRoot, { recursive: true, force: true });
  });

  const response = await fetch(`${ctx.baseUrl}/health`);
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { ok: true, active: 0, queued: 0 });
});

test("generation returns an OpenAI-compatible base64 response", async (t) => {
  const ctx = await fixture();
  t.after(async () => {
    await close(ctx.server);
    await fs.rm(ctx.workRoot, { recursive: true, force: true });
  });

  const response = await fetch(`${ctx.baseUrl}/v1/images/generations`, {
    method: "POST",
    headers: {
      Authorization: "Bearer test-token",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model: "gpt-image-2",
      prompt: "A warm reading corner",
      n: 1,
      size: "1024x1024",
      quality: "high",
      response_format: "b64_json",
    }),
  });

  assert.equal(response.status, 200);
  const body = await response.json();
  assert.equal(
    Buffer.from(body.data[0].b64_json, "base64").toString(),
    "generated-image",
  );
  assert.equal(body.data[0].revised_prompt, "revised");

  const args = ctx.calls[0];
  assert.ok(args.includes("generate"));
  assert.deepEqual(
    args.slice(args.indexOf("--model"), args.indexOf("--model") + 2),
    ["--model", "openai/gpt-image-2"],
  );
  assert.deepEqual(
    args.slice(args.indexOf("--size"), args.indexOf("--size") + 2),
    ["--size", "1024x1024"],
  );
});

test("editing accepts Open WebUI multipart image fields", async (t) => {
  const ctx = await fixture();
  t.after(async () => {
    await close(ctx.server);
    await fs.rm(ctx.workRoot, { recursive: true, force: true });
  });

  const form = new FormData();
  form.set("model", "gpt-image-2");
  form.set("prompt", "Keep the room, change the wall colour");
  form.set("n", "1");
  form.append(
    "image[]",
    new Blob([Buffer.from("input-image")], { type: "image/png" }),
    "room.png",
  );

  const response = await fetch(`${ctx.baseUrl}/v1/images/edits`, {
    method: "POST",
    headers: { Authorization: "Bearer test-token" },
    body: form,
  });

  assert.equal(response.status, 200);
  const body = await response.json();
  assert.equal(body.data.length, 1);
  const args = ctx.calls[0];
  assert.ok(args.includes("edit"));
  assert.equal(args.filter((arg) => arg === "--file").length, 1);
});

test("image endpoints require authentication", async (t) => {
  const ctx = await fixture();
  t.after(async () => {
    await close(ctx.server);
    await fs.rm(ctx.workRoot, { recursive: true, force: true });
  });

  const response = await fetch(`${ctx.baseUrl}/v1/images/generations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt: "test" }),
  });
  assert.equal(response.status, 401);
  assert.equal((await response.json()).error.code, "invalid_api_key");
  assert.equal(ctx.calls.length, 0);
});

test("unknown models are rejected instead of becoming CLI arguments", async (t) => {
  const ctx = await fixture();
  t.after(async () => {
    await close(ctx.server);
    await fs.rm(ctx.workRoot, { recursive: true, force: true });
  });

  const response = await fetch(`${ctx.baseUrl}/v1/images/generations`, {
    method: "POST",
    headers: {
      Authorization: "Bearer test-token",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ model: "unknown", prompt: "test" }),
  });
  assert.equal(response.status, 400);
  assert.equal(ctx.calls.length, 0);
});
