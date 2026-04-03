# API Change Radar

API Change Radar is a FastAPI-based backend service that compares two OpenAPI specifications, detects meaningful API changes, classifies their risk level, stores the analysis, and exposes the result as JSON, Markdown, and a minimal HTML demo report.

This project is designed as a production-minded backend portfolio project. The goal is not to ship a toy diff script, but a reviewable service with clear architecture, deterministic behavior, persistence, observability, and a clean Docker-first distribution flow.

\---

## What this project does

API changes often create silent breakage, release risk, and integration problems. A plain text diff is not enough for real review.

API Change Radar focuses on questions like:

* What changed between version A and version B?
* Which changes are likely to break consumers?
* Which changes are low-risk and which ones need review?
* Can the result be persisted and retrieved as a structured report?

\---

## Key features

* Compare exactly two OpenAPI specs
* Accept JSON or YAML spec uploads
* Optional changelog text input
* Deterministic diff and severity classification
* PostgreSQL-backed persistence for runs, artifacts, and reports
* Structured report retrieval API
* Markdown export for reports
* Minimal HTML demo report page
* Health, readiness, and metrics endpoints
* Optional AI changelog interpretation behind a feature flag
* Docker-first deployment for easy local usage

\---

## Project status

Current status: **pre-MVP / active build**

The current version already supports the core ingestion, analysis, storage, and report retrieval flow, but the project is still evolving.

\---

## Architecture summary

Main parts of the system:

* **Ingestion API**: accepts two spec files and optional changelog text
* **Validator / Parser**: validates OpenAPI input and reads JSON/YAML
* **Normalizer**: converts specs into a canonical internal representation
* **Diff Engine**: computes deterministic findings
* **Severity Engine**: classifies findings into risk levels
* **Report Store**: persists runs, findings, artifacts, and report state
* **Read API**: returns structured reports and demo views
* **Observability Layer**: exposes logs, traces, and metrics

More detail can live in `docs/architecture.md`.

\---

## Tech stack

* Python 3.12
* FastAPI
* PostgreSQL
* SQLAlchemy + Alembic
* Docker / Docker Compose
* Pytest
* OpenTelemetry
* GitHub Actions

\---

## Distribution model

This repository is distributed in a Docker-first way:

* **GitHub repository** stores the source code, `docker-compose.yml`, `.env.example`, examples, and README
* **Docker Hub** stores the prebuilt application image

### Normal user flow

A normal user does **not** need to build the image locally.

They will:

1. get the project folder from GitHub
2. use the `docker-compose.yml` file in the repository
3. pull the application image from Docker Hub
4. start the stack with Docker Compose

### Docker Hub image

```text
fatihayibasan/api-change-radar:latest
```

### Which Compose file is for what?

* `docker-compose.yml` -> **release / end-user file**

  * pulls the app image from Docker Hub
  * recommended for normal usage
* `docker-compose.dev.yml` -> **development file**

  * builds the image locally
  * intended for development and local modification

If you are a normal user, use **`docker-compose.yml`**.

\---

## Quick start for normal users

### Prerequisites

You need:

* Docker Desktop or Docker Engine
* Docker Compose support

### 1\) Get the repository from GitHub

Either clone it:

```bash
git clone <YOUR\_GITHUB\_REPOSITORY\_URL>
cd <YOUR\_REPOSITORY\_FOLDER>
```

Or download the repository ZIP from GitHub and extract it.

### 2\) Create your environment file

Linux / macOS:

```bash
cp .env.example .env
```

PowerShell:

```powershell
Copy-Item .env.example .env
```

### 3\) Start the stack

Recommended first run:

```bash
docker compose pull
docker compose up -d
```

What this does:

* pulls `postgres:16`
* pulls `fatihayibasan/api-change-radar:latest`
* starts PostgreSQL
* starts the FastAPI app
* runs database migrations through the container entrypoint

### 4\) Verify that the service is running

Open these in your browser:

* Health check: `http://localhost:8000/healthz`
* Readiness: `http://localhost:8000/readyz`
* Swagger UI: `http://localhost:8000/docs`
* ReDoc: `http://localhost:8000/redoc`
* Metrics: `http://localhost:8000/metrics`

If everything is correct, `/healthz` should return:

