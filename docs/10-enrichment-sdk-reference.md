# Enrichment SDK Reference

This document is a script-author course-style reference for the enrichment SDK.

Where `docs/08-enrichment.md` explains the subsystem architecture, this file goes deeper into the actual developer experience of writing scripts against `EnrichmentContext`.

It explains not just what methods exist, but:

- why the methods are shaped this way
- what happens internally when you call them
- which methods are safer for common enrichment work
- what gets audited
- what does and does not roll back cleanly
- what patterns are good or dangerous in scripts

## Public Import

```python
from soc_enrich import EnrichmentContext
```

Why this import path exists:

- user scripts should not import internal implementation modules directly
- `soc_enrich` is the public API surface
- the internal implementation may evolve while the public import path stays stable

## Minimal Script Skeleton

```python
from soc_enrich import EnrichmentContext

ENRICHMENT_META = {
    "type": "play_batch",
    "name": "My Enrichment",
    "description": "Describe what this script does.",
}

def run(ctx: EnrichmentContext) -> None:
    pass
```

What this means operationally:

- the runner imports this file dynamically
- the runner reads `ENRICHMENT_META`
- the runner creates an `EnrichmentContext`
- the runner calls `run(ctx)`

Single-item or param-driven version:

```python
from soc_enrich import EnrichmentContext

ENRICHMENT_META = {
    "type": "play_single",
    "name": "One Item Enrichment",
    "description": "Acts on one selected document.",
}

def run(ctx: EnrichmentContext, params: dict) -> None:
    doc_id = params["_id"]
```

What this means operationally:

- the runner still imports the same way
- but now it expects to pass runtime parameters into the script
- if no params are supplied, the script still receives an empty dict-like runtime value path from the runner call site if used that way

## Metadata Reference

### `type`

Allowed values:

- `play_single`
- `play_batch`
- `play_periodic`

Current meaning:

- UI/runtime classification
- not a different class
- not a different transport model

Think of `type` primarily as a surrounding-system hint.

It tells the UI and orchestration layer what kind of experience the script wants:

- `play_single` means “this enrichment is conceptually aimed at one chosen thing”
- `play_batch` means “this enrichment is conceptually aimed at many documents”
- `play_periodic` means “this enrichment should eventually be runnable on a schedule”

It does **not** currently mean three different SDK classes.

### `name`

Human-readable display name.

### `description`

Human-readable summary.

## Document Shape Returned By Reads

Read methods return a convenience shape that includes both Elasticsearch metadata and the document body.

Typical keys:

- `_id`
- `_index`
- `_source`
- top-level `_source` fields copied onto the returned dict

That means all of these are common patterns:

```python
doc["_id"]
doc["_index"]
doc["_source"]
doc.get("alert")
doc.get("event")
```

Why the SDK returns this mixed convenience shape:

- Elasticsearch hits naturally have `_id`, `_index`, and `_source`
- script authors often want both the metadata and the document body
- copying `_source` fields to the top level makes common field access shorter

Tradeoff:

- the returned object is convenience-oriented rather than a raw Elasticsearch hit object

If you want the exact original Elasticsearch response shape, use `ctx.raw` and call the client yourself.

## Read Methods

### `ctx.get(index, id)`

Use when you know exactly which document you want.

Example:

```python
doc = ctx.get(index="soc-alerts", id="abc123")
print(doc["_index"])
print(doc["_source"])
```

Internal behavior:

```text
ctx.get(index, id)
   -> Elasticsearch GET /<index>/_doc/<id>
   -> result passed through _format_hit(...)
   -> script receives convenience dict
```

When it is the right tool:

- you know the exact target doc id
- you are writing a `play_single` style enrichment
- you want to inspect one selected alert before deciding on mutation

### `ctx.search(index, query=None, size=100, sort=None)`

Use when you want a small result list.

Example:

```python
docs = ctx.search(
    index="soc-alerts",
    query={"term": {"event.dataset": "suricata.alert"}},
    size=25,
)
```

If `query` is omitted, a `match_all` query is used.

Internal behavior:

```text
ctx.search(...)
   -> if query is None, use {"match_all": {}}
   -> Elasticsearch search API
   -> format each hit with _format_hit(...)
   -> return Python list
```

