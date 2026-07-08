from __future__ import annotations

import dash
import re
from dash import ALL, Input, Output, State, callback, ctx, dcc, html, no_update
from dash.exceptions import PreventUpdate

from ui.helpers import api_delete, api_get, api_post, error_banner, metric_card, topbar
from ui.pages.enrichment_layout import (
    DEFAULT_SCRIPT, BACKDROP_HIDDEN, BACKDROP_SHOW, PANEL_HIDDEN, PANEL_SHOW, NODE_PANEL_SHOW,
    edit_panel, overview_section, render_runs_table,
)

dash.register_page(__name__, path="/enrichment")


def _reload_data() -> dict:
    enrichments = api_get("/api/enrich/enrichments").get("enrichments", [])
    clusters = api_get("/api/enrich/clusters").get("clusters", [])
    runs = api_get("/api/enrich/runs?limit=200").get("runs", [])
    scripts = api_get("/api/enrich/scripts").get("scripts", [])
    total_ops = sum(r.get("docs_updated", 0) + r.get("docs_created", 0) + r.get("docs_deleted", 0) for r in runs)
    return {"enrichments": enrichments, "clusters": clusters, "scripts": scripts, "run_count": len(runs), "total_ops": total_ops}


def _valid_schedule(value: str) -> bool:
    return not value or re.fullmatch(r"[1-9]\d*[smhd]", value.strip().lower()) is not None


def _close() -> dict:
    return {"open": False, "type": None, "key": None}


def _click_key(component_id) -> str | None:
    if isinstance(component_id, dict):
        return f"{component_id.get('type')}:{component_id.get('name', '')}"
    if isinstance(component_id, str):
        return component_id
    return None


def layout() -> html.Div:
    return html.Div([
        topbar(
            "Enrichment",
            html.Button([html.I(className="ti ti-network", style={"fontSize": "13px"}), " Ping all"], id="enrich-ping-btn", className="topbar-btn", n_clicks=0),
            html.Div(className="pages", children=[
                html.Button("Overview", id="enrich-tab-overview", className="page-btn active", n_clicks=0),
                html.Button("Rollback", id="enrich-tab-rollback", className="page-btn", n_clicks=0),
            ]),
            html.Button([html.I(className="ti ti-refresh", style={"fontSize": "13px"}), " Refresh"], id="enrich-refresh-btn", className="topbar-btn", n_clicks=0),
        ),
        html.Div(id="enrich-banner"),
        overview_section(),
        html.Div(id="enrich-rollback-section", className="content", style={"display": "none"}, children=[html.Div(id="enrich-runs-content")]),
        html.Div(id="enrich-backdrop", n_clicks=0, style=BACKDROP_HIDDEN),
        edit_panel(),
        dcc.Store(id="enrich-data", data={}),
        dcc.Store(id="enrich-panel-state", data=_close()),
        dcc.Store(id="enrich-click-counts", data={}),
        dcc.Store(id="enrich-ping-data", data=[]),
        dcc.Store(id="enrich-run-result", data={}),
        dcc.Interval(id="enrich-poll", interval=30_000, n_intervals=0),
    ])


# ── Data loading ──────────────────────────────────────────────────────────────

@callback(Output("enrich-data", "data"), Input("enrich-poll", "n_intervals"), Input("enrich-refresh-btn", "n_clicks"), prevent_initial_call=False)
def _load_data(_p, _r):
    return _reload_data()


# ── Overview rendering ────────────────────────────────────────────────────────

@callback(Output("enrich-metrics", "children"), Output("enrich-nodes-table", "children"), Output("enrich-list-rows", "children"),
          Input("enrich-data", "data"), Input("enrich-ping-data", "data"), Input("enrich-search", "value"))
