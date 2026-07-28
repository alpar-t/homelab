#!/usr/bin/env node
"use strict";

/**
 * OpenAI-compatible image API backed by OpenClaw's synchronous image CLI.
 *
 * Open WebUI owns the client-tool loop and chat attachments, while this
 * adapter reuses OpenClaw's configured providers and Codex OAuth profile.
 * It intentionally exposes only image generation and editing.
 */

const crypto = require("node:crypto");
const fs = require("node:fs/promises");
const http = require("node:http");
const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");

const execFileAsync = promisify(execFile);

const ALLOWED_BACKGROUNDS = new Set(["transparent", "opaque", "auto"]);
const ALLOWED_FORMATS = new Set(["png", "jpeg", "webp"]);
const ALLOWED_QUALITIES = new Set(["low", "medium", "high", "auto"]);
const MAX_PROMPT_CHARS = 32_000;

class HttpError extends Error {
  constructor(status, message, code = "invalid_request_error") {
    super(message);
    this.name = "HttpError";
    this.status = status;
    this.code = code;
  }
}

function readPositiveInt(value, fallback, label) {
  if (value === undefined || value === "") return fallback;
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed <= 0) {
    throw new Error(`${label} must be a positive integer`);
  }
  return parsed;
}

function loadSettings(env) {
  const token = env.IMAGE_API_TOKEN?.trim();
  if (!token) throw new Error("IMAGE_API_TOKEN is required");

  return {
    token,
    host: env.IMAGE_API_HOST?.trim() || "0.0.0.0",
    port: readPositiveInt(env.IMAGE_API_PORT, 18801, "IMAGE_API_PORT"),
    model: env.OPENCLAW_IMAGE_MODEL?.trim() || "openai/gpt-image-2",
    nodeBin: env.OPENCLAW_NODE_BIN?.trim() || process.execPath,
    cliPath: env.OPENCLAW_CLI_PATH?.trim() || "/app/dist/index.js",
    cliTimeoutMs: readPositiveInt(
      env.OPENCLAW_IMAGE_TIMEOUT_MS,
      300_000,
      "OPENCLAW_IMAGE_TIMEOUT_MS",
    ),
    maxBodyBytes: readPositiveInt(
      env.IMAGE_API_MAX_BODY_BYTES,
      60 * 1024 * 1024,
      "IMAGE_API_MAX_BODY_BYTES",
    ),
    maxConcurrent: readPositiveInt(
      env.IMAGE_API_MAX_CONCURRENT,
      1,
      "IMAGE_API_MAX_CONCURRENT",
    ),
    maxQueue: readPositiveInt(env.IMAGE_API_MAX_QUEUE, 8, "IMAGE_API_MAX_QUEUE"),
    workRoot: env.IMAGE_API_WORK_ROOT?.trim() || "/tmp/openclaw-image-api",
  };
}

function createSemaphore(maxConcurrent, maxQueue) {
  let active = 0;
  const waiters = [];

  return {
    async acquire() {
      if (active < maxConcurrent) {
        active += 1;
        return;
      }
      if (waiters.length >= maxQueue) {
        throw new HttpError(429, "Image generation queue is full", "rate_limit_exceeded");
      }
      await new Promise((resolve) => waiters.push(resolve));
    },
    release() {
      const next = waiters.shift();
      if (next) next();
      else active -= 1;
    },
    stats() {
      return { active, queued: waiters.length };
    },
  };
}

function timingSafeTokenMatch(actual, expected) {
  const actualBuffer = Buffer.from(actual);
  const expectedBuffer = Buffer.from(expected);
  return (
    actualBuffer.length === expectedBuffer.length &&
    crypto.timingSafeEqual(actualBuffer, expectedBuffer)
  );
}

function requireAuthorization(req, expectedToken) {
  const header = req.headers.authorization || "";
  const match = /^Bearer\s+(.+)$/i.exec(header);
  if (!match || !timingSafeTokenMatch(match[1], expectedToken)) {
    throw new HttpError(401, "Invalid API key", "invalid_api_key");
  }
}

async function readBody(req, maxBodyBytes) {
  const declaredLength = Number(req.headers["content-length"] || 0);
  if (declaredLength > maxBodyBytes) {
    throw new HttpError(413, "Request body is too large", "request_too_large");
  }

  const chunks = [];
  let size = 0;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > maxBodyBytes) {
      throw new HttpError(413, "Request body is too large", "request_too_large");
    }
    chunks.push(chunk);
  }
  return Buffer.concat(chunks);
}

function parseJsonBody(buffer) {
  try {
    return JSON.parse(buffer.toString("utf8"));
  } catch {
    throw new HttpError(400, "Request body must be valid JSON");
  }
}

function requirePrompt(value) {
  if (typeof value !== "string" || !value.trim()) {
    throw new HttpError(400, "prompt is required");
  }
  if (value.length > MAX_PROMPT_CHARS) {
    throw new HttpError(400, `prompt must not exceed ${MAX_PROMPT_CHARS} characters`);
  }
  return value;
}

