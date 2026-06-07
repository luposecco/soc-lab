# Enrichment System

This document explains the enrichment subsystem as a system.

It is about architecture, boundaries, configuration, execution flow, and safety.

For the method-by-method SDK reference, read:

- `docs/10-enrichment-sdk-reference.md`

For the lower-level internal implementation walkthrough, read:

- `docs/11-enrichment-internals.md`

## Why The Enrichment Subsystem Exists

SOC Lab already stores and searches data in Elasticsearch. That alone is not enough for realistic analyst workflows.

In practice, analysts and detection engineers often need to do things like:

- add triage fields to matching alerts
- set risk scores
- annotate documents with investigation context
- clean up temporary fields
- write new derived documents
- target different Elasticsearch environments without rewriting all connection logic

The enrichment subsystem exists so a user can write Python logic for that work while SOC Lab handles the surrounding concerns.

Those surrounding concerns include:

- how to connect to the correct cluster
- how to expose a simpler script-facing API
- how to keep mutation behavior auditable
- how to support rollback where reasonable
- how to classify enrichments for the UI and future schedulers

## System Model

At the highest level, the subsystem looks like this:

```text
configured enrichment entry
   -> script loader
   -> cluster manager
   -> enrichment context
   -> user script
   -> target Elasticsearch cluster
   -> central audit index in lab cluster
```

That same flow from a UI/API perspective:

```text
UI or API run request
   -> core.enrich.runner
   -> choose allowed target cluster(s)
   -> import user script
   -> create EnrichmentContext
   -> call run(ctx) or run(ctx, params)
   -> write per-document audit records for supported mutations
```

## File Layout

The enrichment subsystem spans three logical areas.

### Public script-author import surface

```text
soc_enrich/
└── __init__.py
```

Purpose:

- provide a clean, stable import path for scripts

### Internal implementation

```text
core/enrich/
├── audit.py
├── clusters.py
├── context.py
├── rollback.py
├── runner.py
├── scripts.py
└── utils.py
```

Purpose:

- implement the actual runtime behavior

### User content and operator config

```text
data/enrichments/
├── config/
│   ├── clusters.yml
│   └── enrichments.yml
└── scripts/
    └── *.py
```

Purpose:

- store cluster definitions
- store configured enrichment entries
- store user-written enrichment scripts

## Public Script Contract

User scripts live under:

```text
data/enrichments/scripts/
```

They import the SDK like this:

```python
from soc_enrich import EnrichmentContext
```

They may declare metadata like this:

```python
ENRICHMENT_META = {
    "type": "play_batch",
    "name": "Example Risk",
    "description": "Adds a risk score to severe alerts missing one.",
}
```

They must define either:

```python
def run(ctx):
    ...
```

or:

```python
def run(ctx, params):
    ...
```

The second form exists so the surrounding system can pass runtime values into a script, for example in a GUI-driven single-item flow.

## Meaning Of Enrichment Types

Current allowed metadata types are:

- `play_single`
- `play_batch`
- `play_periodic`

These are mainly classification labels for the surrounding system.

Important clarification:

they are **not** currently three different SDK classes.

Instead, they mean roughly:

- `play_single`: this enrichment conceptually acts on one chosen thing
- `play_batch`: this enrichment conceptually acts on many documents
- `play_periodic`: this enrichment conceptually belongs on a schedule

The SDK object is still `EnrichmentContext` in all three cases.

## Cluster Routing Model

Cluster definitions live in:

```text
data/enrichments/config/clusters.yml
```

### Implicit `lab`

The system always provides a built-in `lab` cluster.

That means enrichment can work even if the user has configured no extra external clusters.

By default, `lab` points at the main SOC Lab Elasticsearch URL.

### Additional clusters

Additional named clusters can be declared in YAML.

These definitions tell SOC Lab:

- what hosts to connect to
- what auth style to use
- which environment variable holds the secret if auth is needed

### Why cluster routing is in SOC Lab instead of in each script

Without a cluster manager, every script would need to:

- parse config itself
- decide where secrets come from
- create its own Elasticsearch clients
- duplicate connection logic

That would make scripts harder to write and harder to review.