def _render_overview(data, ping_data, search):
    data = data or {}
    enrichments = data.get("enrichments", [])
    clusters = data.get("clusters", [])
    ping_idx = {p["name"]: p for p in (ping_data or [])}
    online = sum(1 for p in (ping_data or []) if p.get("ok"))
    n = len(clusters)
    node_label = f"{online}/{n}" if ping_data else str(n)
    node_color = "green" if ping_data and online == n > 0 else ("amber" if ping_data and online < n else "blue")

    metrics = [
        metric_card("Nodes", node_label, "cluster nodes", node_color),
        metric_card("Enrichments", str(len(enrichments)), "configured", "blue"),
        metric_card("Runs", str(data.get("run_count", 0)), "in history", "blue"),
        metric_card("Total ops", str(data.get("total_ops", 0)), "audit records", "amber"),
    ]

    table_rows = []
    for c in clusters:
        name = c["name"]
        ping = ping_idx.get(name, {})
        ok = ping.get("ok")
        status = "online" if ok else ("offline" if ping else "—")
        lat = f"{ping['latency_ms']} ms" if ping.get("latency_ms") is not None else "—"
        detail = " · ".join(filter(None, [ping.get("version", ""), (c.get("auth_type") or "none") if c.get("auth_type") not in ("none", None) else ""]))
        table_rows.append(html.Tr([
            html.Td(html.Span(name, className="mono")),
            html.Td(html.Span(c.get("mode", "?"), className=f"tag {'running' if c.get('mode') == 'internal' else 'blue'}")),
            html.Td(html.Span(status, className=f"tag {'running' if ok else 'stopped' if ping else 'warning'}")),
            html.Td(lat, style={"textAlign": "right", "fontSize": "11px", "color": "#888780"}),
            html.Td(detail, style={"fontSize": "11px", "color": "#888780"}),
            html.Td(html.Button([html.I(className="ti ti-pencil", style={"fontSize": "11px"}), " Edit"],
                id={"type": "enrich-edit-node", "name": name}, className="rule-btn", n_clicks=0)),
        ]))

    nodes_table = html.Table([
        html.Thead(html.Tr([html.Th("Node"), html.Th("Role"), html.Th("Status"), html.Th("Latency", style={"textAlign": "right"}), html.Th("Detail"), html.Th("")])),
        html.Tbody(table_rows or [html.Tr(html.Td("No clusters configured.", colSpan=6, style={"color": "#888780", "fontSize": "12px", "padding": "12px"}))]),
    ], className="tbl")

    q = (search or "").lower()
    filtered = [e for e in enrichments if not q or any(q in str(v).lower() for v in [e.get("display_name"), e.get("name"), e.get("script"), *e.get("targets", [])])]
    if not filtered:
        list_rows: list = [html.Div("No enrichments. Click '+ New script'." if not enrichments else "No results.", style={"fontSize": "12px", "color": "#888780", "padding": "8px 0"})]
    else:
        list_rows = []
        for e in filtered:
            name = e["name"]
            on_log = e.get("on_log", False)
            schedule = e.get("schedule", "")
            title = [html.Span(e.get("display_name", name))]
            if on_log:
                title.append(html.Span("log trigger", className="tag purple", style={"fontSize": "10px"}))
            if not e.get("enabled", True):
                title.append(html.Span("disabled", className="tag warning", style={"fontSize": "10px"}))
            pills: list = [html.Span(e.get("script", ""), className="meta-pill script mono")]
            pills += [html.Span(t, className="meta-pill target") for t in e.get("targets", [])]
            if schedule:
                pills.append(html.Span(f"every {schedule}", className="meta-pill schedule"))
            if on_log:
                actions: list = [html.Button([html.I(className="ti ti-pencil", style={"fontSize": "11px"}), " Edit"],
                    id={"type": "enrich-edit-script", "name": name}, className="rule-btn", n_clicks=0)]
            else:
                actions = [
                    html.Button([html.I(className="ti ti-player-play-filled", style={"fontSize": "11px"}), " Run"],
                        id={"type": "enrich-run", "name": name}, className="topbar-btn primary",
                        style={"padding": "4px 10px", "fontSize": "12px"}, n_clicks=0),
                    html.Button([html.I(className="ti ti-flask", style={"fontSize": "11px"}), " Dry"],
                        id={"type": "enrich-dry", "name": name}, className="rule-btn", n_clicks=0),
                    html.Button([html.I(className="ti ti-pencil", style={"fontSize": "11px"}), " Edit"],
                        id={"type": "enrich-edit-script", "name": name}, className="rule-btn", n_clicks=0),
                ]
            list_rows.append(html.Div([
                html.Div([html.Div(title, className="list-title"),
                          html.Div(e.get("description", ""), className="list-desc") if e.get("description") else None,
                          html.Div(pills, className="list-meta")], className="list-main"),
                html.Div(actions, className="row-actions"),
            ], className="list-row enrich-row"))

    return metrics, nodes_table, list_rows


