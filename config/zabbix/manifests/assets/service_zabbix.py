"""Anonymous Zabbix API and frontend contracts; no alert or account mutations."""
import json
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inputs = set()
        self.assets = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "input":
            self.inputs.add(attrs.get("name"))
        if tag == "link" and attrs.get("rel") == "stylesheet":
            self.assets.append(attrs.get("href", ""))


def request(ctx, url, max_bytes=262144, **kwargs):
    return ctx.http(url, timeout=min(6, ctx.remaining()), max_bytes=max_bytes, **kwargs)


def run(ctx, config):
    base = config["base_url"]
    checks = []
    try:
        response = request(ctx, urljoin(base, "api_jsonrpc.php"), method="POST",
                           headers={"Content-Type": "application/json-rpc"},
                           data=json.dumps({"jsonrpc": "2.0", "method": "apiinfo.version",
                                            "params": {}, "id": 1}).encode())
        result = json.loads(response.body)
        good = (response.status == 200 and isinstance(result, dict)
                and result.get("jsonrpc") == "2.0" and type(result.get("id")) is int
                and result["id"] == 1 and "error" not in result
                and isinstance(result.get("result"), str)
                and re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", result["result"]) is not None)
        detail = "JSON-RPC version contract valid" if good else "JSON-RPC version contract invalid"
    except Exception:
        good, detail = False, "JSON-RPC version request unavailable"
    checks.append(ctx.check("Zabbix JSON-RPC capability", not good, detail))
    try:
        response = request(ctx, base)
        page = Page()
        page.feed(response.body.decode("utf-8"))
        if response.status != 200 or not {"name", "password"}.issubset(page.inputs):
            raise ValueError()
        asset = next((urljoin(base, path) for path in page.assets
                      if path and urlsplit(urljoin(base, path)).netloc == urlsplit(base).netloc
                      and urlsplit(urljoin(base, path)).scheme == urlsplit(base).scheme
                      and urlsplit(path).path.endswith(".css")), None)
        if asset is None:
            raise ValueError()
        response = request(ctx, asset, max_bytes=1048576)
        content_type = next((v for k, v in response.headers.items()
                             if k.lower() == "content-type"), "")
        good = (response.status == 200 and content_type.split(";", 1)[0].strip() == "text/css"
                and len(response.body.strip()) > 100 and b"{" in response.body
                and b"}" in response.body and b"<html" not in response.body.lower())
        detail = "Login bootstrap and stylesheet valid" if good else "Frontend stylesheet contract invalid"
    except Exception:
        good, detail = False, "Frontend bootstrap or asset unavailable"
    checks.append(ctx.check("Zabbix frontend capability", not good, detail))
    return checks
