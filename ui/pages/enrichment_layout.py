from __future__ import annotations

from dash import dcc, html
from dash_ace import DashAceEditor

from ui.helpers import lcol, lpanel, lrow, ltable

DEFAULT_SCRIPT = '''\
"""Description of this enrichment."""

from __future__ import annotations

from enrich_sdk import EnrichmentContext


def run(ctx: EnrichmentContext) -> None:
    # ctx.update_by_query(
    #     index="soc-alerts",
    #     query={"bool": {"must": [{"term": {"field": "value"}}]}},
    #     fields={"enriched.field": "value"},
    # )
    pass
'''

PANEL_HIDDEN = {"display": "none"}
PANEL_SHOW = {
    "display": "flex", "position": "fixed",
    "left": "calc(224px + 10vw)", "right": "10vw", "top": "10vh", "bottom": "10vh",
    "background": "#f4f3ef", "zIndex": "101", "flexDirection": "column",
    "boxShadow": "0 32px 80px rgba(0,0,0,0.28), 0 8px 24px rgba(0,0,0,0.12)",
    "borderRadius": "18px", "border": "0.5px solid rgba(0,0,0,0.12)", "overflow": "hidden",
}
NODE_PANEL_SHOW = {
    **PANEL_SHOW,
    "left": "calc(224px + 14vw)", "right": "14vw", "top": "14vh", "bottom": "14vh",
}
BACKDROP_HIDDEN = {"display": "none"}
BACKDROP_SHOW = {
    "display": "block", "position": "fixed", "inset": "0",
    "background": "rgba(0,0,0,0.28)", "zIndex": "100", "cursor": "pointer",
}

_LBL = {"fontSize": "12px", "color": "#5f5e5a", "marginBottom": "5px", "display": "block"}
_INP = {"width": "100%"}


def _field(label: str, *children) -> html.Div:
    return html.Div(className="field", children=[html.Span(label, style=_LBL), *children])


def _toggle_field(label: str, toggle_id: str, label_id: str, value_id: str, default: list[str]) -> html.Div:
    return html.Div(className="field", children=[
        html.Span(label, style=_LBL),
        html.Div(className="toggle-field", children=[
            html.Button(id=toggle_id, className="toggle", n_clicks=0, type="button", **{"aria-label": label}),
            html.Span(id=label_id, className="toggle-label"),
            dcc.Checklist(id=value_id, options=[{"label": " yes", "value": "yes"}], value=default, style={"display": "none"}),
        ]),
    ])


def script_panel_section() -> html.Div:
    return html.Div(id="enrich-script-section", style={
        "display": "flex", "flexDirection": "column", "flex": "1", "minHeight": "0", "overflow": "hidden",
    }, children=[
        html.Div(className="form-grid compact enrich-script-form", style={"flexShrink": "0", "gridTemplateColumns": "1fr 1.3fr 1.7fr"}, children=[
            html.Label(className="field", children=[html.Span("Config key", style=_LBL), dcc.Input(id="enrich-edit-key", className="setting-input mono", style=_INP)]),
            html.Label(className="field", children=[html.Span("Display name", style=_LBL), dcc.Input(id="enrich-edit-name", className="setting-input", style=_INP)]),
            html.Div(className="field", children=[html.Span("Script path", style=_LBL), html.Div(className="inline-field", children=[
                dcc.Dropdown(id="enrich-edit-script-path", options=[], clearable=False, className="mono", style={"flex": "1", "minWidth": "0", "fontSize": "13px"}),
            ])]),
            html.Label(className="field", children=[html.Span("Schedule", style=_LBL),
                dcc.Input(id="enrich-edit-schedule", className="setting-input mono", placeholder="30s · 15m · 2h", style=_INP)]),
            html.Div(className="field", children=[
                html.Span("Target nodes", style=_LBL),
                dcc.Checklist(id="enrich-edit-targets", options=[], value=[], className="node-checklist-dash",
                    labelStyle={"display": "flex", "alignItems": "center", "gap": "8px", "padding": "7px 10px",
                                "fontSize": "13px", "cursor": "pointer", "borderBottom": "0.5px solid rgba(0,0,0,0.06)"},
                    inputStyle={"cursor": "pointer", "flexShrink": "0"}),
            ]),
            html.Div(style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "12px"}, children=[
                _toggle_field("Enabled", "enrich-enabled-toggle", "enrich-enabled-toggle-label", "enrich-edit-enabled", ["yes"]),
                _toggle_field("Log trigger", "enrich-onlog-toggle", "enrich-onlog-toggle-label", "enrich-edit-onlog", []),
            ]),
            html.Label(className="field", style={"gridColumn": "span 3"}, children=[html.Span("Description", style=_LBL),
                dcc.Textarea(id="enrich-edit-desc", className="setting-input",
                    style={"width": "100%", "height": "54px", "resize": "vertical", "padding": "7px 12px", "fontSize": "13px"})]),
        ]),
        html.Div(className="button-row", style={"flexShrink": "0"}, children=[
            html.Button([html.I(className="ti ti-check", style={"fontSize": "12px"}), " Validate"], id="enrich-validate-btn", className="topbar-btn", n_clicks=0),
            html.Button([html.I(className="ti ti-device-floppy", style={"fontSize": "12px"}), " Save"], id="enrich-save-btn", className="topbar-btn primary", n_clicks=0),
            html.Div(id="enrich-validate-result", style={"fontSize": "12px", "flex": "1", "color": "#5f5e5a"}),
            html.Button(html.I(className="ti ti-trash", style={"fontSize": "12px"}), id="enrich-delete-btn", className="topbar-btn danger", n_clicks=0),
        ]),
        DashAceEditor(id="enrich-code-editor", value=DEFAULT_SCRIPT, mode="python", theme="tomorrow_night",
            tabSize=4, fontSize=12, enableBasicAutocompletion=False, enableLiveAutocompletion=False,
            enableSnippets=False, wrapEnabled=True, showPrintMargin=False, highlightActiveLine=False,
            showGutter=True, className="rule-ace-editor",
            style={"flex": "1", "minHeight": "0", "width": "100%", "marginTop": "12px"}),
        html.Div(id="enrich-script-footer", style={"fontSize": "10px", "color": "#888780", "fontFamily": "monospace", "flexShrink": "0", "marginTop": "8px"}),
    ])


