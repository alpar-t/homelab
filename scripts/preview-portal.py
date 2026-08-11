#!/usr/bin/env python3
"""Serve the Newjoy portal locally with admin view-switching enabled."""

from __future__ import annotations

import argparse
import http.server
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ASSET_ROOT = Path(__file__).resolve().parents[1] / "config/portal/manifests/assets"
CATALOGS = {"admin", "family", "baloo", "base"}


class PortalPreviewHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, directory=str(ASSET_ROOT), **kwargs)

    def send_text(self, body: str, content_type: str) -> None:
        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        request = urlparse(self.path)

        if request.path == "/catalog.json":
            requested = parse_qs(request.query).get("view", ["admin"])[0]
            view = requested if requested in CATALOGS else "admin"
            catalog_path = ASSET_ROOT / "catalog" / f"{view}.json"
            self.send_text(catalog_path.read_text(encoding="utf-8"), "application/json")
            return

        if request.path == "/whoami":
            self.send_text("Local preview · advanced_apps\n", "text/plain")
            return

        if request.path.startswith("/catalog/"):
            self.send_error(404, "Catalog files are internal")
            return

        if request.path == "/oauth2/sign_out":
            self.send_response(302)
            self.send_header("Location", "/")
            self.end_headers()
            return

        super().do_GET()

    def log_message(self, message: str, *args: object) -> None:
        print(f"portal-preview: {message % args}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    if not ASSET_ROOT.is_dir():
        raise SystemExit(f"Portal assets not found: {ASSET_ROOT}")

    server = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), PortalPreviewHandler)
    print(f"Newjoy portal preview: http://127.0.0.1:{args.port}")
    print("The preview acts as an advanced_apps member; use View as to switch catalogs.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nPreview stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