When it is the right tool:

- previewing likely matches
- returning a small working set
- grabbing a few examples before deciding on a larger batch logic

When it is the wrong tool:

- large result sets
- “iterate every matching doc in the index” style jobs

### `ctx.scan(index, query=None, batch_size=500)`

Use when you want to iterate over many documents.

Example:

```python
for doc in ctx.scan(index="soc-alerts", query={"match_all": {}}, batch_size=500):
    print(doc["_id"])
```

Internal behavior:

```text
ctx.scan(...)
   -> initial Elasticsearch search with scroll="2m"
   -> yield formatted hits batch by batch
   -> keep calling scroll API until no hits remain
   -> clear scroll when done
```

Why this matters:

- it avoids loading every match into one big list up front
- it makes large enrichment jobs more memory-friendly
- it gives scripts a natural `for doc in ...` loop model

Operational caution:

- `scan` still represents potentially large work
- if your query is too broad, your script can still end up touching huge numbers of docs

### `ctx.exists(index, id)`

Use when you only need to know whether a document exists.

Example:

```python
if ctx.exists(index="soc-alerts", id="abc123"):
    print("document exists")
```

This is a fast guard-style helper.

Use it when:

- you want to ensure a target exists before deciding between create/update logic
- you do not need the document body yet

## Write Methods

### `ctx.index_doc(index, doc, id=None)`

Purpose:

- create one new document

Important behavior:

- explicit existing ids error
- no silent replace behavior
- if `id` is omitted, Elasticsearch generates one

Example:

```python
ctx.index_doc(
    index="scratch-notes",
    id="note-1",
    doc={
        "@timestamp": "2026-06-07T12:00:00Z",
        "message": "hello",
    },
)
```

Internal behavior:

```text
if dry_run:
   return would_create summary

if explicit id:
   Elasticsearch create API
else:
   Elasticsearch index API with generated id

increment created counter
write audit record marked rollback_supported=False
```

Why create-only semantics were chosen:

- enrichment users usually mean one of two things very clearly:
  - create something new
  - update something existing
- silently replacing old docs with “create-like” code is easy to misuse
- forcing overwrite behavior into a different path keeps scripts safer and easier to read

When `index_doc` is a good choice:

- creating a scratch/testing document
- generating a new derived document
- seeding a test index

When `index_doc` is a bad choice:

- changing an existing alert or event
- broad enrichment changes to already-existing docs

### `ctx.update_doc(index, id, fields)`

Purpose:

- update one existing document partially

Important behavior:

- creates missing fields
- overwrites existing fields
- supports dotted nested paths

Example:

```python
ctx.update_doc(
    index="soc-alerts",
    id="abc123",
    fields={
        "risk.score": 90,
        "risk.reason": "matched enrichment condition",
        "triage.status": "open",
    },
)
```

Internal behavior:

```text
1. fetch current doc with ctx.get(...)
2. compute field_state(...) for each requested field
3. if dry_run: return would_update summary
4. run nested-field update script in Elasticsearch
5. increment updated counter
6. write audit record with before/after and changed_fields
```

Why it reads first:

- rollback needs to know what the field looked like before the change
- the system must distinguish:
  - field absent
  - field present with null
  - field present with some concrete value

Why it uses a script instead of a plain `doc={...}` merge for nested dotted fields:

- `risk.score` should behave like a nested path, not just a flat string key
- the script creates intermediate maps if needed

This is the core enrichment mutation primitive.

If you are writing enrichment logic that tags, scores, annotates, or triages documents, this is usually the method you want.

### `ctx.remove_fields(index, id, fields)`

Purpose:

- remove one or more fields from one document

Example:

```python
ctx.remove_fields(
    index="soc-alerts",
    id="abc123",
    fields=["triage.temp_note", "triage.temp_flag"],
)
```

Internal behavior:

```text
1. fetch current doc
2. compute field_state(...) for each field being removed
3. if dry_run: return would_update summary
4. run nested-field removal script in Elasticsearch
5. increment updated counter
6. write rollback-capable audit record
```

Why this exists separately from `update_doc(..., fields={...})` with nulls:

- removing a field and setting a field to null are not the same operation
- rollback and reasoning are cleaner when deletion semantics are explicit

### `ctx.delete_doc(index, id)`

Purpose:

- delete one document

Example:

```python
ctx.delete_doc(index="scratch-notes", id="note-1")
```

Important limitation:

- v1 rollback does not restore deleted docs

Internal behavior:

```text
if dry_run:
   return would_delete summary

Elasticsearch delete API
increment deleted counter
write audit record marked rollback_supported=False
```

This is the sharpest document-level mutation tool in the current SDK.

Use it only when document deletion is truly the desired effect, not when you merely want to remove enrichment fields.

## Query-Wide Convenience Methods

### `ctx.update_by_query(index, query, fields, batch_size=500)`

Purpose:

- update all matching docs with the same field set

Example:

```python
ctx.update_by_query(
    index="soc-alerts",
    query={"term": {"event.dataset": "suricata.alert"}},
    fields={"risk.score": 70},
)
```

Implementation note:

- this currently performs a controlled scan plus per-document updates rather than blindly delegating to raw Elasticsearch `_update_by_query`

Why that matters:

- it keeps audit behavior per document consistent
- it keeps rollback information field-precise per document
- it makes behavior easier to reason about in script and UI summaries

Internal model:

```text
scan matches
   -> for each doc
      -> call update_doc(...)
         -> compute before-state
         -> mutate
         -> audit
```

Tradeoff:

- more Python-side orchestration than a pure server-side `_update_by_query`
- but much better consistency with the audit/rollback model

### `ctx.remove_by_query(index, query, fields, batch_size=500)`

Purpose:

- remove the same set of fields from all matching docs

Example:

```python
ctx.remove_by_query(
    index="soc-alerts",
    query={"term": {"triage.status": "temporary"}},
    fields=["triage.status", "triage.temp_note"],
)
```

Internal model:

```text
scan matches
   -> for each doc
      -> call remove_fields(...)
         -> compute before-state
         -> mutate
         -> audit
```

## Index Methods

### `ctx.create_index(index, mappings=None, settings=None)`

Example:

```python
ctx.create_index(
    index="enrichment-test",
    mappings={
        "properties": {
            "@timestamp": {"type": "date"},
            "message": {"type": "text"},
            "risk.score": {"type": "integer"},
        }
    },
)
```

Internal behavior:

- honors dry-run mode
- forwards mappings/settings if provided
- delegates to Elasticsearch indices.create

Typical use cases:

- create a scratch index for testing
- prepare a derived index for future workflows
- experiment with mappings from inside an enrichment script

### `ctx.delete_index(index)`

Example:

```python
ctx.delete_index("enrichment-test")
```

Operational warning:

- deleting an index is far broader than deleting one document

That is why `delete_index` should generally be thought of as an advanced or operational method, not a routine enrichment method.

## Raw Client

### `ctx.raw`

Example:

```python
info = ctx.raw.info()
```

Use this when the wrapper does not provide what you need.

Prefer wrapper methods for normal mutations so audit/rollback behavior stays coherent.

Good reasons to use `raw`:

- you need an Elasticsearch API the wrapper does not expose
- you are doing a read-only query that is more specialized than `search` or `scan`

Less good reasons to use `raw`:

- habit from working directly with Elasticsearch elsewhere
- bypassing wrapper semantics for common document mutations

## Dry Run Behavior

If the runner launches the script with dry-run enabled:

- read methods still query normally
- write methods return `would_*` style summaries instead of mutating
- audit records are not written for skipped writes

This is very useful for validating scope before a batch run.

Think of dry run as “tell me what would happen, but do not change the target cluster.”

This is especially useful when:

- a query may match more documents than expected
- you are testing a new enrichment for the first time
- you are wiring a UI flow and want safe previews

## What Gets Audited And What Does Not

The wrapper writes audit records for its mutation paths.

Current practical model:

- `update_doc` and `remove_fields` produce rollback-capable audit records
- `update_by_query` and `remove_by_query` inherit that behavior through per-document calls
- `index_doc` and `delete_doc` are audited, but currently marked not rollback-supported

