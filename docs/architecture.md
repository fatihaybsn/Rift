# Architecture Overview

## Purpose

API Change Radar compares two OpenAPI specs, extracts meaningful changes, evaluates their severity, and stores the result as a report.

The system is intentionally designed around a deterministic core.  
Any future AI-assisted functionality is secondary and must not override the deterministic output.

---

## High-level flow

1. Client submits:
   - old spec
   - new spec
   - optional changelog text

2. Service validates and parses inputs

3. Specs are normalized into a canonical internal model

4. Diff engine computes structured findings

5. Severity engine assigns risk levels

6. Findings and metadata are stored

7. Client retrieves the final report

---

## Main components

### 1. Ingestion API
Responsible for:
- accepting the request
- validating input shape
- creating an analysis run
- storing raw artifacts

### 2. Parser / Validator
Responsible for:
- parsing JSON or YAML
- validating OpenAPI structure
- producing clear validation errors

### 3. Normalizer
Responsible for:
- converting specs into a canonical internal representation
- reducing format differences that should not affect semantic comparison
- preparing data for deterministic diffing

### 4. Diff Engine
Responsible for:
- comparing normalized old/new snapshots
- producing structured findings such as:
  - path added/removed
  - method added/removed
  - request/response field changes
  - status code changes
  - auth changes
  - enum narrowing

### 5. Severity Engine
Responsible for:
- classifying findings using explicit rules
- producing a severity and short explanation for each finding

### 6. Report Store
Responsible for persisting:
- analysis runs
- raw input artifacts
- normalized snapshots
- findings
- optional migration tasks
- audit-style metadata

### 7. Read API
Responsible for:
- exposing run status
- exposing report data
- supporting JSON and later Markdown export

### 8. Observability Layer
Responsible for:
- structured logging
- request/run correlation
- metrics
- tracing

---

## Architectural principles

### Deterministic core first
The main business value must come from deterministic parsing, normalization, diffing, and severity rules.

### Narrow MVP
The first version must stay small and focused.

### Explicit domain model
The system should use clear domain concepts instead of overly generic abstractions.

### Report-oriented design
The output is not just a diff result.  
It is a stored, reviewable report.

### AI is optional
If an AI layer is added later, it may help summarize changelog text or suggest migration tasks, but it must never become the source of truth.

---

## Out of scope for MVP

The following are intentionally excluded from the first version:

- remote spec fetching
- webhooks
- Slack/Jira notifications
- full frontend application
- multi-tenant auth
- codebase impact analysis
- release blocking policies
- auto-remediation or autonomous action-taking

---

## Expected data model (initial direction)

Planned entities:

- `analysis_runs`
- `spec_artifacts`
- `normalized_snapshots`
- `findings`
- `migration_tasks`
- `audit_logs`

This model may evolve, but the first version should preserve traceability from raw input to final report.

---

## Planned deployment direction

Initial deployment goal:
- local development with Docker Compose
- public demo deployment later
- single service architecture for MVP

No microservice split is planned for the first version.