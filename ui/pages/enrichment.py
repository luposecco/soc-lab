from __future__ import annotations

from datetime import datetime, timezone

import dash
from dash import ALL, Input, Output, State, callback, ctx, dcc, html, no_update
from dash.exceptions import PreventUpdate
from dash_ace import DashAceEditor

from ui.helpers import api_delete, api_get, api_post, error_banner, lcol, lpanel, lrow, ltable, metric_card, topbar

dash.register_page(__name__, path="/enrichment")

_DEFAULT_SCRIPT = '''\
"""Description of this enrichment."""

from __future__ import annotations

from enrich_sdk import EnrichmentContext


def run(ctx: EnrichmentContext) -> None:
    # Enrich documents matching a query
    # ctx.update_by_query(
    #     index="soc-alerts",
    #     query={"bool": {"must": [{"term": {"field": "value"}}]}},
    #     fields={"enriched.field": "value"},
    # )
    pass
'''

_PANEL_HIDDEN = {"display": "none"}
_PANEL_SHOW = {
    "display": "flex",
    "position": "fixed",
    "left": "calc(224px + 14px)",
    "right": "14px",
    "top": "14px",
    "bottom": "14px",
    "background": "#f4f3ef",
    "zIndex": "101",
    "flexDirection": "column",
    "boxShadow": "0 32px 80px rgba(0,0,0,0.28), 0 8px 24px rgba(0,0,0,0.12)",
    "borderRadius": "18px",
    "border": "0.5px solid rgba(0,0,0,0.12)",
    "overflow": "hidden",
}
_BACKDROP_HIDDEN = {"display": "none"}
_BACKDROP_SHOW = {
    "display": "block",
    "position": "fixed",
    "inset": "0",
    "background": "rgba(0,0,0,0.28)",
    "zIndex": "100",
    "cursor": "pointer",
}


def _reload_data() -> dict:
    enrichments = api_get("/api/enrich/enrichments").get("enrichments", [])
    clusters = api_get("/api/enrich/clusters").get("clusters", [])
    scripts = api_get("/api/enrich/scripts").get("scripts", [])
    runs = api_get("/api/enrich/runs?limit=200").get("runs", [])
    total_ops = sum(
        r.get("docs_updated", 0) + r.get("docs_created", 0) + r.get("docs_deleted", 0)
        for r in runs
    )
    return {
        "enrichments": enrichments,
        "clusters": clusters,
        "scripts": scripts,
        "run_count": len(runs),
        "total_ops": total_ops,
    }


def _panel_close_state() -> dict:
    return {"open": False, "type": None, "key": None}