Why this split exists:

- field-level rollback is strong for field mutations
- full document recreation after a delete is a different and more complex problem

## Example Patterns

### Pattern: single selected alert

```python
from soc_enrich import EnrichmentContext

ENRICHMENT_META = {
    "type": "play_single",
    "name": "Mark Reviewed",
    "description": "Marks one alert as reviewed.",
}

def run(ctx: EnrichmentContext, params: dict) -> None:
    doc = ctx.get(index="soc-alerts", id=params["_id"])
    ctx.update_doc(
        index=doc["_index"],
        id=doc["_id"],
        fields={"triage.status": "reviewed"},
)
```

Why this pattern is good:

- the UI only needs to supply `_id`
- the script owns the index/alias choice
- the script can inspect the document before mutating it

### Pattern: broad batch update

```python
from soc_enrich import EnrichmentContext

ENRICHMENT_META = {
    "type": "play_batch",
    "name": "Add Risk Score",
    "description": "Adds the same risk score to all matching docs.",
}

def run(ctx: EnrichmentContext) -> None:
    ctx.update_by_query(
        index="soc-alerts",
        query={"term": {"event.dataset": "suricata.alert"}},
        fields={"risk.score": 50},
)
```

Why this pattern is good:

- very simple when every matching document should get the same field set
- audit/rollback behavior stays consistent
- script stays short and readable

### Pattern: conditional scan

```python
from soc_enrich import EnrichmentContext

ENRICHMENT_META = {
    "type": "play_batch",
    "name": "Conditional Risk",
    "description": "Sets fields only when a per-doc condition matches.",
}

def run(ctx: EnrichmentContext) -> None:
    for doc in ctx.scan(index="soc-alerts", query={"match_all": {}}):
        if doc.get("alert", {}).get("severity") == 1:
            ctx.update_doc(index=doc["_index"], id=doc["_id"], fields={"risk.score": 95})
```

Why this pattern is good:

- useful when the logic depends on per-document inspection
- avoids trying to cram complex branching into one query

Tradeoff:

- more Python-side looping
- potentially slower for very large match sets

### Pattern: cleanup fields

```python
from soc_enrich import EnrichmentContext

ENRICHMENT_META = {
    "type": "play_batch",
    "name": "Cleanup Fields",
    "description": "Removes stale fields.",
}

def run(ctx: EnrichmentContext) -> None:
    ctx.remove_by_query(
        index="soc-alerts",
        query={"term": {"triage.status": "temporary"}},
        fields=["triage.status", "triage.temp_note"],
    )
```

Why this pattern is good:

- explicit field removal
- rollback-capable
- easy to reason about later

## Common Mistakes To Avoid

### Mistake 1: using `index_doc` when you mean `update_doc`

If the target document already exists and you mean “change fields on it”, use `update_doc`, not `index_doc`.

### Mistake 2: using `search(size=...)` for huge result sets

If you mean “process many or all matches”, use `scan`.

### Mistake 3: using `delete_doc` to remove enrichment state

Most of the time you want `remove_fields`, not full document deletion.

### Mistake 4: jumping straight to `ctx.raw` for normal work

The wrapper exists for a reason. Use `raw` when you need a missing API, not as the default habit.

## Best Practices

1. declare `ENRICHMENT_META`
2. use `run(ctx)` unless runtime params are actually needed
3. prefer wrapper methods over `ctx.raw` for normal mutations
4. use `scan` for large result sets instead of huge `search(size=...)`
5. use dry-run before a new wide batch enrichment
6. treat `delete_doc` as a sharp tool because rollback does not restore deletes in v1

## Related Files

## Related Files

- `docs/08-enrichment.md`
- `core/enrich/context.py`
- `core/enrich/runner.py`
- `core/enrich/scripts.py`
- `core/enrich/audit.py`
- `core/enrich/rollback.py`
- `data/enrichments/config/enrichments.yml`
- `data/enrichments/config/clusters.yml`

## Best Short Mental Model

If you want one sentence to carry around in your head, use this:

```text
EnrichmentContext is a small, auditable, rollback-aware wrapper over common Elasticsearch operations.
```

That is the practical meaning of the SDK.
