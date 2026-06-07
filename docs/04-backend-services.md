# Backend Services

This document explains the `core/` service layer.

If FastAPI is the backend interface, `core/` is the behavior implementation.

## Why `core/` Matters

The route handlers should stay reasonably thin.

The real decisions about how the lab behaves belong in reusable Python modules.

That is what `core/` is for.

```text
FastAPI route
   -> core module
   -> Docker / Elasticsearch / Kibana / filesystem
```

This is not just an organizational preference.

It directly affects maintainability:

- route handlers stay smaller
- backend logic becomes reusable
- UI does not need to know implementation details
- enrichment, API, and future CLI paths can share behavior

## `core/settings.py`

This is the simplest but most reused module.

It provides:

- repo root lookup
- Elasticsearch URL
- Kibana URL
- FastAPI host/port
- Dash host/port

Why it matters:

- keeps path and URL defaults centralized
- lets the app use environment overrides without scattering them everywhere

Even though this module is small, it is strategically important. Configuration helpers like this reduce an entire class of “hardcoded localhost/path” mistakes across the repo.

## `core/stack/`

This package is about service lifecycle and health.

### `core/stack/runtime.py`

Think of this as the imperative control module.

It is where the repo actually performs actions like:

- `docker compose up`
- `docker compose down`
- start/stop/restart one service
- collect service logs
- collect runtime stats

This module is about mutation and operational control.

When reading this file, think in terms of capability groups:

- process/service lifecycle control
- runtime directory preparation
- logs and stats access
- uninstall/cleanup behavior

This is not a pure “Docker wrapper.” It is the operational control layer for the stack.

### `core/stack/docker.py`

This module is smaller and more read-only.

It primarily asks Docker Compose what services exist and what state they are in.

Use this when you need inventory, not when you need to change the system.

That distinction matters because inventory and mutation logic usually age differently. Keeping them separated reduces the chance that read paths accidentally carry side effects.

### `core/stack/health.py`

This module aggregates health information into shapes useful for the UI.

It combines things like:

- Docker service states
- Elasticsearch or Kibana availability
- counts or log-derived health signals

This is a summarization layer.

It exists because the UI does not want to consume raw Docker or raw ES responses everywhere. It wants operator-friendly summaries.

## `core/elastic/`

This package is about Elasticsearch and Kibana behavior that belongs to the lab itself rather than to one specific feature page.

### `core/elastic/client.py`

Tiny but important.

It is the shared Elasticsearch client factory.

This gives the rest of the codebase one obvious way to get a client for the main lab cluster.

That is a surprisingly big deal. “One obvious way to get the primary ES client” is one of the simplest consistency wins in the codebase.

### `core/elastic/kibana.py`

This is a small wrapper around Kibana REST endpoints.

Its main job is not full Kibana administration. It focuses on the operations SOC Lab actually needs, especially data view lifecycle.

That scope control is good engineering. The repo is not trying to build a complete Kibana SDK. It is wrapping the tiny subset of Kibana behavior the app actually relies on.

### `core/elastic/loader.py`

This is one of the more specialized modules.

It loads Security Onion templates and ingest pipelines into Elasticsearch.

That matters because the lab depends on those assets for Suricata event normalization.

Conceptual flow:

```text
fetch upstream SO assets
   -> patch for local compatibility
   -> push templates and pipelines into Elasticsearch
```

Important design idea:

this module is a compatibility layer between upstream Security Onion ingest assets and this repo's smaller, local-lab runtime model.

That is why it contains patching behavior rather than acting as a blind downloader.

### `core/elastic/aliases.py`

This is a central module for enterprise-style index naming.

Main responsibilities:

- list aliases and indices
- validate alias creation input
- create aliases against concrete indices
- create managed templates for wildcard-backed aliases
- protect reserved system aliases
- ensure matching Kibana data views exist
- delete alias metadata and related templates safely

This module is important because aliasing is one of the repo's core ideas: recreate enterprise naming without duplicating data.

This file is worth studying carefully because it combines:

- user input validation
- Elasticsearch alias semantics
- wildcard template management
- Kibana data-view sync
- system alias protection

It is both a feature module and a safety module.

## `core/capture/`

This package is about packet workflows.

### `core/capture/replay.py`

This module replays a PCAP through Suricata.

Its workflow is not just “run Suricata on a file”. It also manages surrounding state.

Typical responsibilities:

- resolve the requested PCAP path safely
- optionally wipe prior replay state
- clear relevant alert and index state
- run Suricata replay
- optionally shift timestamps to now
- re-ensure aliases
- wait for documents to appear

This is a stateful workflow module.

That is important because replay is not just a one-command shell-out. It is a coordinated state transition involving:

- possible cleanup
- packet analysis
- log shipping
- alias readiness
- delayed document visibility

### `core/capture/live.py`

This module manages continuous live capture.

The model is:

```text
dumpcap writes rotating packet files
   -> completed chunks are queued
   -> chunks are replayed through Suricata
   -> events land in Elasticsearch
```

This is more operationally complex than replay because it manages a queue, chunk lifecycle, and session state over time.

If replay is “one transaction,” live capture is more like “a continuously advancing mini pipeline.”