def node_panel_section() -> html.Div:
    return html.Div(id="enrich-node-section", style={
        "display": "none", "flexDirection": "column", "flex": "1", "minHeight": "0",
    }, children=[
        html.Div(className="form-grid compact", style={"flexShrink": "0"}, children=[
            html.Label(className="field", children=[html.Span("Node name", style=_LBL), dcc.Input(id="enrich-node-name", className="setting-input mono", style=_INP)]),
            html.Label(className="field", children=[html.Span("Mode", style=_LBL),
                dcc.Dropdown(id="enrich-node-mode",
                    options=[{"label": "Internal", "value": "internal"}, {"label": "External", "value": "external"}],
                    value="external", clearable=False, style={"fontSize": "13px"})]),
            html.Label(className="field", style={"gridColumn": "span 2"}, children=[html.Span("Hosts (one per line)", style=_LBL),
                dcc.Textarea(id="enrich-node-hosts", className="setting-input", placeholder="https://es01.example:9200",
                    style={"width": "100%", "height": "70px", "resize": "vertical", "padding": "7px 12px", "fontSize": "13px"})]),
            html.Label(className="field", style={"gridColumn": "span 2"}, children=[html.Span("Auth type", style=_LBL),
                dcc.Dropdown(id="enrich-node-authtype",
                    options=[{"label": "None", "value": "none"}, {"label": "API Key (env var)", "value": "api_key"}, {"label": "Basic auth", "value": "basic"}],
                    value="none", clearable=False, style={"fontSize": "13px"})]),
            html.Label(className="field", style={"gridColumn": "span 2"}, children=[html.Span("API Key env var", style=_LBL),
                dcc.Input(id="enrich-node-authenv", className="setting-input mono", placeholder="ES_API_KEY", style=_INP)]),
            html.Label(className="field", children=[html.Span("Username", style=_LBL),
                dcc.Input(id="enrich-node-authuser", className="setting-input", placeholder="elastic", style=_INP)]),
            html.Label(className="field", children=[html.Span("Password env var", style=_LBL),
                dcc.Input(id="enrich-node-authpass", className="setting-input mono", placeholder="ES_PASS", style=_INP)]),
        ]),
        html.Div(className="button-row", style={"flexShrink": "0"}, children=[
            html.Button([html.I(className="ti ti-network", style={"fontSize": "12px"}), " Ping"], id="enrich-ping-node-btn", className="topbar-btn", n_clicks=0),
            html.Button([html.I(className="ti ti-device-floppy", style={"fontSize": "12px"}), " Save"], id="enrich-save-node-btn", className="topbar-btn primary", n_clicks=0),
            html.Button(html.I(className="ti ti-trash", style={"fontSize": "12px"}), id="enrich-delete-node-btn", className="topbar-btn danger", n_clicks=0, style={"marginLeft": "auto"}),
        ]),
        html.Div(id="enrich-node-ping-result", style={"marginTop": "10px", "fontSize": "12px"}),
        html.Div("data/enrichments/config/clusters.yml",
            style={"fontSize": "10px", "color": "#888780", "fontFamily": "monospace", "marginTop": "auto", "paddingTop": "12px", "flexShrink": "0"}),
    ])


def edit_panel() -> html.Div:
    return html.Div(id="enrich-panel", style=PANEL_HIDDEN, children=[
        html.Div(className="edit-panel-header", children=[
            html.Div(id="enrich-panel-header-icon"),
            html.Span(id="enrich-panel-header-title", className="edit-panel-title"),
            html.Button(html.I(className="ti ti-x", style={"fontSize": "13px"}), id="enrich-panel-close", className="topbar-btn", n_clicks=0),
        ]),
        html.Div(className="edit-panel-body", children=[
            html.Div(className="card", style={"flex": "1", "display": "flex", "flexDirection": "column", "overflow": "hidden", "minHeight": "0"}, children=[
                script_panel_section(),
                node_panel_section(),
            ]),
        ]),
    ])


