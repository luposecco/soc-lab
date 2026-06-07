from __future__ import annotations

from typing import Any

import dash
from dash import Input, Output, State, callback, dcc, html

from ui.helpers import api_delete, api_get, api_post, error_banner, topbar

dash.register_page(__name__, path="/settings")


# ── helpers ──────────────────────────────────────────────────────────────────

def _section_label(text: str) -> html.Div:
    return html.Div(text, style={
        "fontSize": "11px", "fontWeight": "500", "color": "#888780",
        "textTransform": "uppercase", "letterSpacing": "0.05em", "padding": "4px 2px 0",
    })


def _indices_table(indices: list[dict[str, Any]]) -> html.Div:
    def dot(health: str) -> html.Div:
        c = {"green": "green", "yellow": "yellow", "red": "red"}.get(health, "yellow")
        return html.Div(className=f"dot {c}", style={"display": "inline-block", "verticalAlign": "middle"})

    if not indices:
        return html.P("No indices found.", style={"fontSize": "12px", "color": "#888780", "padding": "8px 0"})

    rows = [
        html.Tr([
            html.Td([dot(idx.get("health", "yellow")), html.Span(idx.get("index", ""), className="mono", style={"marginLeft": "6px"})]),
            html.Td(idx.get("status", "—"), style={"fontSize": "11px", "color": "#888780"}),
            html.Td(f'{int(idx.get("docs.count") or 0):,}', style={"textAlign": "right", "fontSize": "12px", "fontWeight": "500"}),
            html.Td(idx.get("store.size", "—"), style={"fontSize": "11px", "color": "#888780", "textAlign": "right"}),
        ])
        for idx in indices
    ]
    header = html.Thead(html.Tr([
        html.Th("Index"),
        html.Th("Status"),
        html.Th("Docs", style={"textAlign": "right"}),
        html.Th("Size", style={"textAlign": "right"}),
    ]))
    return html.Div(html.Table([header, html.Tbody(rows)], className="tbl"))


def _aliases_table(aliases: list[dict[str, Any]], templates: list[dict[str, Any]]) -> html.Div:
    # Group alias → backing indices
    seen: dict[str, list[str]] = {}
    alias_meta: dict[str, dict[str, Any]] = {}
    for row in aliases:
        alias = row.get("alias", "")
        idx = row.get("index", "")
        seen.setdefault(alias, []).append(idx)
        alias_meta[alias] = row

    # Templates per alias
    tmpl_by_alias: dict[str, list[str]] = {}
    for t in templates:
        a = t.get("alias", "")
        tmpl_by_alias.setdefault(a, []).append(t.get("pattern", ""))

    if not seen:
        return html.P("No aliases found. Create one below.", style={"fontSize": "12px", "color": "#888780", "padding": "8px 0"})

    rows = []
    for alias, idxs in seen.items():
        patterns = tmpl_by_alias.get(alias, [])
        backing_text = ", ".join(idxs[:3]) + ("…" if len(idxs) > 3 else "")
        if patterns:
            backing_text += f" + wildcard: {', '.join(patterns[:2])}"
        manageable = alias_meta.get(alias, {}).get("manageable", True)
        system_managed = alias_meta.get(alias, {}).get("system_managed", False)
        alias_cell = [html.Span(alias, className="mono")]
        if system_managed:
            alias_cell.append(html.Span("System", className="tag blue", style={"marginLeft": "8px"}))
        rows.append(html.Tr([
            html.Td(alias_cell),
            html.Td(backing_text, style={"fontSize": "11px", "color": "#888780"}),
            html.Td(
                html.Button(
                    "Delete" if manageable else "Locked",
                    id={"type": "alias-delete-btn", "alias": alias},
                    className="svc-btn stop" if manageable else "svc-btn",
                    disabled=not manageable,
                ),
                style={"textAlign": "right"},
            ),
        ]))

    header = html.Thead(html.Tr([html.Th("Alias"), html.Th("Backing indices"), html.Th()]))
    return html.Div(html.Table([header, html.Tbody(rows)], className="tbl"))


