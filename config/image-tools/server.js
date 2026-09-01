#!/usr/bin/env node

import { createServer as createHttpServer } from "node:http";
import { mkdir, open, readFile, realpath, stat } from "node:fs/promises";
import { dirname, extname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { randomUUID } from "node:crypto";
import { fileURLToPath } from "node:url";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import sharp from "sharp";
import { z } from "zod";

const DEFAULT_HOST = "127.0.0.1";
const DEFAULT_PORT = 18807;
const DEFAULT_READ_ROOTS = ["/state/media/inbound", "/state/media/generated"];
const DEFAULT_OUTPUT_ROOT = "/state/media/generated/image-tools";
const MAX_MCP_REQUEST_BYTES = 128 * 1024;
const MAX_INPUT_BYTES = 20 * 1024 * 1024;
const MAX_OUTPUT_BYTES = 8 * 1024 * 1024;
const MAX_INPUT_PIXELS = 40_000_000;
const MAX_DIMENSION = 8_192;
const DEFAULT_MODEL_SIDE = 4_096;
const PROCESS_TIMEOUT_SECONDS = 30;
const OUTPUT_MIME = new Map([
  ["jpeg", "image/jpeg"],
  ["png", "image/png"],
  ["webp", "image/webp"],
]);
const OUTPUT_EXTENSION = new Map([
  ["jpeg", ".jpg"],
  ["png", ".png"],
  ["webp", ".webp"],
]);

function integer(value, name, minimum, maximum) {
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < minimum || parsed > maximum) {
    throw new Error(`${name} must be an integer from ${minimum} to ${maximum}`);
  }
  return parsed;
}

function finiteNumber(value, name, minimum, maximum) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < minimum || parsed > maximum) {
    throw new Error(`${name} must be from ${minimum} to ${maximum}`);
  }
  return parsed;
}

function isWithin(root, target) {
  const child = relative(root, target);
  return child === "" || (!child.startsWith(`..${sep}`) && child !== ".." && !isAbsolute(child));
}

async function existingRoots(values) {
  const roots = [];
  for (const value of values) {
    try {
      roots.push(await realpath(resolve(value)));
    } catch (error) {
      if (error?.code !== "ENOENT") throw error;
    }
  }
  return roots;
}

export async function confinedMediaFile(inputPath, roots = DEFAULT_READ_ROOTS) {
  if (typeof inputPath !== "string" || !inputPath.trim()) throw new Error("path must be a non-empty string");
  const normalized = inputPath.startsWith("MEDIA:") ? inputPath.slice("MEDIA:".length) : inputPath;
  if (!isAbsolute(normalized) || normalized.includes("\0")) throw new Error("path must be an absolute media path");
  const [target, allowedRoots] = await Promise.all([realpath(normalized), existingRoots(roots)]);
  if (!allowedRoots.some((root) => isWithin(root, target))) throw new Error("path is outside the allowed media roots");
  const metadata = await stat(target);
  if (!metadata.isFile()) throw new Error("path must identify a regular file");
  if (metadata.size < 1 || metadata.size > MAX_INPUT_BYTES) {
    throw new Error(`image must be from 1 to ${MAX_INPUT_BYTES} bytes`);
  }
  return { path: target, size: metadata.size };
}

function transformSchemaShape() {
  return {
    path: z.string().describe("Absolute path under /state/media/inbound or /state/media/generated"),
    format: z.enum(["jpeg", "png", "webp"]).default("jpeg"),
    quality: z.number().int().min(1).max(100).default(90),
    width: z.number().int().min(1).max(MAX_DIMENSION).optional(),
    height: z.number().int().min(1).max(MAX_DIMENSION).optional(),
    fit: z.enum(["cover", "contain", "fill", "inside", "outside"]).default("inside"),
    crop: z.object({
      left: z.number().int().min(0).max(MAX_DIMENSION),
      top: z.number().int().min(0).max(MAX_DIMENSION),
      width: z.number().int().min(1).max(MAX_DIMENSION),
      height: z.number().int().min(1).max(MAX_DIMENSION),
    }).optional(),
    rotate: z.number().min(-360).max(360).optional(),
    flip: z.boolean().default(false),
    flop: z.boolean().default(false),
    grayscale: z.boolean().default(false),
    blur: z.number().min(0.3).max(20).optional(),
    sharpen: z.boolean().default(false),
    brightness: z.number().min(0.1).max(3).optional(),
    saturation: z.number().min(0).max(3).optional(),
  };
}