def overview_section() -> html.Div:
    return html.Div(id="enrich-overview-section", className="content", children=[
        html.Div(id="enrich-metrics", className="metrics"),
        html.Div(style={**lrow(min_col="320px", gap="14px"), "flex": "1", "minHeight": "0", "marginBottom": "16px"}, children=[
            html.Div(style={**lcol(gap="14px"), "flex": "1"}, children=[
                html.Div(className="card", style=ltable(min_h=160, fill=True), children=[
                    html.Div(className="card-header", children=[
                        html.Span("Target cluster nodes", className="card-title"),
                        html.Div(style={"display": "flex", "alignItems": "center", "gap": "8px"}, children=[
                            html.Span("clusters.yml", className="card-action mono"),
                            html.Button([html.I(className="ti ti-plus", style={"fontSize": "11px"}), " Add node"], id="enrich-add-node-btn", className="rule-btn", n_clicks=0),
                        ]),
                    ]),
                    html.Div(id="enrich-nodes-table", className="table-panel-body"),
                ]),
                html.Div(className="card", style=lpanel(min_h=120, fill=True), children=[
                    html.Div(className="card-header", children=[
                        html.Span("Run console", className="card-title"),
                        html.Span(id="enrich-console-badge"),
                    ]),
                    html.Div(id="enrich-console-body", children=[
                        html.Div("Run an enrichment to see output here.", style={"fontSize": "12px", "color": "#888780", "padding": "4px 0"}),
                    ]),
                ]),
            ]),
            html.Div(style={**lcol(gap="14px"), "flex": "1"}, children=[
                html.Div(className="card", style=ltable(min_h=300, fill=True), children=[
                    html.Div(className="card-header", children=[
                        html.Span("Configured enrichments", className="card-title"),
                        html.Button([html.I(className="ti ti-plus", style={"fontSize": "11px"}), " New script"], id="enrich-new-script-btn", className="rule-btn", n_clicks=0),
                    ]),
                    html.Div(className="filterbar", style={"marginBottom": "8px", "flexShrink": "0"}, children=[
                        html.I(className="ti ti-search", style={"fontSize": "14px", "color": "#888780", "flexShrink": "0"}),
                        dcc.Input(id="enrich-search", placeholder="Search enrichments…", debounce=True,
                            className="search-input", style={"flex": "1", "paddingLeft": "10px", "backgroundImage": "none"}),
                    ]),
                    html.Div(id="enrich-list-rows", className="list-rows compact-list table-panel-body"),
                ]),
            ]),
        ]),
    ])


def render_runs_table(runs: list[dict]) -> list:
    if not runs:
        return [html.Div("No enrichment runs recorded yet.", style={"fontSize": "13px", "color": "#888780", "padding": "20px 0"})]
    hdr_style = {"display": "grid", "gridTemplateColumns": "1fr 120px 100px 80px 80px 100px",
                 "gap": "12px", "padding": "6px 0", "borderBottom": "0.5px solid rgba(0,0,0,0.1)",
                 "fontSize": "11px", "fontWeight": "600", "color": "#888780", "textTransform": "uppercase"}
    row_style = {**hdr_style, "padding": "8px 0", "borderBottom": "0.5px solid rgba(0,0,0,0.06)",
                 "alignItems": "center", "fontSize": "13px", "fontWeight": "normal"}
    rows: list = [html.Div(style=hdr_style, children=["Run ID", "Enrichment", "Cluster", "Ops", "Dry", ""])]
    for r in runs:
        run_id = r.get("run_id", "")
        ops = r.get("docs_updated", 0) + r.get("docs_created", 0) + r.get("docs_deleted", 0)
        is_dry = r.get("dry_run", False)
        ts = (r.get("timestamp", "") or run_id)[:16].replace("T", " ")
        rows.append(html.Div(style=row_style, children=[
            html.Span(ts, className="mono", style={"fontSize": "11px", "color": "#5f5e5a"}),
            html.Span(r.get("enrichment", "—"), style={"fontWeight": "500"}),
            html.Span(r.get("cluster", "—"), className="mono"),
            html.Span(str(ops)),
            html.Span("dry" if is_dry else "live", className=f"tag {'warning' if is_dry else 'running'}", style={"fontSize": "10px"}),
            html.Button([html.I(className="ti ti-history", style={"fontSize": "11px"}), " Rollback"],
                id={"type": "enrich-rollback-run", "run_id": run_id}, className="rule-btn", n_clicks=0, style={"fontSize": "11px"})
            if not is_dry else html.Span("—", style={"color": "#888780", "fontSize": "11px"}),
        ]))
    return rows
