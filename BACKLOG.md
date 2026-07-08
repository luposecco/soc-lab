# Backlog

## Enrichment

### Bugs

- **Rollback ops count always 0** — `render_runs_table` reads `docs_updated + docs_created + docs_deleted` but `audit.list_runs()` returns `operations` (total audit record count). Fix: either rename the key in `list_runs()` output to match, or read the right field in `render_runs_table`.

- **Cluster node edit loses auth config** — `ClusterDef.to_dict()` returns only `name`, `mode`, `hosts`, `auth_type`. Auth env var names (`auth_env`, `auth_user`, `auth_pass_env`) are not included, so editing an existing node blanks out those fields. Fix: add them to `to_dict()` and expose via `/api/enrich/clusters`.

### Missing features

- **Per-alert enrichment trigger** — `on_log: true` enrichments have no UI entry point. Intended flow: button next to each alert on the alerts page → opens a picker showing all `on_log` enrichments → user picks one → calls `POST /api/enrich/run/{name}` with `params={"_id": alert_id}`. Nothing on the alerts page touches enrichments yet.

- **No enrichment history per alert** — no way to see which runs have touched a specific document. Would need a reverse lookup in the audit index by `doc_id`, surfaced either on the alerts page or in a detail drawer.


### Completed

- **Scheduler** — implemented a FastAPI-managed background scheduler that executes enabled enrichments with interval schedules like `30s`, `15m`, `2h`, and `1d`.

- **Script path dropdown / validation** — the edit panel script path now uses the scripts list from `GET /api/enrich/scripts`; API script paths are normalized, restricted to `data/enrichments/scripts`, and required to end in `.py`.

- **Schedule format validation** — schedules are validated in the UI before save and in the API/core before persistence or execution.

## Other

- nothing tracked yet