def layout() -> html.Div:
    return html.Div([
        topbar(
            "Enrichment",
            html.Button(
                [html.I(className="ti ti-network", style={"fontSize": "13px"}), " Ping all"],
                id="enrich-ping-btn", className="topbar-btn", n_clicks=0,
            ),
            html.Div(className="pages", children=[
                html.Button("Overview", id="enrich-tab-overview", className="page-btn active", n_clicks=0),
                html.Button("Rollback", id="enrich-tab-rollback", className="page-btn", n_clicks=0),
            ]),
            html.Button(
                [html.I(className="ti ti-refresh", style={"fontSize": "13px"}), " Refresh"],
                id="enrich-refresh-btn", className="topbar-btn", n_clicks=0,
            ),
        ),
        html.Div(id="enrich-banner"),

        # ── Overview section ──────────────────────────────────────────────────
        html.Div(id="enrich-overview-section", className="content", children=[
            html.Div(id="enrich-metrics", className="metrics"),
            html.Div(style={**lrow(min_col="320px", gap="14px"), "flex": "1", "minHeight": "0", "marginBottom": "16px"}, children=[
                # Left column: nodes table + run console
                html.Div(style={**lcol(gap="14px"), "flex": "1"}, children=[
                    html.Div(className="card", style={**ltable(min_h=160, fill=True)}, children=[
                        html.Div(className="card-header", children=[
                            html.Span("Target cluster nodes", className="card-title"),
                            html.Div(style={"display": "flex", "alignItems": "center", "gap": "8px"}, children=[
                                html.Span("clusters.yml", className="card-action mono"),
                                html.Button(
                                    [html.I(className="ti ti-plus", style={"fontSize": "11px"}), " Add node"],
                                    id="enrich-add-node-btn", className="rule-btn", n_clicks=0,
                                ),
                            ]),
                        ]),
                        html.Div(id="enrich-nodes-table", className="table-panel-body"),
                    ]),
                    html.Div(className="card", style={**lpanel(min_h=120, fill=True)}, children=[
                        html.Div(className="card-header", children=[
                            html.Span("Run console", className="card-title"),
                            html.Span(id="enrich-console-badge"),
                        ]),
                        html.Div(id="enrich-console-body", children=[
                            html.Div(
                                "Run an enrichment to see output here.",
                                style={"fontSize": "12px", "color": "#888780", "padding": "4px 0"},
                            ),
                        ]),
                    ]),
                ]),
                # Right column: enrichment list
                html.Div(style={**lcol(gap="14px"), "flex": "1"}, children=[
                    html.Div(className="card", style={**ltable(min_h=300, fill=True)}, children=[
                        html.Div(className="card-header", children=[
                            html.Span("Configured enrichments", className="card-title"),
                            html.Button(
                                [html.I(className="ti ti-plus", style={"fontSize": "11px"}), " New script"],
                                id="enrich-new-script-btn", className="rule-btn", n_clicks=0,
                            ),
                        ]),
                        html.Div(className="filterbar", style={"marginBottom": "8px", "flexShrink": "0"}, children=[
                            html.I(className="ti ti-search", style={"fontSize": "14px", "color": "#888780", "flexShrink": "0"}),
                            dcc.Input(
                                id="enrich-search", placeholder="Search enrichments…", debounce=True,
                                className="search-input", style={"flex": "1", "paddingLeft": "10px", "backgroundImage": "none"},
                            ),
                        ]),
                        html.Div(id="enrich-list-rows", className="list-rows compact-list table-panel-body"),
                    ]),
                ]),
            ]),
        ]),

        # ── Rollback section ──────────────────────────────────────────────────
        html.Div(id="enrich-rollback-section", className="content", style={"display": "none"}, children=[
            html.Div(id="enrich-runs-content"),
        ]),

        # ── Edit panel overlay ────────────────────────────────────────────────
        html.Div(id="enrich-backdrop", n_clicks=0, style=_BACKDROP_HIDDEN),
        html.Div(id="enrich-panel", style=_PANEL_HIDDEN, children=[
            # Panel header (static wrapper, content populated by callback)
            html.Div(className="edit-panel-header", children=[
                html.Div(id="enrich-panel-header-icon"),
                html.Span(id="enrich-panel-header-title", className="edit-panel-title"),
                html.Button(
                    html.I(className="ti ti-x", style={"fontSize": "13px"}),
                    id="enrich-panel-close", className="topbar-btn", n_clicks=0,
                ),
            ]),
            html.Div(className="edit-panel-body", children=[
                html.Div(className="card", style={
                    "flex": "1", "display": "flex", "flexDirection": "column",
                    "overflow": "hidden", "minHeight": "0",
                }, children=[

                    # ── Script section ────────────────────────────────────────
                    html.Div(id="enrich-script-section", style={
                        "display": "flex", "flexDirection": "column", "flex": "1", "minHeight": "0", "overflow": "hidden",
                    }, children=[
                        html.Div(className="form-grid compact", style={"flexShrink": "0"}, children=[
                            html.Label(className="field", children=[
                                html.Span("Config key", style={"fontSize": "12px", "color": "#5f5e5a", "marginBottom": "5px", "display": "block"}),
                                dcc.Input(id="enrich-edit-key", className="setting-input mono", style={"width": "100%"}),
                            ]),
                            html.Label(className="field", children=[
                                html.Span("Display name", style={"fontSize": "12px", "color": "#5f5e5a", "marginBottom": "5px", "display": "block"}),
                                dcc.Input(id="enrich-edit-name", className="setting-input", style={"width": "100%"}),
                            ]),
                            html.Div(className="field", style={"gridColumn": "span 2"}, children=[
                                html.Span("Script path", style={"fontSize": "12px", "color": "#5f5e5a", "marginBottom": "5px", "display": "block"}),
                                html.Div(className="inline-field", children=[
                                    dcc.Input(id="enrich-edit-script-path", className="setting-input mono", style={"flex": "1", "minWidth": "0"}),
                                ]),
                            ]),
                            html.Div(className="field", style={"gridColumn": "span 2"}, children=[
                                html.Span("Target nodes", style={"fontSize": "12px", "color": "#5f5e5a", "marginBottom": "5px", "display": "block"}),
                                dcc.Checklist(
                                    id="enrich-edit-targets",
                                    options=[],
                                    value=[],
                                    className="node-checklist-dash",
                                    labelStyle={
                                        "display": "flex", "alignItems": "center", "gap": "8px",
                                        "padding": "7px 10px", "fontSize": "13px", "cursor": "pointer",
                                        "borderBottom": "0.5px solid rgba(0,0,0,0.06)",
                                    },
                                    inputStyle={"cursor": "pointer", "flexShrink": "0"},
                                ),
                            ]),
                            html.Div(className="field", children=[
                                html.Span("Enabled", style={"fontSize": "12px", "color": "#5f5e5a", "marginBottom": "5px", "display": "block"}),
                                dcc.Checklist(
                                    id="enrich-edit-enabled",
                                    options=[{"label": " Active", "value": "yes"}],
                                    value=["yes"],
                                    style={"fontSize": "13px"},
                                ),
                            ]),
                            html.Div(className="field", children=[
                                html.Span("Log trigger", style={"fontSize": "12px", "color": "#5f5e5a", "marginBottom": "5px", "display": "block"}),
                                dcc.Checklist(
                                    id="enrich-edit-onlog",
                                    options=[{"label": " On log", "value": "yes"}],
                                    value=[],
                                    style={"fontSize": "13px"},
                                ),
                            ]),
                            html.Label(className="field", style={"gridColumn": "span 2"}, children=[
                                html.Span("Schedule", style={"fontSize": "12px", "color": "#5f5e5a", "marginBottom": "5px", "display": "block"}),
                                dcc.Input(
                                    id="enrich-edit-schedule", className="setting-input mono",
                                    placeholder="30s · 15m · 2h  (leave empty to disable)", style={"width": "100%"},
                                ),
                            ]),
                            html.Label(className="field", style={"gridColumn": "span 2"}, children=[
                                html.Span("Description", style={"fontSize": "12px", "color": "#5f5e5a", "marginBottom": "5px", "display": "block"}),
                                dcc.Textarea(
                                    id="enrich-edit-desc", className="setting-input",
                                    style={"width": "100%", "height": "54px", "resize": "vertical", "padding": "7px 12px", "fontSize": "13px"},
                                ),
                            ]),
                        ]),
                        html.Div(className="button-row", style={"flexShrink": "0"}, children=[
                            html.Button(
                                [html.I(className="ti ti-check", style={"fontSize": "12px"}), " Validate"],
                                id="enrich-validate-btn", className="topbar-btn", n_clicks=0,
                            ),
                            html.Button(
                                [html.I(className="ti ti-device-floppy", style={"fontSize": "12px"}), " Save"],
                                id="enrich-save-btn", className="topbar-btn primary", n_clicks=0,
                            ),
                            html.Div(id="enrich-validate-result", style={"fontSize": "12px", "flex": "1", "color": "#5f5e5a"}),
                            html.Button(
                                html.I(className="ti ti-trash", style={"fontSize": "12px"}),
                                id="enrich-delete-btn", className="topbar-btn danger", n_clicks=0,
                            ),
                        ]),
                        DashAceEditor(
                            id="enrich-code-editor",
                            value=_DEFAULT_SCRIPT,
                            mode="python",
                            theme="tomorrow_night",
                            tabSize=4,
                            fontSize=12,
                            enableBasicAutocompletion=False,
                            enableLiveAutocompletion=False,
                            enableSnippets=False,
                            wrapEnabled=True,
                            showPrintMargin=False,
                            highlightActiveLine=False,
                            showGutter=True,
                            className="rule-ace-editor",
                            style={"flex": "1", "minHeight": "0", "width": "100%", "marginTop": "12px"},
                        ),
                        html.Div(id="enrich-script-footer", style={
                            "fontSize": "10px", "color": "#888780", "fontFamily": "monospace",
                            "flexShrink": "0", "marginTop": "8px",
                        }),
                    ]),

                    # ── Node section ──────────────────────────────────────────
                    html.Div(id="enrich-node-section", style={
                        "display": "none", "flexDirection": "column", "flex": "1", "minHeight": "0",
                    }, children=[
                        html.Div(className="form-grid compact", style={"flexShrink": "0"}, children=[
                            html.Label(className="field", children=[
                                html.Span("Node name", style={"fontSize": "12px", "color": "#5f5e5a", "marginBottom": "5px", "display": "block"}),
                                dcc.Input(id="enrich-node-name", className="setting-input mono", style={"width": "100%"}),
                            ]),
                            html.Label(className="field", children=[
                                html.Span("Mode", style={"fontSize": "12px", "color": "#5f5e5a", "marginBottom": "5px", "display": "block"}),
                                dcc.Dropdown(
                                    id="enrich-node-mode",
                                    options=[{"label": "Internal", "value": "internal"}, {"label": "External", "value": "external"}],
                                    value="external", clearable=False, style={"fontSize": "13px"},
                                ),
                            ]),
                            html.Label(className="field", style={"gridColumn": "span 2"}, children=[
                                html.Span("Hosts (one per line)", style={"fontSize": "12px", "color": "#5f5e5a", "marginBottom": "5px", "display": "block"}),
                                dcc.Textarea(
                                    id="enrich-node-hosts", className="setting-input",
                                    placeholder="https://es01.example:9200",
                                    style={"width": "100%", "height": "70px", "resize": "vertical", "padding": "7px 12px", "fontSize": "13px"},
                                ),
                            ]),
                            html.Label(className="field", style={"gridColumn": "span 2"}, children=[
                                html.Span("Auth type", style={"fontSize": "12px", "color": "#5f5e5a", "marginBottom": "5px", "display": "block"}),
                                dcc.Dropdown(
                                    id="enrich-node-authtype",
                                    options=[
                                        {"label": "None", "value": "none"},
                                        {"label": "API Key (env var)", "value": "api_key"},
                                        {"label": "Basic auth", "value": "basic"},
                                    ],
                                    value="none", clearable=False, style={"fontSize": "13px"},
                                ),
                            ]),
                            html.Label(className="field", style={"gridColumn": "span 2"}, children=[
                                html.Span("API Key env var", style={"fontSize": "12px", "color": "#5f5e5a", "marginBottom": "5px", "display": "block"}),
                                dcc.Input(id="enrich-node-authenv", className="setting-input mono", placeholder="ES_API_KEY", style={"width": "100%"}),
                            ]),
                            html.Label(className="field", children=[
                                html.Span("Username", style={"fontSize": "12px", "color": "#5f5e5a", "marginBottom": "5px", "display": "block"}),
                                dcc.Input(id="enrich-node-authuser", className="setting-input", placeholder="elastic", style={"width": "100%"}),
                            ]),
                            html.Label(className="field", children=[
                                html.Span("Password env var", style={"fontSize": "12px", "color": "#5f5e5a", "marginBottom": "5px", "display": "block"}),
                                dcc.Input(id="enrich-node-authpass", className="setting-input mono", placeholder="ES_PASS", style={"width": "100%"}),
                            ]),
                        ]),
                        html.Div(className="button-row", style={"flexShrink": "0"}, children=[
                            html.Button(
                                [html.I(className="ti ti-network", style={"fontSize": "12px"}), " Ping"],
                                id="enrich-ping-node-btn", className="topbar-btn", n_clicks=0,
                            ),
                            html.Button(
                                [html.I(className="ti ti-device-floppy", style={"fontSize": "12px"}), " Save"],
                                id="enrich-save-node-btn", className="topbar-btn primary", n_clicks=0,
                            ),
                            html.Button(
                                html.I(className="ti ti-trash", style={"fontSize": "12px"}),
                                id="enrich-delete-node-btn", className="topbar-btn danger", n_clicks=0,
                                style={"marginLeft": "auto"},
                            ),
                        ]),
                        html.Div(id="enrich-node-ping-result", style={"marginTop": "10px", "fontSize": "12px"}),
                        html.Div(
                            "data/enrichments/config/clusters.yml",
                            style={"fontSize": "10px", "color": "#888780", "fontFamily": "monospace", "marginTop": "auto", "paddingTop": "12px", "flexShrink": "0"},
                        ),
                    ]),
                ]),
            ]),
        ]),

        # ── Stores ───────────────────────────────────────────────────────────
        dcc.Store(id="enrich-data", data={}),
        dcc.Store(id="enrich-panel-state", data={"open": False, "type": None, "key": None}),
        dcc.Store(id="enrich-ping-data", data=[]),
        dcc.Store(id="enrich-run-result", data={}),
        dcc.Interval(id="enrich-poll", interval=30_000, n_intervals=0),
    ])


