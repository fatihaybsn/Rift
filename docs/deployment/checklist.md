# API Change Radar - Release & Readiness Checklist

Use this checklist to ensure the project is ready for a release or a stable portfolio demonstration.

## 1. Codebase Health

- [ ] **Tests pass locally:** Run `make check` (executes `ruff` and `pytest`).
- [ ] **Migrations are clean:** Run `alembic upgrade head` on a fresh database without errors.
- [ ] **No print statements:** All observability should use the structured logger.
- [ ] **Formatting & Linting:** `ruff format --check .` and `ruff check .` report no findings.
- [ ] **Dependencies fixed:** `pyproject.toml` dependencies are clearly pinned or managed.

## 2. Docker & Environment

- [ ] **Container builds successfully:** `docker compose build app` finishes without caching errors.
- [ ] **Smoke test passes:** Execution of `./scripts/smoke.sh` returns a generated report without crashing.
- [ ] **Env template updated:** `docker-compose.yml` and `.env.example` are kept in sync with any new settings configured in `app/core/settings.py`.
- [ ] **No secrets in repo:** Verify no API keys, private Postgres URLs, or LLM keys are hardcoded or tracked in Git.

## 3. API & Documentation

- [ ] **Swagger docs populate:** `http://localhost:8000/docs` correctly displays all models and routes.
- [ ] **Health endpoint responsive:** `http://localhost:8000/healthz` returns `{"status": "healthy"}`.
- [ ] **Demo examples run:** The files provided in `examples/` can be successfully ingested and parsed by the Diff Engine.
- [ ] **README up to date:** Core MVP scope is respected and architectural notes accurately reflect the repo state.

## 4. Operational Boundaries

- [ ] **Determinism remains authoritative:** Check that any newly added logic acts consistently and that LLM behavior strictly operates as an optional add-on layer without altering diff results.
- [ ] **Port bindings:** Docker-compose maps ports correctly.

## 5. Artifacts Created

- [ ] **Report structure stable:** The returned JSON/Markdown schema aligns with the documented models. The demo HTML view efficiently presents the latest run.
- [ ] **Versioning:** Update versions in both the application code (if applicable) and git tags for stable snapshots.
