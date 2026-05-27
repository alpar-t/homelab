# Baloo — Personal AI Assistant

Named after the bear in The Jungle Book. A self-hosted AI assistant accessible over WhatsApp (and potentially other channels), deployed on the homelab k3s cluster.

## Goals

- Conversational AI over WhatsApp using a dedicated phone number
- Understands Romanian, Hungarian, English (auto-detects language per message)
- Handles images, voice memos, group chats
- Stateless by design — no internal persistent memory managed by the assistant
- All configuration and context live in git repos, synced via ArgoCD
- The assistant's "knowledge about the user" lives in the private `life` repo; updated explicitly by the user via a PR that they review and merge
- Extensible: cluster services, browser tasks, home automation (via hass-mcp)
- Separate behaviour profiles (e.g. restricted mode when talking with kids)

## Design principles

### Statelessness

The assistant itself holds no persistent state that matters. Every conversation turn is reconstructed from:
- The user's `life` private repo (personal context, preferences, family info, etc.)
- The homelab repo (cluster context)
- Conversation history from a short rolling window (ephemeral, lost on pod restart is acceptable)

The assistant can propose memory updates ("I think we should record X in your life repo"), which triggers a PR. The user reviews and merges — nothing is written autonomously.

OpenClaw supports this: `OPENCLAW_STATE_DIR` can point to an ephemeral volume; a custom context engine plugin loads the life repo content into the system prompt at conversation start.

### Configuration-as-code

All config (system prompts, behaviour profiles, tool permissions, channel routing) lives in `config/baloo/` in this repo, synced by ArgoCD. No runtime config mutations. OpenClaw is 12-factor compliant: `OPENCLAW_CONFIG_PATH` and `OPENCLAW_STATE_DIR` are env vars.

## Technology decisions

### OpenClaw as the base

