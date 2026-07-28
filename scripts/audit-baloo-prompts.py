#!/usr/bin/env python3
"""Static consistency checks for Baloo prompts, tools, workspaces, and cron jobs."""

from __future__ import annotations

import fnmatch
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BALOO = ROOT / "config" / "baloo"
CONFIG_PATH = BALOO / "openclaw.json"
CRON_PATH = BALOO / "cron-jobs.json"
AGENTS_ROOT = BALOO / "agents"

BUILTIN_TOOLS = {
    "browser",
    "cron",
    "image_generate",
    "session_status",
    "web_fetch",
}

# Exact MCP names used by the prompt/config. Broad TREK and Maps policies remain
# wildcards because those agents intentionally support general trip editing.
KNOWN_EXACT_MCP_TOOLS = {
    "github-life__add_issue_comment",
    "github-life__create_branch",
    "github-life__create_issue",
    "github-life__create_or_update_file",
    "github-life__create_pull_request",
    "github-life__get_file_contents",
    "github-life__get_issue",
    "github-life__get_pull_request",
    "github-life__get_pull_request_comments",
    "github-life__get_pull_request_files",
    "github-life__get_pull_request_reviews",
    "github-life__get_pull_request_status",
    "github-life__list_commits",
    "github-life__list_issues",
    "github-life__list_pull_requests",
    "github-life__search_code",
    "github-life__search_issues",
    "github-life__search_repositories",
    "github-life__search_users",
    "github-life__update_issue",
    "github-life__update_pull_request_branch",
    "hass__GetDateTime",
    "hass__GetLiveContext",
    "google-maps__maps_directions",
    "google-maps__maps_place_details",
    "google-maps__maps_search_places",
    "google-timezone__lookup",
    "k8s__kubectl_describe",
    "k8s__kubectl_get",
    "k8s__kubectl_logs",
    "searxng__searxng_web_search",
    "trek__get_detailed_weather",
    "trek__get_settlement_summary",
    "trek__get_trip_summary",
    "trek__get_weather",
    "trek__list_places",
    "trek__list_trip_members",
    "trek__list_trips",
}

BANNED_TEXT = {
    "searxng__search": "use searxng__searxng_web_search",
}

UNQUALIFIED_GITHUB_CALL = re.compile(
    r"(?<!github-life__)\b("
    r"get_file_contents|create_branch|create_or_update_file|create_pull_request"
    r")\s*\("
)


def matches(tool: str, patterns: list[str]) -> bool:
    lowered = tool.lower()
    return any(fnmatch.fnmatchcase(lowered, pattern.lower()) for pattern in patterns)


def configured_agents(config: dict) -> dict[str, dict]:
    return {agent["id"]: agent for agent in config["agents"]["list"]}


def prompt_files(agent: dict) -> list[Path]:
    workspace = agent["workspace"]
    prefix = "/git/link/"
    if not workspace.startswith(prefix):
        return []
    local = ROOT / workspace.removeprefix(prefix)
    return sorted(local.glob("*.md"))


