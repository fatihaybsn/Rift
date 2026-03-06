# API Change Radar - Claude Rules

## Product boundary
This repository is for a narrow MVP backend service.

The MVP includes:
- two OpenAPI spec inputs
- optional changelog text
- parsing and validation
- normalization
- deterministic diffing
- severity classification
- persisted reports
- read APIs
- basic observability

The MVP does NOT include:
- remote fetching
- webhook integrations
- Slack/Jira integrations
- full frontend
- multi-tenant RBAC
- codebase impact analysis
- LLM override of deterministic findings

## Engineering rules
- Prefer explicit code over clever abstractions.
- Keep modules small and readable.
- Do not introduce unnecessary frameworks.
- Add or update tests for meaningful behavior.
- Preserve deterministic output ordering.
- Favor boring, reviewable changes.

## AI-specific rule
If an LLM layer is added later, it may assist with changelog summary or migration hints only.
It must never override deterministic diff findings or severity rules.

## Workflow
Before implementing:
1. inspect the current repository state
2. propose a short plan for the requested change
3. implement only the requested scope
4. run relevant checks
5. summarize changed files and known limitations

## Output expectations
At the end of each task, provide:
- summary
- changed files
- commands run
- test results
- known limitations
- suggested commit message