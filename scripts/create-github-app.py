#!/usr/bin/env python3
"""
Creates the 'baloo-homelab' GitHub App via the manifest flow, then creates
the k8s Secret in the baloo namespace with the app credentials.

Usage:
    python3 scripts/create-github-app.py

What it does:
    1. Starts a local HTTP server to receive the GitHub OAuth callback
    2. Opens a browser with a self-submitting form → GitHub creates the app
    3. Captures the one-time code from the redirect
    4. Exchanges the code for app credentials (app ID, client ID, private key)
    5. Creates kubectl secret in the baloo namespace

The private key is never committed to the repo. Store it in the k8s Secret only.
"""

import http.server
import json
import os
import subprocess
import sys
import threading
import urllib.parse
import urllib.request
from pathlib import Path

PORT = 3721
CALLBACK_URL = f"http://localhost:{PORT}/callback"
GITHUB_ORG = "alpar-t"
K8S_NAMESPACE = "baloo"
K8S_SECRET_NAME = "baloo-github-app"

MANIFEST = {
    "name": "baloo-homelab",
    "url": f"https://github.com/{GITHUB_ORG}",
    "redirect_url": CALLBACK_URL,
    "public": False,
    "default_permissions": {
        "contents": "write",
        "pull_requests": "write",
        "metadata": "read",
    },
}

HTML = f"""<!DOCTYPE html>
<html>
<head><title>Creating baloo-homelab GitHub App...</title></head>
<body>
<p>Submitting GitHub App manifest — log in to GitHub if prompted, then approve.</p>
<form id="f" action="https://github.com/settings/apps/new" method="post">
  <input type="hidden" name="manifest" value='{json.dumps(MANIFEST)}'>
</form>
<script>document.getElementById('f').submit();</script>
</body>
</html>
"""

code_received = threading.Event()
received_code = None


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        global received_code
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if parsed.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(HTML.encode())

        elif parsed.path == "/callback":
            code = params.get("code", [None])[0]
            if code:
                received_code = code
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"<p>App created! Check your terminal.</p>")
                code_received.set()
            else:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"No code in callback.")
        else:
            self.send_response(404)
            self.end_headers()


def exchange_code(code):
    url = f"https://api.github.com/app-manifests/{code}/conversions"
    token = subprocess.check_output(["gh", "auth", "token"]).decode().strip()
    req = urllib.request.Request(
        url,
        method="POST",
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Length": "0",
        },
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def create_k8s_secret(app_id, client_id, client_secret, private_key):
    # Write key to a temp file for kubectl --from-file
    key_path = Path("/tmp/baloo-github-app.pem")
    key_path.write_text(private_key)
    key_path.chmod(0o600)

    # Delete existing secret if present (idempotent)
    subprocess.run(
        ["kubectl", "delete", "secret", K8S_SECRET_NAME, "-n", K8S_NAMESPACE, "--ignore-not-found"],
        check=True,
    )

    subprocess.run(
        [
            "kubectl", "create", "secret", "generic", K8S_SECRET_NAME,
            "-n", K8S_NAMESPACE,
            f"--from-literal=app-id={app_id}",
            f"--from-literal=client-id={client_id}",
            f"--from-literal=client-secret={client_secret}",
            f"--from-file=private-key={key_path}",
        ],
        check=True,
    )

    key_path.unlink()
    print(f"k8s Secret '{K8S_SECRET_NAME}' created in namespace '{K8S_NAMESPACE}'.")


def main():
    server = http.server.HTTPServer(("localhost", PORT), Handler)
    t = threading.Thread(target=server.serve_forever)
    t.daemon = True
    t.start()

    url = f"http://localhost:{PORT}/"
    print(f"Opening {url} in browser — log in to GitHub if prompted, then approve the app.")
    subprocess.run(["open", url])

    print("Waiting for GitHub callback...")
    code_received.wait(timeout=120)

    if not received_code:
        print("Timed out waiting for callback.")
        sys.exit(1)

    server.shutdown()
    print("Exchanging code for app credentials...")
    creds = exchange_code(received_code)

    app_id = creds["id"]
    client_id = creds["client_id"]
    client_secret = creds.get("client_secret", "")
    private_key = creds["pem"]

    print(f"\n=== baloo-homelab GitHub App created ===")
    print(f"APP_ID:    {app_id}")
    print(f"CLIENT_ID: {client_id}")
    print()

    create_k8s_secret(app_id, client_id, client_secret, private_key)

    print(f"\nNext: install the app on repos with:")
    print(f"  python3 scripts/github-app-repos.py add <owner/repo>")


if __name__ == "__main__":
    main()
