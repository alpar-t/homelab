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
    checks.append(dict(ctx.check("Emby scoped library query", True,
        "coverage deferred: no native session token or household-library access is granted to monitoring",
        severity=1), observation='deferred', notification='dashboard'))
    return checks
