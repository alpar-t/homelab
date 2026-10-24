# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "fastapi==0.116.1",
#   "httpx==0.28.1",
#   "pypdf==6.0.0",
#   "python-multipart==0.0.20",
#   "uvicorn==0.35.0",
# ]
# ///
"""Warm uv's offline cache for Baloo's technical-plan-api.py."""

import fastapi
import httpx
import pypdf
import uvicorn

assert fastapi and httpx and pypdf and uvicorn
