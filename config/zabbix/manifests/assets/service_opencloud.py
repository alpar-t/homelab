"""Read-only OpenCloud API and isolated WebDAV metadata probes."""
import base64
import json
import re
import urllib.parse
import xml.etree.ElementTree as ET

DAV = "{DAV:}"
BODY = b'<d:propfind xmlns:d="DAV:"><d:prop><d:resourcetype/><d:getetag/></d:prop></d:propfind>'


def metadata_valid(body, path):
    # Reject DTDs rather than permitting entity expansion in remote XML.
    if b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
        return False
    root = ET.fromstring(body)
    rows = root.findall(DAV + "response")
    if root.tag != DAV + "multistatus" or len(rows) != 1:
        return False
    href = urllib.parse.urlsplit(rows[0].findtext(DAV + "href", ""))
    if urllib.parse.unquote(href.path).rstrip("/") != urllib.parse.unquote(path).rstrip("/"):
        return False
    props = {}
    for part in rows[0].findall(DAV + "propstat"):
        if re.fullmatch(r"HTTP/\d(?:\.\d)? 200(?: .*)?", part.findtext(DAV + "status", "")):
            prop = part.find(DAV + "prop")
            if prop is not None:
                props.update({item.tag: item for item in prop})
    kind, etag = props.get(DAV + "resourcetype"), props.get(DAV + "getetag")
    return (kind is not None and kind.find(DAV + "collection") is not None
            and etag is not None and bool((etag.text or "").strip()))


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
    try:
        path = config.get("workspace_path", "")
        # A source-controlled, explicitly selected space/folder; no discovery/listing.
        if not path.startswith(("/dav/spaces/", "/remote.php/dav/spaces/")) or not path.endswith("/"):
            raise ValueError("workspace not configured")
        parts = urllib.parse.urlsplit(path)
        if parts.netloc or parts.query or parts.fragment or any(x in (".", "..") for x in urllib.parse.unquote(path).split("/")):
            raise ValueError("invalid workspace path")
        username, token = ctx.secret("opencloud-username"), ctx.secret("opencloud-app-token")
        auth = base64.b64encode((username + ":" + token).encode()).decode()
        response = ctx.http(base + path, method="PROPFIND", headers={
            "Authorization": "Basic " + auth, "Depth": "0", "Content-Type": "application/xml"},
            data=BODY, timeout=min(8, ctx.remaining()), max_bytes=32768)
        healthy = response.status == 207 and metadata_valid(response.body, path)
        result.append(ctx.check("OpenCloud monitor storage metadata", not healthy,
                                "authenticated collection metadata available" if healthy else "authentication or collection metadata failed"))
    except Exception:
        result.append(ctx.check("OpenCloud monitor storage metadata", True,
                                "monitor workspace, credentials or metadata unavailable"))
    return result
