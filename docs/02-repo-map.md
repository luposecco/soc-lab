# Repository Map

This document is a directory-by-directory map of the repository.

It answers questions like:

- where is the real application code?
- which folders are runtime state versus source code?
- where do rules, pipelines, and sample data live?
- what should a new developer read first?

## Top-Level Layout

```text
api/            FastAPI application
config/         Service configuration files
core/           Main Python service layer
data/           Rules, pipelines, enrichments, sample ingest files, PCAP input
docker/         Container entrypoint scripts
docs/           Main documentation set
runtime/        Runtime logs and generated status files
enrich_sdk/    Public enrichment SDK package surface
ui/             Dash web UI
.soc-lab/       Runtime PID files and local web process logs
compose.yml     Docker Compose stack definition
requirements.txt Python dependencies
start.sh        Main startup script
stop.sh         Main stop script
restart.sh      Restart helper
reset.sh        Destructive reset helper
```

## Expanded Tree With File Roles

This is a more explicit tree for the parts of the repo that matter most during development.

```text
api/
├── main.py                     # creates FastAPI app, CORS, mounts routers
├── models.py                   # request and response models shared by routes
├── utils.py                    # API error helper(s)
└── routes/
    ├── alerts.py               # alert search and aggregations
    ├── capture.py              # replay, live capture, upload, pipeline endpoints
    ├── enrichment.py           # enrichment cluster/run/history/rollback endpoints
    ├── indices.py              # alias and index inventory + alias create/delete
    ├── network.py              # Suricata flow queries and summaries
    ├── overview.py             # dashboard summary endpoint
    ├── rules.py                # rules inventory, validation, compile, file editing
    └── stack.py                # stack control and service log/status endpoints

core/
├── confirm.py                  # interactive safety prompt helper
├── settings.py                 # repo-root and URL/port helper functions
├── capture/
│   ├── live.py                 # live capture chunking and replay workflow
│   └── replay.py               # one-shot PCAP replay workflow
├── elastic/
│   ├── aliases.py              # alias creation, deletion, system aliases, data views
│   ├── client.py               # lab Elasticsearch client factory
│   ├── kibana.py               # Kibana REST wrapper
│   └── loader.py               # Security Onion template/pipeline loader
├── enrich/
│   ├── audit.py                # enrichment audit index logic
│   ├── clusters.py             # cluster config parsing and ES client routing
│   ├── context.py              # main script-facing SDK implementation
│   ├── rollback.py             # rollback engine for field-level mutations
│   ├── runner.py               # config-driven script execution orchestration
│   ├── scripts.py              # dynamic script import and metadata validation
│   └── utils.py                # nested field/query helpers used by the SDK
├── ingest/
│   ├── bulk.py                 # bulk ingest request helpers
│   ├── llm.py                  # LLM/Ollama workflow wrapper for pipeline generation
│   ├── pipeline.py             # ingest pipeline lookup and upload
│   ├── pipeline_gen.py         # generated pipeline construction logic
│   ├── preprocess.py           # file preprocessing and format detection
│   └── upload.py               # high-level log upload workflow
├── rules/
│   └── compile.py              # compile checks, watcher, rule status files
└── stack/
    ├── docker.py               # Docker service inventory helpers
    ├── health.py               # stack/service health aggregation
    └── runtime.py              # start/stop/restart/logs/stats control layer

ui/
├── app.py                      # Dash app shell and page container
├── helpers.py                  # shared HTTP helpers and shared UI components
├── assets/
│   └── style.css               # global CSS styling
└── pages/
    ├── alerts.py               # alerts page
    ├── aliases.py              # richer alias management page
    ├── capture_live.py         # live capture page
    ├── capture_pcap.py         # PCAP replay page
    ├── enrichment.py           # enrichment page
    ├── ingest.py               # generic log upload page
    ├── network.py              # network flows page
    ├── overview.py             # dashboard page
    ├── rules.py                # rule editor/inventory page
    ├── settings.py             # simpler admin/settings alias page
    └── stack.py                # stack control page
```

## `api/`

`api/` contains the FastAPI backend.

### What lives here

- app startup and router registration
- request models
- route handlers
- small API error helpers

### Important files

- `api/main.py`
  - creates the FastAPI app
  - mounts routers
  - exposes `/api/health`
- `api/models.py`
  - request and response models shared across routes
- `api/utils.py`
  - small shared API helpers such as HTTP error wrapping
- `api/routes/*.py`
  - one router file per functional area

### Important design note

The route files are not supposed to be the main business logic layer.

The preferred direction is:

```text
route handler
   -> core/* service module
```

Some route files already follow that model cleanly. Some still contain more orchestration logic than ideal.

## `core/`

`core/` is the most important code directory in the repo.

This is the service layer used by FastAPI and indirectly by the UI.

### Subpackages

#### `core/stack/`

Docker and runtime lifecycle behavior.

- `runtime.py` - start/stop/restart services, logs, stats, teardown
- `docker.py` - container/service listing helpers
- `health.py` - health summaries and service card shaping

#### `core/elastic/`

Elasticsearch and Kibana helper logic.

- `client.py` - base Elasticsearch client creation
- `kibana.py` - Kibana REST helpers
- `loader.py` - Security Onion template and pipeline loading
- `aliases.py` - alias management, system aliases, managed templates, Kibana data views

#### `core/capture/`

Packet replay and live capture logic.

- `replay.py` - replay a PCAP through Suricata
- `live.py` - rotate live capture chunks and replay them continuously

