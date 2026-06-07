# API Reference

This document explains the FastAPI application structure and the purpose of each router.

It is not meant to be a generated OpenAPI dump. It is meant to explain how the backend is organized and where each route sends work.

## App Entry Point

File:

- `api/main.py`

Main responsibilities:

- create the FastAPI app
- configure CORS
- register routers
- expose the health endpoint

Conceptual structure:

```text
FastAPI app
   ├─ /api/health
   ├─ /api/stack/*
   ├─ /api/overview/*
   ├─ /api/indices and /api/aliases
   ├─ /api/rules/*
   ├─ /api/capture/*
   ├─ /api/alerts/*
   ├─ /api/network/*
   └─ /api/enrich/*
```

The important design point is that `api/main.py` is intentionally small.

That is good. It means the application boot file is mostly about composition, not behavior.

## Request Models

File:

- `api/models.py`

This file contains Pydantic models used by the API.

Why this matters:

- request validation lives here
- field names become part of the stable contract between UI and API

In a repo like this, the request models are part of the application architecture, not just an implementation detail. They define the shape of the conversation between UI and backend.

Examples:

- `AliasCreateRequest`
- `CaptureReplayRequest`
- `CaptureUploadRequest`
- `EnrichRunRequest`
- `RuleFileWriteRequest`
- `RuleValidateRequest`
- `LiveCaptureStartRequest`
- `PipelineUploadRequest`
- `HealthResponse`

## Error Handling Pattern

File:

- `api/utils.py`

The helper `bad(...)` converts Python exceptions into HTTP exceptions.

Why this matters:

- many routes follow a simple `try/except` wrapper style
- the UI expects JSON error output patterns that come from this layer

## Router Overview

### `/api/stack`

File:

- `api/routes/stack.py`

Purpose:

- stack lifecycle control
- service status retrieval
- service log retrieval

Typical actions:

- start or stop all services
- start, stop, or restart one service
- list current services and health summaries
- fetch service logs for display in the UI

Delegation pattern:

- primarily uses `core.stack.runtime`, `core.stack.docker`, and `core.stack.health`

This is one of the better examples of the intended route-to-service pattern.

### `/api/overview`

File:

- `api/routes/overview.py`

Purpose:

- aggregate high-level summary data for the dashboard page

This route is intentionally summary-oriented rather than feature-rich.

Its job is to make the dashboard cheap for the UI to consume, not to expose every underlying detail.

### `/api/indices` and `/api/aliases`

File:

- `api/routes/indices.py`

Purpose:

- inventory indices and aliases
- create aliases
- delete aliases
- expose managed-template and Kibana-view state

Delegation pattern:

- mostly uses `core.elastic.aliases`
- uses Kibana helper logic to report UI sync state

Important note:

this router is the backend surface for one of the repo's most important abstraction layers: enterprise-style alias recreation.

This router is also a good place to study if you want to understand how the repo maps local-lab data into enterprise-like naming conventions without copying documents.

### `/api/alerts`

File:

- `api/routes/alerts.py`

Purpose:

- alert listing
- alert timeline aggregation
- alert stats aggregation

Important note:

this router queries Elasticsearch more directly than some others. It is thinner and closer to the raw query layer.

That is acceptable here because alerts are already a fairly query-centric domain and do not require as much orchestration as capture or rules workflows.

### `/api/network`

File:

- `api/routes/network.py`

Purpose:

- query Suricata flow events
- return list and aggregate data for the network page

Important note:

this route is also relatively direct and Elasticsearch-centric.

The domain here is “search flow docs and summarize them,” so the directness is appropriate.

### `/api/capture`

File:

- `api/routes/capture.py`

Purpose:

- PCAP inventory and metadata
- replay start and replay status
- live capture management
- generic log upload
- pipeline listing and upload

This is one of the densest routers.

It mixes:

- direct file and subprocess logic
- delegation into `core.capture.*`
- delegation into `core.ingest.*`

