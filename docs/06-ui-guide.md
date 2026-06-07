# UI Guide

This document explains the Dash UI structure, how pages are organized, and how the UI talks to the API.

## UI Architecture

SOC Lab's web UI is a Dash app.

Important architectural rule:

the Dash app is a presentation layer, not the system control layer.

It should not directly manipulate Docker, Elasticsearch, or files. It should call FastAPI.

Diagram:

```text
Dash page / callback
   -> ui.helpers.api_get/api_post/api_delete
   -> FastAPI endpoint
   -> core service logic
```

This boundary is one of the most important design choices in the current repo.

It means the UI should be thought of as:

- a presentation layer
- a page-state layer
- a polling and interaction layer

But not as the final authority over backend behavior.

## Main Entry Point

File:

- `ui/app.py`

Responsibilities:

- create the Dash app
- enable multi-page routing
- define the persistent shell layout
- render the sidebar
- show global health indicators such as alert count and stack state

The shell is the frame around all pages.

That matters because every page is rendered *inside* this shell. So navigation, sidebar state, and some polling behavior are global concerns, not page-local concerns.

## Shared UI Helpers

File:

- `ui/helpers.py`

This file is important because it keeps the pages from duplicating common patterns.

### API helpers

- `api_get(path)`
- `api_post(path, body)`
- `api_delete(path)`

These wrap `httpx` calls to the FastAPI backend.

They generally return:

- decoded JSON on success
- `{"error": ...}` on failure

That failure contract shapes how most page callbacks are written.

This is one of the quiet structural patterns of the UI codebase: callbacks often do not raise on backend failure, they render around returned `{"error": ...}` shapes.

### Rendering helpers

Common helpers include things like:

- top bars
- metric cards
- tags and badges
- error banners
- terminal-style log rendering

This helps pages stay visually consistent.

## Styling

File:

- `ui/assets/style.css`

This file defines the base visual language used across pages.

Important reusable classes include:

- `.card`
- `.metrics`
- `.tbl`
- `.tag`
- `.terminal`
- `.topbar-btn`

A lot of the UI consistency comes from these shared primitives rather than page-specific CSS.

## Page Registration Model

Each page under `ui/pages/` typically does:

```python
dash.register_page(__name__, path="...")
```

That means Dash auto-discovers pages and plugs them into the multi-page app.

## Common Page Pattern

Most pages follow a recurring shape.

```text
layout()
  -> make initial api_get calls
  -> render topbar, metrics, cards, tables

callbacks
  -> respond to buttons, filters, intervals
  -> call api_get/api_post/api_delete
  -> transform backend JSON into Dash components
```

This is worth internalizing because it explains why so many pages feel structurally similar.

The repo is intentionally using a repeatable page pattern instead of inventing a different architecture for each feature.

This pattern is simple and effective, but it means initial page load often depends on synchronous server-side API requests.

## Important Pages

### Overview page

File:

- `ui/pages/overview.py`

Purpose:

- high-level dashboard
- summary metrics
- recent alerts
- service health snapshot
- rules status snapshot

Use this page when you want the system state at a glance.

It is effectively the “is the lab broadly alive and doing something sensible?” page.

### Alerts page

File:

- `ui/pages/alerts.py`

Purpose:

- alert list
- severity and dataset filtering
- timeline and alert stats

This page is a search and triage surface over `soc-alerts`.

That is an important subtlety: it is searching the *unified alert alias*, not just one raw index.

### Network page

File:

- `ui/pages/network.py`

Purpose:

- explore Suricata flow records
- summarize protocol and host behavior

This page is useful for traffic-oriented rather than alert-oriented browsing.

### Stack page

File:

- `ui/pages/stack.py`

Purpose:

- control services
- inspect logs
- inspect watcher state

This page acts like an operations dashboard and control panel.

It is one of the clearest expressions of the UI's relationship to FastAPI: the page is a controller that asks the API to do real system work.

### Rules page

File:

- `ui/pages/rules.py`

Purpose:

- browse Suricata, Sigma, and ElastAlert rules
- edit rule files
- validate and compile