function normalizeCount(value) {
  if (value === undefined || value === null || value === "") return 1;
  const count = Number(value);
  if (!Number.isInteger(count) || count < 1 || count > 4) {
    throw new HttpError(400, "n must be an integer between 1 and 4");
  }
  return count;
}

function normalizeOptionalEnum(value, allowed, label) {
  if (value === undefined || value === null || value === "") return undefined;
  const normalized = String(value).toLowerCase();
  if (!allowed.has(normalized)) {
    throw new HttpError(400, `${label} is not supported`);
  }
  return normalized;
}

function normalizeOptionalSize(value) {
  if (value === undefined || value === null || value === "" || value === "auto") {
    return undefined;
  }
  const normalized = String(value);
  if (!/^\d{2,5}x\d{2,5}$/.test(normalized)) {
    throw new HttpError(400, "size must use WIDTHxHEIGHT format");
  }
  return normalized;
}

function resolveModel(requestedModel, configuredModel) {
  if (!requestedModel) return configuredModel;
  const requested = String(requestedModel);
  const configuredBare = configuredModel.includes("/")
    ? configuredModel.slice(configuredModel.indexOf("/") + 1)
    : configuredModel;
  if (requested === configuredModel || requested === configuredBare) return configuredModel;
  throw new HttpError(400, `Unsupported image model: ${requested}`);
}

function addOptionalCliArgs(args, options) {
  if (options.count) args.push("--count", String(options.count));
  if (options.size) args.push("--size", options.size);
  if (options.quality) args.push("--quality", options.quality);
  if (options.outputFormat) args.push("--output-format", options.outputFormat);
  if (options.background) args.push("--background", options.background);
}

function parseCliJson(stdout) {
  const trimmed = String(stdout || "").trim();
  if (!trimmed) throw new Error("OpenClaw image CLI returned no output");

  try {
    return JSON.parse(trimmed);
  } catch {
    const start = trimmed.indexOf("{");
    const end = trimmed.lastIndexOf("}");
    if (start >= 0 && end > start) {
      try {
        return JSON.parse(trimmed.slice(start, end + 1));
      } catch {
        // Fall through to the stable error below.
      }
    }
    throw new Error("OpenClaw image CLI returned malformed JSON");
  }
}

function safeOutputPath(outputPath, workDir) {
  if (typeof outputPath !== "string" || !outputPath) {
    throw new Error("OpenClaw image CLI returned an output without a path");
  }
  const resolvedRoot = `${path.resolve(workDir)}${path.sep}`;
  const resolvedOutput = path.resolve(outputPath);
  if (!resolvedOutput.startsWith(resolvedRoot)) {
    throw new Error("OpenClaw image CLI returned an unsafe output path");
  }
  return resolvedOutput;
}

function extensionForMime(mimeType) {
  switch (String(mimeType || "").toLowerCase()) {
    case "image/jpeg":
    case "image/jpg":
      return ".jpg";
    case "image/webp":
      return ".webp";
    default:
      return ".png";
  }
}

async function parseMultipart(body, headers) {
  let form;
  try {
    const request = new Request("http://localhost/images/edits", {
      method: "POST",
      headers,
      body,
    });
    form = await request.formData();
  } catch {
    throw new HttpError(400, "Request body must be valid multipart form data");
  }

  const files = [...form.getAll("image"), ...form.getAll("image[]")].filter(
    (value) => value && typeof value.arrayBuffer === "function",
  );
  if (files.length === 0) throw new HttpError(400, "At least one image is required");
  if (files.length > 5) throw new HttpError(400, "At most five input images are supported");

  return {
    prompt: requirePrompt(form.get("prompt")),
    model: form.get("model"),
    count: normalizeCount(form.get("n")),
    size: normalizeOptionalSize(form.get("size")),
    quality: normalizeOptionalEnum(form.get("quality"), ALLOWED_QUALITIES, "quality"),
    background: normalizeOptionalEnum(
      form.get("background"),
      ALLOWED_BACKGROUNDS,
      "background",
    ),
    outputFormat: normalizeOptionalEnum(
      form.get("output_format"),
      ALLOWED_FORMATS,
      "output_format",
    ),
    files,
  };
}

