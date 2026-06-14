# SOC Lab

SOC Lab is a local security operations lab built around:

- Elasticsearch
- Kibana
- Suricata
- Filebeat
- ElastAlert2
- FastAPI
- Dash
- a Python enrichment SDK

It is designed for realistic security-data workflows, not just static demos. You can replay PCAPs, capture live traffic, ingest raw logs, test detections, recreate enterprise alias names, and run enrichment logic against one or more Elasticsearch targets.

## Host Dependencies

`./start.sh` installs the Python package requirements from `requirements.txt` into a local `.venv`, but it expects the host tools below to already exist.

| Dependency | Required | Used for | Notes |
| --- | --- | --- | --- |
| Docker | Yes | Running Elasticsearch, Kibana, Suricata, Filebeat, and ElastAlert2 | `start.sh`, `stop.sh`, and `reset.sh` all depend on a working Docker daemon. |
| Docker Compose v2 | Yes | Bringing the stack up with `docker compose` | The repo uses the `docker compose` subcommand, not legacy `docker-compose`. |
| Python 3 | Yes | FastAPI, Dash, repo automation, enrichment, ingest helpers | `start.sh` creates `.venv` with `python3 -m venv`. |
| Python `venv` support | Yes | Creating the local virtual environment | On some Linux distros this is a separate package such as `python3-venv`. |
| `curl` | Yes | Startup health checks for Elasticsearch and Kibana | Used directly in `start.sh` and throughout the ops docs. |
| `lsof` | Yes | Killing stale host processes bound to UI/API ports | Used by `start.sh`, `stop.sh`, and `reset.sh`. |
| `dumpcap` | Optional | Live capture mode | Required for the live capture workflow implemented in `core/capture/live.py` and exposed through the current UI/API flow. Installed with Wireshark or tshark packages. |
| `capinfos` | Optional | Fast PCAP metadata inspection in the capture UI/API | Used for packet count and duration in `/api/capture/pcap/info`. Usually installed with Wireshark. |
| Ollama | Optional | AI-generated ingest pipelines | Required only for LLM-assisted pipeline generation/upload flows. |
| `jq` | Optional | Pretty-printing JSON during manual verification and debugging | Used in docs/examples, not required for the lab to run. |

Python packages installed automatically into `.venv` by `start.sh`:

- `python-evtx`
- `pyyaml`
- `elasticsearch`
- `fastapi`
- `uvicorn`
- `dash`
- `dash-ace`
- `httpx`
- `scapy`

Feature notes:

- Basic lab startup needs only the required dependencies in the table.
- Live capture needs `dumpcap` permissions that allow your current user to run `dumpcap -D` successfully.
- PCAP replay from existing files does not require `dumpcap`, but the richer PCAP info view uses `capinfos` when available.
- AI pipeline generation is optional and only works when Ollama is running locally.

## Quick Run

Start everything:

```bash
./start.sh
```

Open:

- Dash UI: `http://127.0.0.1:8050`
- FastAPI API: `http://127.0.0.1:8000`
- Kibana: `http://localhost:5601`
- Elasticsearch: `http://localhost:9200`

Stop everything:

```bash
./stop.sh
```

Restart everything:

```bash
./restart.sh
```

Destructive reset:

```bash
./reset.sh
```

Current documentation set:

- `docs/README.md` - reading order and documentation map
- `docs/03-runtime-stack.md` - current startup and runtime behavior
- `docs/09-operations.md` - verification and troubleshooting commands

## Enrichment SDK Quick Start

User scripts live under:

```text
data/enrichments/scripts/
```

They import the public SDK surface like this:

```python
from enrich_sdk import EnrichmentContext
```

Minimal example:

```python
from enrich_sdk import EnrichmentContext

ENRICHMENT_META = {
    "type": "play_batch",
    "name": "Risk Scorer",
    "description": "Adds risk fields to matching alerts.",
}

def run(ctx: EnrichmentContext) -> None:
    ctx.update_by_query(
        index="soc-alerts",
        query={
            "bool": {
                "must": [{"term": {"event.dataset": "suricata.alert"}}],
                "must_not": [{"exists": {"field": "risk.score"}}],
            }
        },
        fields={
            "risk.score": 80,
            "risk.reason": "matched enrichment policy",
        },
    )
```

Important SDK semantics:

- `index_doc(...)` is create-only
- `update_doc(...)` mutates an existing document and creates missing fields if needed
- `search(...)` is for smaller result sets returned as a list
- `scan(...)` is for iterating larger result sets
- mutating methods write audit records into the central lab cluster
- field-level rollback supports update/remove style mutations

For the deeper docs, read:

- `docs/08-enrichment.md`
- `docs/10-enrichment-sdk-reference.md`
- `docs/11-enrichment-internals.md`

## What The System Is Trying To Do

At a very high level, SOC Lab takes security-relevant input and moves it through the same kinds of stages you would see in a real security analytics environment.

```text
raw input
  ├─ PCAP replay
  ├─ live network capture
  └─ generic log upload

       |
       v
normalization / ingestion
       |
       v
Elasticsearch indices and aliases
       |
       ├─ Kibana search and dashboards
       ├─ ElastAlert2 detections
       └─ enrichment scripts
```

The repo also gives you a web control plane on top of that runtime stack.

## Architecture In One Diagram

This diagram is intentionally detailed. It shows the host-run web control plane, Docker networking, service boundaries, and the main data paths.

```text
HOST MACHINE
┌───────────────────────────────────────────────────────────────────────────────────────────────┐
│                                                                                               │
│  Browser                                                                                      │
│    │                                                                                          │
│    ├─ HTTP http://127.0.0.1:8050 ───────────────────────────────► Dash UI                     │
│    │                                                              ui/app.py + ui/pages/*      │
│    │                                                                 │                        │
│    │                                                                 ├─ HTTP api_get/api_post │
│    │                                                                 │                        │
│    └─ HTTP http://localhost:5601 ──────────────────────────────────► Kibana port forward      │
│                                                                                               │
│  Host-run Python control plane                                                                │
│    ┌─────────────────────────┐          Python imports          ┌──────────────────────────┐  │
│    │ FastAPI :8000           │ ───────────────────────────────► │ core/* service modules   │  │
│    │ api/main.py             │                                  │ stack/ elastic/ capture/ │  │
│    │ api/routes/*.py         │ ◄─────────────────────────────── │ ingest/ rules/ enrich/   │  │
│    └─────────────────────────┘            return JSON           │ settings/ confirm        │  │
│                                                                 └─────────────┬────────────┘  │
│                                                                               │               │
│                                                                               │ subprocess /  │
│                                                                               │ HTTP / files  │
│                                                                               v               │
│                                                                   local files + Docker CLI    │
│                                                                                               │
└───────────────────────────────────────────────────────────────────────────────────────────────┘

DOCKER INTERNAL NETWORK
─────────────────────────────────────────────────────────────────────────────────────────────────

┌──────────────────────┐       HTTP :9200        ┌──────────────────────────────────────────────┐
│      Kibana          │ ──────────────────────► │              Elasticsearch                   │
│  query/render layer  │ ◄────────────────────── │  stores docs, aliases, templates, pipelines  │
└──────────────────────┘      JSON results       │                                              │
                                                 │  important indices/aliases:                  │
                                                 │    suricata-*                                │
                                                 │    elastalert2_alerts                        │
                                                 │    soc-alerts                                │
                                                 │    soc-lab-enrichment-audit-*                │
                                                 └────────────────┬─────────────────────────────┘
                                                                  ▲
                                                                  │ POST /_bulk, /_search, etc
                        tails eve.json                            │
┌──────────────────────┐  from bind mount  ┌──────────────────────┴─────────────────────────────┐
│      Filebeat        │ ─────────────────►│              Elasticsearch ingest                  │
│ reads eve.json       │                   │  pipelines normalize Suricata and uploaded logs    │
└───────────┬──────────┘                   └────────────────────────────────────────────────────┘
            │
            │ bind-mounted file
            v
┌───────────────────────────────────────────────────────────────────────────────────────────────┐
│ runtime/logs/suricata/eve.json                                                                │
│ shared file path between host and containers                                                  │
└───────────────────────────────▲───────────────────────────────────────────────────────────────┘
                                │ writes JSON events
                                │
                     docker exec│suricata -r <pcap>
                                │
┌──────────────────────┐        │        PCAPs from bind mount        ┌─────────────────────────┐
│      Suricata        │ ◄──────┴──────────────────────────────────── │ data/pcap on host       │
│ decode/reassembly    │                                              │ replay files + live     │
│ rules -> eve.json    │                                              │ capture chunks          │
└──────────────────────┘                                              └─────────────────────────┘

┌──────────────────────┐       HTTP :9200        ┌──────────────────────────────────────────────┐
│    ElastAlert2       │ ──────────────────────► │              Elasticsearch                   │
│ scheduled searches   │ ◄────────────────────── │  queries suricata-* and writes alert docs    │
│ writes alert docs    │      query results      └──────────────────────────────────────────────┘
└──────────────────────┘
```

