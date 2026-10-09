"""Credential-free technical-plan API compatibility and access guard checks."""
import json


def compatible(document):
    if not isinstance(document, dict) or not str(document.get("openapi", "")).startswith("3."):
        return False
    if document.get("info", {}).get("title") != "Newjoy Verified Artifact Preview":
        return False
    paths = document.get("paths", {})
    schemas = document.get("components", {}).get("schemas", {})
    for path, operation, model, fields in (
        ("/preview_opencloud_pdf", "preview_opencloud_pdf", "PreviewPdf", ("path",)),
        ("/preview_opencloud_image", "preview_opencloud_image", "PreviewWebsiteImage", ("path",)),
        ("/import_plan_attachment", "import_plan_attachment", "ImportAttachment", ("filename", "projectPath", "destinationKind")),
    ):
        post = paths.get(path, {}).get("post", {})
        if post.get("operationId") != operation or "200" not in post.get("responses", {}):
            return False
        body = post.get("requestBody", {})
        if body.get("required") is not True or body.get("content", {}).get("application/json", {}).get("schema", {}).get("$ref") != "#/components/schemas/" + model:
            return False
        schema = schemas.get(model, {})
        if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
            return False
        if not set(fields).issubset(schema.get("required", [])):
            return False
        if any(schema.get("properties", {}).get(field, {}).get("type") != "string" for field in fields):
            return False
    return True


def run(ctx, config):
    base = config["url"].rstrip("/")
    records = []
    try:
        response = ctx.http(base + "/openapi.json", timeout=min(5, ctx.remaining()), max_bytes=131072)
        valid = response.status == 200 and compatible(json.loads(response.body))
        detail = "preview/import API models compatible" if valid else "OpenAPI unavailable or incompatible preview/import models"
    except Exception:
        valid, detail = False, "OpenAPI request or parsing failed"
    records.append(ctx.check("Technical plans API contract", not valid, detail))
    try:
        # No bearer and no workspace: source confirms auth dependency runs before
        # renderer invocation; this request never creates files or invokes Blender.
        response = ctx.http(base + "/internal/get-plan-schema", method="POST", data=b"{}",
                            headers={"Content-Type": "application/json"}, timeout=min(5, ctx.remaining()), max_bytes=4096)
        payload = json.loads(response.body)
        guarded = response.status == 401 and payload == {"detail": "Bearer authentication is required"}
        detail = "internal schema route enforces bearer authentication" if guarded else "internal schema route missing or authentication contract changed"
    except Exception:
        guarded, detail = False, "internal schema authentication probe failed"
    records.append(ctx.check("Technical plans internal access guard", not guarded, detail))
    return records