```json
{"status":"healthy","service":"api-change-radar"}
```

### 5\) Stop the stack

```bash
docker compose down
```

To also remove the PostgreSQL volume:

```bash
docker compose down -v
```

\---

## Updating to a newer image version

If a newer image is pushed to Docker Hub, update with:

```bash
docker compose pull
docker compose up -d
```

\---

## Development setup

If you want to modify the source code and build locally instead of using the Docker Hub image:

```bash
docker compose -f docker-compose.dev.yml up --build -d
```

Stop it with:

```bash
docker compose -f docker-compose.dev.yml down -v
```

Use `docker-compose.dev.yml` only for development work.

\---

## How to use the application

This project is primarily a **backend API**, not a full frontend product.

The main user-facing interface is the FastAPI interactive docs page:

```text
http://localhost:8000/docs
```

That is the easiest way to test the full flow.

### Main usage flow

1. Upload **exactly two** OpenAPI spec files
2. Optionally include changelog text
3. Receive a `run\_id`
4. Check the run status until it becomes `completed`
5. Fetch the final report
6. Optionally open the demo HTML report page

### Supported spec formats

* JSON
* YAML

### Upload limits

* exactly **two** spec files are required
* each spec file must be non-empty
* spec file size limit is enforced by the API
* optional `changelog\_text` is also size-limited

\---

## Fastest manual test via Swagger UI

Open:

```text
http://localhost:8000/docs
```

Then use these endpoints in order.

### 1\) Create a run

Endpoint:

```text
POST /api/v1/runs
```

Input:

* `specs`: upload two files
* `changelog\_text`: optional text

Response example:

```json
{
  "run\_id": "8a0d1d9e-0000-0000-0000-000000000000",
  "status": "pending"
}
```

### 2\) Check run status

Endpoint:

```text
GET /api/v1/runs/{run\_id}
```

Wait until `status` becomes `completed`.

### 3\) Fetch the JSON report

Endpoint:

```text
GET /api/v1/reports/{report\_id}
```

At the moment, `report\_id` is the same UUID as the `run\_id`.

### 4\) Fetch the Markdown report

Endpoint:

```text
GET /api/v1/reports/{report\_id}?format=markdown
```

### 5\) Open the minimal HTML demo report

You can open either of these:

```text
GET /api/v1/reports/{report\_id}/demo
GET /api/v1/demo/runs/{report\_id}
```

\---

## Example test files included in the repo

The repository includes example specs in:

* `examples/v1.yaml`
* `examples/v2.yaml`

You can use them directly in Swagger UI or with `curl`.

\---

## Example usage with curl

### Create a run

```bash
curl -X POST http://localhost:8000/api/v1/runs \\
  -F "specs=@examples/v1.yaml;type=application/yaml" \\
  -F "specs=@examples/v2.yaml;type=application/yaml" \\
  -F "changelog\_text=Example changelog for demo"
```

This returns a `run\_id`.

### Check the run status

```bash
curl http://localhost:8000/api/v1/runs/<RUN\_ID>
```

### Fetch the JSON report

```bash
curl http://localhost:8000/api/v1/reports/<RUN\_ID>
```

### Fetch the Markdown report

```bash
curl "http://localhost:8000/api/v1/reports/<RUN\_ID>?format=markdown"
```

### Open the demo HTML page in the browser

```text
http://localhost:8000/api/v1/reports/<RUN\_ID>/demo
```

\---

## One-shot smoke test

A simple smoke script is included for an end-to-end check.

Linux / macOS / Git Bash / WSL:

```bash
chmod +x scripts/smoke.sh
./scripts/smoke.sh
```

What it does:

* waits for `/healthz`
* creates sample spec files
* submits a run
* waits for background processing to finish
* fetches the final Markdown report

\---

## API surface summary

### Base URLs

* Root: `/`
* API prefix: `/api/v1`

### Health and observability

* `GET /healthz`
* `GET /readyz`
* `GET /metrics`

### Runs

* `POST /api/v1/runs`
* `GET /api/v1/runs/{run\_id}`

### Reports

* `GET /api/v1/reports/{report\_id}`
* `GET /api/v1/reports/{report\_id}?format=markdown`
* `GET /api/v1/reports/{report\_id}/demo`
* `GET /api/v1/demo/runs/{report\_id}`

