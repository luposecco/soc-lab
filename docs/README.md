# Documentation Guide

This directory is the main documentation set for SOC Lab.

The goal is not just to describe what files exist. The goal is to explain:

- what the lab is trying to do
- how data moves through it
- where logic lives in the repo
- what each major module is responsible for
- how to debug it when something breaks
- how to safely extend it as a developer

The docs are written for two audiences at the same time:

1. a human developer who is new to the repo
2. an LLM or automation agent that needs a stable mental model of the system

## Suggested Reading Order

If you are new, read in this order:

1. `01-system-overview.md`
2. `02-repo-map.md`
3. `03-runtime-stack.md`
4. `04-backend-services.md`
5. `05-api-reference.md`
6. `06-ui-guide.md`
7. `07-data-flows.md`
8. `08-enrichment.md`
9. `09-operations.md`
10. `10-enrichment-sdk-reference.md`
11. `11-enrichment-internals.md`

## File Guide

### `01-system-overview.md`

Use this when you need the big picture first.

It explains:

- the lab's purpose
- the major runtime components
- how Docker, FastAPI, Dash, Elasticsearch, Kibana, Suricata, Filebeat, and ElastAlert2 relate
- the main architectural boundaries

### `02-repo-map.md`

Use this when you want to know where code lives.

It explains:

- the top-level directory layout
- what each subdirectory is for
- which folders are source code, runtime state, sample data, or generated artifacts

### `03-runtime-stack.md`

Use this when you need to understand startup, shutdown, Docker, and local state.

It explains:

- `compose.yml`
- `start.sh`, `stop.sh`, `restart.sh`, `reset.sh`
- service configs under `config/`
- container entrypoint scripts under `docker/`
- runtime state under `.soc-lab/` and `runtime/`

### `04-backend-services.md`

Use this when you want to work inside `core/`.

It explains:

- service boundaries in `core/`
- stack control modules
- Elasticsearch and Kibana helper modules
- capture modules
- ingest modules
- rules modules
- enrichment modules

### `05-api-reference.md`

Use this when you are changing the backend API or a UI page that depends on it.

It explains:

- the FastAPI app layout
- router responsibilities
- request models
- where each endpoint delegates work

### `06-ui-guide.md`

Use this when you are changing the Dash app.

It explains:

- the shell app layout
- helper patterns
- page structure
- callback and polling patterns
- how the UI talks to the API

### `07-data-flows.md`

Use this when you need a low-level operational walkthrough.

It explains:

- PCAP replay
- live capture
- generic log upload
- alias creation
- rules compilation and watching
- enrichment execution

### `08-enrichment.md`

Use this when you are writing or extending enrichment scripts and the enrichment SDK.

It explains:

- cluster routing
- script metadata
- `EnrichmentContext`
- audit records
- rollback rules
- current limitations

### `09-operations.md`

Use this when you are running or debugging the system.

It explains:

- common operator tasks
- failure modes
- verification commands
- where to look for logs and runtime state

### `10-enrichment-sdk-reference.md`

Use this when you are actively writing enrichment scripts and need a method-level reference.

It explains:

- metadata fields
- valid `run(...)` signatures
- what each context method does
- mutation semantics
- dry-run behavior
- example script patterns

### `11-enrichment-internals.md`

Use this when you are changing the enrichment implementation itself.

It explains:

- how each `core/enrich/*.py` file works
- internal execution flow
- internal mutation scripts
- audit and rollback internals
- where to modify the subsystem safely

## Relationship To Existing Root Docs

There are still a few important root-level docs:

- `README.md` is the short landing page
- `EXPLANATION.md` is a long, older deep dive that still contains valuable conceptual material
- `WEB_MIGRATION_DESIGN.md` tracks the web-era architecture direction
- `ENRICHMENT_DESIGN.md` tracks enrichment design decisions

Those files are still useful. This `docs/` tree is meant to be the main maintained documentation set for the current repo layout.

## Maintenance Rules For Future Docs

When adding or updating docs:

- prefer many focused files over one giant file
- keep code-oriented docs aligned with actual file boundaries
- include diagrams when a workflow spans multiple components
- explain low-level behavior, not just feature lists
- document failure modes and debugging paths, not just happy paths
- avoid assuming the reader already understands Elasticsearch, Dash, FastAPI, Docker, or security tooling internals
