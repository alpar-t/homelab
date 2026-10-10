"""Read-only Vikunja v2 configuration and project-query contract checks."""
import json


def _get(ctx, url, headers=None):
    remaining = ctx.remaining()
    if remaining <= 0:
        raise ValueError("deadline")
    response = ctx.http(url, headers=headers, timeout=min(5, remaining), max_bytes=65536)
    if response.status != 200:
        raise ValueError("HTTP status")
    body = json.loads(response.body)
    if not isinstance(body, dict):
        raise ValueError("object required")
    return body


def run(ctx, config):
    results = []
    base = config["base_url"].rstrip("/")
    try:
        info = _get(ctx, base + "/info")
        auth = info.get("auth", {}).get("openid_connect", {})
        valid = (isinstance(info.get("version"), str) and bool(info["version"].strip())
                 and info.get("frontend_url") == config["frontend_url"]
                 and auth.get("enabled") is True
                 and isinstance(auth.get("providers"), list)
                 and any(isinstance(p, dict) and p.get("key") == "pocketid"
                         for p in auth["providers"]))
        results.append(ctx.check("Vikunja API configuration", not valid,
                                 "v2 version, frontend and Pocket ID configuration valid" if valid
                                 else "v2 instance configuration invalid"))
    except Exception:
        results.append(ctx.check("Vikunja API configuration", True,
                                 "v2 instance configuration unavailable or malformed"))
    try:
        token = ctx.secret(config["token_key"])
    except Exception:
        results.append(dict(ctx.check("Vikunja authenticated project query", True,
                                 "coverage deferred: dedicated read-only credential unavailable", 1),
                            observation="deferred", notification="dashboard"))
        return results
    try:
        data = _get(ctx, base + "/projects?page=1&per_page=1",
                    {"Authorization": "Bearer " + token})
        items, total = data.get("items"), data.get("total")
        valid = (type(total) is int and total >= 0
                 and type(data.get("page")) is int and data["page"] == 1
                 and type(data.get("per_page")) is int and data["per_page"] == 1
                 and type(data.get("total_pages")) is int and data["total_pages"] >= 0
                 and ((items is None and total == 0)
                      or (isinstance(items, list) and len(items) <= 1
                          and len(items) == min(total, 1)
                          and all(isinstance(p, dict) and type(p.get("id")) is int
                                  and p["id"] > 0 and isinstance(p.get("title"), str) for p in items))))
        results.append(ctx.check("Vikunja authenticated project query", not valid,
                                 "authenticated paginated project read succeeded" if valid
                                 else "authenticated project response schema invalid"))
    except Exception:
        results.append(ctx.check("Vikunja authenticated project query", True,
                                 "authenticated project read failed or malformed"))
    return results
