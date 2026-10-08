"""Read-only qBittorrent session and global connectivity baseline."""
import json
import re


def run(ctx, config):
    names = ("qBittorrent Web API session", "qBittorrent transfer connectivity")
    base = config["url"].rstrip("/")

    def get(path, limit=16384):
        remaining = ctx.remaining()
        if remaining <= 0:
            raise ValueError("deadline")
        response = ctx.http(base + "/api/v2/" + path,
                            headers={"Referer": base + "/"},
                            timeout=min(5, remaining), max_bytes=limit)
        if response.status != 200:
            raise ValueError("API unavailable")
        return response.body

    try:
        version = get("app/version", 128).decode("ascii").strip()
        if not re.fullmatch(r"v?\d+\.\d+\.\d+(?:[a-zA-Z0-9.+-]*)", version):
            raise ValueError("invalid version")
        session = ctx.check(names[0], False, "Application version contract and existing API session usable")
    except Exception:
        return [ctx.check(name, True, "API unavailable, unauthorized, timed out or invalid; no login attempted") for name in names]
    try:
        info = json.loads(get("transfer/info"))
        if not isinstance(info, dict) or info.get("connection_status") not in ("connected", "firewalled", "disconnected"):
            raise ValueError("invalid connectivity")
        for key in ("dl_info_speed", "up_info_speed"):
            if type(info.get(key)) is not int or info[key] < 0:
                raise ValueError("invalid transfer statistics")
        offline_active = False
        if info["connection_status"] == "disconnected":
            # One item suffices; never emit names, hashes, trackers or paths.
            torrents = json.loads(get("torrents/info?filter=downloading&limit=1", 32768))
            if not isinstance(torrents, list) or len(torrents) > 1:
                raise ValueError("invalid queue")
            if torrents and (not isinstance(torrents[0], dict) or not isinstance(torrents[0].get("state"), str)):
                raise ValueError("invalid torrent state")
            offline_active = bool(torrents)
        detail = ("Global session disconnected with unfinished download activity" if offline_active else
                  "Global transfer API usable; connected, firewalled or disconnected idle session accepted")
        return [session, ctx.check(names[1], offline_active, detail)]
    except Exception:
        return [session, ctx.check(names[1], True, "Transfer or queue API unavailable, unauthorized, timed out or invalid")]
