# Runtime Stack

This document explains how the lab starts, what each Docker service does, what the startup scripts do, and where runtime state is stored.

## Runtime Layers

SOC Lab has two runtime layers:

1. Docker services for the actual lab stack
2. host-run Python processes for the control plane

Diagram:

```text
Host machine
  ├─ start.sh
  ├─ FastAPI process
  ├─ Dash process
  ├─ rules watcher process
  └─ docker compose services
       ├─ Elasticsearch
       ├─ Kibana
       ├─ Suricata
       ├─ Filebeat
       └─ ElastAlert2
```

## `compose.yml`

`compose.yml` defines the Docker services.

This file is the spine of the runtime stack.

It does not contain the full application logic, but it *does* define the boundaries that the rest of the repo must respect:

- which services exist
- which ports are published to the host
- which volumes persist state
- which host directories are bind-mounted into containers
- which entrypoint scripts take over container startup behavior

That means if the runtime stack behaves strangely, `compose.yml` is one of the first files that should be checked.

### Elasticsearch service

Important details:

- image: `docker.elastic.co/elasticsearch/elasticsearch:8.13.0`
- published port: `9200`
- persistent volume: `es_data`
- single-node mode
- security disabled for local-lab simplicity

Why this matters:

- single-node mode avoids cluster formation logic
- disabled auth/TLS keeps the local lab easy to use
- persistent volume means data survives container restarts unless you destroy volumes

Operational meaning of the volume:

- replayed and uploaded data survives `docker compose stop`
- data does **not** survive `docker compose down -v` or `./reset.sh`

Operational meaning of the published port:

- the host control plane and browser tools can reach Elasticsearch directly on `localhost:9200`
- other containers usually reach it by Docker DNS name `elasticsearch:9200`

### Kibana service

Important details:

- image: `docker.elastic.co/kibana/kibana:8.13.0`
- published port: `5601`
- talks to Elasticsearch over Docker internal networking

Kibana depends on Elasticsearch health. It does not own data. It is just the UI layer on top of Elasticsearch.

This distinction matters because Kibana problems often look like “the data is gone” when really the data is still in Elasticsearch and Kibana is just not healthy or not configured with the right data view.

### Suricata service

Important details:

- image: `jasonish/suricata:latest`
- entrypoint script: `docker/suricata-start.sh`
- mounted config: `config/suricata/suricata.yaml`
- mounted threshold file: `config/suricata/threshold.config`
- mounted logs: `runtime/logs/suricata`
- mounted PCAP input: `data/pcap`
- mounted custom rules: `data/rules/suricata`
- persistent ET rules volume: `suricata_rules`

Important mental model:

the container stays alive, but Suricata packet processing is usually triggered later with `docker exec`.

That means this container is not just “the Suricata daemon.” It is also a prepared environment holding:

- the Suricata binary
- the Suricata config
- the mounted custom rule directory
- the persisted ET rules volume
- the bind-mounted output log path

The repo uses that prepared environment as a reusable execution target.

### Filebeat service

Important details:

- image: `docker.elastic.co/beats/filebeat:8.13.0`
- mounted config: `config/filebeat/filebeat.yml`
- mounted Suricata log path: `runtime/logs/suricata`
- persistent registry volume: `filebeat_data`

Filebeat tracks file offsets so it knows what parts of `eve.json` it has already sent.

This is one of the main reasons replay workflows can be tricky: the event production step and the shipping step are separate, and Filebeat keeps its own state about what it has already consumed.

### ElastAlert2 service

Important details:

- image: `jertel/elastalert2:latest`
- entrypoint script: `docker/elastalert-start.sh`
- mounted config: `config/elastalert2/elastalert2.yml`
- mounted static rules: `config/elastalert2/rules`
- mounted Sigma rules: `data/rules/sigma`

This service does not just run ElastAlert2. Its entrypoint also performs conversion and startup preparation.

That means ElastAlert2 startup is not a trivial “launch the binary” event. It is also a rule preparation event.

## `start.sh`

`start.sh` is the main operator entry point.

It does much more than `docker compose up -d`.

### What it does, in order

```text
1. check prerequisites
2. ensure Python virtual environment exists
3. install/update Python dependencies
4. stop stale host-run processes on ports/PID files
5. start Docker services with docker compose
6. wait for Elasticsearch
7. wait for Kibana
8. load Security Onion templates and pipelines
9. ensure system aliases
10. start FastAPI
11. start Dash
12. start rules watcher
```

This is important because the repo does not consider “containers are up” to be the same thing as “the lab is ready.”

The lab is only considered ready once:

- the containers are up
- Elasticsearch is reachable
- Kibana is reachable enough for data-view work
- SO assets are loaded
- aliases are ensured
- FastAPI is running
- Dash is running
- the watcher is started if applicable

### Why the startup script is important

The stack is not just containers. The repo depends on post-start initialization.

For example:

- Elasticsearch needs templates and pipelines loaded
- aliases such as `soc-alerts` need to exist
- FastAPI and Dash are separate host processes
- the rules watcher is its own local process

Without `start.sh`, the containers may be alive but the lab would not be fully initialized.

In other words:

```text
docker compose up -d
```

is a necessary step, but not the complete SOC Lab bootstrap procedure.

## `stop.sh`

`stop.sh` stops both layers:

1. host-run processes
2. Docker containers

It uses PID files and port checks to kill:

- FastAPI
- Dash
- rules watcher