## Main Data Paths

### Path 1: PCAP replay

```text
PCAP file
  -> docker exec suricata suricata -r <pcap>
  -> Suricata writes events to eve.json
  -> Filebeat tails eve.json
  -> Filebeat bulk-indexes events into Elasticsearch
  -> Kibana and the SOC Lab UI can query them
  -> ElastAlert2 later queries them and may write alerts
```

### Path 2: Live capture

```text
host interface
  -> dumpcap writes rotating .pcapng chunks
  -> SOC Lab queue logic notices completed chunks
  -> each chunk is replayed through Suricata
  -> eve.json updates
  -> Filebeat ships events
  -> Elasticsearch stores them
```

### Path 3: Generic log upload

```text
uploaded or local log file
  -> preprocess / detect format
  -> optional ingest pipeline selection or generation
  -> bulk ingest into Elasticsearch
  -> Kibana data view creation
  -> searchable in Kibana and the Dash UI
```

### Path 4: Enrichment

```text
UI/API request
  -> enrichment runner
  -> target cluster client
  -> script run(ctx) or run(ctx, params)
  -> document reads/writes on target ES cluster
  -> audit record written to central lab cluster
```

## Repository Structure

This is the current repo snapshot in a `tree`-style layout. It is meant to help a new human or LLM understand where responsibilities live.