# ── Ping all ──────────────────────────────────────────────────────────────────

@callback(Output("enrich-ping-data", "data"), Input("enrich-ping-btn", "n_clicks"), prevent_initial_call=True)
def _ping_all(n):
    if not n:
        raise PreventUpdate
    return api_post("/api/enrich/clusters/ping").get("clusters", [])


# ── Run enrichment ────────────────────────────────────────────────────────────

@callback(Output("enrich-run-result", "data"),
          Input({"type": "enrich-run", "name": ALL}, "n_clicks"),
          Input({"type": "enrich-dry", "name": ALL}, "n_clicks"),
          prevent_initial_call=True)
def _run_enrichment(run_clicks, dry_clicks):
    if not any((run_clicks or []) + (dry_clicks or [])):
        raise PreventUpdate
    tid = ctx.triggered_id
    if not isinstance(tid, dict):
        raise PreventUpdate
    name, dry = tid.get("name", ""), tid.get("type") == "enrich-dry"
    return {"name": name, "dry": dry, "result": api_post(f"/api/enrich/run/{name}", {"dry_run": dry, "params": {}})}


@callback(Output("enrich-console-badge", "children"), Output("enrich-console-body", "children"), Input("enrich-run-result", "data"))
def _render_console(run_result):
    if not run_result:
        return None, html.Div("Run an enrichment to see output here.", style={"fontSize": "12px", "color": "#888780", "padding": "4px 0"})
    name, dry, result = run_result.get("name", ""), run_result.get("dry", False), run_result.get("result", {})
    badge = html.Span("dry run" if dry else "live", className=f"tag {'warning' if dry else 'running'}")
    if result.get("error"):
        return badge, [error_banner(f"Run failed: {result['error']}")]
    run_id = result.get("run_id", "")
    lines = [html.Div([html.Span("[DRY]" if dry else "[RUN]", style={"color": "#6B9DD8", "marginRight": "8px", "fontWeight": "600"}), f"run_id={run_id}"])]
    for r in result.get("results", []):
        cluster = r.get("cluster", "?")
        if r.get("ok"):
            lines.append(html.Div([html.Span("[OK]", style={"color": "#56d364", "marginRight": "8px"}),
                f"cluster={cluster}  updated={r.get('docs_updated',0)}  created={r.get('docs_created',0)}  deleted={r.get('docs_deleted',0)}"]))
        else:
            lines.append(html.Div([html.Span("[ERR]", style={"color": "#f85149", "marginRight": "8px"}), f"cluster={cluster}  error={r.get('error','?')}"]))
    return badge, [html.Div(lines, className="terminal", style={"height": "120px", "fontSize": "12px"})]


# ── Tab switching ─────────────────────────────────────────────────────────────

@callback(Output("enrich-overview-section", "style"), Output("enrich-rollback-section", "style"),
          Output("enrich-tab-overview", "className"), Output("enrich-tab-rollback", "className"),
          Output("enrich-runs-content", "children"),
          Input("enrich-tab-overview", "n_clicks"), Input("enrich-tab-rollback", "n_clicks"), prevent_initial_call=True)