Then it runs `docker compose stop`.

Volumes are preserved.

That means Elasticsearch data, Filebeat registry state, and Suricata ET rules remain intact.

This is why `stop.sh` is the safe “pause the environment” command, while `reset.sh` is the destructive “wipe the environment” command.

## `restart.sh`

`restart.sh` is just:

```text
stop.sh
then
start.sh
```

It is intentionally simple.

## `reset.sh`

`reset.sh` is destructive.

It:

- prompts for explicit confirmation
- stops host-run web processes
- runs `docker compose down -v`
- removes Docker volumes
- clears local runtime state files

This is how you wipe Elasticsearch data and restart the lab from a clean state.

## Runtime State Directories

There are two important runtime-state directories.

### `.soc-lab/`

This is local control-plane state.

Common contents:

- `web-api.pid`
- `web-dash.pid`
- `rules-watcher.pid`
- `web-api.log`
- `web-dash.log`
- `rules-watcher.log`

Use this when debugging startup failures of the host-side processes.

This directory matters because the web control plane is not containerized in the current development model.

So if FastAPI or Dash crashes, the first evidence is usually here, not in Docker logs.

### `runtime/`

This is operational runtime output.

Common contents:

- Suricata `eve.json`
- Suricata log files
- rules compile logs
- rules watcher logs
- rules status JSON

Use this when debugging packet processing or rules behavior.

In practical terms:

- `.soc-lab/` is mostly “host control-plane runtime state”
- `runtime/` is mostly “lab operational artifacts and logs”

## Config Files And What They Control

### `config/suricata/suricata.yaml`

Controls:

- loaded rule files
- enabled event output types
- network variables like `HOME_NET`
- Suricata packet processing behavior

This file determines what kinds of events reach `eve.json`.

### `config/suricata/threshold.config`

Controls alert suppression.

This is where noisy or undesirable signatures can be suppressed without removing the rules themselves.

### `config/filebeat/filebeat.yml`

Controls:

- which log files Filebeat tails
- how those events are tagged
- which index naming pattern is used
- which ingest pipeline is called in Elasticsearch

This file determines how Suricata events are shipped and where they land.

### `config/elastalert2/elastalert2.yml`

Controls:

- how often ElastAlert2 searches
- scan lookback window
- alert timing behavior
- writeback settings

This file strongly affects detection responsiveness and replay behavior.

## Container Entrypoint Scripts

### `docker/suricata-start.sh`

This script prepares the Suricata container.

Main job:

- make sure ET rules exist in the persistent rules volume

After setup, the container can remain alive and later be used for `docker exec suricata suricata -r ...` operations.

### `docker/elastalert-start.sh`

This script does more work.

Main jobs:

- install/ensure Sigma backend support
- convert Sigma rules into ElastAlert2 rules
- prepare writeback indices
- start ElastAlert2

This means ElastAlert2 service startup is also a rules-preparation step.

## End-to-End Startup Diagram

```text
./start.sh
   |
   +-> ensure .venv and pip deps
   |
   +-> docker compose up -d
   |      |
   |      +-> elasticsearch container
   |      +-> kibana container
   |      +-> suricata container
   |      +-> filebeat container
   |      +-> elastalert2 container
   |
   +-> wait for Elasticsearch HTTP health
   +-> wait for Kibana HTTP health
   +-> load Security Onion templates and pipelines
   +-> ensure system aliases and views
   +-> start FastAPI on host
   +-> start Dash on host
   +-> start rules watcher on host
```

Another way to see the same flow is by runtime layer:

```text
layer 1: local Python environment
   -> ensure .venv and dependencies

layer 2: Docker data stack
   -> containers up
   -> ES healthy
   -> Kibana healthy

layer 3: data-plane initialization
   -> SO templates/pipelines
   -> aliases/data views

layer 4: host-run control plane
   -> FastAPI
   -> Dash
   -> rules watcher
```

## Failure Boundaries

When the lab does not come up correctly, the failure is usually in one of these layers:

### Layer 1: Docker did not start correctly

Symptoms:

- `docker compose up` fails
- services not listed or unhealthy

Typical causes:

- Docker daemon not running
- bad container image pull
- invalid mounted config

### Layer 2: Docker started, but stack initialization failed

Symptoms:

- containers are up, but Kibana views missing
- aliases missing
- SO pipelines not loaded

Typical causes:

- Elasticsearch reachable but not ready enough yet
- Kibana not yet available
- GitHub fetch for SO assets failed
- loader patching failed

### Layer 3: Host-run control plane failed

Symptoms:

- API not reachable on `8000`
- Dash not reachable on `8050`
- watcher not running

Typical causes:

- missing Python dependencies
- bad import error
- port conflict
- stale PID state

There is also a subtle fourth class that often gets overlooked.

### Layer 4: Services are healthy, but system assumptions are broken

Symptoms:

- data exists but UI views are empty
- replay ran but alerts are not visible where expected
- alias queries behave differently from raw index queries

Typical causes:

- missing or stale Kibana data views
- missing alias attachment or managed template
- wrong time range in Kibana
- ingest pipeline mismatch
- enrichment targeting the wrong cluster or alias

## Best Operational Mental Model

Think of the runtime stack as:

```text
containers provide the lab engines
host-run Python processes provide the lab controls
start.sh stitches them together into one usable system
```

That is the key to understanding why startup, shutdown, and debugging work the way they do.