# ── Helper: render runs list ──────────────────────────────────────────────────

def _render_runs(runs: list[dict]) -> list:
    if not runs:
        return [html.Div("No enrichment runs recorded yet.", style={"fontSize": "13px", "color": "#888780", "padding": "20px 0"})]

    header = html.Div(style={
        "display": "grid",
        "gridTemplateColumns": "1fr 120px 100px 80px 80px 100px",
        "gap": "12px",
        "padding": "6px 0",
        "borderBottom": "0.5px solid rgba(0,0,0,0.1)",
        "fontSize": "11px",
        "fontWeight": "600",
        "color": "#888780",
        "textTransform": "uppercase",
        "letterSpacing": "0.04em",
    }, children=["Run ID", "Enrichment", "Cluster", "Ops", "Dry", ""])

    rows = [header]
    for run in runs:
        run_id = run.get("run_id", "")
        enrichment = run.get("enrichment", "—")
        cluster = run.get("cluster", "—")
        ops = run.get("docs_updated", 0) + run.get("docs_created", 0) + run.get("docs_deleted", 0)
        is_dry = run.get("dry_run", False)
        ts_raw = run.get("timestamp", "")
        ts = ts_raw[:16].replace("T", " ") if ts_raw else run_id[:20]
        rows.append(html.Div(style={
            "display": "grid",
            "gridTemplateColumns": "1fr 120px 100px 80px 80px 100px",
            "gap": "12px",
            "padding": "8px 0",
            "borderBottom": "0.5px solid rgba(0,0,0,0.06)",
            "alignItems": "center",
            "fontSize": "13px",
        }, children=[
            html.Span(ts, className="mono", style={"fontSize": "11px", "color": "#5f5e5a"}),
            html.Span(enrichment, style={"fontWeight": "500"}),
            html.Span(cluster, className="mono"),
            html.Span(str(ops), style={"textAlign": "right"}),
            html.Span("dry" if is_dry else "live", className=f"tag {'warning' if is_dry else 'running'}", style={"fontSize": "10px"}),
            html.Button(
                [html.I(className="ti ti-history", style={"fontSize": "11px"}), " Rollback"],
                id={"type": "enrich-rollback-run", "run_id": run_id},
                className="rule-btn",
                n_clicks=0,
                style={"fontSize": "11px"},
            ) if not is_dry else html.Span("—", style={"color": "#888780", "fontSize": "11px"}),
        ]))
    return rows