function normalizedOptions(input = {}) {
  const format = input.format || "jpeg";
  if (!OUTPUT_MIME.has(format)) throw new Error("format must be jpeg, png, or webp");
  const options = {
    format,
    quality: input.quality === undefined ? 90 : integer(input.quality, "quality", 1, 100),
    fit: input.fit || "inside",
    flip: Boolean(input.flip),
    flop: Boolean(input.flop),
    grayscale: Boolean(input.grayscale),
    sharpen: Boolean(input.sharpen),
  };
  if (!["cover", "contain", "fill", "inside", "outside"].includes(options.fit)) throw new Error("invalid fit");
  for (const field of ["width", "height"]) {
    if (input[field] !== undefined) options[field] = integer(input[field], field, 1, MAX_DIMENSION);
  }
  if (input.crop) {
    options.crop = {
      left: integer(input.crop.left, "crop.left", 0, MAX_DIMENSION),
      top: integer(input.crop.top, "crop.top", 0, MAX_DIMENSION),
      width: integer(input.crop.width, "crop.width", 1, MAX_DIMENSION),
      height: integer(input.crop.height, "crop.height", 1, MAX_DIMENSION),
    };
  }
  if (input.rotate !== undefined) options.rotate = finiteNumber(input.rotate, "rotate", -360, 360);
  if (input.blur !== undefined) options.blur = finiteNumber(input.blur, "blur", 0.3, 20);
  if (input.brightness !== undefined) options.brightness = finiteNumber(input.brightness, "brightness", 0.1, 3);
  if (input.saturation !== undefined) options.saturation = finiteNumber(input.saturation, "saturation", 0, 3);
  return options;
}

export async function transformBuffer(input, rawOptions = {}) {
  const data = Buffer.isBuffer(input) ? input : Buffer.from(input);
  if (data.length < 1 || data.length > MAX_INPUT_BYTES) {
    throw new Error(`image must be from 1 to ${MAX_INPUT_BYTES} bytes`);
  }
  const options = normalizedOptions(rawOptions);
  let pipeline = sharp(data, {
    failOn: "error",
    limitInputPixels: MAX_INPUT_PIXELS,
    pages: 1,
    sequentialRead: true,
  }).autoOrient();
  if (options.crop) pipeline = pipeline.extract(options.crop);
  if (options.rotate !== undefined) pipeline = pipeline.rotate(options.rotate, { background: "#ffffff" });
  if (options.flip) pipeline = pipeline.flip();
  if (options.flop) pipeline = pipeline.flop();
  if (options.width || options.height) {
    pipeline = pipeline.resize({
      width: options.width,
      height: options.height,
      fit: options.fit,
      withoutEnlargement: options.fit === "inside",
    });
  }
  if (options.grayscale) pipeline = pipeline.grayscale();
  if (options.blur !== undefined) pipeline = pipeline.blur(options.blur);
  if (options.sharpen) pipeline = pipeline.sharpen();
  if (options.brightness !== undefined || options.saturation !== undefined) {
    pipeline = pipeline.modulate({ brightness: options.brightness, saturation: options.saturation });
  }
  if (options.format === "jpeg") pipeline = pipeline.flatten({ background: "#ffffff" }).jpeg({ quality: options.quality });
  if (options.format === "png") pipeline = pipeline.png({ compressionLevel: 8 });
  if (options.format === "webp") pipeline = pipeline.webp({ quality: options.quality });
  const { data: output, info } = await pipeline
    .timeout({ seconds: PROCESS_TIMEOUT_SECONDS })
    .toBuffer({ resolveWithObject: true });
  if (output.length > MAX_OUTPUT_BYTES) throw new Error(`transformed image exceeds ${MAX_OUTPUT_BYTES} bytes`);
  return {
    data: output,
    mimeType: OUTPUT_MIME.get(options.format),
    format: options.format,
    width: info.width,
    height: info.height,
    size: output.length,
  };
}

async function imageMetadata(data) {
  const metadata = await sharp(data, {
    failOn: "error",
    limitInputPixels: MAX_INPUT_PIXELS,
    pages: 1,
    sequentialRead: true,
  }).metadata();
  return {
    format: metadata.format || null,
    width: metadata.width || null,
    height: metadata.height || null,
    pages: metadata.pages || 1,
    orientation: metadata.orientation || null,
    space: metadata.space || null,
    channels: metadata.channels || null,
    hasAlpha: Boolean(metadata.hasAlpha),
  };
}

async function saveGenerated(result, outputRoot = DEFAULT_OUTPUT_ROOT) {
  await mkdir(outputRoot, { recursive: true });
  const outputPath = join(outputRoot, `${randomUUID()}${OUTPUT_EXTENSION.get(result.format)}`);
  const handle = await open(outputPath, "wx", 0o600);
  try {
    await handle.writeFile(result.data);
  } finally {
    await handle.close();
  }
  return outputPath;
}

function toolError(error) {
  return {
    content: [{ type: "text", text: error instanceof Error ? error.message : String(error) }],
    isError: true,
  };
}

