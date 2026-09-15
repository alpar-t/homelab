import assert from "node:assert/strict";
import { mkdtemp, mkdir, realpath, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import sharp from "sharp";
import { cleanupAudioChunks, confinedMediaFile, createImageToolsHttpServer, splitAudioFile, transformBuffer } from "./server.js";

async function fixture() {
  return sharp({ create: { width: 32, height: 24, channels: 4, background: "#3b82f6" } }).avif().toBuffer();
}

async function renderedGlyph(glyph) {
  const svg = Buffer.from(`<svg xmlns="http://www.w3.org/2000/svg" width="120" height="100">
    <rect width="100%" height="100%" fill="#fff"/>
    <text x="12" y="76" font-family="DejaVu Sans, sans-serif" font-size="72" fill="#111">${glyph}</text>
  </svg>`);
  return (await transformBuffer(svg, { format: "png" })).data;
}

test("normalizes AVIF input to visible bounded JPEG", async () => {
  const result = await transformBuffer(await fixture(), { format: "jpeg", width: 16, height: 16, fit: "inside" });
  const metadata = await sharp(result.data).metadata();
  assert.equal(result.mimeType, "image/jpeg");
  assert.equal(metadata.format, "jpeg");
  assert.equal(metadata.width, 16);
  assert.equal(metadata.height, 12);
});

test("rasterizes distinct Romanian glyphs with the packaged preview font", async () => {
  const [blank, breve, circumflex, commaS, commaT] = await Promise.all([
    renderedGlyph(" "),
    renderedGlyph("ă"),
    renderedGlyph("â"),
    renderedGlyph("ș"),
    renderedGlyph("ț"),
  ]);
  assert.notDeepEqual(breve, blank);
  assert.notDeepEqual(breve, circumflex);
  assert.notDeepEqual(commaS, commaT);
});

test("confines source paths to configured media roots and rejects symlink escapes", async () => {
  const directory = await mkdtemp(join(tmpdir(), "image-tools-"));
  try {
    const root = join(directory, "media");
    const outside = join(directory, "outside.avif");
    await mkdir(root);
    await writeFile(outside, await fixture());
    const allowed = join(root, "allowed.avif");
    await writeFile(allowed, await fixture());
    assert.equal((await confinedMediaFile(allowed, [root])).path, await realpath(allowed));
    await symlink(outside, join(root, "escape.avif"));
    await assert.rejects(confinedMediaFile(join(root, "escape.avif"), [root]), /outside the allowed media roots/);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

test("serves the generic raw transform endpoint", async () => {
  const server = createImageToolsHttpServer();
  await new Promise((resolvePromise) => server.listen(0, "127.0.0.1", resolvePromise));
  try {
    const address = server.address();
    const response = await fetch(`http://127.0.0.1:${address.port}/v1/transform?format=jpeg&maxSide=20`, {
      method: "POST",
      headers: { "content-type": "image/avif" },
      body: await fixture(),
    });
    assert.equal(response.status, 200);
    assert.equal(response.headers.get("content-type"), "image/jpeg");
    const metadata = await sharp(Buffer.from(await response.arrayBuffer())).metadata();
    assert.equal(metadata.width, 20);
    assert.equal(metadata.height, 15);
  } finally {
    await new Promise((resolvePromise) => server.close(resolvePromise));
  }
});

test("serves bounded metadata for raw browser-upload bytes", async () => {
  const server = createImageToolsHttpServer();
  await new Promise((resolvePromise) => server.listen(0, "127.0.0.1", resolvePromise));
  try {
    const address = server.address();
    const response = await fetch(`http://127.0.0.1:${address.port}/v1/metadata`, {
      method: "POST",
      headers: { "content-type": "image/avif" },
      body: await fixture(),
    });
    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), {
      format: "heif",
      width: 32,
      height: 24,
      pages: 1,
      orientation: null,
      space: "srgb",
      channels: 4,
      hasAlpha: true,
    });
  } finally {
    await new Promise((resolvePromise) => server.close(resolvePromise));
  }
});

test("splits long confined audio into ordered temporary chunks and cleans them", async () => {
  const directory = await mkdtemp(join(tmpdir(), "audio-split-"));
  try {
    const root = join(directory, "inbound");
    const outputRoot = join(directory, "chunks");
    await mkdir(root);
    const input = join(root, "long.ogg");
    await writeFile(input, Buffer.alloc(2048, 1));
    const calls = [];
    const runner = async (command, args) => {
      calls.push({ command, args });
      if (command === "ffprobe") return { stdout: "3246.9\n", stderr: "" };
      const pattern = args.at(-1);
      await Promise.all([0, 1, 2].map((index) => writeFile(
        pattern.replace("%03d", String(index).padStart(3, "0")),
        Buffer.alloc(2048, index + 1),
      )));
      return { stdout: "", stderr: "" };
    };
    const result = await splitAudioFile(input, {
      readRoots: [root],
      outputRoot,
      segmentSeconds: 1200,
      runner,
    });
    assert.equal(result.durationSeconds, 3246.9);
    assert.match(result.jobId, /^[0-9a-f-]{36}$/);
    assert.deepEqual(result.chunks.map((path) => path.slice(-12)), ["part-000.ogg", "part-001.ogg", "part-002.ogg"]);
    assert.equal(calls[1].command, "ffmpeg");
    assert.ok(calls[1].args.includes("libopus"));
    await cleanupAudioChunks(result.jobId, outputRoot);
    await assert.rejects(realpath(join(outputRoot, result.jobId)), /ENOENT/);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

test("serves bounded audio split and cleanup endpoints", async () => {
  const jobId = "123e4567-e89b-42d3-a456-426614174000";
  const calls = [];
  const server = createImageToolsHttpServer({
    splitAudio: async (path, options) => {
      calls.push({ operation: "split", path, options });
      return { jobId, durationSeconds: 3246.9, segmentSeconds: 1200, chunks: ["/state/media/generated/audio-chunks/part-000.ogg"] };
    },
    cleanupAudio: async (value) => calls.push({ operation: "cleanup", jobId: value }),
  });
  await new Promise((resolvePromise) => server.listen(0, "127.0.0.1", resolvePromise));
  try {
    const address = server.address();
    const split = await fetch(`http://127.0.0.1:${address.port}/v1/audio/split`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ path: "/state/media/inbound/long.ogg", segmentSeconds: 1200 }),
    });
    assert.equal(split.status, 200);
    assert.equal((await split.json()).jobId, jobId);
    const cleanup = await fetch(`http://127.0.0.1:${address.port}/v1/audio/split/${jobId}`, { method: "DELETE" });
    assert.equal(cleanup.status, 204);
    assert.deepEqual(calls, [
      { operation: "split", path: "/state/media/inbound/long.ogg", options: { segmentSeconds: 1200 } },
      { operation: "cleanup", jobId },
    ]);
  } finally {
    await new Promise((resolvePromise) => server.close(resolvePromise));
  }
});
