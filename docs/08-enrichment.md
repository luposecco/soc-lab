# Enrichment System

> For the SDK method reference see `docs/10-enrichment-sdk-reference.md`.
> For the internal code walkthrough see `docs/11-enrichment-internals.md`.

---

## Why the Enrichment Subsystem Exists

Elasticsearch stores and retrieves data. It does not post-process it. Analysts frequently need to:

- Add a risk score or triage tag to alerts that match a pattern
- Annotate a single alert with a ticket reference mid-investigation
- Sync derived documents from external threat feeds on a schedule
- Map hostnames to asset owners across all historical data

The enrichment subsystem lets users write Python scripts for this work. SOC Lab handles the surrounding concerns: cluster connectivity, dry-run safety, audit logging, and rollback.

---

## Architecture Decisions

### No `ENRICHMENT_META` in scripts

**Decision:** Script files contain only `def run(ctx)`. All metadata lives in `enrichments.yml`.

**Why:** Keeping metadata in the script created coupling — renaming a field meant editing two places, and the validator had to load the script just to read the name. Putting everything in YAML makes config editable without touching Python. Scripts are pure logic.

**What changed:** `core/enrich/scripts.py` no longer validates or reads `ENRICHMENT_META`. `core/enrich/runner.py` reads all config (name, targets, schedule, on_log, description) from `enrichments.yml`.

### Run types replaced by YAML flags

**Decision:** No `run_type` field. Three behaviours are expressed differently:

| Behaviour | How to specify |
|---|---|
| Batch (run on demand against all matching docs) | Default — set nothing |
| Scheduled (runs automatically on an interval) | `schedule: 15m` in the YAML |
| Log trigger (appears in the per-alert enrichment menu) | `on_log: true` in the YAML |

**Why:** `run_type` was both UI classification and execution behaviour in one field. Separating them means a script can be both a log trigger and manually runnable without needing a new type value.

**UI effect:** Log-trigger scripts show only an Edit button in the enrichment list (no Run/Dry buttons, because they are driven per-alert, not in bulk from the overview).

### `ctx.params` always available

**Decision:** `EnrichmentContext.params` is always a `dict`, never `None`. It is set before `run()` is called.

**Why:** Scripts don't need to guard `if params is None`. They call `ctx.params.get("_id")` and get `None` if nothing was passed. No conditional imports needed.

**SDK contract:** Scripts that accept a second positional argument (`def run(ctx, params)`) still work — `params` will be the same dict as `ctx.params`. Both arities are supported for backwards compatibility.

### YAML is the single source of truth for config

`enrichments.yml` stores: config key, display name, script path, target clusters, enabled flag, on_log flag, schedule, description. The API CRUD endpoints write back to this file. The UI reads from the API.

### The `lab` cluster is built-in and cannot be deleted

`ClusterManager.load()` always injects the `lab` cluster pointing to `SOC_LAB_ES_URL` (or `localhost:9200`). It can be overridden in `clusters.yml` but cannot be removed from the UI. The delete endpoint rejects `name == "lab"` explicitly.

---

## File Layout

```text
data/enrichments/
├── config/
│   ├── enrichments.yml   # per-enrichment config (CRUD via API)
│   └── clusters.yml      # external cluster config (CRUD via API)
└── scripts/
    └── *.py              # enrichment script files (read/write via API)

core/enrich/
├── audit.py              # audit index writes, reads, conflict detection
├── clusters.py           # cluster loading, ES client creation, ping
├── context.py            # EnrichmentContext — the script-facing API
├── rollback.py           # rollback execution
├── runner.py             # config-driven orchestration (load + run)
├── scripts.py            # script loading and invocation
└── utils.py              # nested field helpers

api/routes/enrichment.py  # all API routes under /api/enrich/*
ui/pages/enrichment.py    # Dash page (callbacks)
ui/pages/enrichment_layout.py # Dash layout components
```

---

## enrichments.yml Format

```yaml
enrichments:
  example_risk:                        # config key — used as enrichment ID in API and runs
    name: "Example Risk"               # display name shown in the UI
    description: "Adds a risk score to critical severity alerts missing one."
    script: scripts/example_enrichment.py  # relative to data/enrichments/
    targets:
      - lab                            # cluster names from clusters.yml
    enabled: true
    on_log: false                      # true → appears in per-alert enrichment menu

  annotate_alert:
    name: "Alert Annotator"
    script: scripts/annotate_alert.py
    targets:
      - lab
    enabled: true
    on_log: true                       # log trigger; no Run/Dry buttons shown

  ioc_sync:
    name: "IoC Feed Sync"
    script: scripts/ioc_sync.py
    targets:
      - lab
    enabled: true
    schedule: 15m                      # simple interval: 30s, 5m, 2h, etc.
```

**Config key rules:** Lowercase, alphanumeric, underscores. Used as the `name` field in API responses and in audit records. Cannot be changed after creation without losing run history linkage.

---

## clusters.yml Format

