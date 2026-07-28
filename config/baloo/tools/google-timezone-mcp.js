#!/usr/bin/env node
"use strict";

/*
 * Read-only MCP wrapper for the Google Maps Time Zone API.
 *
 * OpenClaw starts this as a stdio child. It reuses the existing
 * GOOGLE_MAPS_API_KEY and exposes one tool:
 *   google-timezone__lookup(latitude, longitude, timestamp?)
 */

const TIMEZONE_ENDPOINT =
  "https://maps.googleapis.com/maps/api/timezone/json";

function finiteNumber(value, name) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`${name} must be a finite number`);
  }
  return value;
}

function normalizeInput(input) {
  const latitude = finiteNumber(input?.latitude, "latitude");
  const longitude = finiteNumber(input?.longitude, "longitude");
  const timestamp =
    input?.timestamp === undefined
      ? Math.floor(Date.now() / 1000)
      : finiteNumber(input.timestamp, "timestamp");

  if (latitude < -90 || latitude > 90) {
    throw new Error("latitude must be between -90 and 90");
  }
  if (longitude < -180 || longitude > 180) {
    throw new Error("longitude must be between -180 and 180");
  }
  if (!Number.isInteger(timestamp) || timestamp < 0) {
    throw new Error("timestamp must be a non-negative Unix timestamp in seconds");
  }

  return { latitude, longitude, timestamp };
}

async function lookupTimezone(input, options = {}) {
  const apiKey = options.apiKey ?? process.env.GOOGLE_MAPS_API_KEY;
  const fetchImpl = options.fetchImpl ?? globalThis.fetch;
  if (!apiKey) throw new Error("GOOGLE_MAPS_API_KEY is required");
  if (typeof fetchImpl !== "function") throw new Error("fetch is unavailable");

  const normalized = normalizeInput(input);
  const url = new URL(TIMEZONE_ENDPOINT);
  url.searchParams.set(
    "location",
    `${normalized.latitude},${normalized.longitude}`
  );
  url.searchParams.set("timestamp", String(normalized.timestamp));
  url.searchParams.set("key", apiKey);

  const response = await fetchImpl(url, {
    headers: { accept: "application/json" },
    signal: AbortSignal.timeout(10_000),
  });
  if (!response.ok) {
    throw new Error(`Google Time Zone API returned HTTP ${response.status}`);
  }

  const body = await response.json();
  if (body.status !== "OK") {
    const detail = body.errorMessage ? `: ${body.errorMessage}` : "";
    throw new Error(`Google Time Zone API ${body.status || "UNKNOWN"}${detail}`);
  }

  return {
    latitude: normalized.latitude,
    longitude: normalized.longitude,
    timestamp: normalized.timestamp,
    timeZoneId: body.timeZoneId,
    timeZoneName: body.timeZoneName,
    rawOffsetSeconds: body.rawOffset,
    dstOffsetSeconds: body.dstOffset,
    utcOffsetSeconds: body.rawOffset + body.dstOffset,
  };
}

async function main() {
  if (!process.env.GOOGLE_MAPS_API_KEY) {
    throw new Error("GOOGLE_MAPS_API_KEY is required");
  }

  // The SDK is bundled in the pinned OpenClaw image. Anchor resolution there
  // because OpenClaw intentionally strips NODE_PATH from stdio MCP children.
  const { createRequire } = require("module");
  const req = createRequire(
    `${
      process.env.OPENCLAW_NODE_MODULES || "/app/node_modules"
    }/google-timezone-mcp-anchor.js`
  );
  const { Server } = req("@modelcontextprotocol/sdk/server/index.js");
  const {
    StdioServerTransport,
  } = req("@modelcontextprotocol/sdk/server/stdio.js");
  const {
    CallToolRequestSchema,
    ListToolsRequestSchema,
  } = req("@modelcontextprotocol/sdk/types.js");

  const server = new Server(
    { name: "google-timezone", version: "1.0.0" },
    { capabilities: { tools: {} } }
  );

  server.setRequestHandler(ListToolsRequestSchema, async () => ({
    tools: [
      {
        name: "lookup",
        description:
          "Resolve the IANA timezone and UTC/DST offsets for coordinates at a Unix timestamp. Use coordinates from a trusted geocoder; the timestamp defaults to now.",
        inputSchema: {
          type: "object",
          additionalProperties: false,
          properties: {
            latitude: {
              type: "number",
              minimum: -90,
              maximum: 90,
              description: "Latitude in decimal degrees.",
            },
            longitude: {
              type: "number",
              minimum: -180,
              maximum: 180,
              description: "Longitude in decimal degrees.",
            },
            timestamp: {
              type: "integer",
              minimum: 0,
              description:
                "Unix timestamp in seconds. Omit to resolve the timezone and DST offset for now.",
            },
          },
          required: ["latitude", "longitude"],
        },
      },
    ],
  }));

  server.setRequestHandler(CallToolRequestSchema, async (request) => {
    if (request.params.name !== "lookup") {
      return {
        isError: true,
        content: [
          {
            type: "text",
            text: `Unknown tool: ${request.params.name}`,
          },
        ],
      };
    }

    try {
      const result = await lookupTimezone(request.params.arguments);
      return {
        structuredContent: result,
        content: [{ type: "text", text: JSON.stringify(result) }],
      };
    } catch (error) {
      return {
        isError: true,
        content: [
          {
            type: "text",
            text: error?.message || String(error),
          },
        ],
      };
    }
  });

  await server.connect(new StdioServerTransport());
  process.stderr.write("google-timezone-mcp: stdio server ready\n");
}

module.exports = { lookupTimezone, normalizeInput };

if (require.main === module) {
  main().catch((error) => {
    process.stderr.write(
      `google-timezone-mcp: fatal: ${error?.stack || error}\n`
    );
    process.exit(1);
  });
}
