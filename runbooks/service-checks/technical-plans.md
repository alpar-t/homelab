# Technical-plan API functional baseline

Every five minutes the collector checks the internal port 18809 API with a
25-second deadline and bounded responses. Three failed samples use the shared
functional alert debounce. No credentials or additional Kubernetes RBAC are
required. The service has no ingress-isolating NetworkPolicy; no network policy
change is needed for collector traffic.

`Technical plans API contract` validates OpenAPI 3, the application identity,
three preview/import operation IDs, success responses, JSON request model
references, required string fields, and rejection of extra model properties.
It catches wrong-service routing, broken schema generation and incompatible
preview/import API upgrades. Version strings alone are deliberately not pinned.
`Technical plans internal access guard` sends an empty unauthenticated POST to
`/internal/get-plan-schema` and requires the source-defined 401 JSON response.
It catches a missing internal route or an accidentally removed bearer guard.
Neither request accesses household files, submits a render, starts a workspace,
or invokes an LLM.

The deployed source authority is Baloo `openclaw/tools/technical-plan-api.py`;
its internal routes are omitted from OpenAPI. `/health` is a constant response
and is already covered by pod probes, so it is not used here. Successful API
startup imports FastAPI, Pydantic, httpx and pypdf, but these checks do **not**
prove runtime CairoSVG/uv rendering, semantic plan validation, OpenCloud access,
chat authorization or artifact publishing. Existing validation requires a
persisted workspace; no isolated in-memory validation endpoint is available.
The schema route invokes the actual renderer only after service authentication.
Its existing token is the broad OpenClaw gateway token, also authorized for
workspace mutation. Do not copy it to monitoring. Deeper coverage needs a
separately scoped read-only schema/validation endpoint before provisioning any
monitoring credential. This baseline must not be described as a successful
plan-generation test.

For failures, compare the API route/model definitions with this contract and
check the service and deployment. Do not diagnose by publishing a test plan.
