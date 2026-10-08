"""Passive Prowlarr v1 API checks; never test or search an indexer."""
import json
from datetime import datetime


def run(ctx, config):
    names = ("Prowlarr API health", "Prowlarr enabled indexers")
    try:
        key = ctx.secret(config["credential_key"])
    except Exception:
        return [ctx.check(n, True, "monitor API credential unavailable") for n in names]
    try:
        payloads = []
        for endpoint in ("health", "indexer", "indexerstatus"):
            if ctx.remaining() <= 0:
                raise ValueError()
            response = ctx.http(config["base_url"] + "/api/v1/" + endpoint,
                                headers={"X-Api-Key": key, "Accept": "application/json"},
                                timeout=min(6, ctx.remaining()), max_bytes=262144,
                                follow_redirects=False)
            if response.status != 200:
                return [ctx.check(n, True, "API request rejected; HTTP " + str(response.status)) for n in names]
            value = json.loads(response.body)
            if not isinstance(value, list) or len(value) > 1000:
                raise ValueError()
            payloads.append(value)
        health, indexers, statuses = payloads
        enabled = set()
        ids = set()
        for item in indexers:
            if not isinstance(item, dict) or type(item.get("id")) is not int or item["id"] <= 0 or type(item.get("enable")) is not bool or item["id"] in ids:
                raise ValueError()
            ids.add(item["id"])
            if item["enable"]:
                enabled.add(item["id"])
        errors = 0
        for item in health:
            if not isinstance(item, dict) or item.get("type") not in ("ok", "notice", "warning", "error") or not isinstance(item.get("source"), str):
                raise ValueError()
            # Indexer failures are checked from cached status, with disabled/empty
            # configuration filtered explicitly. Warnings remain advisory.
            if item["type"] == "error" and not item["source"].startswith("Indexer") and item["source"] != "NoIndexerAvailableCheck":
                errors += 1
        blocked = set()
        for item in statuses:
            if not isinstance(item, dict) or type(item.get("indexerId")) is not int:
                raise ValueError()
            until = item.get("disabledTill")
            if until is not None:
                if not isinstance(until, str):
                    raise ValueError()
                stamp = datetime.fromisoformat(until.replace("Z", "+00:00"))
                if stamp.tzinfo is None:
                    raise ValueError()
                if item["indexerId"] in enabled and stamp.timestamp() > ctx.now:
                    blocked.add(item["indexerId"])
        return [ctx.check(names[0], errors > 0, "API schema valid; non-indexer health errors=" + str(errors)),
                ctx.check(names[1], bool(blocked), "enabled=" + str(len(enabled)) + "; temporarily blocked=" + str(len(blocked)))]
    except Exception:
        return [ctx.check(n, True, "API response unavailable or malformed") for n in names]