OpenClaw (https://github.com/openclaw/openclaw) is confirmed as the foundation. Key findings from source review:

- **WhatsApp**: Uses **Baileys v7.0.0-rc11** (unofficial WA Web protocol) — exactly what we want. No Business API needed.
- **Images**: Handled natively via jimp; passed as media buffers.
- **Voice messages**: Audio buffers extracted from WhatsApp and passed to transcription provider registry.
- **Group chats**: Supported with group session management and configurable group policies.
- **Claude/Anthropic**: Direct SDK usage (`@anthropic-ai/sdk`), full tool use, streaming, prompt caching built-in.
- **System prompt**: Fully customizable; `extraSystemPrompt` per-run injection supported.
- **Docker**: Multi-stage Dockerfile, health endpoints (`/healthz`, `/readyz`), non-root user, ports 18789 (gateway) and 18790 (bridge).
- **Plugins**: Comprehensive TypeScript plugin SDK. Channel plugins, provider plugins, tool providers. Bash execution with security gates.
- **Config**: 12-factor, env-var driven, config file path configurable.

**What OpenClaw does NOT have built-in:**
- GitHub repo reading/indexing (needs custom plugin or web-fetch via GitHub API)
- Whisper STT (infrastructure is ready via transcription provider registry, but no provider implemented)

### WhatsApp connector

Baileys v7 (already what OpenClaw uses). Session auth files stored on a Longhorn PVC. This is the only truly stateful part and is acceptable — losing it means re-scanning the QR code.

### Whisper STT

Self-hosted **faster-whisper** with `large-v3` model:
- Best quality for Romanian and Hungarian among open models
- Automatic language detection per audio clip (Whisper outputs the detected language)
- Runs on Intel Alder Lake-N CPU with INT8 quantization (~2–4s per 30s clip)
- Optional: OpenVINO backend to use i915 iGPU (faster, slightly more complex)

Deployed as **`wyoming-faster-whisper`** (Rhasspy project):
- Implements Wyoming protocol → HA Assist uses it directly as voice STT backend
- Also exposes HTTP API → OpenClaw transcription provider plugin calls it
- One instance, two consumers (Baloo + Home Assistant)
- Eliminates cloud STT for HA voice, reducing latency significantly

Resource estimate: ~1.5GB RAM for model loaded, schedule on a single node with GPU resource request (`gpu.intel.com/i915`) if using OpenVINO.

### Life repo context

OpenClaw has a swappable context engine (`/src/context-engine/registry.ts`). Custom plugin will:
1. At conversation start, fetch the `life` repo via GitHub API (or git clone to ephemeral volume)
2. Inject relevant sections into the system prompt
3. When the assistant proposes a memory update, generate a PR to the `life` repo for user review

### Model

Claude via Anthropic API (separate billing from Claude.ai Pro). `claude-sonnet-4-6` or latest Sonnet as default; can override per session.

### Kids mode

Route by sender phone number (configured in `config/baloo/profiles.yaml`). Numbers listed under `kids` get a restricted system prompt addendum injected via `extraSystemPrompt`. OpenClaw supports per-session model and prompt overrides.

## Deployment

Namespace: `baloo`

```
apps/baloo.yaml             # ArgoCD Application
config/baloo/
  manifests/
    namespace.yaml
    whisper.yaml            # wyoming-faster-whisper Deployment + Service + PVC (model cache)
    openclaw.yaml           # OpenClaw Deployment + Service
    secrets.yaml            # External Secrets: ANTHROPIC_API_KEY, WA session, GitHub token
    ingress.yaml            # internal ingress
  config/
    openclaw.json           # OpenClaw config (mounted as ConfigMap)
    system-prompt.txt       # base Baloo persona and instructions
    profiles.yaml           # phone number → profile mapping (adult/kids/etc.)
    profiles/
      default.txt
      kids.txt
```

## Open questions / next steps

- [ ] Write wyoming-faster-whisper k8s manifests (whisper.yaml); test with HA voice first
- [ ] Containerize OpenClaw: decide whether to use upstream image or build custom with extensions baked in
- [ ] Write custom context engine plugin to load `life` repo at conversation start
- [ ] Write custom Whisper transcription provider plugin for OpenClaw → wyoming HTTP API
- [ ] Design `profiles.yaml` schema and kids-mode routing logic
- [ ] Decide: full life repo injection vs chunked RAG (pgvector on existing CNPG)
- [ ] Decide: conversation history backend (ephemeral in-memory, or Postgres for cross-restart continuity)
- [ ] wyoming-faster-whisper: CPU-only first, evaluate if OpenVINO iGPU is needed for HA latency
- [ ] GitHub `life` repo: read-only deploy key for Baloo to fetch context

## Framework comparison (research 2026-05-19)

Evaluated four frameworks before settling on OpenClaw. Notes preserved for future reference.

| | **OpenClaw** | **ElizaOS** | **Letta** | **Wechaty** |
|---|---|---|---|---|
| **WhatsApp** | Baileys (unofficial) ✅ | Cloud API only ❌ | None ❌ | Unified SDK ✅ |
| **Images/audio/groups** | All native ✅ | Cloud API caps ⚠️ | N/A | Messages only |
| **Claude + tool use** | Direct SDK, full tool use, streaming, prompt caching ✅ | Supported but no embeddings, tool use unconfirmed ⚠️ | ✅ | Custom |
| **Whisper/STT** | Provider registry ready, no impl ⚠️ | Not built-in ❌ | None ❌ | None ❌ |
| **Stateless design** | Designed for it, context engine swappable ✅ | Persistent shared DB with security vuln ❌ | DB required ❌ | Stateless by default ✅ |
| **Health endpoints** | `/healthz` + `/readyz` ✅ | None documented ❌ | N/A | N/A |
| **k8s readiness** | Docker + health endpoints, no official k8s docs ⚠️ | No k8s docs, no health endpoints ❌ | Docker ⚠️ | Docker ⚠️ |
| **12-factor config** | Fully env-var driven ✅ | Mostly ✅ | Mostly ✅ | Code-first |
| **Stars / activity** | Moderate | 18.4k stars, very active ✅ | Active | Moderate |

**Why not ElizaOS**: Requires WhatsApp Business Cloud API (Meta verification headache). No confirmed Claude tool use. No health endpoints. Memory has documented security vulnerabilities (context manipulation attacks). Not designed for stateless operation.

**Why not Letta**: Requires PostgreSQL, no WhatsApp, built around persistent memory — the opposite of the design goal.

**Why not Wechaty**: Just a messaging abstraction layer, no LLM integration. Would still need everything else.

**Foundation-backed landscape**: The Linux Foundation formed the Agentic AI Foundation (Dec 2025) around MCP, Goose (Block), and AGENTS.md — none are personal assistant frameworks. CNCF's Kagent is k8s-ops focused. No foundation-backed chatbot/messaging AI agent framework exists.

## Status

Architecture decided. OpenClaw confirmed as foundation. Starting with wyoming-faster-whisper (highest immediate value: improves HA voice + unblocks Baloo voice memos).
