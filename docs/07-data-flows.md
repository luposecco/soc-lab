# Data Flows

This document explains the main workflows of the repo at a low level.

The goal is to answer not just “what command exists” but “what actually happens internally when I use it?”

## Flow 1: Start The Lab

```text
./start.sh
   -> ensure Python venv and dependencies
   -> docker compose up -d
   -> wait for Elasticsearch
   -> wait for Kibana
   -> load SO templates and pipelines
   -> ensure system aliases
   -> start FastAPI
   -> start Dash
   -> start rules watcher
```

Low-level meaning:

- Docker services become available first
- then Elasticsearch is prepared for Suricata-style ingest
- then host-side control plane processes are started
- then the watcher begins monitoring rules folders

This ordering is not accidental.

It reflects a dependency chain:

- the control plane assumes the runtime stack exists
- the UI assumes the API exists
- the rules watcher assumes runtime directories exist
- useful queries assume Elasticsearch has already been initialized with the required templates, pipelines, and aliases

## Flow 2: PCAP Replay

Main user path:

```text
UI or API requests replay
   -> backend validates file path / upload
   -> optional reset of prior replay state
   -> docker exec suricata suricata -r <pcap>
   -> Suricata writes eve.json
   -> Filebeat ships eve.json lines to Elasticsearch
   -> Elasticsearch ingest pipelines normalize documents
   -> ElastAlert2 later queries and writes alerts
```

Detailed diagram:

```text
PCAP file
   |
   v
Suricata replay inside container
   |
   +-> decode traffic
   +-> evaluate rules
   +-> write event JSON lines
   v
runtime/logs/suricata/eve.json
   |
   v
Filebeat tailer
   |
   +-> bulk HTTP ingest to Elasticsearch
   v
suricata-* indices
   |
   +-> Kibana search
   +-> alias views such as soc-alerts
   +-> ElastAlert2 scheduled queries
   v
elastalert2_alerts
```

Important details:

- replay is synchronous from the backend point of view
- ingest is asynchronous after Suricata writes the file
- alert creation is even later because ElastAlert2 runs on a schedule

That means one replay operation actually crosses three timing domains:

1. synchronous Suricata processing
2. asynchronous Filebeat shipping
3. scheduled ElastAlert2 detection

This is why “the replay finished” is not the same thing as “all derived results are already visible.”

## Flow 3: Live Capture

Live capture is more complex because it is continuous.

Model:

```text
dumpcap writes rotating chunk files
   -> completed chunks are detected
   -> chunks are replayed through Suricata one by one
   -> Suricata writes eve.json
   -> Filebeat ships events
   -> Elasticsearch indexes docs
   -> ElastAlert2 may generate alerts
```

Important operational reason for this design:

the repo avoids trying to wire host network interfaces directly into a long-running Suricata container as the primary model. Instead, it normalizes live capture into a replay-like chunk pipeline.

That gives the repo:

- portability
- inspectable artifacts
- reuse of the replay path

It also means live capture intentionally inherits many of the same internal mechanics as replay, which reduces the number of completely different data pipelines the repo has to support.

## Flow 4: Generic Log Upload

This flow is for non-PCAP input.

Conceptual choices:

```text
input file
   -> preprocess
   -> detect format
   -> choose ingest strategy
       - direct JSON ingest
       - CEF conversion then ingest
       - explicit ingest pipeline
       - LLM-generated ingest pipeline
   -> bulk load to Elasticsearch
   -> ensure Kibana data view
```

Why this is useful:

the lab is not limited to network traffic. It can also model enterprise log sources and their parsing paths.

That is a strategic capability expansion. It turns the lab from a Suricata-only environment into a broader Elasticsearch-backed ingest and detection environment.

## Flow 5: Alias Creation

Alias creation is one of the most strategically important flows in the repo.

It allows the lab to reproduce enterprise-facing names without copying data.

Conceptual flow:

```text
user requests alias
   -> validate alias name and source specs
   -> resolve concrete indices
   -> build alias actions
   -> create/update alias in Elasticsearch
   -> if wildcard source exists, create managed template
   -> ensure Kibana data view with same logical name
```