\---

## Environment variables

Below are the most important settings for normal usage.

|Variable|Example / Default|Description|
|-|-|-|
|`APP\_NAME`|`api-change-radar`|Service name used in app metadata/logging|
|`ENVIRONMENT`|`production` or `development`|Environment label|
|`DEBUG`|`false`|Enables debug-style behavior|
|`DOCS\_ENABLED`|`true`|Enables `/docs` and `/redoc`|
|`APP\_PORT`|`8000`|Host port exposed by Docker Compose|
|`POSTGRES\_USER`|`radar`|PostgreSQL user|
|`POSTGRES\_PASSWORD`|`radar`|PostgreSQL password|
|`POSTGRES\_DB`|`api\_change\_radar`|PostgreSQL database name|
|`DATABASE\_URL`|generated in compose|Database connection string used by the app|
|`LOG\_LEVEL`|`INFO`|Logging level|
|`TRACING\_EXPORTER`|`none`|Trace export mode|
|`OTLP\_ENDPOINT`|empty|OTLP collector URL when tracing is enabled|
|`ENABLE\_LLM\_CHANGELOG`|`false`|Enables optional AI changelog interpretation|
|`LLM\_LOW\_CONFIDENCE\_THRESHOLD`|`0.6`|AI confidence threshold|

### Recommended `.env` example for Docker usage

```env
IMAGE\_TAG=latest
APP\_PORT=8000
POSTGRES\_USER=radar
POSTGRES\_PASSWORD=radar
POSTGRES\_DB=api\_change\_radar
APP\_NAME=api-change-radar
ENVIRONMENT=production
DEBUG=false
DOCS\_ENABLED=true
LOG\_LEVEL=INFO
TRACING\_EXPORTER=none
ENABLE\_LLM\_CHANGELOG=false
LLM\_LOW\_CONFIDENCE\_THRESHOLD=0.6
```

\---

## Local database and migrations

Database migrations are managed with Alembic.

When you run the Docker stack, migrations are executed automatically by the application container entrypoint before the FastAPI server starts.

If you run the project manually outside Docker, typical migration commands are:

```bash
alembic upgrade head
alembic downgrade base
```

\---

## CI summary

The repository includes GitHub Actions-based CI with checks for formatting, linting, migrations, tests, and container validation.

\---

## Design principles

* deterministic logic first
* explicit over clever
* narrow scope over broad ambition
* tests for meaningful business logic
* observability is part of the system
* AI is optional and non-authoritative

\---

## MVP scope

The initial version supports:

* uploading two OpenAPI specs
* optional changelog text input
* parsing and validating JSON/YAML specs
* normalization into a canonical model
* deterministic diff computation
* severity classification
* persistence of runs and reports
* report retrieval endpoints
* health/readiness endpoints
* metrics, traces, and structured logs

### Non-goals for the first version

The MVP intentionally does **not** include:

* remote URL fetching
* GitHub/webhook integrations
* Slack/Jira integrations
* full frontend application
* multi-tenant auth or RBAC
* codebase impact analysis
* autonomous AI decision-making
* LLM-based override of deterministic results

\---

## Demo / portfolio notes

For demos, the easiest path is:

1. start the stack with Docker Compose
2. open Swagger UI
3. upload two example specs
4. wait for the run to complete
5. open the HTML demo report page

This gives a clean recruiter / reviewer flow without needing a separate frontend.

\---

## Troubleshooting

### `docker compose` says no configuration file provided

You are not inside the repository folder that contains `docker-compose.yml`.

Move into the project folder first, then run:

```bash
docker compose pull
docker compose up -d
```

### Port 8000 is already in use

Change the host port in `.env`:

```env
APP\_PORT=8001
```

Then restart:

```bash
docker compose up -d
```

### Health check works but there is no UI homepage

That is expected. This project is an API-first backend service.

Use:

* `/docs` for Swagger UI
* `/redoc` for alternate docs
* `/api/v1/reports/<RUN\_ID>/demo` for the report demo page

### Want to fully reset the stack?

```bash
docker compose down -v
```

\---

## Author

Built by **Fatih Ayıbasan** as a backend-focused portfolio project.