def _switch_tab(ov, rb):
    if ctx.triggered_id == "enrich-tab-rollback":
        runs = api_get("/api/enrich/runs?limit=100").get("runs", [])
        card = [html.Div(className="card", style={"flex": "1"}, children=[
            html.Div(className="card-header", children=[html.Span("Run history", className="card-title"), html.Span(f"{len(runs)} runs", style={"fontSize": "11px", "color": "#888780"})]),
            html.Div(render_runs_table(runs)),
        ])]
        return {"display": "none"}, {"display": "flex"}, "page-btn", "page-btn active", card
    return {"display": "flex"}, {"display": "none"}, "page-btn active", "page-btn", no_update


# ── Rollback action ───────────────────────────────────────────────────────────

@callback(Output("enrich-banner", "children", allow_duplicate=True), Output("enrich-runs-content", "children", allow_duplicate=True),
          Input({"type": "enrich-rollback-run", "run_id": ALL}, "n_clicks"), prevent_initial_call=True)
def _do_rollback(n_clicks_list):
    if not any(n_clicks_list or []):
        raise PreventUpdate
    tid = ctx.triggered_id
    if not isinstance(tid, dict):
        raise PreventUpdate
    run_id = tid.get("run_id", "")
    result = api_post(f"/api/enrich/rollback/{run_id}?force=true")
    runs = api_get("/api/enrich/runs?limit=100").get("runs", [])
    card = [html.Div(className="card", style={"flex": "1"}, children=[
        html.Div(className="card-header", children=[html.Span("Run history", className="card-title")]),
        html.Div(render_runs_table(runs)),
    ])]
    if result.get("error"):
        return error_banner(f"Rollback failed: {result['error']}"), card
    ok = html.Div(f"Rolled back {run_id[:30]}…", style={"background": "#EAF3DE", "color": "#3B6D11", "padding": "10px 20px", "fontSize": "13px", "borderBottom": "0.5px solid rgba(0,0,0,0.08)"})
    return ok, card


# ── Panel open/close ──────────────────────────────────────────────────────────

@callback(Output("enrich-panel-state", "data"), Output("enrich-click-counts", "data"),
          Input({"type": "enrich-edit-script", "name": ALL}, "n_clicks"),
          Input({"type": "enrich-edit-node", "name": ALL}, "n_clicks"),
          Input("enrich-new-script-btn", "n_clicks"), Input("enrich-add-node-btn", "n_clicks"),
          Input("enrich-panel-close", "n_clicks"), Input("enrich-backdrop", "n_clicks"),
          State("enrich-click-counts", "data"), prevent_initial_call=True)
def _panel_state(script_clicks, node_clicks, new_script, add_node, close, backdrop, previous_counts):
    current_counts = {}
    for group in ctx.inputs_list[:2]:
        for item in group:
            key = _click_key(item.get("id"))
            if key:
                current_counts[key] = item.get("value") or 0
    current_counts.update({
        "enrich-new-script-btn": new_script or 0,
        "enrich-add-node-btn": add_node or 0,
        "enrich-panel-close": close or 0,
        "enrich-backdrop": backdrop or 0,
    })

    tid = ctx.triggered_id
    click_key = _click_key(tid)
    if not click_key or current_counts.get(click_key, 0) <= (previous_counts or {}).get(click_key, 0):
        return no_update, current_counts

    if isinstance(tid, dict):
        t = tid.get("type", "")
        name = tid.get("name", "")
        if t == "enrich-edit-script":
            return {"open": True, "type": "script", "key": name}, current_counts
        if t == "enrich-edit-node":
            return {"open": True, "type": "node", "key": name}, current_counts
    if tid == "enrich-new-script-btn":
        return {"open": True, "type": "new_script", "key": None}, current_counts
    if tid == "enrich-add-node-btn":
        return {"open": True, "type": "new_node", "key": None}, current_counts
    return _close(), current_counts


@callback(Output("enrich-backdrop", "style"), Output("enrich-panel", "style"), Input("enrich-panel-state", "data"))
def _show_panel(state):
    if state and state.get("open"):
        if state.get("type") == "new_node":
            return BACKDROP_SHOW, NODE_PANEL_SHOW
        return BACKDROP_SHOW, PANEL_SHOW
    return BACKDROP_HIDDEN, PANEL_HIDDEN


