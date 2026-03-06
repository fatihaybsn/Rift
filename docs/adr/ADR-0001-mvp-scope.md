# ADR-0001: Freeze MVP Scope for API Change Radar

## Status

Accepted

## Context

API Change Radar is intended to be a production-minded backend portfolio project.

The main risk is not lack of ideas.  
The main risk is uncontrolled scope growth.

Without an explicit MVP boundary, the project could easily expand into:
- remote fetching
- CI integrations
- team notifications
- full UI work
- multi-tenant access control
- codebase impact analysis
- AI-heavy, non-deterministic behavior

That would make the first version slower, weaker, and harder to finish at a high standard.

## Decision

The MVP will focus on a narrow backend workflow:

1. accept two OpenAPI specs
2. optionally accept changelog text
3. parse and validate the specs
4. normalize both specs into a canonical internal model
5. compute a deterministic diff
6. classify findings by severity using explicit rules
7. persist runs, artifacts, and reports
8. expose report retrieval endpoints
9. include basic health/readiness endpoints
10. include basic observability hooks

## Included in MVP

- local submission of two spec files
- JSON/YAML parsing
- OpenAPI validation
- deterministic normalization
- deterministic diff engine
- severity classification
- persisted report model
- read/report endpoints
- basic markdown/json export direction
- structured logs / metrics / traces baseline

## Excluded from MVP

The first version will not include:

- remote URL fetching
- GitHub/webhook integrations
- Slack/Jira integrations
- full frontend application
- multi-tenant auth / RBAC
- codebase impact analysis
- release gate policy engine
- autonomous AI decision-making
- LLM-based override of deterministic findings

## Consequences

### Positive
- keeps the project finishable
- protects engineering quality
- makes testing easier
- preserves a clean product boundary
- keeps the deterministic core as the main value

### Negative
- first version will not feel like a full product platform
- integrations and workflow automation will come later
- some demo scenarios will remain manual in MVP

## Notes

Any future AI-assisted changelog interpretation must remain secondary and non-authoritative.

The deterministic diff engine is the source of truth.