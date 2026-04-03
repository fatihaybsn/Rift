# API Change Radar - Deployment Guide

This guide covers deploying API Change Radar primarily for **local development**, **demo scenarios**, and **self-hosted Docker** environments. 

*(Note: While the app is built to be scalable, the current deployment focus is self-contained Docker environments rather than managed cloud services like Cloud Run. Cloud documentation may be added later as an optional distribution method).*

---

## 1. Local Docker Deployment (Preferred for Testing)

The easiest way to run the application locally without installing Python or Postgres on your host machine is via Docker Compose.

### Prerequisites
- Docker and Docker Compose installed

### Steps

1. **Clone the repository:**
   ```bash
   git clone <repository_url>
   cd api_change_radar
   ```

2. **Configure environment:**
   Copy the example environment file. The default credentials in `docker-compose.yml` match `.env.example`.
   ```bash
   cp .env.example .env
   ```

3. **Start the stack:**
   This will build the application image, start PostgreSQL, run database migrations, and boot the FastAPI application.
   ```bash
   docker compose up -d app
   ```

4. **Verify the service:**
   The API will be available at `http://localhost:8000`.
   - Health check: `http://localhost:8000/healthz`
   - Interactive Swagger docs: `http://localhost:8000/docs`

5. **Run the demo flow:**
   To test the full system end-to-end, you can run the provided smoke script:
   ```bash
   ./scripts/smoke.sh
   ```

6. **Tear down:**
   ```bash
   docker compose down
   ```

---

## 2. Self-Hosted Server Deployment (Docker)

To run API Change Radar on a personal server (e.g., a VPS on DigitalOcean, Linode, or AWS EC2), you can use the same Docker Compose setup.

### Prerequisites
- A Linux server with Docker and Docker Compose installed.
- (Optional but recommended) A reverse proxy like NGINX or Traefik configured for SSL/TLS termination.

### Steps

1. **Transfer the code to your server** or clone the repository directly.
2. **Create a production `.env` file:**
   - Change `ENVIRONMENT` to `production`.
   - Change `DEBUG` to `false`.
   - Update `DATABASE_URL` if you use an external managed database instead of the sidecar Postgres container.
   - Set strong passwords for Postgres if using the sidecar container (update `POSTGRES_PASSWORD` in `docker-compose.yml` and `DATABASE_URL` in `.env`).

3. **Start the containers as a background daemon:**
   ```bash
   docker compose up -d db
   # Wait a few seconds for the database to be ready
   docker compose up -d app
   ```

4. **Expose securely:**
   By default, the app binds to port `8000`. It is highly recommended to bind it only to `127.0.0.1` locally and route external traffic through a reverse proxy (like NGINX) with an SSL certificate from Let's Encrypt.
   
   Example `docker-compose.yml` adjustment:
   ```yaml
   ports:
     - "127.0.0.1:8000:8000"
   ```

---

## Environment Variable Reference

API Change Radar is configured completely via environment variables (12-factor app style).

### Core Configuration

| Variable | Default (Example) | Description |
|---|---|---|
| `APP_NAME` | `Rift` | The name of the application (used in logs/tracing) |
| `ENVIRONMENT` | `development` | Deployment environment (`development` or `production`) |
| `DEBUG` | `false` | Enables verbose error traces in API responses if true |
| `DOCS_ENABLED` | `true` | If true, exposes `/docs` (Swagger UI). Suggest `false` for prod |
| `API_PREFIX` | `/api/v1` | URL prefix for the REST API |
| `DATABASE_URL` | `postgresql+psycopg://...` | Connection string for Postgres |
| `DATABASE_ECHO` | `false` | If true, SQLAlchemy prints all SQL queries (keep false in prod) |

### Observability

| Variable | Default | Description |
|---|---|---|
| `LOG_LEVEL` | `INFO` | Base logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `TRACING_EXPORTER` | `none` | Where to send OpenTelemetry traces (`none`, `otlp`, `console`) |
| `OTLP_ENDPOINT` | *(empty)* | Endpoint for OTLP collector (e.g., `http://localhost:4318/v1/traces`) |
| `REQUEST_ID_HEADER` | `X-Request-ID` | Header name to extract or inject correlation ID |

### AI Features (Optional)

The AI changelog interpretation feature is specifically disabled by default to maintain deterministic execution as the main system value.

| Variable | Default | Description |
|---|---|---|
| `ENABLE_LLM_CHANGELOG` | `false` | Set to `true` to enable AI changelog evaluation (requires provider keys) |
| `LLM_LOW_CONFIDENCE_THRESHOLD` | `0.6` | Threshold under which the AI result is flagged as low confidence |

---

## 3. Demo / Presentation Flow

If you are demoing the application (e.g., for a portfolio or recruiter review), follow this simple flow:

1. **Pre-flight:** Start the app with `docker compose up -d app` and verify the `/docs` UI is accessible.
2. **Submit Specs:** Use Postman, `curl`, or the Swagger UI (`/docs`) to POST to `/api/v1/runs`. Provide the `examples/v1.yaml` and `examples/v2.yaml` files, along with an optional dummy changelog.
3. **Capture ID:** Note the `run_id` returned by the POST request.
4. **Trigger Processing:** *(Note: Until background workers are integrated natively, orchestrate the run via the provided CLI script)*.
   ```bash
   docker compose exec app python scripts/process_run.py <run_id>
   ```
5. **View Report:** Open browser or `curl` the endpoint:
   - Minimal HTML demo report: `http://localhost:8000/api/v1/demo/runs/<run_id>`
   - JSON structured data: `http://localhost:8000/api/v1/reports/<run_id>`
   - Markdown export: `http://localhost:8000/api/v1/reports/<run_id>?format=markdown`