# ── Callbacks: Data loading ───────────────────────────────────────────────────

@callback(
    Output("enrich-data", "data"),
    Input("enrich-poll", "n_intervals"),
    Input("enrich-refresh-btn", "n_clicks"),
    prevent_initial_call=False,
)
def _load_data(_poll, _refresh):
    return _reload_data()


# ── Callbacks: Overview rendering ─────────────────────────────────────────────

@callback(
    Output("enrich-metrics", "children"),
    Output("enrich-nodes-table", "children"),
    Output("enrich-list-rows", "children"),
    Input("enrich-data", "data"),
    Input("enrich-ping-data", "data"),
    Input("enrich-search", "value"),
)
def _render_overview(data, ping_data, search):
    data = data or {}
    enrichments = data.get("enrichments", [])
    clusters = data.get("clusters", [])
    run_count = data.get("run_count", 0)
    total_ops = data.get("total_ops", 0)

    ping_idx: dict = {p["name"]: p for p in (ping_data or [])}
    online = sum(1 for p in (ping_data or []) if p.get("ok"))
    total_nodes = len(clusters)

    node_label = f"{online}/{total_nodes}" if ping_data else str(total_nodes)
    node_color = "green" if ping_data and online == total_nodes and total_nodes > 0 else ("amber" if ping_data and online < total_nodes else "blue")

    metrics = [
        metric_card("Nodes", node_label, "cluster nodes", node_color),
        metric_card("Enrichments", str(len(enrichments)), "configured", "blue"),
        metric_card("Runs", str(run_count), "in history", "blue"),
        metric_card("Total ops", str(total_ops), "audit records", "amber"),
    ]

    # Nodes table
    table_rows = []
    for c in clusters:
        name = c["name"]
        ping = ping_idx.get(name, {})
        online_flag = ping.get("ok")
        status = "online" if online_flag else ("offline" if ping else "—")
        latency = f"{ping['latency_ms']} ms" if ping.get("latency_ms") is not None else "—"
        version = ping.get("version", "")
        mode = c.get("mode", "?")
        auth = c.get("auth_type", "none")
        mode_cls = "running" if mode == "internal" else "blue"
        status_cls = "running" if online_flag else ("stopped" if ping else "warning")
        detail_parts = []
        if version:
            detail_parts.append(version)
        if auth != "none":
            detail_parts.append(auth)
        detail = " · ".join(detail_parts)
        table_rows.append(html.Tr([
            html.Td(html.Span(name, className="mono")),
            html.Td(html.Span(mode, className=f"tag {mode_cls}")),
            html.Td(html.Span(status, className=f"tag {status_cls}")),
            html.Td(latency, style={"textAlign": "right", "fontSize": "11px", "color": "#888780"}),
            html.Td(detail, style={"fontSize": "11px", "color": "#888780"}),
            html.Td(html.Button(
                [html.I(className="ti ti-pencil", style={"fontSize": "11px"}), " Edit"],
                id={"type": "enrich-edit-node", "name": name},
                className="rule-btn", n_clicks=0,
            )),
        ]))

    nodes_table = html.Table([
        html.Thead(html.Tr([
            html.Th("Node"), html.Th("Role"), html.Th("Status"),
            html.Th("Latency", style={"textAlign": "right"}), html.Th("Detail"), html.Th(""),
        ])),
        html.Tbody(table_rows if table_rows else [
            html.Tr(html.Td("No clusters configured.", colSpan=6, style={"color": "#888780", "fontSize": "12px", "padding": "12px"}))
        ]),
    ], className="tbl")

    # Enrichment list
    q = (search or "").lower()
    filtered = [
        e for e in enrichments
        if not q or q in e.get("display_name", "").lower()
        or q in e.get("name", "").lower()
        or q in e.get("script", "").lower()
        or any(q in t.lower() for t in e.get("targets", []))
    ]

    if not filtered:
        list_rows = [html.Div(
            "No enrichments configured. Click '+ New script' to create one." if not enrichments else "No results.",
            style={"fontSize": "12px", "color": "#888780", "padding": "8px 0"},
        )]
    else:
        list_rows = []
        for e in filtered:
            name = e["name"]
            display_name = e.get("display_name", name)
            on_log = e.get("on_log", False)
            schedule = e.get("schedule", "")
            enabled = e.get("enabled", True)
            script = e.get("script", "")
            targets = e.get("targets", [])
            description = e.get("description", "")

            title_children: list = [html.Span(display_name)]
            if on_log:
                title_children.append(html.Span("log trigger", className="tag purple", style={"fontSize": "10px"}))
            if not enabled:
                title_children.append(html.Span("disabled", className="tag warning", style={"fontSize": "10px"}))

            pills: list = [html.Span(script, className="meta-pill script mono")]
            for t in targets:
                pills.append(html.Span(t, className="meta-pill target"))
            if schedule:
                pills.append(html.Span(f"every {schedule}", className="meta-pill schedule"))

            if on_log:
                actions: list = [
                    html.Button(
                        [html.I(className="ti ti-pencil", style={"fontSize": "11px"}), " Edit"],
                        id={"type": "enrich-edit-script", "name": name},
                        className="rule-btn", n_clicks=0,
                    ),
                ]
            else:
                actions = [
                    html.Button(
                        [html.I(className="ti ti-player-play-filled", style={"fontSize": "11px"}), " Run"],
                        id={"type": "enrich-run", "name": name},
                        className="topbar-btn primary",
                        style={"padding": "4px 10px", "fontSize": "12px"},
                        n_clicks=0,
                    ),
                    html.Button(
                        [html.I(className="ti ti-flask", style={"fontSize": "11px"}), " Dry"],
                        id={"type": "enrich-dry", "name": name},
                        className="rule-btn", n_clicks=0,
                    ),
                    html.Button(
                        [html.I(className="ti ti-pencil", style={"fontSize": "11px"}), " Edit"],
                        id={"type": "enrich-edit-script", "name": name},
                        className="rule-btn", n_clicks=0,
                    ),
                ]

            list_rows.append(html.Div([
                html.Div([
                    html.Div(title_children, className="list-title"),
                    html.Div(description, className="list-desc") if description else None,
                    html.Div(pills, className="list-meta"),
                ], className="list-main"),
                html.Div(actions, className="row-actions"),
            ], className="list-row enrich-row"))

    return metrics, nodes_table, list_rows


