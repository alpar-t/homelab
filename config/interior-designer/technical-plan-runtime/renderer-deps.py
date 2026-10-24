# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "cairosvg>=2.8,<3",
#   "jsonschema>=4.25,<5",
#   "pypdf>=6,<7",
# ]
# ///
"""Warm uv's offline cache and smoke-test Cairo output for Baloo's renderer."""

from io import BytesIO

import cairosvg
import jsonschema
from pypdf import PdfReader

svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><circle cx="5" cy="5" r="2"/></svg>'
pdf = cairosvg.svg2pdf(bytestring=svg)
png = cairosvg.svg2png(bytestring=svg)
assert len(PdfReader(BytesIO(pdf)).pages) == 1
assert png.startswith(b"\x89PNG")
assert jsonschema
