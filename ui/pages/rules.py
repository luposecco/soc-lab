from __future__ import annotations

import time
from urllib.parse import quote as _url_quote

import dash
from dash import ALL, Input, Output, State, callback, ctx, dcc, html

from ui.helpers import api_delete, api_get, api_post, error_banner, lrow, ltable, topbar
from ui.pages.rules_editor import editor_card as _editor_card, metrics_row as _metrics_row, rules_table as _rules_table

dash.register_page(__name__, path="/rules")

_TYPE_OPTS = [{"label": "All types", "value": ""}, {"label": "Sigma", "value": "sigma"}, {"label": "Suricata", "value": "suricata"}, {"label": "ElastAlert", "value": "elastalert"}]
_STATUS_OPTS = [{"label": "All statuses", "value": ""}, {"label": "Enabled", "value": "enabled"}, {"label": "Disabled", "value": "disabled"}, {"label": "Error", "value": "error"}]
_SOURCE_OPTS = [{"label": "All sources", "value": ""}, {"label": "Local", "value": "local"}, {"label": "ET / imported", "value": "docker"}]
_GUI_SURI_DIR = "data/rules/suricata/gui"
_GUI_SIGMA_DIR = "data/rules/sigma/gui"


def _load_sigma_elastalert() -> dict[str, list]:
    return {rule_type: (resp.get("files", []) if isinstance(resp := api_get(f"/api/rules/files?type={rule_type}"), dict) else []) for rule_type in ("sigma", "elastalert")}


def _editor_state_payload(path: str = "", name: str = "", content: str = "", readonly: bool = False) -> dict:
    return {"path": path, "name": name, "content": content, "readonly": readonly, "saved_at": time.time()}


def layout() -> html.Div:
    return html.Div([
        topbar("Rules", dcc.Interval(id="rules-poll", interval=60_000, n_intervals=0), html.Button([html.I(className="ti ti-refresh", style={"fontSize": "13px"}), " Refresh"], id="rules-refresh-btn", className="topbar-btn", n_clicks=0), html.Button([html.I(className="ti ti-player-play", style={"fontSize": "13px"}), " Compile"], id="rules-compile-btn", className="topbar-btn primary", n_clicks=0)),
        html.Div(id="rules-banner"),
        html.Div(className="content", children=[
            html.Div(id="rules-metrics", children=_metrics_row(0, 0, 0), style={"flexShrink": "0"}),
            html.Div(className="filterbar", style={"marginBottom": "4px", "flexShrink": "0"}, children=[
                html.I(className="ti ti-search", style={"fontSize": "14px", "color": "#888780", "flexShrink": "0"}),
                dcc.Input(id="rules-search", placeholder="Search rules…", debounce=True, className="search-input", style={"flex": "1"}),
                dcc.Dropdown(id="rules-type-filter", options=_TYPE_OPTS, value="", clearable=False, style={"width": "140px", "fontSize": "12px"}),
                dcc.Dropdown(id="rules-status-filter", options=_STATUS_OPTS, value="", clearable=False, style={"width": "140px", "fontSize": "12px"}),
                dcc.Dropdown(id="rules-source-filter", options=_SOURCE_OPTS, value="", clearable=False, style={"width": "150px", "fontSize": "12px"}),
                dcc.Upload(id="rules-import-upload", children=html.Button([html.I(className="ti ti-file-import", style={"fontSize": "12px"}), " Import"], className="topbar-btn"), multiple=False),
                html.Button([html.I(className="ti ti-plus", style={"fontSize": "12px"}), " New rule"], id="rules-new-btn", className="topbar-btn primary", n_clicks=0),
            ]),
            html.Div(style={**lrow(), "height": "clamp(500px, calc(100vh - 220px), 900px)", "minHeight": "500px", "marginBottom": "20px"}, children=[
                html.Div(className="card", style=ltable(fill=True, min_h=500), children=[html.Div(className="card-header", children=[html.Span("Rules", className="card-title"), html.Span(id="rules-count-label", style={"fontSize": "11px", "color": "#888780"})]), html.Div(id="rules-list", children=_rules_table([]), className="table-panel-body")]),
                html.Div(id="rules-editor-wrap", style={"display": "flex", "flexDirection": "column", "minHeight": "0"}, children=_editor_card()),
            ]),
        ]),
        dcc.Store(id="rules-selected-path", data=""), dcc.Store(id="rules-active-tab", data=""), dcc.Store(id="rules-editor-store", storage_type="local"), dcc.Store(id="rules-hydrated", storage_type="memory"),
    ])


