# AGENTS.md

This file is the authoritative project-level instruction source for agents working in this repository.

## Project Rules

- Keep orchestration, tools, MCP, skills, RAG, memory, channels, and security modules decoupled.
- Prefer typed interfaces and explicit schemas over implicit dictionaries.
- Do not hardcode credentials, tokens, private endpoints, or personal data.
- Treat high-risk tools as approval-gated and idempotent by default.
- Use parameterized database queries only.
- Validate dynamic SQL field names with allowlists before use.

## Development Boundaries

- Scaffold production-facing interfaces, but keep real external calls behind adapters.
- Store secrets in environment variables or secret managers, never in Git.
- Add tests when changing schema validation, tool registration, memory writes, or channel event normalization.

## Memory Policy

- `AGENTS.md` is the authoritative behavior and project-rule source.
- `SOUL.md` is for persona and style only.
- `MEMORY.md` is for stable facts and preferences that have a clear source.