def _create_alias_form() -> html.Div:
    return html.Div(
        className="card",
        style={"marginTop": "0"},
        children=[
            html.Div(className="card-header", children=[html.Span("Create alias", className="card-title")]),
            html.Div(
                style={"display": "flex", "gap": "8px", "alignItems": "flex-start", "flexWrap": "wrap"},
                children=[
                    html.Div([
                        html.Div("Alias name", style={"fontSize": "11px", "color": "#888780", "marginBottom": "4px"}),
                        dcc.Input(id="alias-name-input", placeholder="e.g. so-alerts", className="setting-input", style={"width": "180px"}),
                    ]),
                    html.Div([
                        html.Div("Source index / pattern", style={"fontSize": "11px", "color": "#888780", "marginBottom": "4px"}),
                        dcc.Input(id="alias-sources-input", placeholder="e.g. suricata-* filebeat-*", className="setting-input", style={"width": "260px"}),
                    ]),
                    html.Div(
                        html.Button([html.I(className="ti ti-plus", style={"fontSize": "13px"}), " Create"], id="alias-create-btn", className="topbar-btn primary"),
                        style={"paddingTop": "19px"},
                    ),
                ],
            ),
            html.Div(id="alias-form-status", style={"marginTop": "8px"}),
        ],
    )


# ── layout ────────────────────────────────────────────────────────────────────

def layout() -> html.Div:
    data = api_get("/api/aliases")
    indices_data = api_get("/api/indices")

    aliases = data.get("aliases", []) if isinstance(data, dict) else []
    templates = data.get("managed_templates", []) if isinstance(data, dict) else []
    indices = indices_data if isinstance(indices_data, list) else []
    api_err = data.get("error") if isinstance(data, dict) else str(data)

    return html.Div([
        topbar(
            "Indices & Aliases",
            html.Button([html.I(className="ti ti-refresh", style={"fontSize": "13px"}), " Refresh"], id="settings-refresh-btn", className="topbar-btn"),
        ),
        html.Div(id="settings-banner"),
        html.Div(className="content", children=[
            error_banner(f"Elasticsearch unavailable: {api_err}") if api_err else None,
            html.Div(id="settings-alias-table-wrap", children=[
                _section_label("Aliases"),
                html.Div(className="card", children=[_aliases_table(aliases, templates)]),
                _create_alias_form(),
            ]),
            html.Div(id="settings-indices-wrap", children=[
                _section_label("Indices"),
                html.Div(className="card", children=[_indices_table(indices)]),
            ]),
        ]),
    ])


# ── callbacks ─────────────────────────────────────────────────────────────────

@callback(
    Output("settings-alias-table-wrap", "children"),
    Output("settings-banner", "children"),
    Input("alias-create-btn", "n_clicks"),
    Input({"type": "alias-delete-btn", "alias": dash.ALL}, "n_clicks"),
    Input("settings-refresh-btn", "n_clicks"),
    State("alias-name-input", "value"),
    State("alias-sources-input", "value"),
    prevent_initial_call=True,
)
def _handle_actions(_create, _deletes, _refresh, alias_name, sources_raw):
    from dash import ctx
    banner = []
    trigger = ctx.triggered_id

    if trigger == "alias-create-btn":
        if not alias_name or not sources_raw:
            banner = [error_banner("Alias name and at least one source are required.")]
        else:
            sources = sources_raw.strip().split()
            result = api_post("/api/aliases", {"alias": alias_name, "sources": sources})
            if result.get("error"):
                banner = [error_banner(f"Error: {result['error']}")]
            else:
                banner = [html.Div(
                    f"Alias '{result.get('alias', alias_name)}' created successfully.",
                    style={"background": "#EAF3DE", "color": "#3B6D11", "borderRadius": "8px", "padding": "10px 14px", "fontSize": "12px"},
                )]

    elif isinstance(trigger, dict) and trigger.get("type") == "alias-delete-btn":
        alias_to_delete = trigger["alias"]
        result = api_delete(f"/api/aliases/{alias_to_delete}")
        if result.get("error"):
            banner = [error_banner(f"Error: {result['error']}")]
        else:
            banner = [html.Div(
                f"Alias '{alias_to_delete}' deleted.",
                style={"background": "#EAF3DE", "color": "#3B6D11", "borderRadius": "8px", "padding": "10px 14px", "fontSize": "12px"},
            )]

    data = api_get("/api/aliases")
    aliases = data.get("aliases", []) if isinstance(data, dict) else []
    templates = data.get("managed_templates", []) if isinstance(data, dict) else []

    return [
        _section_label("Aliases"),
        html.Div(className="card", children=[_aliases_table(aliases, templates)]),
        _create_alias_form(),
    ], banner