# ── Populate panel form ───────────────────────────────────────────────────────

_SS = {"display": "flex", "flexDirection": "column", "flex": "1", "minHeight": "0", "overflow": "hidden"}
_SH = {"display": "none", "flexDirection": "column", "flex": "1", "minHeight": "0"}
_NS = {"display": "flex", "flexDirection": "column", "flex": "1", "minHeight": "0"}
_NH = {"display": "none", "flexDirection": "column", "flex": "1", "minHeight": "0"}

@callback(
    Output("enrich-panel-header-icon", "children"), Output("enrich-panel-header-title", "children"),
    Output("enrich-script-section", "style"), Output("enrich-node-section", "style"),
    Output("enrich-edit-key", "value"), Output("enrich-edit-key", "disabled"),
    Output("enrich-edit-name", "value"), Output("enrich-edit-script-path", "value"),
    Output("enrich-edit-script-path", "options"),
    Output("enrich-edit-targets", "options"), Output("enrich-edit-targets", "value"),
    Output("enrich-edit-enabled", "value"), Output("enrich-edit-onlog", "value"),
    Output("enrich-edit-schedule", "value"), Output("enrich-edit-desc", "value"),
    Output("enrich-code-editor", "value"), Output("enrich-script-footer", "children"),
    Output("enrich-node-name", "value"), Output("enrich-node-name", "disabled"),
    Output("enrich-node-mode", "value"), Output("enrich-node-hosts", "value"),
    Output("enrich-node-authtype", "value"), Output("enrich-node-authenv", "value"),
    Output("enrich-node-authuser", "value"), Output("enrich-node-authpass", "value"),
    Input("enrich-panel-state", "data"), State("enrich-data", "data"), prevent_initial_call=True)
def _populate_panel(state, data):
    if not state or not state.get("open"):
        raise PreventUpdate
    data = data or {}
    enrichments = data.get("enrichments", [])
    clusters = data.get("clusters", [])
    scripts = data.get("scripts", [])
    panel_type = state.get("type")
    key = state.get("key")
    cluster_opts = [{"label": c["name"], "value": c["name"]} for c in clusters]
    script_opts = [{"label": s, "value": s} for s in scripts]

    blank_node = ("", False, "external", "", "none", "", "", "")

    if panel_type in ("script", "new_script"):
        e = next((x for x in enrichments if x["name"] == key), None) if panel_type == "script" else None
        icon = html.Span(html.I(className="ti ti-file-code"), className="edit-context-icon script")
        title = e.get("display_name", key) if e else "New script"
        sp = e.get("script", "") if e else "scripts/new_enrichment.py"
        if sp and sp not in scripts:
            script_opts = [{"label": sp, "value": sp}, *script_opts]
        code_resp = api_get(f"/api/enrich/script-content?path={sp}") if sp and e else {}
        code = code_resp.get("content") or DEFAULT_SCRIPT
        footer = f"data/enrichments/{sp} · config: data/enrichments/config/enrichments.yml" if sp else ""
        return (icon, title, _SS, _NH,
                key or "", panel_type == "script",
                e.get("display_name", key) if e else "", sp,
                script_opts, cluster_opts, e.get("targets", ["lab"]) if e else ["lab"],
                ["yes"] if (e.get("enabled", True) if e else True) else [],
                ["yes"] if (e.get("on_log", False) if e else False) else [],
                e.get("schedule", "") if e else "", e.get("description", "") if e else "",
                code, footer, *blank_node)

    if panel_type in ("node", "new_node"):
        c = next((x for x in clusters if x["name"] == key), None) if panel_type == "node" else None
        icon = html.Span(html.I(className="ti ti-server"), className="edit-context-icon node")
        title = key if c else "Add node"
        hosts_text = "\n".join(c.get("hosts", [])) if c else ""
        blank_script = ("", False, "", "", script_opts, cluster_opts, [], ["yes"], [], "", "", DEFAULT_SCRIPT, "")
        return (icon, title, _SH, _NS, *blank_script,
                key or "", panel_type == "node",
                c.get("mode", "external") if c else "external", hosts_text,
                c.get("auth_type", "none") if c else "none", "", "", "")

    raise PreventUpdate


