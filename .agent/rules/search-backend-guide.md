# Search Backend — agent guide

Scope: `search-backend/` (Python 3.11, FastAPI, SQLModel, deployed to Railway).

## Before declaring work done

Run both from `search-backend/`:

```
uvx ruff@0.15.14 check .
pyright
```

- **Ruff:** rules and target Python version live in `search-backend/ruff.toml`. Do not pass `--select` on the command line — the config file is the source of truth.
- **Pyright:** config is `pyrightconfig.json` at repo root (basic mode).

Fix or justify every new `E`/`F` Ruff finding and every new Pyright error you introduce. If you touch a file that already has lint or type debt, leave it no worse than you found it — do **not** opportunistically auto-fix unrelated debt in a feature PR. Cleanup belongs in focused PRs.

## Conventions

- Dependencies in `search-backend/requirements.txt`; pin exact versions.
- Don't add comments that restate the code; only document non-obvious *why*.
- Don't add error handling, fallbacks, or validation for cases that can't happen — trust internal callers; validate only at system boundaries (HTTP input, external APIs).
- Auth: JWT-based, see `docs/internals/auth-jwt-spec.md`.
- Embeddings: pluggable providers (`LocalEmbeddingProvider`, `OpenAIEmbeddingProvider`) in `services.py`.

## Out of scope for this guide

chrome-plugin, firefox-plugin, storage, docs, railway. Add separate guides under `.agent/rules/` if needed.