export function createMcpServer(options = {}) {
  const roots = options.readRoots || DEFAULT_READ_ROOTS;
  const outputRoot = options.outputRoot || DEFAULT_OUTPUT_ROOT;
  const server = new McpServer({ name: "homelab-image-tools", version: "1.0.0" });
  server.registerTool("inspect_image", {
    title: "Inspect image",
    description: "Read bounded image metadata from an inbound or generated Baloo media path without modifying the file.",
    inputSchema: { path: z.string() },
    annotations: { readOnlyHint: true },
  }, async ({ path }) => {
    try {
      const source = await confinedMediaFile(path, roots);
      const metadata = await imageMetadata(await readFile(source.path));
      return { content: [{ type: "text", text: JSON.stringify({ path: source.path, bytes: source.size, ...metadata }) }] };
    } catch (error) {
      return toolError(error);
    }
  });
  server.registerTool("transform_image", {
    title: "Transform image",
    description: "Convert and safely transform an inbound or generated Baloo image. Supports resize, crop, rotate, flip, grayscale, blur, sharpen, brightness and saturation; returns visible image content and a new generated-media path without overwriting files.",
    inputSchema: transformSchemaShape(),
    annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false },
  }, async (input) => {
    try {
      const source = await confinedMediaFile(input.path, roots);
      const result = await transformBuffer(await readFile(source.path), input);
      const outputPath = await saveGenerated(result, outputRoot);
      return {
        content: [
          { type: "text", text: JSON.stringify({ path: outputPath, mimeType: result.mimeType, width: result.width, height: result.height, bytes: result.size }) },
          { type: "image", data: result.data.toString("base64"), mimeType: result.mimeType },
        ],
      };
    } catch (error) {
      return toolError(error);
    }
  });
  return server;
}

async function readBoundedBody(request, limit) {
  const length = Number(request.headers["content-length"] || 0);
  if (Number.isFinite(length) && length > limit) throw new Error(`request exceeds ${limit} bytes`);
  const chunks = [];
  let size = 0;
  for await (const chunk of request) {
    size += chunk.length;
    if (size > limit) throw new Error(`request exceeds ${limit} bytes`);
    chunks.push(chunk);
  }
  return Buffer.concat(chunks, size);
}

function internalTransformOptions(url) {
  const side = url.searchParams.get("maxSide");
  const options = {
    format: url.searchParams.get("format") || "jpeg",
    quality: url.searchParams.get("quality") || 90,
    fit: "inside",
  };
  if (side !== null) {
    const value = integer(side, "maxSide", 1, MAX_DIMENSION);
    options.width = value;
    options.height = value;
  }
  return options;
}

export function createImageToolsHttpServer(options = {}) {
  return createHttpServer(async (request, response) => {
    const url = new URL(request.url || "/", "http://localhost");
    try {
      if (request.method === "GET" && url.pathname === "/health") {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ ok: true }));
        return;
      }
      if (request.method === "POST" && url.pathname === "/v1/transform") {
        const source = await readBoundedBody(request, MAX_INPUT_BYTES);
        const result = await transformBuffer(source, internalTransformOptions(url));
        response.writeHead(200, {
          "content-type": result.mimeType,
          "content-length": result.data.length,
          "x-image-width": result.width,
          "x-image-height": result.height,
          "cache-control": "no-store",
        });
        response.end(result.data);
        return;
      }
      if (request.method === "POST" && url.pathname === "/mcp") {
        const announced = request.headers["content-length"];
        const length = Number(announced);
        if (announced === undefined || request.headers["transfer-encoding"] || !Number.isInteger(length) || length < 1) {
          throw new Error("MCP requests require a bounded Content-Length");
        }
        if (length > MAX_MCP_REQUEST_BYTES) throw new Error("MCP request is too large");
        const mcp = createMcpServer(options);
        const transport = new StreamableHTTPServerTransport({ sessionIdGenerator: undefined, enableJsonResponse: true });
        response.on("close", () => {
          transport.close().catch(() => {});
          mcp.close().catch(() => {});
        });
        await mcp.connect(transport);
        await transport.handleRequest(request, response);
        return;
      }
      response.writeHead(404, { "content-type": "application/json" });
      response.end(JSON.stringify({ error: "not_found" }));
    } catch (error) {
      if (!response.headersSent) {
        response.writeHead(400, { "content-type": "application/json" });
        response.end(JSON.stringify({ error: error instanceof Error ? error.message : String(error) }));
      } else {
        response.destroy();
      }
    }
  });
}

async function main() {
  sharp.cache({ memory: 64, files: 0, items: 32 });
  sharp.concurrency(Math.max(1, Math.min(2, sharp.concurrency())));
  const host = process.env.IMAGE_TOOLS_HOST || DEFAULT_HOST;
  const port = integer(process.env.IMAGE_TOOLS_PORT || DEFAULT_PORT, "IMAGE_TOOLS_PORT", 1, 65_535);
  const server = createImageToolsHttpServer();
  server.listen(port, host, () => process.stderr.write(`homelab-image-tools listening on http://${host}:${port}\n`));
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((error) => {
    process.stderr.write(`${error instanceof Error ? error.stack : String(error)}\n`);
    process.exitCode = 1;
  });
}