def main() -> int:
    errors: list[str] = []
    config = json.loads(CONFIG_PATH.read_text())
    cron = json.loads(CRON_PATH.read_text())
    agents = configured_agents(config)

    for agent_id, agent in agents.items():
        policy = agent.get("tools", {})
        allow = policy.get("allow")
        deny = policy.get("deny")
        if not isinstance(allow, list):
            errors.append(f"{agent_id}: tools.allow must be explicit")
            continue
        if not isinstance(deny, list):
            errors.append(f"{agent_id}: tools.deny must be explicit")
            continue

        for tool in allow:
            if matches(tool, deny):
                errors.append(f"{agent_id}: {tool} is both allowed and denied")
            if "__" in tool and "*" not in tool and tool not in KNOWN_EXACT_MCP_TOOLS:
                errors.append(f"{agent_id}: unknown exact MCP tool {tool}")
            if "__" not in tool and "*" not in tool and tool not in BUILTIN_TOOLS:
                errors.append(f"{agent_id}: unknown built-in tool {tool}")

        for sensitive in ("hass", "github-life", "google-timezone"):
            uses_namespace = any(
                pattern.lower().startswith(f"{sensitive}__") for pattern in allow
            )
            if not uses_namespace and f"{sensitive}__*" not in deny:
                errors.append(
                    f"{agent_id}: must explicitly deny unused {sensitive}__*"
                )

        files = prompt_files(agent)
        if not files:
            errors.append(f"{agent_id}: workspace has no prompt files")
            continue

        heartbeat_enabled = agent.get("heartbeat", {}).get("every", "0m") != "0m"
        has_heartbeat = any(path.name == "HEARTBEAT.md" for path in files)
        if heartbeat_enabled != has_heartbeat:
            errors.append(
                f"{agent_id}: heartbeat config/file mismatch "
                f"(enabled={heartbeat_enabled}, file={has_heartbeat})"
            )

        for path in files:
            text = path.read_text()
            relative = path.relative_to(ROOT)
            for banned, replacement in BANNED_TEXT.items():
                if banned in text:
                    errors.append(f"{relative}: {banned} is invalid; {replacement}")
            if UNQUALIFIED_GITHUB_CALL.search(text):
                errors.append(
                    f"{relative}: qualify GitHub calls with github-life__"
                )

            for token in re.findall(r"`([^`\s()]+)`", text):
                if token not in BUILTIN_TOOLS and "__" not in token:
                    continue
                if "*" in token:
                    namespace = token.split("__", 1)[0] + "__"
                    if not any(item.lower().startswith(namespace.lower()) for item in allow):
                        errors.append(
                            f"{relative}: referenced namespace {token} is not allowed"
                        )
                    continue
                if "__" in token and token not in KNOWN_EXACT_MCP_TOOLS:
                    errors.append(f"{relative}: unknown exact MCP tool {token}")
                if not matches(token, allow) or matches(token, deny):
                    errors.append(
                        f"{relative}: referenced tool {token} is unavailable to {agent_id}"
                    )

    configured_workspaces = {
        Path(agent["workspace"]).name
        for agent in agents.values()
    }
    prompt_dirs = {
        path.name for path in AGENTS_ROOT.iterdir() if any(path.glob("*.md"))
    }
    for orphan in sorted(prompt_dirs - configured_workspaces):
        errors.append(f"orphan prompt workspace: config/baloo/agents/{orphan}")

    cron_names: set[str] = set()
    for job in cron.get("jobs", []):
        name = job.get("name")
        if name in cron_names:
            errors.append(f"cron: duplicate job name {name}")
        cron_names.add(name)

        agent_id = job.get("agent")
        if agent_id not in agents:
            errors.append(f"cron {name}: unknown agent {agent_id}")
            continue
        policy = agents[agent_id]["tools"]
        for tool in job.get("tools", []):
            if "__" in tool and tool not in KNOWN_EXACT_MCP_TOOLS:
                errors.append(f"cron {name}: unknown exact MCP tool {tool}")
            if not matches(tool, policy["allow"]) or matches(tool, policy["deny"]):
                errors.append(
                    f"cron {name}: tool {tool} is unavailable to {agent_id}"
                )

    trips_deny = agents["trips"]["tools"]["deny"]
    for tool in ("trek__create_trip", "trek__delete_trip"):
        if tool not in trips_deny:
            errors.append(f"trips: shared agent must deny {tool}")

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        print(f"Baloo audit failed with {len(errors)} error(s).", file=sys.stderr)
        return 1

    prompt_count = sum(len(prompt_files(agent)) for agent in agents.values())
    print(
        f"Baloo audit passed: {len(agents)} agents, "
        f"{prompt_count} prompt files, {len(cron_names)} managed cron jobs."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
