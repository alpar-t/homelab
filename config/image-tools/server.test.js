import assert from "node:assert/strict";
import { mkdtemp, mkdir, realpath, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import sharp from "sharp";
import { confinedMediaFile, createImageToolsHttpServer, transformBuffer } from "./server.js";

async function fixture() {
  return sharp({ create: { width: 32, height: 24, channels: 4, background: "#3b82f6" } }).avif().toBuffer();
}

test("normalizes AVIF input to visible bounded JPEG", async () => {
  const result = await transformBuffer(await fixture(), { format: "jpeg", width: 16, height: 16, fit: "inside" });
  const metadata = await sharp(result.data).metadata();
  assert.equal(result.mimeType, "image/jpeg");
  assert.equal(metadata.format, "jpeg");
  assert.equal(metadata.width, 16);
  assert.equal(metadata.height, 12);
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
