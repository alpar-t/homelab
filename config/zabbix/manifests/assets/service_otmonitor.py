"""Observe OpenTherm exchanges without opening a command-capable connection."""
import datetime as dt
import re
from zoneinfo import ZoneInfo

FRAME = re.compile(r"^(\S+) (\d{2}:\d{2}:\d{2}\.\d+)\s+([BR])([0-9A-F]{8})\s+(Read-Data|Read-Ack)\s+")
NAME = "OTmonitor live OpenTherm exchanges"


def evaluate(text, now, max_age, timezone):
    latest = {}
    for line in text.splitlines():
        match = FRAME.match(line)
        if not match:
            continue
        stamp, clock, origin, frame, kind = match.groups()
        ident = int(frame[2:4], 16)
        if (origin, kind, ident) not in (("R", "Read-Data", 0),
                                        ("B", "Read-Ack", 0), ("B", "Read-Ack", 25)):
            continue
        try:
            received = dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            if received.tzinfo is None:
                continue
            local = received.astimezone(ZoneInfo(timezone))
            source = dt.datetime.combine(local.date(), dt.time.fromisoformat(clock), local.tzinfo)
            # Daily file timestamps have no date; handle midnight without trusting
            # the sidecar's ingestion timestamp alone when it replays old files.
            source = min((source + dt.timedelta(days=day) for day in (-1, 0, 1)),
                         key=lambda value: abs(value.timestamp() - received.timestamp()))
            age = now - min(source.timestamp(), received.timestamp())
            if -30 <= now - received.timestamp() <= max_age and -30 <= age <= max_age:
                latest[(origin, ident)] = True
        except (ValueError, OverflowError):
            continue
    missing = [label for key, label in ((("R", 0), "gateway status request"),
               (("B", 0), "boiler status acknowledgement"),
               (("B", 25), "boiler temperature acknowledgement")) if key not in latest]
    return bool(missing), ("missing recent " + ", ".join(missing) if missing else
                           "recent gateway requests and boiler status/temperature acknowledgements")


def run(ctx, config):
    try:
        if ctx.remaining() < 15:
            raise TimeoutError()
        pods = ctx.kube.get("/api/v1/namespaces/otmonitor/pods?labelSelector=app%3Dotmonitor&limit=10")["items"]
        active = [pod for pod in pods if not pod.get("metadata", {}).get("deletionTimestamp")
                  and pod.get("status", {}).get("phase") == "Running"]
        if len(active) != 1:
            return [ctx.check(NAME, True, "expected one running telemetry source")]
        if ctx.remaining() < 15:
            raise TimeoutError()
        text = ctx.kube.logs("otmonitor", active[0]["metadata"]["name"], "log-tailer",
                             since_seconds=180, limit_bytes=131072, tail_lines=600, timestamps=True)
        bad, detail = evaluate(text, ctx.now, config["max_age_seconds"], config["timezone"])
        return [ctx.check(NAME, bad, detail)]
    except Exception:
        return [ctx.check(NAME, True, "OpenTherm telemetry unavailable (API/log permission, format or timeout)")]
