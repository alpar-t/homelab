"""Read-only Radarr health and storage contract using its native API."""
import json


def run(ctx, config):
    names = ("Radarr system health", "Radarr root folders")
    try:
        token = ctx.secret(config["credential_key"])
    except Exception:
        return [ctx.check(n, True, "monitor credential unavailable") for n in names]
    records = []
    for name, endpoint in zip(names, ("health", "rootfolder")):
        try:
            remaining = ctx.remaining()
            if remaining <= 0:
                raise ValueError()
            response = ctx.http(config["base_url"].rstrip("/") + "/api/v3/" + endpoint,
                                headers={"X-Api-Key": token},
                                timeout=min(5, remaining), max_bytes=131072,
                                follow_redirects=False)
            if response.status != 200:
                records.append(ctx.check(name, True, "read-only API returned HTTP " + str(response.status)))
                continue
            rows = json.loads(response.body)
            if not isinstance(rows, list) or len(rows) > 1000:
                raise ValueError()
            if endpoint == "health":
                if any(not isinstance(r, dict) or r.get("type") not in ("ok", "notice", "warning", "error")
                       or not isinstance(r.get("source"), str) or not r["source"] for r in rows):
                    raise ValueError()
                problems = sum(r["type"] in ("warning", "error") for r in rows)
                detail = "native health warnings/errors=" + str(problems)
            else:
                if any(not isinstance(r, dict) or type(r.get("accessible")) is not bool for r in rows):
                    raise ValueError()
                problems = sum(not r["accessible"] for r in rows)
                detail = "configured roots=" + str(len(rows)) + "; inaccessible=" + str(problems)
            records.append(ctx.check(name, bool(problems), detail))
        except Exception:
            records.append(ctx.check(name, True, "read-only API unavailable or malformed"))
    return records
