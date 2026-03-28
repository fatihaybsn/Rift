# API Change Radar

API Change Radar is a backend tool that compares two OpenAPI specifications, detects meaningful API changes, classifies their risk level, and produces a structured report for review.

This project is being built as a production-minded backend portfolio project. The goal is not to create a toy diff script, but a clean and reviewable service that reflects real engineering discipline.

## What problem it solves

API changes often cause silent breakage, release risk, and integration issues.

A simple text diff is not enough.  
Engineering teams need answers to questions like:

- What changed between version A and version B?
- Which changes are likely to break consumers?
- Which changes are low-risk and which ones require careful review?
- Can the result be stored, queried, and presented as a usable report?

API Change Radar focuses on that workflow.

## Project goals

This repository aims to demonstrate:

- clear backend architecture
- deterministic business logic
- explicit validation and error handling
- report-oriented product design
- observability and testability
- practical engineering tradeoffs
- controlled use of AI only where it actually helps

## MVP scope

The initial version will support:

- uploading two OpenAPI specs
- optional changelog text input
- parsing and validating JSON/YAML specs
- normalizing specs into a canonical internal model
- computing deterministic diffs
- classifying findings by severity
- persisting analysis runs and reports
- exposing report retrieval endpoints
- basic health/readiness endpoints
- basic metrics, traces, and structured logs

## Non-goals for the first version

The MVP will intentionally not include:

- remote URL fetching
- GitHub/webhook integrations
- Slack/Jira integrations
- full frontend application
- multi-tenant auth or RBAC
- codebase impact analysis
- autonomous AI decision-making
- LLM-based override of deterministic results

## Design principles

- deterministic logic first
- explicit over clever
- narrow scope over broad ambition
- tests for meaningful business logic
- observability is part of the system
- AI is optional and non-authoritative

## Planned architecture

The service is expected to contain these main parts:

- **Ingestion API**  
  Accepts two specs and optional changelog text.

- **Validator / Parser**  
  Parses JSON/YAML and validates OpenAPI input.

- **Normalizer**  
  Converts both specs into a canonical internal representation.
  For MVP determinism, canonical output intentionally excludes `servers`.
  Parameter serialization controls (`style`, `explode`) are deferred: only
  default semantics are accepted, non-default values fail loudly.

- **Diff Engine**  
  Computes structured, deterministic findings.

- **Severity Engine**  
  Maps findings to explicit severity levels.

- **Report Store**  
  Persists runs, artifacts, normalized snapshots, and findings.

- **Read API**  
  Returns run details and generated reports.

- **Observability Layer**  
  Adds metrics, traces, and structured logs.

More detail will be added in `docs/architecture.md`.

## Planned stack

- Python 3.12
- FastAPI
- PostgreSQL
- SQLAlchemy + Alembic
- Docker / Docker Compose
- Pytest
- OpenTelemetry
- GitHub Actions

## Demo report view (minimal)

For demo purposes, the service also exposes a small server-rendered HTML report page:

- `GET /api/v1/demo/runs/{report_id}` (demo-first route)
- `GET /api/v1/reports/{report_id}/demo` (report-scoped alias)

The page is intentionally minimal and read-only. It shows summary counts, top
high-severity findings, and links to authoritative raw report outputs:

- JSON: `GET /api/v1/reports/{report_id}`
- Markdown: `GET /api/v1/reports/{report_id}?format=markdown`

## Local database configuration

Create a local `.env` from the template and set your PostgreSQL role/password:

```bash
cp .env.example .env
```

`DATABASE_URL` must point to a role that exists in your local PostgreSQL instance.
If you see `FATAL: role "postgres" does not exist`, replace `postgres` in the URL
with your local PostgreSQL role.

## Database migrations (current scaffold)

Persistence schema migrations are managed with Alembic.

```bash
alembic upgrade head
alembic downgrade base
```

Migration tests use a real PostgreSQL database URL from `TEST_POSTGRES_DATABASE_URL`.
For safety, the database name must include `test`.

## Repository status

Current status: **pre-MVP / active build**

This repository is being developed incrementally.  
The early focus is:

1. freeze scope
2. bootstrap the backend
3. build the deterministic diff core
4. add persistence and reporting
5. add observability and tests
6. add optional AI-assisted changelog interpretation later

## Development roadmap

- [ ] repository scaffold
- [ ] FastAPI bootstrap
- [ ] database setup
- [ ] run creation API
- [ ] OpenAPI parsing and validation
- [ ] normalization pipeline
- [ ] deterministic diff engine
- [ ] severity rules
- [ ] report retrieval API
- [ ] observability
- [ ] test hardening
- [ ] optional changelog interpreter
- [ ] Dockerized local stack
- [ ] CI pipeline
- [ ] deployable demo version

## Why this project matters as a portfolio piece

This project is intentionally designed to show:

- backend engineering maturity
- API contract thinking
- explicit rule-based domain logic
- production-minded service design
- disciplined scope control
- useful, non-hype AI integration

## Author

Built by Fatih Ayıbasan as a backend-focused portfolio project.