#### `core/ingest/`

Generic log ingest and pipeline generation.

- `upload.py` - high-level upload orchestration
- `preprocess.py` - decompress / normalize inputs / detect format
- `bulk.py` - NDJSON bulk upload helpers
- `pipeline.py` - pipeline discovery and upload
- `pipeline_gen.py` - pipeline generation logic
- `llm.py` - LLM/Ollama workflow wrapper

#### `core/rules/`

Rule compilation and watcher behavior.

- `compile.py` - compile checks, rule counts, status writing, watcher lifecycle

#### `core/enrich/`

Enrichment SDK internals, runner, cluster routing, audit, rollback.

- `context.py` - script-facing SDK class
- `clusters.py` - cluster config loader and client routing
- `scripts.py` - dynamic script loader and metadata parsing
- `runner.py` - orchestration for enrichment execution
- `audit.py` - audit index writing and run history
- `rollback.py` - safe field-level rollback logic
- `utils.py` - small field/query helpers

#### Cross-cutting files

- `settings.py` - repo root, URLs, and ports
- `confirm.py` - safety prompt helper

## `ui/`

`ui/` contains the Dash application.

### What lives here

- the shell app layout
- page registration
- API client helpers
- page callbacks and rendering helpers
- CSS

### Important files

- `ui/app.py`
  - main Dash app entry point
  - sidebar layout
  - page container
- `ui/helpers.py`
  - shared HTTP helpers for calling FastAPI
  - shared UI builders like cards and banners
- `ui/pages/*.py`
  - one page per major feature area
- `ui/assets/style.css`
  - global styling

## `config/`

`config/` holds configuration files that are mounted into containers or used by runtime services.

### Subdirectories

#### `config/suricata/`

- `suricata.yaml` - main Suricata config
- `threshold.config` - alert suppression tuning

#### `config/filebeat/`

- `filebeat.yml` - Filebeat input and output config

#### `config/elastalert2/`

- `elastalert2.yml` - ElastAlert2 runtime config
- `rules/` - static native ElastAlert2 rules

## `docker/`

`docker/` contains container entrypoint scripts mounted into services.

- `suricata-start.sh`
  - Suricata container entrypoint
  - ensures ET rules exist in the mounted rules volume
- `elastalert-start.sh`
  - ElastAlert2 container entrypoint
  - converts Sigma rules and starts ElastAlert2

These are runtime bootstrap scripts, not the main application control plane.

## `data/`

`data/` is a mixed directory. It contains user-editable assets, samples, and some generated artifacts.

### `data/rules/`

User-facing rule content.

- `data/rules/suricata/` - custom Suricata rules
- `data/rules/sigma/` - Sigma rules

The UI and watcher treat these as editable rule sources.

### `data/pipelines/`

Ingest pipeline assets.

- `data/pipelines/elasticsearch/` - built-in or bundled pipeline definitions
- `data/pipelines/generated/` - generated pipelines
- `data/pipelines/custom/` - user-uploaded custom pipelines if present

### `data/ingest/`

Sample log files used for manual testing, demos, or parser work.

These are not core source code. They are test and example artifacts.

### `data/pcap/`

PCAP input and live capture artifacts.

- user-dropped replay files
- live capture chunk files under `data/pcap/live/`

### `data/enrichments/`

Enrichment configuration and user scripts.

- `config/clusters.yml` - attached/managed cluster definitions
- `config/enrichments.yml` - enrichment routing configuration
- `scripts/` - enrichment scripts written against `enrich_sdk`

## `enrich_sdk/`

This is the public import surface for the enrichment SDK.

Right now it is intentionally small.

Example intended usage:

```python
from enrich_sdk import EnrichmentContext
```

The implementation lives in `core/enrich/`, but `enrich_sdk/` is the user-facing package name.

## `runtime/`

`runtime/` contains generated runtime artifacts.

Examples include:

- Suricata logs
- rules compile logs
- rules status JSON

This directory is operational state, not primary source code.

## `.soc-lab/`

This is another runtime-state directory.

It stores small local control-plane artifacts such as:

- FastAPI PID file
- Dash PID file
- rules watcher PID file
- local log files for host-run processes

If you are debugging startup or shutdown behavior, this folder matters.

## Which Directories New Contributors Should Read First

If you want to work on backend behavior:

```text
core/
api/
config/
docker/
```

If you want to work on the UI:

```text
ui/
api/
core/
```

If you want to work on enrichment:

```text
enrich_sdk/
core/enrich/
data/enrichments/
api/routes/enrichment.py
ui/pages/enrichment.py
```

If you want to work on ingest and log parsing:

```text
core/ingest/
data/pipelines/
data/ingest/
api/routes/capture.py
ui/pages/ingest.py
```

## What Is Source Code Versus Runtime State

This distinction matters a lot.

### Source code / intended to edit

- `api/`
- `core/`
- `ui/`
- `config/`
- `docker/`
- `enrich_sdk/`
- `docs/`
- `data/enrichments/`
- `data/rules/`

### Mostly runtime or generated state

- `.soc-lab/`
- `runtime/`
- `data/pcap/live/`
- some files under `data/pipelines/generated/`

### Mostly sample/test assets

- `data/ingest/`
- sample rules under `data/rules/*/gui/`

## Practical Rule Of Thumb

When you see a file in the repo, ask:

1. is this application logic?
2. is this service configuration?
3. is this user content?
4. is this generated runtime state?

That classification usually tells you whether it should be edited by hand, regenerated by the app, or treated as an operational artifact.