# ── Toggle controls ───────────────────────────────────────────────────────────

@callback(Output("enrich-edit-enabled", "value", allow_duplicate=True),
          Input("enrich-enabled-toggle", "n_clicks"), State("enrich-edit-enabled", "value"), prevent_initial_call=True)
def _toggle_enabled(n, value):
    if not n:
        raise PreventUpdate
    return [] if "yes" in (value or []) else ["yes"]


@callback(Output("enrich-edit-onlog", "value", allow_duplicate=True),
          Input("enrich-onlog-toggle", "n_clicks"), State("enrich-edit-onlog", "value"), prevent_initial_call=True)
def _toggle_onlog(n, value):
    if not n:
        raise PreventUpdate
    return [] if "yes" in (value or []) else ["yes"]


@callback(Output("enrich-enabled-toggle", "className"), Output("enrich-enabled-toggle-label", "children"), Output("enrich-enabled-toggle-label", "className"),
          Output("enrich-onlog-toggle", "className"), Output("enrich-onlog-toggle-label", "children"), Output("enrich-onlog-toggle-label", "className"),
          Input("enrich-edit-enabled", "value"), Input("enrich-edit-onlog", "value"))
def _render_toggles(enabled, onlog):
    enabled_on = "yes" in (enabled or [])
    onlog_on = "yes" in (onlog or [])
    return (
        "toggle on" if enabled_on else "toggle", "Active" if enabled_on else "Disabled", "toggle-label" if enabled_on else "toggle-label off",
        "toggle on" if onlog_on else "toggle", "On log" if onlog_on else "Manual", "toggle-label" if onlog_on else "toggle-label off",
    )


# ── Validate script ───────────────────────────────────────────────────────────

@callback(Output("enrich-validate-result", "children"),
          Input("enrich-validate-btn", "n_clicks"),
          State("enrich-code-editor", "value"), State("enrich-edit-script-path", "value"), prevent_initial_call=True)
def _validate(n, code, path):
    if not n:
        raise PreventUpdate
    r = api_post("/api/enrich/script-validate", {"content": code or "", "path": path or ""})
    return html.Span("✓ Valid", style={"color": "#3B6D11", "fontWeight": "500"}) if r.get("ok") else html.Span(f"✗ {r.get('error', 'Invalid')}", style={"color": "#A32D2D"})


# ── Save / delete script ──────────────────────────────────────────────────────

@callback(Output("enrich-banner", "children", allow_duplicate=True), Output("enrich-panel-state", "data", allow_duplicate=True), Output("enrich-data", "data", allow_duplicate=True),
          Input("enrich-save-btn", "n_clicks"),
          State("enrich-panel-state", "data"), State("enrich-edit-key", "value"), State("enrich-edit-name", "value"),
          State("enrich-edit-script-path", "value"), State("enrich-edit-targets", "value"),
          State("enrich-edit-enabled", "value"), State("enrich-edit-onlog", "value"),
          State("enrich-edit-schedule", "value"), State("enrich-edit-desc", "value"),
          State("enrich-code-editor", "value"), prevent_initial_call=True)
def _save_script(n, _state, key, name, script_path, targets, enabled_v, onlog_v, schedule, desc, code):
    if not n:
        raise PreventUpdate
    key = (key or "").strip() or "".join(c if c.isalnum() or c == "_" else "_" for c in (name or "").lower()).strip("_")
    if not key:
        return error_banner("Config key required"), no_update, no_update
    if not _valid_schedule(schedule or ""):
        return error_banner("Schedule must use interval format like 30s, 15m, 2h, or 1d"), no_update, no_update
    if script_path and code:
        r = api_post("/api/enrich/script-content", {"path": script_path, "content": code})
        if r.get("error"):
            return error_banner(f"Script save failed: {r['error']}"), no_update, no_update
    r = api_post(f"/api/enrich/enrichments/{key}", {"display_name": name or key, "script": script_path or "",
        "targets": targets or [], "enabled": "yes" in (enabled_v or []), "on_log": "yes" in (onlog_v or []),
        "schedule": schedule or "", "description": desc or ""})
    if r.get("error"):
        return error_banner(f"Save failed: {r['error']}"), no_update, no_update
    return [], _close(), _reload_data()


