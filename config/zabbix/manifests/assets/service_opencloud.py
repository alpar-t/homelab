"""Anonymous OpenCloud status contract; authenticated DAV coverage stays deferred."""
import json

def run(ctx, config):
    result = []
    base = config["base_url"].rstrip("/")
    try:
        response = ctx.http(base + "/status.php", timeout=min(8, ctx.remaining()), max_bytes=32768)
        payload = json.loads(response.body)
        healthy = (response.status == 200 and isinstance(payload, dict)
                   and payload.get("installed") is True
                   and payload.get("maintenance") is False
                   and isinstance(payload.get("version"), str) and bool(payload["version"])
                   and payload.get("productname") == "OpenCloud")
        result.append(ctx.check("OpenCloud API contract", not healthy,
                                "status API available" if healthy else "status API invalid or maintenance enabled"))
    except Exception:
        result.append(ctx.check("OpenCloud API contract", True, "status API unavailable or malformed"))
    result.append(dict(ctx.check('OpenCloud monitor storage metadata', True, 'coverage deferred: native App Tokens can write the identity personal space; no file credential is mounted', severity=1), observation='deferred', notification='dashboard'))
    return result