```yaml
clusters:
  # lab is always injected by code — override only to change URL or mode
  # lab:
  #   mode: internal
  #   hosts:
  #     - http://localhost:9200

  customer_prod:
    mode: external
    hosts:
      - https://es01.example:9200
      - https://es02.example:9200
    auth:
      type: api_key
      env: CUSTOMER_PROD_ES_API_KEY   # env var holding the API key

  research:
    mode: external
    hosts:
      - https://research-es.example:9200
    auth:
      type: basic
      user: elastic
      pass_env: RESEARCH_ES_PASS      # env var holding the password
```

**Auth types:** `none` (default), `api_key` (via env var), `basic` (user + password env var). Credentials are never stored in the YAML — only the env var names.

---

## Script Contract

A minimal script:

```python
"""One-line description."""
from enrich_sdk import EnrichmentContext

def run(ctx: EnrichmentContext) -> None:
    ctx.update_by_query(
        index="soc-alerts",
        query={"bool": {"must": [{"term": {"alert.severity": 1}}],
                        "must_not": [{"exists": {"field": "risk.score"}}]}},
        fields={"risk.score": 95, "risk.reason": "Critical severity alert"},
    )
```

Rules:
- Must define `def run(ctx)` or `def run(ctx, params)` — no other form is supported
- No `ENRICHMENT_META` — metadata lives in `enrichments.yml`
- `ctx.params` is always a dict (populated at call time, empty dict if nothing passed)
- Scripts run synchronously in the API worker — avoid blocking calls longer than ~30s

---

## Execution Flow

```
UI "Run" button clicked
  → POST /api/enrich/run/{name}  {dry_run: false, params: {}}
    → load enrichments.yml, look up config
    → verify enabled=true
    → load script file into fresh module
    → ClusterManager.load() → get_client(cluster_name) → Elasticsearch client
    → for each target cluster:
        ctx = EnrichmentContext(es, cluster, enrichment, run_id, dry_run)
        ctx.params = {} (or passed params)
        invoke_script(script, ctx)
          → script.run(ctx)
          → ctx.update_by_query / ctx.update_doc / etc.
            → if dry_run: return plan counts, skip writes
            → if live: write to ES + write audit record per document
    → return run_id + per-cluster results
```

---

## Dry Run Semantics

When `dry_run=True`:
- All write methods return plan dicts instead of executing
- Audit records are NOT written
- ES is still queried to count matching documents
- The run console shows `[DRY]` prefix

Use dry run to verify query scope before writing.

---

## Audit and Rollback

Every live write (`update_doc`, `remove_fields`) creates an audit record in `soc-lab-enrichment-audit-YYYY.MM.DD` with:

```json
{
  "run_id": "example_risk-20260706-210305-f40332",
  "enrichment": "example_risk",
  "cluster": "lab",
  "index": "soc-alerts",
  "doc_id": "abc123",
  "operation": "update_doc",
  "before": {"risk.score": null},
  "after":  {"risk.score": 95},
  "changed_fields": ["risk.score"],
  "rollback_supported": true
}
```

Rollback reads all records for a `run_id`, checks for later conflicting writes (via `has_later_field_changes`), and undoes each field to its `before` value. Use `force=true` to roll back even when conflicts exist.

Bulk writes (`update_by_query`, `remove_by_query`) call `update_doc` / `remove_fields` per document, so each document is individually audited and rollback-able.

`index_doc` and `delete_doc` set `rollback_supported: false` — they are not reversible through the rollback system.

---

## UI Overview

The enrichment page at `/enrichment` has two tabs:

**Overview tab:**
- Metrics: nodes online, enrichment count, total runs, total audit ops
- Cluster nodes table: mode, ping status, latency, Edit button
- Run console: output of the most recent run (live or dry)
- Enrichment list: Run (blue), Dry, Edit buttons per script; search filter

**Rollback tab:**
- All runs in history (aggregated from audit index)
- Rollback button per live run

**Edit panel:** Floats over the content area when Edit is clicked. Shows either the script form (config key, name, path, target nodes checklist, enabled toggle, log trigger toggle, schedule, description, code editor) or the node form (name, mode, hosts, auth). Validate + Save + Delete actions.

---

## API Routes Summary

```
GET    /api/enrich/clusters             list all clusters with mode/auth_type
POST   /api/enrich/clusters/ping        ping all clusters → latency + version
POST   /api/enrich/clusters/{name}/test ping a single cluster
POST   /api/enrich/clusters-config/{name}   save/update cluster in clusters.yml
DELETE /api/enrich/clusters-config/{name}   delete cluster from clusters.yml

GET    /api/enrich/enrichments          list all enrichments from enrichments.yml
POST   /api/enrich/enrichments/{key}    save/update enrichment config
DELETE /api/enrich/enrichments/{key}    delete enrichment config

GET    /api/enrich/scripts              list .py files under data/enrichments/scripts/
GET    /api/enrich/script-content?path= read a script file
POST   /api/enrich/script-content       write a script file
POST   /api/enrich/script-validate      syntax check + run() presence check

POST   /api/enrich/run/{name}           run an enrichment {cluster, dry_run, params}
GET    /api/enrich/runs?limit=N         list run history (aggregated from audit index)
POST   /api/enrich/rollback/{run_id}    rollback a run (?dry_run=false&force=false)
```
