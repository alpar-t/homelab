#!/usr/bin/env node
"use strict";

/*
 * Reconcile the source-controlled recurring jobs in cron-jobs.json with
 * OpenClaw's SQLite-backed cron store. User-created one-shot reminders are left
 * alone. Jobs prefixed with "managed:" are disabled when removed from the file.
 */

const fs = require("fs");
const { spawnSync } = require("child_process");

const DEFAULT_SPEC = "/git/link/config/baloo/cron-jobs.json";
const OPENCLAW_CLI = "/app/dist/index.js";
const GATEWAY_URL = "ws://127.0.0.1:18789";
const LEGACY_MANAGED_NAMES = new Set(["cluster-health"]);

function isManagedName(name) {
  return name.startsWith("managed:") || LEGACY_MANAGED_NAMES.has(name);
}

function fail(message) {
  throw new Error(`cron-sync: ${message}`);
}

function loadSpec(path) {
  const raw = fs.readFileSync(path, "utf8");
  const spec = JSON.parse(raw);

  if (spec.version !== 1) fail(`unsupported spec version ${spec.version}`);
  if (!Array.isArray(spec.jobs)) fail("jobs must be an array");
  if (!Number.isInteger(spec.pollSeconds) || spec.pollSeconds < 30) {
    fail("pollSeconds must be an integer of at least 30");
  }

  const names = new Set();
  for (const job of spec.jobs) {
    for (const key of ["name", "description", "agent", "message"]) {
      if (typeof job[key] !== "string" || !job[key].trim()) {
        fail(`job is missing non-empty ${key}`);
      }
    }
    if (names.has(job.name)) fail(`duplicate job name: ${job.name}`);
    names.add(job.name);

    const scheduleKeys = ["cron", "every"].filter((key) => job.schedule?.[key]);
    if (scheduleKeys.length !== 1) {
      fail(`${job.name}: schedule must contain exactly one of cron or every`);
    }
    if (job.schedule.timezone && !job.schedule.cron) {
      fail(`${job.name}: timezone is only valid with a cron expression`);
    }
    if (!Array.isArray(job.tools) || job.tools.length === 0) {
      fail(`${job.name}: tools must be a non-empty array`);
    }
    if (!job.delivery?.channel || !job.delivery?.toEnv) {
      fail(`${job.name}: delivery.channel and delivery.toEnv are required`);
    }
    if (!/^[A-Z][A-Z0-9_]*$/.test(job.delivery.toEnv)) {
      fail(`${job.name}: invalid delivery environment variable`);
    }
  }

  return { raw, spec };
}

function parseJsonOutput(output) {
  const start = output.indexOf("{");
  if (start < 0) fail(`command returned no JSON: ${output.trim()}`);
  return JSON.parse(output.slice(start));
}

function runCron(args, expectJson = false) {
  const result = spawnSync(
    process.execPath,
    [OPENCLAW_CLI, "cron", ...args, "--url", GATEWAY_URL],
    {
      encoding: "utf8",
      timeout: 120_000,
      env: process.env,
    }
  );

  if (result.error) throw result.error;
  if (result.status !== 0) {
    fail(
      `openclaw cron ${args[0]} failed: ${(result.stderr || result.stdout).trim()}`
    );
  }
  return expectJson ? parseJsonOutput(result.stdout) : result.stdout;
}

function jobArgs(job, destination, editing) {
  const args = [
    editing ? "edit" : "create",
    ...(editing ? [] : ["--name", job.name]),
    "--description",
    job.description,
    "--agent",
    job.agent,
    "--session",
    job.session || "isolated",
    "--message",
    job.message,
    "--thinking",
    job.thinking || "low",
    "--tools",
    job.tools.join(","),
    "--announce",
    "--channel",
    job.delivery.channel,
    "--to",
    destination,
  ];

  if (job.lightContext) args.push("--light-context");
  else if (editing) args.push("--no-light-context");

  if (job.schedule.cron) {
    args.push("--cron", job.schedule.cron);
    if (job.schedule.timezone) args.push("--tz", job.schedule.timezone);
    if (job.schedule.exact) args.push("--exact");
  } else {
    args.push("--every", job.schedule.every);
  }

  if (editing) args.push("--enable");
  else args.push("--json");
  return args;
}

function reconcile(spec) {
  const listed = runCron(["list", "--all", "--json"], true);
  const existingByName = new Map();
  for (const job of listed.jobs || []) {
    if (existingByName.has(job.name)) {
      fail(`multiple existing jobs named ${job.name}; resolve manually`);
    }
    existingByName.set(job.name, job);
  }

  const desiredNames = new Set(spec.jobs.map((job) => job.name));
  for (const existing of listed.jobs || []) {
    if (
      isManagedName(existing.name) &&
      !desiredNames.has(existing.name) &&
      existing.enabled
    ) {
      runCron(["edit", existing.id, "--disable"]);
      process.stdout.write(`cron-sync: disabled removed job ${existing.name}\n`);
    }
  }

  for (const job of spec.jobs) {
    const destination = process.env[job.delivery.toEnv];
    const existing = existingByName.get(job.name);

    if (!destination) {
      if (existing?.enabled && isManagedName(job.name)) {
        runCron(["edit", existing.id, "--disable"]);
        process.stdout.write(
          `cron-sync: disabled ${job.name}; ${job.delivery.toEnv} is unset\n`
        );
      } else {
        process.stdout.write(
          `cron-sync: skipped ${job.name}; ${job.delivery.toEnv} is unset\n`
        );
      }
      continue;
    }

    if (existing) {
      const args = jobArgs(job, destination, true);
      runCron([args[0], existing.id, ...args.slice(1)]);
      process.stdout.write(`cron-sync: updated ${job.name}\n`);
    } else {
      runCron(jobArgs(job, destination, false), true);
      process.stdout.write(`cron-sync: created ${job.name}\n`);
    }
  }
}

async function waitForGateway() {
  for (;;) {
    try {
      const response = await fetch("http://127.0.0.1:18789/readyz");
      if (response.ok) return;
    } catch {
      // Gateway is still starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 2_000));
  }
}

async function main() {
  const args = process.argv.slice(2);
  const validateOnly = args.includes("--validate");
  const specPath = args.find((arg) => arg !== "--validate") || DEFAULT_SPEC;
  let loaded = loadSpec(specPath);

  if (validateOnly) {
    process.stdout.write(
      `cron-sync: valid ${specPath} (${loaded.spec.jobs.length} jobs)\n`
    );
    return;
  }

  if (!process.env.OPENCLAW_GATEWAY_TOKEN) {
    fail("OPENCLAW_GATEWAY_TOKEN is required");
  }

  await waitForGateway();
  let lastApplied = null;

  for (;;) {
    try {
      loaded = loadSpec(specPath);
      if (loaded.raw !== lastApplied) {
        reconcile(loaded.spec);
        lastApplied = loaded.raw;
      }
    } catch (error) {
      process.stderr.write(`${error.stack || error}\n`);
    }
    await new Promise((resolve) =>
      setTimeout(resolve, loaded.spec.pollSeconds * 1_000)
    );
  }
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exit(1);
});
