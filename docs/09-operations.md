# Operations And Debugging

This document is about running the lab and diagnosing problems.

It is written for day-to-day development and troubleshooting.

## Basic Lifecycle

Start:

```bash
./start.sh
```

Stop:

```bash
./stop.sh
```

Restart:

```bash
./restart.sh
```

Destructive reset:

```bash
./reset.sh
```

## URLs

- Dash UI: `http://127.0.0.1:8050`
- FastAPI: `http://127.0.0.1:8000`
- Elasticsearch: `http://localhost:9200`
- Kibana: `http://localhost:5601`

## First Places To Look When Something Breaks

### Host-side logs

Directory:

```text
.soc-lab/
```

Common files:

- `web-api.log`
- `web-dash.log`
- `rules-watcher.log`

Use these when FastAPI, Dash, or the watcher fails to start.

### Runtime logs

Directory:

```text
runtime/
```

Common areas:

- `runtime/logs/suricata/`
- `runtime/logs/rules/`

Use these when packet replay, shipping, or rules compilation is failing.

### Docker service logs

Useful commands:

```bash
docker compose ps
docker compose logs elasticsearch
docker compose logs kibana
docker compose logs filebeat
docker compose logs elastalert2
docker compose logs suricata
```

## Quick Verification Checklist

When the system is up, verify these in order:

1. Docker services are running
2. Elasticsearch responds on `9200`
3. Kibana responds on `5601`
4. FastAPI responds on `8000`
5. Dash responds on `8050`
6. system aliases exist
7. rules watcher is running if expected

Useful commands:

```bash
curl -s http://localhost:9200/_cluster/health | jq
curl -s http://localhost:5601/api/status | jq
curl -s http://127.0.0.1:8000/api/health | jq
curl -s http://localhost:9200/_cat/aliases?v
```

This ordering matters. If you jump straight into the UI, you may debug the wrong layer first.

Example:

- if Elasticsearch is down, Kibana can look broken, the API can look broken, and the Dash UI can look broken
- but the actual root cause is still Elasticsearch availability

## Replay Debugging

If a PCAP replay seems to “do nothing”, debug in stages.

### Stage 1: did replay start?

Check API logs and replay status endpoint.

### Stage 2: did Suricata write events?

Check:

```bash
ls runtime/logs/suricata
```

and inspect whether `eve.json` exists and has content.

### Stage 3: did Filebeat ship events?

Check Filebeat logs and Elasticsearch counts:

```bash
docker compose logs filebeat
curl -s http://localhost:9200/suricata-*/_count | jq
```

### Stage 4: did alerts fire?

Check:

```bash
curl -s http://localhost:9200/elastalert2_alerts/_count | jq
curl -s http://localhost:9200/soc-alerts/_count | jq
```

### Stage 5: is Kibana looking at the right time range?

This matters a lot when replaying older PCAPs.

If timestamps are old and you did not shift them to now, Kibana's default recent time window may hide the results.

This is one of the easiest ways to mistake a successful replay for a failed replay.

## Alias Debugging

Useful checks:

```bash
curl -s http://localhost:9200/_cat/aliases?v
curl -s http://localhost:9200/_alias/soc-alerts | jq
curl -s http://localhost:9200/_index_template | jq
```

Questions to ask:

- does the alias exist?
- does it point at the indices I expect?
- if wildcard-backed, was the managed template created?
- does Kibana have a matching data view?

Also ask:

- are you querying the alias or a raw backing index?
- if the alias is filtered, is the filter excluding the documents you expected?

## Rules Debugging

Primary artifacts:

```text
runtime/logs/rules/status.json
runtime/logs/rules/suricata-compile.log
runtime/logs/rules/sigma-compile.log
runtime/logs/rules/watcher.log
```

Questions to ask:

- did the compile step run?
- did Suricata validation fail?
- did Sigma conversion fail?
- did the watcher detect the file change?

That last question matters because stale rule status can be caused by watcher behavior, not only by broken rules.

## Enrichment Debugging

Questions to ask in order:

1. did the target cluster definition load?
2. did auth resolve correctly?
3. did the script metadata validate?
4. did the script execute successfully?
5. did audit records get written?
6. if rollback failed, was it blocked by later field changes?

Useful backend areas:

- `data/enrichments/config/clusters.yml`
- `data/enrichments/config/enrichments.yml`
- `data/enrichments/scripts/`
- `core/enrich/*`

Useful Elasticsearch check:

```bash
curl -s http://localhost:9200/soc-lab-enrichment-audit-*/_search | jq
```

Remember that target document state and audit state are different evidence sources.

Examples:

- mutation visible, no audit record: likely an audit-path problem or raw client bypass
- audit record visible, target mutation absent: likely target-cluster or mutation-path problem

## Common Failure Classes

### Dependency failure

Symptoms:

- FastAPI or Dash fails immediately on startup
- import errors in `.soc-lab/*.log`

Typical fix:

- rerun `./start.sh`
- inspect venv dependency installation output

### Docker health failure

Symptoms:

- Elasticsearch or Kibana never becomes ready
- downstream services stay unhealthy or broken

Typical fix:

- inspect `docker compose logs <service>`
- verify Docker resources and local ports

### Ingest failure

Symptoms:

- `eve.json` exists but indices remain empty
- uploads appear to succeed but docs not indexed

Typical fix:

- inspect Filebeat logs
- inspect ingest pipeline existence
- test Elasticsearch directly

### Rules failure

Symptoms:

- watcher log shows repeated compile errors
- alerts do not fire

Typical fix:

- inspect compile logs
- validate problematic rule files

### UI/API mismatch

Symptoms:

- UI buttons fail silently
- JSON shape errors in web logs

Typical fix:

- inspect FastAPI response JSON
- inspect `web-dash.log`
- confirm route contract still matches page expectations

This class of bug often appears after backend response-shape changes where the UI page still expects an older JSON structure.

## Safe Debugging Strategy

The safest debugging order is:

1. verify process/container health
2. verify files/logs exist where expected
3. verify Elasticsearch state directly
4. verify API output directly
5. then inspect UI rendering behavior

This prevents wasting time debugging the wrong layer.

A good mental model is:

```text
verify the producer
then verify the transport
then verify the storage
then verify the query layer
then verify the UI layer
```

## Why This Matters

SOC Lab crosses multiple boundaries:

- host processes
- Docker containers
- filesystem state
- HTTP APIs
- Elasticsearch ingest and search behavior
- asynchronous detection behavior

When something breaks, it is almost always because one step in a chain failed earlier than the visible symptom.

That is why operational debugging in this repo should always be stepwise rather than guess-based.
