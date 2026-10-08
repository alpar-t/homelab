"""Read-only Emby contracts; never retain media metadata in results."""
import json
import re


def _get(ctx, base, path, headers=None):
    response = ctx.http(base + path, headers=headers, timeout=min(6, ctx.remaining()), max_bytes=65536)
    if response.status != 200:
        raise ValueError("unexpected status")
    value = json.loads(response.body)
    if not isinstance(value, dict):
        raise ValueError("invalid object")
    return value


def run(ctx, config):
    base = config["base_url"].rstrip("/")
    checks = []
    try:
        info = _get(ctx, base, "/System/Info/Public")
        valid = (isinstance(info.get("Version"), str)
                 and re.fullmatch(r"[0-9]+(?:\.[0-9]+){2,3}", info["Version"])
                 and isinstance(info.get("Id"), str) and bool(info["Id"]))
        checks.append(ctx.check("Emby public server contract", not valid,
                                "server-info schema valid" if valid else "server-info schema invalid"))
    except Exception:
        checks.append(ctx.check("Emby public server contract", True, "server-info request unavailable or invalid"))
    try:
        token = ctx.secret(config["token_key"])
        user = ctx.secret(config["user_id_key"])
        if not re.fullmatch(r"[0-9a-fA-F-]{32,36}", user):
            raise ValueError("invalid user identifier")
    except Exception:
        checks.append(ctx.check("Emby scoped library query", True, "restricted monitor session credentials unavailable"))
        return checks
    try:
        result = _get(ctx, base, "/Users/" + user + "/Items?Limit=1&Recursive=false&EnableImages=false&EnableUserData=false",
                      {"X-Emby-Token": token})
        items, count = result.get("Items"), result.get("TotalRecordCount")
        valid = (isinstance(items, list) and len(items) <= 1
                 and type(count) is int and count >= len(items)
                 and all(isinstance(item, dict) and isinstance(item.get("Id"), str)
                         and bool(item["Id"]) and isinstance(item.get("Type"), str)
                         and bool(item["Type"]) for item in items))
        checks.append(ctx.check("Emby scoped library query", not valid,
                                "authenticated library query valid (empty permitted)" if valid else "library query schema invalid"))
    except Exception:
        checks.append(ctx.check("Emby scoped library query", True, "authenticated library query unavailable or invalid"))
    return checks
