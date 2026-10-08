"""Anonymous Open WebUI application contract; never calls inference APIs."""
import json
import re
from html.parser import HTMLParser


class Assets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = []

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if key in ("href", "src") and value and re.fullmatch(
                r"/_app/immutable/entry/(?:start|app)\.[A-Za-z0-9_-]+\.js", value
            ):
                self.paths.append(value)


def get(ctx, base, path, limit=262144):
    if ctx.remaining() <= 0:
        raise TimeoutError()
    response = ctx.http(base + path, timeout=min(5, ctx.remaining()), max_bytes=limit)
    if response.status != 200:
        raise ValueError()
    return response


def run(ctx, config):
    base = config["url"].rstrip("/")
    rows = []
    try:
        version = json.loads(get(ctx, base, "/api/version").body)
        app = json.loads(get(ctx, base, "/api/config").body)
        features = app.get("features", {})
        good = (app.get("status") is True and
                isinstance(version.get("version"), str) and
                re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[A-Za-z0-9.+-]*)", version["version"]) and
                app.get("version") == version["version"] and
                app.get("oauth", {}).get("providers", {}).get("oidc") == "Pocket ID" and
                features.get("auth") is True and
                features.get("enable_signup") is False and
                features.get("enable_login_form") is False and
                not app.get("onboarding", False))
        rows.append(ctx.check("Interior Designer backend contract", not good,
                              "API/version and Pocket ID configuration valid" if good else
                              "API/version or configured sign-in contract invalid"))
    except Exception:
        rows.append(ctx.check("Interior Designer backend contract", True,
                              "API/version configuration unavailable or malformed"))
    try:
        response = get(ctx, base, "/")
        parser = Assets()
        parser.feed(response.body.decode("utf-8"))
        if "html" not in next((v for k,v in response.headers.items() if k.lower() == "content-type"), "").lower():
            raise ValueError()
        paths = sorted(set(parser.paths))
        if not any("/start." in p for p in paths) or not any("/app." in p for p in paths):
            raise ValueError()
        # Fetch both entry modules; reject SPA fallback even when HTTP is 200.
        for path in paths[:2]:
            asset = get(ctx, base, path, 1048576)
            content_type = next((v for k,v in asset.headers.items() if k.lower() == "content-type"), "").lower()
            body = asset.body.strip()
            if not ("javascript" in content_type and len(body) > 40 and
                    not body.startswith(b"<") and
                    re.search(rb"\b(?:import|export)\b", body)):
                raise ValueError()
        rows.append(ctx.check("Interior Designer frontend assets", False,
                              "Both referenced application entry modules contain JavaScript"))
    except Exception:
        rows.append(ctx.check("Interior Designer frontend assets", True,
                              "Application HTML or entry modules unavailable or invalid"))
    return rows