@callback(Output("rules-list", "children"), Output("rules-count-label", "children"), Output("rules-metrics", "children"), Output("rules-banner", "children"), Input("rules-poll", "n_intervals"), Input("rules-refresh-btn", "n_clicks"), Input("rules-compile-btn", "n_clicks"), Input("rules-search", "value"), Input("rules-type-filter", "value"), Input("rules-status-filter", "value"), Input("rules-source-filter", "value"), prevent_initial_call=False)
def _update_list(_poll, _refresh, _compile, search, type_filter, status_filter, source_filter):
    banner: list = []
    if ctx.triggered_id == "rules-compile-btn" and (_compile or 0) > 0:
        result = api_post("/api/rules/compile")
        if result.get("error"):
            banner = [error_banner(f"Compile failed: {result['error']}")]
        else:
            ok = result.get("suricata", {}).get("ok", False) and result.get("sigma", {}).get("ok", False) and not result.get("suricata", {}).get("error_count", 0)
            banner = [html.Div("Compile successful", className="banner ok") if ok else error_banner("Compile completed with errors")]

    q = (search or "").strip()
    items: list[dict] = []
    if not type_filter or type_filter == "suricata":
        suri_limit = 50 if q else 20
        params = f"/api/rules/suricata-rules?limit={suri_limit}"
        if q:
            params += f"&q={_url_quote(q, safe='')}"
        if status_filter:
            params += f"&status={status_filter}"
        if source_filter:
            params += f"&source={source_filter}"
        suri_resp = api_get(params)
        if isinstance(suri_resp, dict) and not suri_resp.get("error"):
            items.extend(suri_resp.get("rules", []))

    sigma_files: list[dict] = []
    elastalert_files: list[dict] = []
    for rule_type in ("sigma", "elastalert"):
        if (type_filter and type_filter != rule_type) or source_filter == "docker":
            continue
        resp = api_get(f"/api/rules/files?type={rule_type}")
        files = resp.get("files", []) if isinstance(resp, dict) else []
        if q:
            files = [item for item in files if q.lower() in item.get("name", "").lower() or q.lower() in item.get("file", "").lower()]
        if source_filter:
            files = [item for item in files if item.get("source") == source_filter]
        if status_filter:
            files = [] if status_filter == "disabled" else [item for item in files if item.get("status") == status_filter]
        if rule_type == "sigma":
            sigma_files = files
        else:
            elastalert_files = files
        items.extend(files)

    suri_count_status = "disabled" if status_filter == "disabled" else "error" if status_filter == "error" else "all" if not status_filter else "enabled"
    suri_count_resp = api_get(f"/api/rules/suricata-count?status={suri_count_status}")
    suri_total = suri_count_resp.get("count", 0) if isinstance(suri_count_resp, dict) else 0
    if not type_filter and not q and not status_filter and not source_filter:
        loaded = _load_sigma_elastalert()
        sigma_files, elastalert_files = loaded["sigma"], loaded["elastalert"]
    status_data = api_get("/api/rules/status")
    if not isinstance(status_data, dict):
        status_data = {}
    suri_error_resp = api_get("/api/rules/suricata-rules?limit=1&status=error")
    suricata_rule_error = bool(isinstance(suri_error_resp, dict) and suri_error_resp.get("rules"))
    total_hint = len(items) if len(items) < suri_total else None
    return _rules_table(items, total=total_hint), f"{len(items)} shown · search to filter", _metrics_row(len(sigma_files), suri_total, len(elastalert_files), status_data, suricata_rule_error), banner


@callback(Output("rules-editor-wrap", "children"), Output("rules-selected-path", "data"), Output("rules-editor-store", "data"), Input({"type": "rules-edit-btn", "file": ALL}, "n_clicks"), prevent_initial_call=True)
def _load_rule(n_clicks):
    if not ctx.triggered_id or not any(n_clicks):
        return dash.no_update, dash.no_update, dash.no_update
    path = ctx.triggered_id["file"]
    resp = api_get(f"/api/rules/file?path={_url_quote(path, safe='')}")
    if resp.get("error"):
        return _editor_card(), "", _editor_state_payload()
    content = resp.get("content", "")
    name = ""
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith(("title:", "name:")):
            name = stripped.split(":", 1)[1].strip()
            break
        if "msg:" in stripped:
            name = stripped.split("msg:", 1)[1].split(";")[0].strip().strip('"')
            break
    readonly = resp.get("readonly", False)
    return _editor_card(path=path, name=name, content=content, readonly=readonly), path, _editor_state_payload(path, name, content, readonly)


