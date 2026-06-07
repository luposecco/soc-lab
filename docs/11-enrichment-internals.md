# Enrichment Internals

This document is the low-level internal walkthrough of the enrichment subsystem.

If `docs/08-enrichment.md` explains what the subsystem is, this file explains how the implementation works file by file and function by function.

This is the document to read when you want to modify the enrichment code itself.

## Internal File Map

```text
core/enrich/
├── audit.py                # audit index creation, writes, reads, conflict detection
├── clusters.py             # cluster config parsing and ES client creation
├── context.py              # EnrichmentContext implementation and mutation scripts
├── rollback.py             # rollback execution engine
├── runner.py               # config-driven orchestration
├── scripts.py              # script import + metadata validation + invocation rules
└── utils.py                # nested field and query helpers
```

## `core/enrich/context.py`

This is the most important internal file in the enrichment subsystem.

It is where the script-facing API and the mutation semantics live.

### Internal constants: `_SET_FIELDS_SCRIPT`

This is the Elasticsearch script used by `update_doc`.

Its job is to support dotted paths like:

```python
{"risk.score": 80}
```

What it does conceptually:

```text
for each field path and value:
   split path by dots
   walk ctx._source down nested maps
   create intermediate maps if missing
   set final leaf value
```

Why this matters:

- plain partial updates are not enough if you want consistent nested dotted-path behavior
- scripts should be able to say `risk.score` without worrying about whether `risk` already exists as a nested object

### Internal constants: `_REMOVE_FIELDS_SCRIPT`

This is the Elasticsearch script used by `remove_fields`.

Its job is to support removing dotted nested fields safely.

What it does conceptually:

```text
for each field path:
   split path by dots
   walk nested maps if they exist
   if the full parent path is valid
      remove the leaf key
```

Why this matters:

- field removal should not crash simply because a parent path is missing or not a map

### `EnrichmentContext.__init__(...)`

Stores:

- `_es`
- `cluster`
- `enrichment`
- `run_id`
- `dry_run`
- `_stats`

Important detail:

if no `run_id` is provided, the constructor generates one using:

- enrichment name
- UTC timestamp
- short random suffix

That gives the system a stable run identity for audit and UI reporting.

### `raw`

This property simply returns the underlying Elasticsearch client.

It exists because the wrapper is intentionally not exhaustive.

### `get(index, id)`

Implementation path:

```text
Elasticsearch get API
   -> _format_hit(...)
   -> return convenience dict
```

### `search(index, query=None, size=100, sort=None)`

Implementation path:

```text
default_query(query)
   -> build kwargs
   -> Elasticsearch search API
   -> _format_hit(...) for each hit
   -> return list
```

Important internal design choice:

- the function constructs kwargs and only includes `sort` when supplied
- this keeps the outbound client call cleaner and avoids passing null-y values unnecessarily

### `scan(index, query=None, batch_size=500)`

Implementation path:

```text
initial search with scroll="2m"
   -> while hits exist
      -> yield formatted hits
      -> call scroll API again
   -> clear scroll when done
```

Important internal behavior:

- it uses `try/except` around `clear_scroll` so cleanup failure does not break the calling script after the useful work already finished

### `exists(index, id)`

Implementation is thin by design.

It simply returns boolean existence from the Elasticsearch client.

### `index_doc(index, doc, id=None)`

Implementation flow:

```text
if dry_run:
   return would_create summary

if explicit id:
   _es.create(...)
else:
   _es.index(...)

increment stats
write audit record
return summary
```

Important internal choice:

- explicit ids use `create`, not overwrite-style indexing

This enforces the create-only semantic requested for the SDK.

Audit detail:

- `operation`: `index_doc`
- `rollback_supported`: `False`

### `update_doc(index, id, fields)`

Implementation flow:

```text
ctx.get(...) to fetch current document
   -> field_state(...) for every requested field
   -> if dry_run: return would_update summary
   -> _es.update(...script=_SET_FIELDS_SCRIPT...)
   -> increment stats
   -> write audit record
   -> return summary
```

Important internal reason for fetching the document first:

- rollback needs before-state
- before-state must distinguish absent fields from present null-valued fields

Audit detail:

- `operation`: `update_doc`
- `before`: sentinel-per-field state
- `after`: the requested field map
- `changed_fields`: list of field names
- `rollback_supported`: `True`

### `remove_fields(index, id, fields)`

Implementation flow mirrors `update_doc`, except it uses `_REMOVE_FIELDS_SCRIPT`.

Audit detail:

- `operation`: `remove_fields`
- `before`: sentinel-per-field state
- `after`: empty object
- `changed_fields`: the fields removed
- `rollback_supported`: `True`

### `delete_doc(index, id)`

Implementation flow:

```text
if dry_run:
   return would_delete summary

_es.delete(...)
increment stats
write audit record with rollback_supported=False
```

Why no rollback support flag here:

- restoring deleted docs safely would require a stronger snapshot model than the current field-level one

### `update_by_query(index, query, fields, batch_size=500)`

Despite the name, the implementation is intentionally not a raw Elasticsearch `_update_by_query` wrapper.