```text
soc-lab/
├── api/
│   ├── main.py                  # FastAPI app entry point and router registration
│   ├── models.py                # Pydantic request/response models
│   ├── utils.py                 # API error helpers
│   └── routes/
│       ├── alerts.py            # alert search and aggregations
│       ├── capture.py           # replay, live capture, upload, pipeline endpoints
│       ├── enrichment.py        # enrichment run, cluster, audit, rollback endpoints
│       ├── indices.py           # alias and index inventory / mutation endpoints
│       ├── network.py           # Suricata flow queries and summaries
│       ├── overview.py          # dashboard summary endpoint
│       ├── rules.py             # rule inventory, edit, validate, compile, watcher endpoints
│       └── stack.py             # stack control, service logs, service status
├── config/
│   ├── elastalert2/
│   │   ├── elastalert2.yml      # ElastAlert2 runtime configuration
│   │   └── rules/               # static native ElastAlert2 rules
│   ├── filebeat/
│   │   └── filebeat.yml         # Filebeat input/output shipping config
│   └── suricata/
│       ├── suricata.yaml        # main Suricata configuration
│       └── threshold.config     # alert suppression settings
├── core/
│   ├── capture/
│   │   ├── live.py              # live capture orchestration
│   │   └── replay.py            # PCAP replay orchestration
│   ├── elastic/
│   │   ├── aliases.py           # alias management and Kibana data views
│   │   ├── client.py            # Elasticsearch client factory
│   │   ├── kibana.py            # Kibana REST helper wrapper
│   │   └── loader.py            # Security Onion template/pipeline loader
│   ├── enrich/
│   │   ├── audit.py             # enrichment audit write/read helpers
│   │   ├── clusters.py          # enrichment cluster config loader and routing
│   │   ├── context.py           # main enrichment SDK implementation
│   │   ├── rollback.py          # field-level rollback engine
│   │   ├── runner.py            # enrichment orchestration from config to execution
│   │   ├── scripts.py           # dynamic enrichment script loader
│   │   └── utils.py             # enrichment field/query helpers
│   ├── ingest/
│   │   ├── bulk.py              # bulk ingest helpers
│   │   ├── llm.py               # Ollama/LLM workflow wrapper
│   │   ├── pipeline.py          # ingest pipeline lookup and upload
│   │   ├── pipeline_gen.py      # ingest pipeline generation logic
│   │   ├── preprocess.py        # decompress / detect / normalize inputs
│   │   └── upload.py            # high-level upload orchestration
│   ├── rules/
│   │   └── compile.py           # rules compile checks and watcher lifecycle
│   ├── stack/
│   │   ├── docker.py            # Docker service inventory helpers
│   │   ├── health.py            # stack health aggregation
│   │   └── runtime.py           # stack lifecycle and service control
│   ├── confirm.py               # y/N prompt helper for destructive operations
│   └── settings.py              # repo paths and URL/port configuration helpers
├── data/
│   ├── enrichments/
│   │   ├── config/              # enrichment cluster and run config
│   │   └── scripts/             # user enrichment scripts
│   ├── ingest/                  # sample logs for ingest testing
│   ├── pcap/                    # replay PCAPs and live capture artifacts
│   ├── pipelines/               # built-in, custom, and generated ingest pipelines
│   └── rules/                   # user-editable Suricata and Sigma rules
├── docker/
│   ├── elastalert-start.sh      # ElastAlert2 container entrypoint
│   └── suricata-start.sh        # Suricata container entrypoint
├── docs/                        # main long-form documentation set
├── runtime/                     # runtime logs and generated status files
├── enrich_sdk/
│   └── __init__.py              # public enrichment SDK import surface
├── ui/
│   ├── app.py                   # Dash app entry point
│   ├── helpers.py               # API wrappers and shared UI components
│   ├── assets/style.css         # global CSS styling
│   └── pages/                   # feature pages
├── compose.yml                  # Docker Compose definition for the lab stack
├── start.sh                     # start Docker stack + FastAPI + Dash + watcher
├── stop.sh                      # stop host-run web processes and Docker stack
├── restart.sh                   # restart helper
├── reset.sh                     # destructive reset helper
├── EXPLANATION.md               # older very detailed conceptual deep dive
├── WEB_MIGRATION_DESIGN.md      # web migration architecture notes
└── ENRICHMENT_DESIGN.md         # enrichment design notes and decisions
```

## Documentation Index

The main long-form documentation now lives under `docs/`.

- `docs/README.md` - reading order and documentation map
- `docs/01-system-overview.md` - big-picture architecture and component roles
- `docs/02-repo-map.md` - repo tree and file-role guide
- `docs/03-runtime-stack.md` - Docker stack, startup scripts, config, and runtime state
- `docs/04-backend-services.md` - explanation of `core/` service modules
- `docs/05-api-reference.md` - FastAPI structure and route-to-service mapping
- `docs/06-ui-guide.md` - Dash structure, helper patterns, and page behavior
- `docs/07-data-flows.md` - end-to-end workflow diagrams and low-level behavior
- `docs/08-enrichment.md` - enrichment subsystem deep dive
- `docs/09-operations.md` - debugging and operational verification
- `docs/10-enrichment-sdk-reference.md` - method-level enrichment SDK reference
- `docs/11-enrichment-internals.md` - low-level implementation walkthrough of `core/enrich/*`