@callback(Output("rules-banner", "children", allow_duplicate=True), Output("rules-editor-wrap", "children", allow_duplicate=True), Output("rules-editor-store", "data", allow_duplicate=True), Input("rules-save-btn", "n_clicks"), State("rules-selected-path", "data"), State("rules-editor-name", "value"), State("rules-editor-content", "value"), State("rules-type-filter", "value"), prevent_initial_call=True)
def _save_rule(_n, path, name, content, type_filter):
    if not _n:
        return dash.no_update, dash.no_update, dash.no_update
    if not content:
        return [error_banner("Editor is empty")], dash.no_update, dash.no_update
    if path and path.startswith("docker:"):
        return [error_banner("Built-in ET rules are read-only and cannot be saved")], dash.no_update, dash.no_update
    tab = ("suricata" if path and ("#" in path or path.endswith(".rules") or "/suricata/" in path) else "") or type_filter or "sigma"
    stem = (name or "new-rule").lower().replace(" ", "-").replace("/", "-")
    if tab == "suricata" and path and "#" in path:
        result = api_post("/api/rules/suricata-rule", {"path": path, "content": content})
        if result.get("error"):
            return [error_banner(f"Save failed: {result['error']}")], dash.no_update, dash.no_update
        base, _, ref = path.partition("#")
        suffix = f" (line {int(ref) + 1})" if ref.isdigit() else ""
        return [html.Div(f"Updated: {base}{suffix}", className="banner ok")], _editor_card(path=path, name=name, content=content), _editor_state_payload(path, name or "", content, False)
    if not path:
        path = f"{_GUI_SURI_DIR}/{stem}.rules" if tab == "suricata" else f"{_GUI_SIGMA_DIR}/{stem}.yml" if tab == "sigma" else f"data/rules/{tab}/{stem}.yml"
    result = api_post("/api/rules/file" if not (tab == "suricata" and "#" in path) else "/api/rules/suricata-rule", {"path": path, "content": content})
    if result.get("error"):
        return [error_banner(f"Save failed: {result['error']}")], dash.no_update, dash.no_update
    compile_result = api_post("/api/rules/compile")
    if compile_result.get("error"):
        banner = [html.Div(f"Saved — compile error: {compile_result['error']}", className="banner err")]
    else:
        ok = compile_result.get("suricata", {}).get("ok", False) and compile_result.get("sigma", {}).get("ok", False) and not compile_result.get("suricata", {}).get("error_count", 0)
        banner = [html.Div(f"Saved & compiled: {path}", className="banner ok" if ok else "banner err")]
    return banner, _editor_card(path=path, name=name, content=content), _editor_state_payload(path, name or "", content, False)


@callback(Output("rules-banner", "children", allow_duplicate=True), Input("rules-validate-btn", "n_clicks"), State("rules-editor-content", "value"), State("rules-selected-path", "data"), prevent_initial_call=True)
def _validate_rule(_n, content, path):
    if not _n:
        return dash.no_update
    if not content or not content.strip():
        return [error_banner("Editor is empty")]
    rule_type = "suricata" if (path or "").endswith(".rules") else "yaml" if (path or "").endswith((".yml", ".yaml")) else ""
    result = api_post("/api/rules/validate", {"content": content, "type": rule_type})
    if result.get("error"):
        return [error_banner(f"Validation error: {result['error']}")]
    if result.get("ok"):
        return [html.Div(f"Valid {result.get('type', rule_type or 'rule')} rule", className="banner ok")]
    errors = result.get("errors", [])
    return [error_banner(f"Invalid: {'; '.join(errors[:3]) if errors else 'Validation failed'}")]


@callback(Output("rules-banner", "children", allow_duplicate=True), Output("rules-editor-wrap", "children", allow_duplicate=True), Output("rules-selected-path", "data", allow_duplicate=True), Output("rules-editor-store", "data", allow_duplicate=True), Input("rules-delete-btn", "n_clicks"), State("rules-selected-path", "data"), prevent_initial_call=True)
def _delete_rule(_n, path):
    if not _n:
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update
    if not path:
        return [error_banner("No file selected")], dash.no_update, dash.no_update, dash.no_update
    if path.startswith("docker:"):
        return [error_banner("Built-in ET rules cannot be deleted")], dash.no_update, dash.no_update, dash.no_update
    base = path.split("#")[0]
    result = api_delete(f"/api/rules/file?path={_url_quote(base, safe='')}")
    if result.get("error"):
        return [error_banner(f"Delete failed: {result['error']}")], dash.no_update, path, dash.no_update
    return [html.Div(f"Deleted: {base}", className="banner ok")], _editor_card(), "", _editor_state_payload()