Implementation flow:

```text
docs = list(scan(...))
if dry_run:
   return would_update count
for each doc:
   call update_doc(...)
aggregate update counts
```

Why this matters:

- every affected document gets the same audit/rollback treatment as `update_doc`
- the system keeps one consistent mutation model

Tradeoff:

- more Python-side work than a direct server-side update-by-query call

### `remove_by_query(index, query, fields, batch_size=500)`

Same architectural pattern as `update_by_query`, but using `remove_fields`.

### `create_index(index, mappings=None, settings=None)`

Implementation flow:

```text
if dry_run:
   return would_create summary
assemble kwargs for mappings/settings
_es.indices.create(...)
return summary
```

### `delete_index(index)`

Implementation flow:

```text
if dry_run:
   return would_delete summary
_es.indices.delete(...)
return summary
```

### `summary()`

Returns:

- `run_id`
- `enrichment`
- `cluster`
- `dry_run`
- `docs_created`
- `docs_updated`
- `docs_deleted`

This is what the runner uses to shape per-target results.

### `_format_hit(hit)`

Implementation detail:

- reads `_source`
- returns `_id`, `_index`, `_source`, and a shallow top-level merge of source fields

Why this design was chosen:

- script ergonomics
- easy metadata access
- easy direct field access

## `core/enrich/utils.py`

This file is small, but the helpers here support rollback correctness.

### `default_query(query)`

Returns `query` if present, otherwise `{"match_all": {}}`.

### `nested_field_exists(doc, field_path)`

Walks dotted paths through nested dicts and returns whether the path exists.

### `nested_field_value(doc, field_path)`

Walks dotted paths and returns the value or raises if absent.

### `field_state(doc, field_path)`

Returns one of two sentinel shapes:

```json
{"exists": false}
```

or:

```json
{"exists": true, "value": ...}
```

This is one of the core building blocks of rollback correctness.

## `core/enrich/scripts.py`

This file handles dynamic script loading and invocation rules.

### `VALID_ENRICHMENT_TYPES`

Defines the currently allowed metadata types.

### `EnrichmentScript`

Small dataclass holding:

- path
- module
- meta

### `resolve_script_path(script_path)`

Resolves config-relative script paths under `data/enrichments/`.

This keeps scripts constrained to the expected enrichment directory tree.

### `load_script(script_path, module_name)`

Implementation flow:

```text
resolve repo path
   -> build importlib spec
   -> execute module
   -> normalize ENRICHMENT_META
   -> ensure module.run is callable
   -> return EnrichmentScript dataclass
```

### `invoke_script(script, ctx, params=None)`

Implementation flow:

```text
inspect positional arity of script.module.run
   -> if arity == 1 and params passed: raise error
   -> if arity == 1: call run(ctx)
   -> if arity == 2: call run(ctx, runtime_params)
   -> else: raise signature error
```

Why arity validation is important:

- script contract must stay explicit
- GUI/runtime-param behavior should not rely on guesswork

### `_run_positional_arity(run_fn)`

Uses `inspect.signature(...)` and counts positional parameters.

### `_normalize_meta(raw_meta, path)`

Behavior:

- ensure metadata is a dict
- default type to `play_batch`
- ensure type is allowed
- default display name from filename stem if absent
- default description to empty string

## `core/enrich/clusters.py`

This file turns YAML cluster definitions into usable Elasticsearch clients.

### `ClusterDef`

Dataclass fields:

- `name`
- `mode`
- `hosts`
- `auth_type`
- `auth_env`
- `auth_user`
- `auth_pass_env`

### `ClusterManager.__init__(clusters)`

Stores parsed clusters and an initially empty client cache.

### `ClusterManager.load(path=None)`

Implementation flow:

```text
start with implicit lab cluster
   -> if YAML exists, parse it
   -> if YAML defines lab, override default lab details
   -> parse all other clusters
   -> return manager
```

Important internal design decision:

- `lab` always exists logically
- user config can still override the default `lab` connection details if needed

### `_make_client(name)`

Behavior:

- verify cluster name exists
- assemble Elasticsearch client kwargs from cluster definition
- apply auth handling based on `auth_type`

Important auth behavior:

- `api_key` must find its env var value
- `basic` requires a username and can read password from env
- unsupported auth types fail explicitly

### `get_client(name)`

Behavior:

- create client once if absent
- then reuse cached client on later calls

### `ping(name)`

Behavior:

- create a client
- call `info()`
- measure elapsed time
- return version and latency or error

Why it exists:

- operational visibility
- UI cluster testing

### `ping_all()` / `list_all()` / `names()`

Small convenience methods for the API and UI.

## `core/enrich/runner.py`

This is the execution orchestrator.

### `_DEFAULT_CONFIG`

Points at `data/enrichments/config/enrichments.yml`.

### `EnrichmentDef`

Dataclass fields:

- `name`
- `script`
- `targets`
- `enabled`
- `schedule`
- `meta`

Its `to_dict()` method merges config data with script metadata so the API/UI can expose both together.