Why the managed template matters:

without it, only today's existing indices would carry the alias. Tomorrow's new indices would not automatically inherit it.

This is one of the most important implementation ideas in the alias subsystem. It makes aliasing durable over time instead of just a one-time patch to current state.

## Flow 6: Rules Compilation

Conceptual flow:

```text
compile request or watcher trigger
   -> test Suricata rule config in container
   -> convert Sigma rules in container
   -> count rules
   -> write compile logs
   -> write status.json
```

The key output is not just success/failure text. It is also the machine-readable status file used by the UI.

That status file is part of the system's internal contract. The UI can read status without having to rerun compilation logic every time it wants to render current rule health.

## Flow 7: Rules Watcher

Conceptual flow:

```text
poll rules folders every 2 seconds
   -> hash current relevant files
   -> compare to previous hash
   -> if changed, run compile flow
   -> update status/log artifacts
```

Important note:

this is a polling watcher, not a filesystem-event watcher.

That makes it simpler and more portable.

It also means there is an intentional latency window between editing a rule file and seeing watcher-driven compile results.

## Flow 8: Enrichment Run

Conceptual flow:

```text
user triggers enrichment
   -> API loads enrichment config
   -> runner chooses allowed target clusters
   -> script loader imports script
   -> runner builds EnrichmentContext
   -> script run(ctx) or run(ctx, params)
   -> context performs ES reads/writes
   -> audit records are written for mutations
```

Detailed enrichment diagram:

```text
Dash / API call
   |
   v
core.enrich.runner
   |
   +-> read data/enrichments/config/enrichments.yml
   +-> load cluster config
   +-> import script file
   +-> validate ENRICHMENT_META
   +-> create EnrichmentContext
   v
user script
   |
   +-> ctx.search / ctx.scan / ctx.update_doc / ...
   v
Elasticsearch target cluster
   |
   v
audit record in lab cluster
```

That last line matters a lot.

The target data may be in some other Elasticsearch cluster, but the audit history still lives centrally in the lab cluster. The mutation target and the audit target are intentionally decoupled.

## Flow 9: Enrichment Rollback

Rollback is field-oriented.

Conceptual flow:

```text
rollback request for run_id
   -> read audit records for that run
   -> check whether later runs changed same fields
   -> if blocked, refuse unless forced
   -> replay field restoration/removal in reverse order
```

Why reverse order matters:

if one run touched the same document multiple times, rollback should usually unwind the most recent change first.

Rollback is also intentionally conservative. If later runs touched the same fields, rollback is blocked unless explicitly forced.

## Flow 10: UI Page Load

Most pages follow this pattern:

```text
user opens page
   -> Dash layout() runs
   -> server-side api_get(...) calls fetch initial data
   -> page renders
   -> dcc.Interval polling begins
   -> callbacks refresh status or execute actions
```

This is not a client-heavy SPA model. It is a server-driven Dash model with regular polling.

That means UI behavior is often tightly coupled to backend availability at render time, not only after the page is already loaded in the browser.

## Cross-Flow Timing Realities

Many flows in this repo are not instant because they cross asynchronous boundaries.

Examples:

- Suricata replay finishes before Filebeat ships all events
- Filebeat may finish shipping before ElastAlert2 has run its next scan
- Kibana availability may trail Elasticsearch availability during startup

That is why the repo contains:

- wait loops
- health polling
- status endpoints
- background status files

These are not incidental implementation details. They are direct responses to the fact that the system spans multiple asynchronous stages.

## Best Way To Debug A Flow

When a workflow breaks, split it into stages.

Example for replay:

1. did the backend start the replay?
2. did Suricata produce `eve.json`?
3. did Filebeat ship documents?
4. do documents exist in `suricata-*`?
5. did ElastAlert2 create alerts?
6. does `soc-alerts` show what you expect?

That stepwise model works for nearly every major flow in the repo.

It is often the fastest debugging method because user-visible symptoms usually appear at the end of a chain, while the real failure occurred earlier in the chain.
