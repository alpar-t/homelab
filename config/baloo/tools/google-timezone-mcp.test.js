"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

const {
  lookupTimezone,
  normalizeInput,
} = require("./google-timezone-mcp.js");

test("returns the IANA timezone and combined UTC offset", async () => {
  const fetchImpl = async (url) => {
    assert.equal(url.searchParams.get("location"), "46.7712,23.6236");
    assert.equal(url.searchParams.get("timestamp"), "1785081600");
    assert.equal(url.searchParams.get("key"), "test-key");
    return {
      ok: true,
      async json() {
        return {
          status: "OK",
          timeZoneId: "Europe/Bucharest",
          timeZoneName: "Eastern European Summer Time",
          rawOffset: 7200,
          dstOffset: 3600,
        };
      },
    };
  };

  const result = await lookupTimezone(
    {
      latitude: 46.7712,
      longitude: 23.6236,
      timestamp: 1785081600,
    },
    { apiKey: "test-key", fetchImpl }
  );

  assert.equal(result.timeZoneId, "Europe/Bucharest");
  assert.equal(result.utcOffsetSeconds, 10800);
});

test("rejects invalid coordinates before calling Google", () => {
  assert.throws(
    () => normalizeInput({ latitude: 91, longitude: 23 }),
    /latitude must be between/
  );
});

test("surfaces Google API configuration errors", async () => {
  const fetchImpl = async () => ({
    ok: true,
    async json() {
      return {
        status: "REQUEST_DENIED",
        errorMessage: "This API is not activated on your API project.",
      };
    },
  });

  await assert.rejects(
    lookupTimezone(
      { latitude: 46.7712, longitude: 23.6236, timestamp: 1785081600 },
      { apiKey: "test-key", fetchImpl }
    ),
    /REQUEST_DENIED.*not activated/
  );
});