### `load_enrichment_config(path=None)`

Implementation flow:

```text
read YAML
for each configured enrichment:
   -> load script to read metadata
   -> shape config + metadata into EnrichmentDef
return list of dicts
```

Important design implication:

- configuration listing depends on scripts loading successfully
- broken scripts can therefore surface at “list enrichments” time, not only at run time

### `run_enrichment(...)`

Implementation flow in order:

1. load YAML config
2. verify the named enrichment exists
3. verify it is enabled
4. determine allowed targets
5. if a specific cluster was requested, ensure it is one of the allowed targets
6. load the script module
7. create a shared `run_id`
8. for each target cluster:
   - create or fetch the correct Elasticsearch client
   - create `EnrichmentContext`
   - invoke the script
   - capture success or exception in the results list
9. return a top-level summary object

Important design choice:

- one logical invocation shares one `run_id` across all target clusters

This is useful because the UI and audit history can treat a multi-cluster invocation as one logical run.

## `core/enrich/audit.py`

This file is the audit storage and conflict-detection layer.

### `AUDIT_INDEX_PREFIX`

Current prefix:

```text
soc-lab-enrichment-audit
```

### `_AUDIT_INDEX_MAPPINGS`

Defines audit index mappings for important fields such as:

- `@timestamp`
- `run_id`
- `enrichment`
- `cluster`
- `index`
- `doc_id`
- `operation`
- `changed_fields`
- `rollback_supported`

Important detail:

- `before` and `after` are stored as disabled objects

Why disabled objects:

- keep the payload
- avoid exploding mappings for arbitrarily shaped enrichment field histories

### `_today_index()`

Builds the daily audit index name.

### `write(record)`

Implementation flow:

```text
ensure today's audit index exists
fill in @timestamp if absent
default changed_fields and rollback_supported
index audit document into lab cluster
```

### `read_run(run_id)`

Searches audit indices for all records with the matching `run_id`, sorted oldest to newest.

### `list_runs(limit=50)`

Uses aggregations keyed by `run_id` to summarize history into:

- latest timestamp
- enrichment name
- cluster
- operation count

This is much more UI-friendly than listing every document mutation raw.

### `has_later_field_changes(record)`

This is one of the most important safety checks in the subsystem.

Implementation idea:

```text
is there a later audit record
   on same cluster
   same index
   same doc id
   overlapping changed_fields
   rollback_supported=True
   from a different run_id?
```

If yes, the older record is not safe to roll back automatically without force.

### `_ensure_audit_index(index_name)`

Creates the daily audit index if missing, ignoring the already-exists case.

## `core/enrich/rollback.py`

This file is the rollback engine.

### `rollback(run_id, dry_run=False, force=False)`

Implementation flow:

```text
read_run(run_id)
   -> keep only rollback-supported records
   -> compute blocked records via has_later_field_changes(...)
   -> if dry_run: report only
   -> if blocked and not force: abort
   -> process rollback-supported records in reverse order
      -> restore fields or remove fields as needed
   -> collect errors
   -> return summary
```

Important design choice:

- records are processed in reverse order

Why reverse order:

- later changes should be unwound before earlier ones when the same run touched related state multiple times

### Operation handling inside rollback

#### For `update_doc`

Rollback logic does two things:

- restore old values for fields that previously existed
- remove fields that did not exist before the update

That second step is why the audit sentinel must distinguish “missing” from “present but null”.

#### For `remove_fields`

Rollback restores only fields that previously existed.

### `_expand_fields(fields)`

Converts dotted flat field names into nested dict form suitable for partial document updates.

Example:

```python
{"risk.score": 80}
```

becomes:

```python
{"risk": {"score": 80}}
```

### `_remove_fields_script()`

Returns the nested-field removal Elasticsearch script used during rollback when fields need to be deleted again.

## Internal Safety Philosophy

The internal design is trying to optimize for these properties:

1. script author ergonomics
2. auditable mutations
3. rollback feasibility for field changes
4. explicit behavior over magic

That is why the code prefers:

- separate create vs update semantics
- explicit field removal semantics
- per-document audit records
- explicit rollback conflict checks

## Where To Modify Things

If you want to add a new script-author method:

- start in `core/enrich/context.py`
- decide how audit should behave
- decide whether rollback should support it
- update docs in `docs/08` and `docs/10`

If you want to add a new script metadata field:

- update `core/enrich/scripts.py`
- then update any UI/API consumers that list enrichments

If you want to add a new cluster auth style:

- update `core/enrich/clusters.py`
- then document the config shape and secret-handling expectations

If you want periodic execution:

- keep `context.py` mostly unchanged
- add a scheduler/orchestrator around `runner.py`
- treat schedule config as orchestration metadata, not a context concern

## Best Mental Model For Maintainers

Think of the subsystem like this:

```text
scripts.py decides what a script is
clusters.py decides where it can run
runner.py decides when and against which targets it runs
context.py decides how scripts talk to Elasticsearch safely
audit.py decides what mutation history is remembered
rollback.py decides how that history can be unwound
```

That is the internal architecture in one view.