This is one of the most complex UI pages because it combines inventory, editing, validation, and compilation behavior.

When debugging rules-page issues, it helps to mentally separate the page into four mini-apps:

- inventory browser
- editor
- validation client
- compile/status surface

### Aliases page

File:

- `ui/pages/aliases.py`

Purpose:

- alias inventory
- managed-template visibility
- create/delete aliases
- explain alias composition in a more operator-friendly way

This is the richer alias management page.

It is also one of the most documentation-heavy pages in spirit: it tries to make a conceptually tricky Elasticsearch feature easier to inspect visually.

### Settings page

File:

- `ui/pages/settings.py`

Purpose:

- simpler alias/index management interface

This appears to be a simpler or older admin-oriented page compared with the richer `aliases` page.

### Logs / ingest page

File:

- `ui/pages/ingest.py`

Purpose:

- upload logs
- choose or upload pipelines
- trigger pipeline generation
- inspect available pipeline catalogs

This page is effectively a front-end for a decision engine in `core/ingest/upload.py`.

### PCAP capture page

File:

- `ui/pages/capture_pcap.py`

Purpose:

- choose or upload a PCAP
- start replay
- poll replay status
- view replay history and logs

### Live capture page

File:

- `ui/pages/capture_live.py`

Purpose:

- start or stop live capture
- choose interface and rotation timing
- inspect session history and live output

### Enrichment page

File:

- `ui/pages/enrichment.py`

Purpose:

- inspect enrichment targets and jobs
- run enrichments
- do dry runs
- inspect run history
- trigger rollback

This page is currently more of an operator control surface than a full script-authoring experience. It lists configured enrichments and drives execution, but does not yet expose the full future richness of single-item runtime-param flows.

## Dash Patterns Used In This Repo

### Interval polling

Many pages use `dcc.Interval` to poll the API.

Why:

- simple to implement
- good enough for lab-scale operations
- avoids requiring websockets or server push

Tradeoff:

- less efficient than push-based updates
- but much simpler operationally

This tradeoff is very intentional in a local-lab tool. Simplicity and debuggability often beat protocol sophistication here.

### `dcc.Store`

`dcc.Store` is used for client-side state that spans multiple callbacks.

Examples:

- selected alias
- selected service
- selected rule path
- replay state
- live capture state

This avoids trying to encode all workflow state in visible components.

That matters because many workflows are multi-step and asynchronous. Without local stores, the callbacks would become much harder to reason about.

### Pattern-matching IDs

Pages with repeated rows or cards often use pattern-matching IDs.

Examples:

- service action buttons
- enrichment run buttons
- rollback buttons

This lets one callback handle many repeated controls.

This is a major reason the UI does not explode into one callback per row or per card.

### Helper render functions

Pages often define private functions like:

- `_row(...)`
- `_table(...)`
- `_metrics(...)`
- `_card(...)`

These keep callback bodies from turning into huge blocks of HTML construction.

## UI To API Interaction Model

The UI does not call `core/` directly.

It does this instead:

```text
page callback
   -> api_get/api_post/api_delete
   -> FastAPI route
   -> core service or route-local backend logic
```

One practical consequence of this model is that most state-changing operations are visible in FastAPI logs and API responses even if the page itself is quiet about the details.

This is important because it means:

- FastAPI is the boundary for validation and side effects
- the UI can be replaced later without rewriting the service layer
- the API becomes reusable outside Dash

## Contributor Guidance

When changing the UI:

1. do not add backend logic into Dash callbacks if it belongs in the API
2. reuse `ui/helpers.py` where possible
3. keep page-local render helpers small and named clearly
4. if multiple pages need the same visual pattern, promote it into helpers or shared CSS
5. if a page gets too dense, split rendering logic into more small functions before adding more callbacks

And one more practical rule:

6. if you are tempted to directly call Docker, Elasticsearch, or the filesystem from a page callback, stop and move that behavior behind FastAPI instead

## Practical Mental Model

Think of each page as:

```text
view model + polling + backend calls + reusable UI blocks
```

If you keep the API boundary clean, the UI remains much easier to reason about and maintain.