## Enrichment Entry Config Model

Configured enrichment entries live in:

```text
data/enrichments/config/enrichments.yml
```

Current important concepts include:

- `script`
- `targets`
- `enabled`
- `schedule`

### `script`

Relative path to the Python file to import.

### `targets`

Allowed target cluster names.

This is an allowlist, not just a default.

If a caller requests a cluster outside the configured targets, the runner rejects the execution.

### `enabled`

Simple operational switch for whether the configured entry should be runnable.

### `schedule`

Metadata for periodic runs.

The scheduler worker is not implemented yet, but the model already needs a place to express timing intent.

## `EnrichmentContext` Conceptually

`EnrichmentContext` is the object a script receives.

You can think of it as four things at once:

1. an Elasticsearch client wrapper
2. a carrier for run metadata
3. a mutation audit hook
4. a dry-run control point

That combination is what makes it useful.

If it were only a raw Elasticsearch client, scripts would become repetitive and unsafe.

If it were too abstract, script authors would lose control.

The current design tries to sit in the middle.

## Why The SDK Uses A Wrapper At All

The wrapper exists because normal enrichment code repeats the same patterns constantly.

Examples:

- read a document
- update a few fields
- preserve enough state for later rollback
- know which cluster is being targeted
- produce a run summary

Those are not the most interesting parts of enrichment logic. They are the plumbing.

The wrapper moves that plumbing into SOC Lab so the script can stay focused on enrichment logic.

## Audit Model At A High Level

Mutation audit records are written to the **central lab cluster**, not to every target cluster.

Why central storage:

- one place to inspect run history
- one place to drive rollback logic
- one place for the UI to read historical run summaries

This also means the target cluster does not need to host the audit trail itself in order for SOC Lab to reason about changes.

## Rollback Model At A High Level

Rollback is currently field-level, not full-document snapshot based.

That choice was made because field-level rollback:

- is smaller
- is safer for in-place enrichment
- is less likely to clobber unrelated later document changes
- maps well to the dominant use case of “set or remove some fields”

Tradeoff:

- document deletes are not restored in v1
- full-document reversion is not the current model

## Safety Model

The safety model of enrichment is not “nothing can go wrong.”

The safety model is:

- make common mutations explicit
- keep those mutations auditable
- keep rollback feasible for field-level changes
- refuse rollback when a later run changed the same fields unless the user forces it

This is a pragmatic engineering safety model, not a perfect transactional model.

## Networking And Data Path For Enrichment

The enrichment path is important because it crosses cluster boundaries.

```text
Dash / API
   |
   v
runner loads config
   |
   +-> chooses target cluster(s)
   +-> imports script
   +-> creates EnrichmentContext
   v
script runs against target ES cluster
   |
   +-> reads and writes target docs there
   v
audit record written separately to central lab cluster
```

This means a single logical enrichment run may have two Elasticsearch effects:

1. real document mutations in the selected target cluster
2. audit documents in the lab cluster

That split is intentional.

## What The Subsystem Is Good At Today

It is good at:

- running script-based enrichments against one or more configured clusters
- exposing a smaller script-facing API than the raw Elasticsearch client
- auditing field-level document mutations
- rolling back field-level updates and removals
- distinguishing “field missing” from “field exists with null” for rollback correctness

## What The Subsystem Does Not Fully Do Yet

It does **not** yet fully implement:

- periodic scheduler worker execution
- full GUI single-item runtime-param flows end to end
- rollback restoration for deleted documents
- a much larger high-level enrichment DSL

Those are future directions, not current guarantees.

## What A New Developer Should Read Next

If you want architecture and runtime behavior:

- `docs/11-enrichment-internals.md`

If you want script-author usage and method details:

- `docs/10-enrichment-sdk-reference.md`

If you want current code:

- `core/enrich/context.py`
- `core/enrich/runner.py`
- `core/enrich/audit.py`
- `core/enrich/rollback.py`

## One-Sentence Mental Model

If you want one sentence to carry around in your head, use this:

```text
The enrichment subsystem lets scripts mutate Elasticsearch through a smaller wrapper while SOC Lab handles routing, audit, and rollback-aware safety.
```
