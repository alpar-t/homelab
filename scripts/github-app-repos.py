#!/usr/bin/env python3
"""
Manage which repos the baloo-homelab GitHub App can access.

Reads credentials from the k8s Secret (baloo/baloo-github-app).
Uses JWT auth (app private key) to find the installation, then an
installation token for repo listing. Add/remove use the gh user token.

Usage:
    python3 scripts/github-app-repos.py list
    python3 scripts/github-app-repos.py add  owner/repo [owner/repo ...]
    python3 scripts/github-app-repos.py remove owner/repo [owner/repo ...]
"""

import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

APP_NAME = "baloo-homelab"
K8S_NAMESPACE = "baloo"
K8S_SECRET_NAME = "baloo-github-app"


# ---------- k8s secret helpers ----------

def get_secret_value(key):
    result = subprocess.run(
        ["kubectl", "get", "secret", K8S_SECRET_NAME, "-n", K8S_NAMESPACE,
         "-o", f"jsonpath={{.data.{key}}}"],
        capture_output=True, text=True,
    )
    if result.returncode != 0 or not result.stdout:
        print(f"Could not read '{key}' from secret '{K8S_SECRET_NAME}': {result.stderr.strip()}")
        sys.exit(1)
    return base64.b64decode(result.stdout).decode()


def get_app_id():
    return int(get_secret_value("app-id"))


# ---------- JWT / GitHub App auth ----------

def _b64url(data):
    if isinstance(data, str):
        data = data.encode()
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def make_jwt(app_id):
    """Sign a GitHub App JWT using the private key from the k8s secret."""
    private_key = get_secret_value("private-key")
    header = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}, separators=(",", ":")))
    now = int(time.time())
    payload = _b64url(json.dumps(
        {"iat": now - 60, "exp": now + 600, "iss": str(app_id)},
        separators=(",", ":"),
    ))
    signing_input = f"{header}.{payload}".encode()

    with tempfile.NamedTemporaryFile(suffix=".pem", mode="w", delete=False) as f:
        f.write(private_key)
        key_path = f.name
    try:
        result = subprocess.run(
            ["openssl", "dgst", "-sha256", "-sign", key_path],
            input=signing_input, capture_output=True, check=True,
        )
        sig = _b64url(result.stdout)
    finally:
        os.unlink(key_path)

    return f"{header}.{payload}.{sig}"


def api(path, method="GET", token=None, jwt=None, body=None):
    """Make a GitHub API call. Uses jwt or token for auth."""
    url = f"https://api.github.com{path}"
    auth = f"Bearer {jwt}" if jwt else f"token {token}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={
            "Authorization": auth,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read()) if resp.length != 0 else None
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"GitHub API error {e.code} {method} {path}: {body}", file=sys.stderr)
        sys.exit(1)


def get_installation(app_id):
    jwt = make_jwt(app_id)
    installations = api("/app/installations", jwt=jwt)
    if not installations:
        print(f"No installations found for {APP_NAME}.")
        print(f"Install the app first: https://github.com/apps/{APP_NAME}/installations/new")
        sys.exit(1)
    return installations[0]


def get_installation_token(app_id, installation_id):
    jwt = make_jwt(app_id)
    data = api(f"/app/installations/{installation_id}/access_tokens", method="POST", jwt=jwt)
    return data["token"]


# ---------- gh user-token helper (for add/remove) ----------

def gh_user_token():
    return subprocess.check_output(["gh", "auth", "token"]).decode().strip()


# ---------- repo helpers ----------

def get_repo(repo_slug):
    token = gh_user_token()
    data = api(f"/repos/{repo_slug}", token=token)
    if data is None:
        print(f"Repo not found or no access: {repo_slug}")
        sys.exit(1)
    return data


def setup_branch_protection(repo_slug, default_branch):
    """Require 1 review on the default branch; admins can bypass and merge without review."""
    token = gh_user_token()
    api(
        f"/repos/{repo_slug}/branches/{default_branch}/protection",
        method="PUT", token=token,
        body={
            "required_status_checks": None,
            "enforce_admins": False,
            "required_pull_request_reviews": {
                "required_approving_review_count": 1,
                "dismiss_stale_reviews": False,
                "require_code_owner_reviews": False,
            },
            "restrictions": None,
        },
    )
    print(f"  * branch protection set on '{default_branch}' (1 review required, admins exempt)")


# ---------- commands ----------

def list_repos(app_id, installation_id):
    token = get_installation_token(app_id, installation_id)
    data = api("/installation/repositories", token=token)
    repos = data.get("repositories", []) if data else []
    if not repos:
        print("No repos currently accessible to the app.")
    else:
        print(f"Repos accessible to {APP_NAME}:")
        for r in repos:
            print(f"  {r['full_name']}")


def add_repos(installation_id, repo_slugs):
    token = gh_user_token()
    for slug in repo_slugs:
        repo = get_repo(slug)
        api(f"/user/installations/{installation_id}/repositories/{repo['id']}",
            method="PUT", token=token)
        print(f"  + {slug}")
        setup_branch_protection(slug, repo["default_branch"])


def remove_repos(installation_id, repo_slugs):
    token = gh_user_token()
    for slug in repo_slugs:
        repo = get_repo(slug)
        api(f"/user/installations/{installation_id}/repositories/{repo['id']}",
            method="DELETE", token=token)
        print(f"  - {slug}")


# ---------- main ----------

def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("list", "add", "remove"):
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    app_id = get_app_id()
    installation = get_installation(app_id)
    installation_id = installation["id"]

    if cmd == "list":
        list_repos(app_id, installation_id)
    elif cmd == "add":
        if len(sys.argv) < 3:
            print("Usage: github-app-repos.py add owner/repo [...]")
            sys.exit(1)
        add_repos(installation_id, sys.argv[2:])
    elif cmd == "remove":
        if len(sys.argv) < 3:
            print("Usage: github-app-repos.py remove owner/repo [...]")
            sys.exit(1)
        remove_repos(installation_id, sys.argv[2:])


if __name__ == "__main__":
    main()