@callback(Output("enrich-banner", "children", allow_duplicate=True), Output("enrich-panel-state", "data", allow_duplicate=True), Output("enrich-data", "data", allow_duplicate=True),
          Input("enrich-delete-btn", "n_clicks"), State("enrich-edit-key", "value"), prevent_initial_call=True)
def _delete_script(n, key):
    if not n or not key:
        raise PreventUpdate
    r = api_delete(f"/api/enrich/enrichments/{key}")
    if r.get("error"):
        return error_banner(f"Delete failed: {r['error']}"), no_update, no_update
    return [], _close(), _reload_data()


# ── Save / delete node ────────────────────────────────────────────────────────

@callback(Output("enrich-banner", "children", allow_duplicate=True), Output("enrich-panel-state", "data", allow_duplicate=True), Output("enrich-data", "data", allow_duplicate=True),
          Input("enrich-save-node-btn", "n_clicks"),
          State("enrich-node-name", "value"), State("enrich-node-mode", "value"),
          State("enrich-node-hosts", "value"), State("enrich-node-authtype", "value"),
          State("enrich-node-authenv", "value"), State("enrich-node-authuser", "value"),
          State("enrich-node-authpass", "value"), prevent_initial_call=True)
def _save_node(n, name, mode, hosts_text, auth_type, auth_env, auth_user, auth_pass):
    if not n:
        raise PreventUpdate
    name = (name or "").strip()
    if not name:
        return error_banner("Node name required"), no_update, no_update
    if name == "lab":
        return error_banner("Cannot modify built-in 'lab' cluster via UI"), no_update, no_update
    hosts = [h.strip() for h in (hosts_text or "").splitlines() if h.strip()]
    r = api_post(f"/api/enrich/clusters-config/{name}", {"mode": mode or "external", "hosts": hosts,
        "auth_type": auth_type or "none", "auth_env": auth_env or "", "auth_user": auth_user or "", "auth_pass_env": auth_pass or ""})
    if r.get("error"):
        return error_banner(f"Save failed: {r['error']}"), no_update, no_update
    return [], _close(), _reload_data()


@callback(Output("enrich-banner", "children", allow_duplicate=True), Output("enrich-panel-state", "data", allow_duplicate=True), Output("enrich-data", "data", allow_duplicate=True),
          Input("enrich-delete-node-btn", "n_clicks"), State("enrich-node-name", "value"), prevent_initial_call=True)
def _delete_node(n, name):
    if not n or not name:
        raise PreventUpdate
    if name == "lab":
        return error_banner("Cannot delete built-in 'lab' cluster"), no_update, no_update
    r = api_delete(f"/api/enrich/clusters-config/{name}")
    if r.get("error"):
        return error_banner(f"Delete failed: {r['error']}"), no_update, no_update
    return [], _close(), _reload_data()


# ── Ping node from panel ──────────────────────────────────────────────────────

@callback(Output("enrich-node-ping-result", "children"), Input("enrich-ping-node-btn", "n_clicks"), State("enrich-node-name", "value"), prevent_initial_call=True)
def _ping_node(n, name):
    if not n or not name:
        raise PreventUpdate
    r = api_post(f"/api/enrich/clusters/{name}/test")
    if r.get("ok"):
        ver = f"  v{r['version']}" if r.get("version") else ""
        return html.Span(f"✓ Online — {r.get('latency_ms', '?')} ms{ver}", style={"color": "#3B6D11", "fontWeight": "500"})
    return html.Span(f"✗ {r.get('error', 'Unreachable')}", style={"color": "#A32D2D"})
