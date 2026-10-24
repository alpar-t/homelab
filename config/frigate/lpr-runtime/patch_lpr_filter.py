"""Replace Frigate 0.17.2's two unbounded LPR regex filters with exact lookup."""

import hashlib
import py_compile
from pathlib import Path


EVENT_API = Path("/opt/frigate/frigate/api/event.py")
EXPECTED_SHA256 = "354a16949478578f7b15133f0abc20c4d8d3348192e27480e2ef3f1a888b4d96"
REGEX_FILTER = 'Event.data["recognized_license_plate"].cast("text").regexp(plate)'
EXACT_FILTER = 'Event.data["recognized_license_plate"].cast("text").in_([plate])'

original = EVENT_API.read_bytes()
assert hashlib.sha256(original).hexdigest() == EXPECTED_SHA256, "Frigate event API source changed"
source = original.decode("utf-8")
assert source.count(REGEX_FILTER) == 2, "Expected both LPR regex filter call sites"
assert source.count(EXACT_FILTER) == 0, "Exact LPR filter already present"

patched = source.replace(REGEX_FILTER, EXACT_FILTER)
assert patched.count(REGEX_FILTER) == 0
assert patched.count(EXACT_FILTER) == 2
EVENT_API.write_text(patched, encoding="utf-8")
py_compile.compile(str(EVENT_API), doraise=True)