## `core/ingest/`

This package is about non-PCAP log ingest.

### `core/ingest/upload.py`

This is the main orchestration layer.

It decides how an upload should be handled.

Examples:

- direct JSON ingest
- CEF conversion then ingest
- explicit pipeline use
- LLM-generated pipeline creation
- batch folder processing

This module is high-level policy.

That means if you want to understand why the system chose one ingest mode instead of another, this is the first file to inspect.

### `core/ingest/preprocess.py`

This module normalizes the input before ingest.

Typical work:

- decompressing archives
- converting `.evtx`
- detecting whether the content looks like JSON, CEF, or other text

This file exists so the later upload logic can assume a cleaner, more normalized input model.

### `core/ingest/bulk.py`

This is the low-level NDJSON bulk uploader.

Its job is to speak Elasticsearch bulk format cleanly.

This separation is useful because “how to build NDJSON bulk payloads” is a lower-level concern than “what ingest strategy should we choose for this file?”

### `core/ingest/pipeline.py`

This resolves ingest pipelines.

Typical responsibilities:

- check if a named pipeline already exists in Elasticsearch
- search local pipeline directories
- upload a local pipeline into Elasticsearch
- optionally wrap a pipeline with timestamp override behavior

This file is one of the places where the repo bridges local repo assets and live Elasticsearch state.

### `core/ingest/pipeline_gen.py`

This module contains LLM-assisted pipeline generation logic.

It is not about transport or UI. It is about creating a likely-useful ingest pipeline definition from sample log lines.

This is an important boundary: generation logic stays separate from upload orchestration.

### `core/ingest/llm.py`

This is the operational wrapper around the generation process.

It handles things like:

- choosing an Ollama model
- optionally freeing RAM by stopping Docker temporarily
- writing generated pipeline files into the repo

This file is not “the model prompt” alone. It is operational support code around constrained local environments.

## `core/rules/`

This package is focused on rule compilation and watcher behavior.

### `core/rules/compile.py`

Main responsibilities:

- test Suricata rule validity in-container
- convert Sigma rules and record conversion success/failure
- count rule totals
- write status JSON and logs
- manage the file watcher lifecycle

Important concept:

the watcher is not using filesystem events. It is a polling loop that hashes file metadata on a schedule.

That design is simple and portable.

It also means debugging the watcher is often easier than debugging OS-specific file-notification systems.

## `core/enrich/`

This package powers the enrichment subsystem.

### `core/enrich/context.py`

This is the main script-facing SDK class.

It exposes simpler operations on top of Elasticsearch.

Current examples include:

- `get`
- `search`
- `scan`
- `exists`
- `index_doc`
- `update_doc`
- `remove_fields`
- `delete_doc`
- `update_by_query`
- `remove_by_query`
- `create_index`
- `delete_index`
- `raw`

This module is the most important file for enrichment authors.

It is also one of the most important files for maintainers because it defines the semantics of the public SDK.

### `core/enrich/clusters.py`

Loads cluster definitions and returns the correct Elasticsearch client.

Important behavior:

- always includes implicit `lab`
- supports auth modes such as none, basic, and API key
- caches clients by cluster name

This file is the routing layer between enrichment intent and actual target environments.

### `core/enrich/scripts.py`

Handles dynamic script loading.

It validates:

- script file exists
- `ENRICHMENT_META` is valid
- script defines `run(ctx)` or `run(ctx, params)`

This file makes the script contract explicit and enforceable rather than informal.

### `core/enrich/runner.py`

This is the orchestration layer.

It reads enrichment configuration, loads the script, chooses target clusters, constructs `EnrichmentContext`, and executes the script.

This is the orchestration center of enrichment execution.

### `core/enrich/audit.py`

Writes and reads enrichment audit records.

These records make it possible to:

- inspect runs
- detect later conflicting changes
- support rollback workflows

This file is where enrichment stops being “just a convenient script wrapper” and becomes a controlled mutation system.

### `core/enrich/rollback.py`

Applies field-level rollback in reverse order using the audit history.

Important safety property:

it blocks by default if a later enrichment run changed the same fields.

That is the central safety rule of rollback.

## `core/confirm.py`

This is a tiny but important safety module.

It centralizes yes/no confirmation behavior and supports non-interactive bypass through environment configuration.

Use it when a workflow is destructive or surprising and should not happen silently.

## Dependency Direction

The intended direction is:

```text
api/ routes
   -> core/* modules

ui/ pages
   -> api/ over HTTP

core/*
   -> external systems
      - Docker
      - Elasticsearch
      - Kibana
      - local filesystem
      - subprocesses
```

Avoid the reverse direction.

Examples of things to avoid:

- `core/` importing UI logic
- Dash mutating Docker or Elasticsearch directly
- route files becoming giant monoliths that bypass `core/`

## Contributor Heuristic

If you are adding a new feature, ask:

1. is this a backend behavior?
2. is this just an API wrapper around an existing behavior?
3. is this a UI rendering concern?

If the answer is “backend behavior”, it probably belongs in `core/` first, then gets exposed through `api/`, then consumed from `ui/`.

That is the dominant engineering direction of the repo.