function createImageApiServer(options = {}) {
  const env = options.env || process.env;
  const settings = loadSettings(env);
  const execute = options.execute || execFileAsync;
  const semaphore = createSemaphore(settings.maxConcurrent, settings.maxQueue);

  async function runImageCli(kind, input, requestId) {
    const workDir = await fs.mkdtemp(path.join(settings.workRoot, `${requestId}-`));
    const outputBase = path.join(workDir, "output");

    try {
      const args = [
        settings.cliPath,
        "infer",
        "image",
        kind,
        "--json",
        "--model",
        resolveModel(input.model, settings.model),
        "--prompt",
        input.prompt,
        "--output",
        outputBase,
        "--timeout-ms",
        String(settings.cliTimeoutMs),
      ];

      addOptionalCliArgs(args, input);

      if (kind === "edit") {
        for (const [index, file] of input.files.entries()) {
          const filePath = path.join(
            workDir,
            `input-${index + 1}${extensionForMime(file.type)}`,
          );
          await fs.writeFile(filePath, Buffer.from(await file.arrayBuffer()));
          args.push("--file", filePath);
        }
      }

      let commandResult;
      try {
        commandResult = await execute(settings.nodeBin, args, {
          env,
          maxBuffer: 4 * 1024 * 1024,
          timeout: settings.cliTimeoutMs + 10_000,
          killSignal: "SIGKILL",
        });
      } catch (error) {
        const detail = String(error.stderr || error.message || "unknown error")
          .trim()
          .slice(0, 2_000);
        if (error.killed || error.signal === "SIGKILL") {
          throw new HttpError(504, "Image generation timed out", "timeout");
        }
        throw new HttpError(
          502,
          `OpenClaw image generation failed: ${detail}`,
          "image_generation_failed",
        );
      }

      const result = parseCliJson(commandResult.stdout);
      if (!result.ok || !Array.isArray(result.outputs) || result.outputs.length === 0) {
        throw new HttpError(
          502,
          result.error || "OpenClaw returned no generated images",
          "image_generation_failed",
        );
      }

      const data = [];
      for (const output of result.outputs) {
        const outputPath = safeOutputPath(output.path, workDir);
        const image = await fs.readFile(outputPath);
        data.push({
          b64_json: image.toString("base64"),
          ...(output.revisedPrompt ? { revised_prompt: output.revisedPrompt } : {}),
        });
      }

      return {
        created: Math.floor(Date.now() / 1_000),
        data,
      };
    } finally {
      await fs.rm(workDir, { recursive: true, force: true }).catch(() => {});
    }
  }

  async function handleImageRequest(req, route, requestId) {
    requireAuthorization(req, settings.token);
    const body = await readBody(req, settings.maxBodyBytes);
    let input;
    let kind;

    if (route === "/v1/images/generations") {
      const data = parseJsonBody(body);
      input = {
        prompt: requirePrompt(data.prompt),
        model: data.model,
        count: normalizeCount(data.n),
        size: normalizeOptionalSize(data.size),
        quality: normalizeOptionalEnum(data.quality, ALLOWED_QUALITIES, "quality"),
        background: normalizeOptionalEnum(
          data.background,
          ALLOWED_BACKGROUNDS,
          "background",
        ),
        outputFormat: normalizeOptionalEnum(
          data.output_format,
          ALLOWED_FORMATS,
          "output_format",
        ),
      };
      kind = "generate";
    } else {
      input = await parseMultipart(body, req.headers);
      kind = "edit";
    }

    await semaphore.acquire();
    try {
      return await runImageCli(kind, input, requestId);
    } finally {
      semaphore.release();
    }
  }

  return http.createServer(async (req, res) => {
    const requestId = crypto.randomUUID();
    const startedAt = Date.now();
    const route = new URL(req.url || "/", "http://localhost").pathname;

    function send(status, payload) {
      const body = JSON.stringify(payload);
      res.writeHead(status, {
        "Content-Type": "application/json",
        "Content-Length": Buffer.byteLength(body),
        "X-Request-Id": requestId,
      });
      res.end(body);
    }

    try {
      if (req.method === "GET" && route === "/health") {
        send(200, { ok: true, ...semaphore.stats() });
        return;
      }

      if (
        route !== "/v1/images/generations" &&
        route !== "/v1/images/edits"
      ) {
        throw new HttpError(404, "Not found", "not_found");
      }
      if (req.method !== "POST") {
        throw new HttpError(405, "Method not allowed", "method_not_allowed");
      }

      const result = await handleImageRequest(req, route, requestId);
      send(200, result);
      console.log(
        JSON.stringify({
          level: "info",
          requestId,
          route,
          durationMs: Date.now() - startedAt,
          outputs: result.data.length,
        }),
      );
    } catch (error) {
      const status = error instanceof HttpError ? error.status : 500;
      const code = error instanceof HttpError ? error.code : "internal_error";
      const message =
        error instanceof HttpError ? error.message : "Internal image adapter error";
      send(status, { error: { message, type: code, code } });
      console.error(
        JSON.stringify({
          level: "error",
          requestId,
          route,
          durationMs: Date.now() - startedAt,
          status,
          error: String(error.message || error).slice(0, 2_000),
        }),
      );
    }
  });
}

if (require.main === module) {
  let server;
  try {
    const settings = loadSettings(process.env);
    fs.mkdir(settings.workRoot, { recursive: true })
      .then(() => {
        server = createImageApiServer({ env: process.env });
        server.listen(settings.port, settings.host, () => {
          console.log(
            JSON.stringify({
              level: "info",
              message: "OpenClaw image API adapter listening",
              host: settings.host,
              port: settings.port,
            }),
          );
        });
      })
      .catch((error) => {
        console.error(error);
        process.exit(1);
      });
  } catch (error) {
    console.error(error);
    process.exit(1);
  }

  for (const signal of ["SIGINT", "SIGTERM"]) {
    process.on(signal, () => {
      if (!server) process.exit(0);
      server.close(() => process.exit(0));
    });
  }
}

module.exports = {
  createImageApiServer,
};