That makes it very powerful, but also one of the places where future refactoring may continue.

If you are trying to understand end-to-end replay or live-capture behavior, this route file is worth reading together with `core/capture/*` and `docs/07-data-flows.md`.

### `/api/rules`

File:

- `api/routes/rules.py`

Purpose:

- rule status
- compile and watcher control
- file listing, reading, writing, deleting
- validation
- Suricata rule inventory and counts
- rule logs

This is another relatively self-contained router with substantial local logic.

Why:

- rule editing and validation involve many small format- and file-specific behaviors

This router is a good example of how a domain can remain partially route-local even in a service-oriented repo, simply because the amount of edge-case parsing and file handling is high.

### `/api/enrich`

File:

- `api/routes/enrichment.py`

Purpose:

- list enrichment target clusters
- test cluster connectivity
- list configured enrichments
- run enrichments
- list audit runs
- request rollback

Delegation pattern:

- uses `core.enrich.clusters`
- uses `core.enrich.runner`
- uses `core.enrich.audit`
- uses `core.enrich.rollback`

This is currently one of the cleanest service-backed routers.

That makes it a useful reference pattern for how future backend features might ideally be structured.

## How Routes Map To `core/`

Diagram:

```text
stack router      -> core.stack.*
overview router   -> core.stack.* + core.elastic.aliases
indices router    -> core.elastic.aliases + core.elastic.kibana
alerts router     -> core.elastic.client + direct ES queries
network router    -> core.elastic.client + direct ES queries
capture router    -> core.capture.* + core.ingest.* + local orchestration
rules router      -> core.rules.compile + local parsing/orchestration
enrich router     -> core.enrich.*
```

This mapping matters because it tells you where to look next when a bug report lands.

Examples:

- bug in alias mutation semantics: start in `api/routes/indices.py`, then move quickly to `core/elastic/aliases.py`
- bug in enrichment run behavior: start in `api/routes/enrichment.py`, then move to `core/enrich/runner.py`
- bug in replay state reset: start in `api/routes/capture.py`, then move to `core/capture/replay.py`

## API Design Patterns In This Repo

### Pattern 1: thin route -> service call

Best examples:

- enrichment routes
- many stack routes
- indices routes

This is the preferred long-term style.

### Pattern 2: route contains orchestration

Examples:

- capture routes
- rules routes

This is still workable, but harder to reuse and harder to test in isolation.

### Pattern 3: route performs direct Elasticsearch query

Examples:

- alerts routes
- network routes

This is acceptable when the route is mostly a search facade and the logic is simple.

The key is not “never query Elasticsearch directly in a route.”

The key is “keep the route honest about what it is doing.”

If the route is mainly formatting and parameterizing a search, directness is fine.

If the route is orchestrating stateful side effects, pushing that behavior into `core/` is usually better.

## Contract Between UI And API

The Dash UI assumes a few stable patterns.

### JSON on success

Routes return JSON payloads shaped for the pages that consume them.

### JSON with `error` on failure

The UI helper layer often treats `{"error": ...}` as the generic failure contract.

### Pollable status endpoints

Long-running actions often follow this pattern:

```text
POST action
   -> backend starts work
GET status endpoint repeatedly
   -> UI renders progress/log output
```

This is used in capture and live operations.

## When Adding A New Endpoint

Preferred process:

1. add or refine behavior in `core/`
2. expose it through a route
3. use a Pydantic model if the body is structured
4. keep route logic small unless there is a strong reason not to
5. make failure behavior explicit and readable in the UI

Also ask one more question:

6. is this endpoint returning raw backend data, or returning a UI-shaped summary?

That distinction often explains why a route exists at all.

## What To Read Alongside This File

- `docs/04-backend-services.md` for service-layer details
- `docs/06-ui-guide.md` for how the UI consumes these routes
- `docs/07-data-flows.md` for end-to-end workflow walkthroughs
