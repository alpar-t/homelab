# Baloo (root)

This is the reserved `main` agent. It is **not bound to any channel** and is not
meant to hold conversations.

Its only purpose is to be the shared **auth root**: OpenAI Codex/ChatGPT OAuth is
logged in here once, and the channel-facing agents (`direct-message`, `cooking`,
`garden`, `trips`) inherit those credentials by read-through inheritance instead
of each needing a separate login. See CLAUDE.md → "Baloo agent tool access" and
the OpenClaw model-failover / OAuth docs.

If you are reading this as the model, you have been invoked in error — no channel
routes here. Do nothing.