# ── Callbacks: Ping all ───────────────────────────────────────────────────────

@callback(
    Output("enrich-ping-data", "data"),
    Input("enrich-ping-btn", "n_clicks"),
    prevent_initial_call=True,
)
def _ping_all(n):
    if not n:
        raise PreventUpdate
    result = api_post("/api/enrich/clusters/ping")
    return result.get("clusters", [])


# ── Callbacks: Run enrichment ─────────────────────────────────────────────────

@callback(
    Output("enrich-run-result", "data"),
    Input({"type": "enrich-run", "name": ALL}, "n_clicks"),
    Input({"type": "enrich-dry", "name": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def _run_enrichment(run_clicks, dry_clicks):
    all_clicks = (run_clicks or []) + (dry_clicks or [])
    if not any(all_clicks):
        raise PreventUpdate
    tid = ctx.triggered_id
    if not tid or not isinstance(tid, dict):
        raise PreventUpdate
    name = tid.get("name", "")
    dry = tid.get("type") == "enrich-dry"
    result = api_post(f"/api/enrich/run/{name}", {"dry_run": dry, "params": {}})
    return {"name": name, "dry": dry, "result": result}


@callback(
    Output("enrich-console-badge", "children"),
    Output("enrich-console-body", "children"),
    Input("enrich-run-result", "data"),
)
def _render_console(run_result):
    if not run_result:
        return None, html.Div("Run an enrichment to see output here.", style={"fontSize": "12px", "color": "#888780", "padding": "4px 0"})

    name = run_result.get("name", "")
    dry = run_result.get("dry", False)
    result = run_result.get("result", {})
    badge = html.Span("dry run" if dry else "live", className=f"tag {'warning' if dry else 'running'}")

    if result.get("error"):
        body = [error_banner(f"Run failed: {result['error']}")]
    else:
        run_id = result.get("run_id", "")
        results = result.get("results", [])
        lines = [html.Div([
            html.Span(f"[{'DRY' if dry else 'RUN'}]", style={"color": "#6B9DD8", "marginRight": "8px", "fontWeight": "600"}),
            f"run_id={run_id}",
        ])]
        for r in results:
            cluster = r.get("cluster", "?")
            if r.get("ok"):
                updated = r.get("docs_updated", 0)
                created = r.get("docs_created", 0)
                deleted = r.get("docs_deleted", 0)
                lines.append(html.Div([
                    html.Span("[OK]", style={"color": "#56d364", "marginRight": "8px"}),
                    f"cluster={cluster}  updated={updated}  created={created}  deleted={deleted}",
                ]))
            else:
                lines.append(html.Div([
                    html.Span("[ERR]", style={"color": "#f85149", "marginRight": "8px"}),
                    f"cluster={cluster}  error={r.get('error', '?')}",
                ]))
        body = [html.Div(lines, className="terminal", style={"height": "120px", "fontSize": "12px"})]

    return badge, body


# ── Callbacks: Tab switching ──────────────────────────────────────────────────

@callback(
    Output("enrich-overview-section", "style"),
    Output("enrich-rollback-section", "style"),
    Output("enrich-tab-overview", "className"),
    Output("enrich-tab-rollback", "className"),
    Output("enrich-runs-content", "children"),
    Input("enrich-tab-overview", "n_clicks"),
    Input("enrich-tab-rollback", "n_clicks"),
    prevent_initial_call=True,
)
def _switch_tab(ov_clicks, rb_clicks):
    is_rollback = ctx.triggered_id == "enrich-tab-rollback"
    if is_rollback:
        runs = api_get("/api/enrich/runs?limit=100").get("runs", [])
        runs_content = [
            html.Div(className="card", style={"flex": "1"}, children=[
                html.Div(className="card-header", children=[
                    html.Span("Enrichment run history", className="card-title"),
                    html.Span(f"{len(runs)} runs", style={"fontSize": "11px", "color": "#888780"}),
                ]),
                html.Div(_render_runs(runs)),
            ])
        ]
        return {"display": "none"}, {"display": "flex"}, "page-btn", "page-btn active", runs_content
    return {"display": "flex"}, {"display": "none"}, "page-btn active", "page-btn", no_update


# ── Callbacks: Rollback action ────────────────────────────────────────────────

@callback(
    Output("enrich-banner", "children", allow_duplicate=True),
    Output("enrich-runs-content", "children", allow_duplicate=True),
    Input({"type": "enrich-rollback-run", "run_id": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def _do_rollback(n_clicks_list):
    if not any(n_clicks_list or []):
        raise PreventUpdate
    tid = ctx.triggered_id
    if not tid or not isinstance(tid, dict):
        raise PreventUpdate
    run_id = tid.get("run_id", "")
    result = api_post(f"/api/enrich/rollback/{run_id}?force=true")
    if result.get("error"):
        banner = error_banner(f"Rollback failed: {result['error']}")
        runs = api_get("/api/enrich/runs?limit=100").get("runs", [])
        return banner, _render_runs(runs)
    runs = api_get("/api/enrich/runs?limit=100").get("runs", [])
    runs_content = [
        html.Div(className="card", style={"flex": "1"}, children=[
            html.Div(className="card-header", children=[html.Span("Enrichment run history", className="card-title")]),
            html.Div(_render_runs(runs)),
        ])
    ]
    banner = html.Div(
        f"Rolled back run {run_id[:30]}…",
        style={"background": "#EAF3DE", "color": "#3B6D11", "padding": "10px 20px", "fontSize": "13px", "borderBottom": "0.5px solid rgba(0,0,0,0.08)"},
    )
    return banner, runs_content


# ── Callbacks: Panel open/close ───────────────────────────────────────────────

@callback(
    Output("enrich-panel-state", "data"),
    Input({"type": "enrich-edit-script", "name": ALL}, "n_clicks"),
    Input({"type": "enrich-edit-node", "name": ALL}, "n_clicks"),
    Input("enrich-new-script-btn", "n_clicks"),
    Input("enrich-add-node-btn", "n_clicks"),
    Input("enrich-panel-close", "n_clicks"),
    Input("enrich-backdrop", "n_clicks"),
    prevent_initial_call=True,
)
def _handle_panel_state(script_clicks, node_clicks, new_script, add_node, close, backdrop):
    all_clicks = list(script_clicks or []) + list(node_clicks or [])
    tid = ctx.triggered_id
    if isinstance(tid, dict):
        t = tid.get("type", "")
        name = tid.get("name", "")
        if t == "enrich-edit-script":
            return {"open": True, "type": "script", "key": name}
        if t == "enrich-edit-node":
            return {"open": True, "type": "node", "key": name}
    if tid == "enrich-new-script-btn":
        return {"open": True, "type": "new_script", "key": None}
    if tid == "enrich-add-node-btn":
        return {"open": True, "type": "new_node", "key": None}
    return _panel_close_state()


@callback(
    Output("enrich-backdrop", "style"),
    Output("enrich-panel", "style"),
    Input("enrich-panel-state", "data"),
)
def _show_panel(state):
    if state and state.get("open"):
        return _BACKDROP_SHOW, _PANEL_SHOW
    return _BACKDROP_HIDDEN, _PANEL_HIDDEN


# ── Callbacks: Populate panel form ────────────────────────────────────────────

@callback(
    Output("enrich-panel-header-icon", "children"),
    Output("enrich-panel-header-title", "children"),
    Output("enrich-script-section", "style"),
    Output("enrich-node-section", "style"),
    Output("enrich-edit-key", "value"),
    Output("enrich-edit-key", "disabled"),
    Output("enrich-edit-name", "value"),
    Output("enrich-edit-script-path", "value"),
    Output("enrich-edit-targets", "options"),
    Output("enrich-edit-targets", "value"),
    Output("enrich-edit-enabled", "value"),
    Output("enrich-edit-onlog", "value"),
    Output("enrich-edit-schedule", "value"),
    Output("enrich-edit-desc", "value"),
    Output("enrich-code-editor", "value"),
    Output("enrich-script-footer", "children"),
    Output("enrich-node-name", "value"),
    Output("enrich-node-name", "disabled"),
    Output("enrich-node-mode", "value"),
    Output("enrich-node-hosts", "value"),
    Output("enrich-node-authtype", "value"),
    Output("enrich-node-authenv", "value"),
    Output("enrich-node-authuser", "value"),
    Output("enrich-node-authpass", "value"),
    Input("enrich-panel-state", "data"),
    State("enrich-data", "data"),
    prevent_initial_call=True,
)
def _populate_panel(state, data):
    if not state or not state.get("open"):
        raise PreventUpdate

    data = data or {}
    enrichments = data.get("enrichments", [])
    clusters = data.get("clusters", [])
    panel_type = state.get("type")
    key = state.get("key")

    _script_show = {"display": "flex", "flexDirection": "column", "flex": "1", "minHeight": "0", "overflow": "hidden"}
    _script_hide = {"display": "none", "flexDirection": "column", "flex": "1", "minHeight": "0"}
    _node_show = {"display": "flex", "flexDirection": "column", "flex": "1", "minHeight": "0"}
    _node_hide = {"display": "none", "flexDirection": "column", "flex": "1", "minHeight": "0"}

    cluster_opts = [{"label": c["name"], "value": c["name"]} for c in clusters]

    # ── Script panels ─────────────────────────────────────────────────────────
    if panel_type in ("script", "new_script"):
        if panel_type == "script":
            enrich = next((e for e in enrichments if e["name"] == key), None)
        else:
            enrich = None

        icon = html.Span(html.I(className="ti ti-file-code"), className="edit-context-icon script")
        title = enrich.get("display_name", key) if enrich else "New script"
        script_path = enrich.get("script", "") if enrich else "scripts/"

        code_result = api_get(f"/api/enrich/script-content?path={script_path}") if script_path and enrich else {}
        code = code_result.get("content", _DEFAULT_SCRIPT) if code_result else _DEFAULT_SCRIPT
        if not code:
            code = _DEFAULT_SCRIPT

        footer = f"data/enrichments/{script_path} · config: data/enrichments/config/enrichments.yml" if script_path else "data/enrichments/config/enrichments.yml"

        return (
            icon, title,
            _script_show, _node_hide,
            key or "", panel_type == "script",
            enrich.get("display_name", key) if enrich else "",
            script_path,
            cluster_opts,
            enrich.get("targets", []) if enrich else ["lab"],
            ["yes"] if (enrich.get("enabled", True) if enrich else True) else [],
            ["yes"] if (enrich.get("on_log", False) if enrich else False) else [],
            enrich.get("schedule", "") if enrich else "",
            enrich.get("description", "") if enrich else "",
            code,
            footer,
            # node form (blank)
            "", False, "external", "", "none", "", "", "",
        )

    # ── Node panels ───────────────────────────────────────────────────────────
    if panel_type in ("node", "new_node"):
        cluster = next((c for c in clusters if c["name"] == key), None) if panel_type == "node" else None

        icon = html.Span(html.I(className="ti ti-server"), className="edit-context-icon node")
        title = key if cluster else "Add node"
        hosts_text = "\n".join(cluster.get("hosts", [])) if cluster else ""
        auth = cluster.get("auth_type", "none") if cluster else "none"

        return (
            icon, title,
            _script_hide, _node_show,
            # script form (blank)
            "", False, "", "", cluster_opts, [], ["yes"], [], "", "", _DEFAULT_SCRIPT, "",
            # node form
            key or "", panel_type == "node",
            cluster.get("mode", "external") if cluster else "external",
            hosts_text,
            auth,
            "", "", "",
        )

    raise PreventUpdate


# ── Callbacks: Validate script ────────────────────────────────────────────────

@callback(
    Output("enrich-validate-result", "children"),
    Input("enrich-validate-btn", "n_clicks"),
    State("enrich-code-editor", "value"),
    State("enrich-edit-script-path", "value"),
    prevent_initial_call=True,
)
def _validate_script(n, code, path):
    if not n:
        raise PreventUpdate
    result = api_post("/api/enrich/script-validate", {"content": code or "", "path": path or ""})
    if result.get("ok"):
        return html.Span("✓ Valid", style={"color": "#3B6D11", "fontWeight": "500"})
    return html.Span(f"✗ {result.get('error', 'Invalid')}", style={"color": "#A32D2D"})


# ── Callbacks: Save / delete script ──────────────────────────────────────────

@callback(
    Output("enrich-banner", "children", allow_duplicate=True),
    Output("enrich-panel-state", "data", allow_duplicate=True),
    Output("enrich-data", "data", allow_duplicate=True),
    Input("enrich-save-btn", "n_clicks"),
    State("enrich-panel-state", "data"),
    State("enrich-edit-key", "value"),
    State("enrich-edit-name", "value"),
    State("enrich-edit-script-path", "value"),
    State("enrich-edit-targets", "value"),
    State("enrich-edit-enabled", "value"),
    State("enrich-edit-onlog", "value"),
    State("enrich-edit-schedule", "value"),
    State("enrich-edit-desc", "value"),
    State("enrich-code-editor", "value"),
    prevent_initial_call=True,
)
def _save_script(n, panel_state, key, name, script_path, targets, enabled_val, onlog_val, schedule, desc, code):
    if not n:
        raise PreventUpdate

    key = (key or "").strip()
    if not key and name:
        key = "".join(c if c.isalnum() or c == "_" else "_" for c in name.lower()).strip("_")
    if not key:
        return error_banner("Config key is required"), no_update, no_update

    # Save script file
    if script_path and code:
        r = api_post("/api/enrich/script-content", {"path": script_path, "content": code})
        if r.get("error"):
            return error_banner(f"Script file save failed: {r['error']}"), no_update, no_update

    # Save enrichment YAML
    r = api_post(f"/api/enrich/enrichments/{key}", {
        "display_name": name or key,
        "script": script_path or "",
        "targets": targets or [],
        "enabled": "yes" in (enabled_val or []),
        "on_log": "yes" in (onlog_val or []),
        "schedule": schedule or "",
        "description": desc or "",
    })
    if r.get("error"):
        return error_banner(f"Save failed: {r['error']}"), no_update, no_update

    return [], _panel_close_state(), _reload_data()


@callback(
    Output("enrich-banner", "children", allow_duplicate=True),
    Output("enrich-panel-state", "data", allow_duplicate=True),
    Output("enrich-data", "data", allow_duplicate=True),
    Input("enrich-delete-btn", "n_clicks"),
    State("enrich-panel-state", "data"),
    State("enrich-edit-key", "value"),
    prevent_initial_call=True,
)
def _delete_script(n, panel_state, key):
    if not n or not key:
        raise PreventUpdate
    r = api_delete(f"/api/enrich/enrichments/{key}")
    if r.get("error"):
        return error_banner(f"Delete failed: {r['error']}"), no_update, no_update
    return [], _panel_close_state(), _reload_data()


# ── Callbacks: Save / delete node ────────────────────────────────────────────

@callback(
    Output("enrich-banner", "children", allow_duplicate=True),
    Output("enrich-panel-state", "data", allow_duplicate=True),
    Output("enrich-data", "data", allow_duplicate=True),
    Input("enrich-save-node-btn", "n_clicks"),
    State("enrich-node-name", "value"),
    State("enrich-node-mode", "value"),
    State("enrich-node-hosts", "value"),
    State("enrich-node-authtype", "value"),
    State("enrich-node-authenv", "value"),
    State("enrich-node-authuser", "value"),
    State("enrich-node-authpass", "value"),
    prevent_initial_call=True,
)
def _save_node(n, name, mode, hosts_text, auth_type, auth_env, auth_user, auth_pass):
    if not n:
        raise PreventUpdate
    name = (name or "").strip()
    if not name:
        return error_banner("Node name is required"), no_update, no_update
    if name == "lab":
        return error_banner("Cannot modify the built-in 'lab' cluster via UI"), no_update, no_update
    hosts = [h.strip() for h in (hosts_text or "").splitlines() if h.strip()]
    r = api_post(f"/api/enrich/clusters-config/{name}", {
        "mode": mode or "external",
        "hosts": hosts,
        "auth_type": auth_type or "none",
        "auth_env": auth_env or "",
        "auth_user": auth_user or "",
        "auth_pass_env": auth_pass or "",
    })
    if r.get("error"):
        return error_banner(f"Save failed: {r['error']}"), no_update, no_update
    return [], _panel_close_state(), _reload_data()


@callback(
    Output("enrich-banner", "children", allow_duplicate=True),
    Output("enrich-panel-state", "data", allow_duplicate=True),
    Output("enrich-data", "data", allow_duplicate=True),
    Input("enrich-delete-node-btn", "n_clicks"),
    State("enrich-node-name", "value"),
    prevent_initial_call=True,
)
def _delete_node(n, name):
    if not n or not name:
        raise PreventUpdate
    if name == "lab":
        return error_banner("Cannot delete the built-in 'lab' cluster"), no_update, no_update
    r = api_delete(f"/api/enrich/clusters-config/{name}")
    if r.get("error"):
        return error_banner(f"Delete failed: {r['error']}"), no_update, no_update
    return [], _panel_close_state(), _reload_data()


# ── Callbacks: Ping node from panel ──────────────────────────────────────────

@callback(
    Output("enrich-node-ping-result", "children"),
    Input("enrich-ping-node-btn", "n_clicks"),
    State("enrich-node-name", "value"),
    prevent_initial_call=True,
)
def _ping_node(n, name):
    if not n or not name:
        raise PreventUpdate
    result = api_post(f"/api/enrich/clusters/{name}/test")
    if result.get("ok"):
        lat = result.get("latency_ms", "?")
        ver = result.get("version", "")
        return html.Span(
            f"✓ Online — {lat} ms{f'  v{ver}' if ver else ''}",
            style={"color": "#3B6D11", "fontWeight": "500"},
        )
    return html.Span(
        f"✗ {result.get('error', 'Unreachable')}",
        style={"color": "#A32D2D"},
    )