@callback(Output("rules-editor-wrap", "children", allow_duplicate=True), Output("rules-selected-path", "data", allow_duplicate=True), Output("rules-editor-store", "data", allow_duplicate=True), Input("rules-new-btn", "n_clicks"), prevent_initial_call=True)
def _new_rule(_n):
    return _editor_card(), "", _editor_state_payload()


@callback(
    Output("rules-editor-wrap", "children", allow_duplicate=True),
    Output("rules-selected-path", "data", allow_duplicate=True),
    Output("rules-editor-store", "data", allow_duplicate=True),
    Input("rules-clear-draft-btn", "n_clicks"),
    prevent_initial_call=True,
)
def _clear_rule_draft(_n):
    if not _n:
        return dash.no_update, dash.no_update, dash.no_update
    return _editor_card(), "", _editor_state_payload()


@callback(Output("rules-banner", "children", allow_duplicate=True), Output("rules-editor-wrap", "children", allow_duplicate=True), Output("rules-selected-path", "data", allow_duplicate=True), Output("rules-editor-store", "data", allow_duplicate=True), Input("rules-import-upload", "contents"), State("rules-import-upload", "filename"), State("rules-type-filter", "value"), prevent_initial_call=True)
def _import_rule(contents, filename, type_filter):
    if not contents or not filename:
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update
    import base64
    data = base64.b64decode(contents.split(",", 1)[-1]).decode("utf-8", errors="replace")
    tab = type_filter or "sigma"
    path = f"{_GUI_SURI_DIR}/{filename}" if tab == "suricata" else f"{_GUI_SIGMA_DIR}/{filename}" if tab == "sigma" else f"data/rules/{tab}/{filename}"
    result = api_post("/api/rules/file", {"path": path, "content": data})
    if result.get("error"):
        return [error_banner(f"Import failed: {result['error']}")], dash.no_update, dash.no_update, dash.no_update
    return [html.Div(f"Imported: {path}", className="banner ok")], _editor_card(path=path, name=filename, content=data), path, _editor_state_payload(path, filename, data, False)


@callback(
    Output("rules-editor-wrap", "children", allow_duplicate=True),
    Output("rules-selected-path", "data", allow_duplicate=True),
    Output("rules-hydrated", "data"),
    Input("rules-editor-store", "data"),
    State("rules-hydrated", "data"),
    prevent_initial_call="initial_duplicate",
)
def _rehydrate_editor(editor_state, already_hydrated):
    if already_hydrated:
        return dash.no_update, dash.no_update, dash.no_update
    if not isinstance(editor_state, dict):
        return dash.no_update, dash.no_update, True
    path = editor_state.get("path", "")
    content = editor_state.get("content", "")
    name = editor_state.get("name", "")
    readonly = bool(editor_state.get("readonly", False))
    saved_at = editor_state.get("saved_at", 0)
    if time.time() - saved_at > 600 or not content:
        return dash.no_update, dash.no_update, True
    return _editor_card(path=path, name=name, content=content, readonly=readonly), path, True


@callback(
    Output("rules-editor-store", "data", allow_duplicate=True),
    Input("rules-editor-name", "value"),
    Input("rules-editor-content", "value"),
    State("rules-selected-path", "data"),
    State("rules-editor-store", "data"),
    prevent_initial_call=True,
)
def _persist_editor_draft(name, content, path, existing_store):
    # Never save an all-empty state — fires from placeholder DashAceEditor init
    # while _load_rule is in flight (stale State: path="", content="").
    if not (path or "") and not (name or "") and not (content or ""):
        return dash.no_update
    # Guard 2: DashAceEditor fires value="" before it initialises its content.
    # If the store already has content for the same path, don't overwrite with empty.
    if not (content or "") and isinstance(existing_store, dict):
        if existing_store.get("content") and existing_store.get("path") == (path or ""):
            return dash.no_update
    return _editor_state_payload(path or "", name or "", content or "", False)
