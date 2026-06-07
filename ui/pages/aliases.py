from __future__ import annotations

from typing import Any

import dash
from dash import Input, Output, State, callback, dcc, html

from ui.helpers import api_delete, api_get, api_post, error_banner, topbar

dash.register_page(__name__, path="/aliases")

ALIAS_TABS = ("all", "system", "user")


def _summary_metric(label: str, value: int, sub: str, color: str) -> html.Div:
    return html.Div(className="metric", children=[
        html.Div(label, className="metric-label"),
        html.Div(str(value), className=f"metric-val {color}"),
        html.Div(sub, className="metric-sub"),
    ])


def _grouped_aliases(data: dict[str, Any] | Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    rows = data.get("grouped_aliases", [])
    return rows if isinstance(rows, list) else []


def _managed_templates(data: dict[str, Any] | Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    rows = data.get("managed_templates", [])
    return rows if isinstance(rows, list) else []


def _summary(data: dict[str, Any] | Any) -> dict[str, int]:
    if not isinstance(data, dict):
        return {}
    summary = data.get("summary", {})
    return summary if isinstance(summary, dict) else {}


def _filter_aliases(entries: list[dict[str, Any]], query: str, tab: str) -> list[dict[str, Any]]:
    normalized = query.strip().lower()
    filtered = []
    for entry in entries:
        if tab == "system" and not entry.get("system_managed"):
            continue
        if tab == "user" and entry.get("system_managed"):
            continue
        haystack = " ".join([
            entry.get("alias", ""),
            " ".join(entry.get("indices", [])),
            " ".join(entry.get("patterns", [])),
            "system" if entry.get("system_managed") else "user",
            "wildcard" if entry.get("has_wildcard") else "",
            "future-only" if entry.get("future_only") else "",
            "locked" if not entry.get("manageable", True) else "",
        ]).lower()
        if normalized and normalized not in haystack:
            continue
        filtered.append(entry)
    return filtered


def _describe_alias(entry: dict[str, Any]) -> str:
    indices = entry.get("indices", [])
    patterns = entry.get("patterns", [])
    alias = entry.get("alias", "")
    if alias == "soc-alerts":
        return f"Unified alert view — covers elastalert2_alerts + suricata-* ({len(indices)} index{'es' if len(indices) != 1 else ''} now)."
    if alias == "suricata":
        return f"All Suricata events — {len(indices)} index{'es' if len(indices) != 1 else ''} now, new suricata-* auto-attach."
    if alias == "sigma-alerts":
        return "ElastAlert2 sigma rule hits — single backing index."
    if entry.get("future_only") and patterns:
        return f"Template ready for {patterns[0]}, no matching index yet."
    if indices and patterns:
        return f"{len(indices)} index{'es' if len(indices) != 1 else ''} + wildcard {patterns[0]}."
    if patterns:
        return f"Wildcard alias for {patterns[0]}, auto-attaches future matches."
    if indices:
        return f"{len(indices)} backing index{'es' if len(indices) != 1 else ''} attached."
    return "No backing indices yet."


def _meta_pills(entry: dict[str, Any]) -> list[str]:
    pills: list[str] = []
    if not entry.get("manageable", True):
        pills.append("Locked")
        pills.append("Startup ensured")
    if entry.get("future_only"):
        pills.append("Zero current matches")
        pills.append("Safe to pre-stage")
    if entry.get("has_wildcard") and not entry.get("future_only"):
        pills.append("Future template enabled")
    if entry.get("data_view_synced"):
        pills.append(f"Data view: {entry.get('alias', '')}")
    if not pills and entry.get("indices"):
        pills.append("Concrete sources")
    return pills[:3]


def _inventory_row(entry: dict[str, Any], selected_alias: str) -> html.Div:
    alias = entry.get("alias", "")
    tags = []
    if entry.get("system_managed"):
        tags.append(html.Span("System", className="tag blue"))
    elif entry.get("future_only"):
        tags.append(html.Span("Future-only", className="tag unknown"))
    elif entry.get("has_wildcard"):
        tags.append(html.Span("Wildcard", className="tag unknown"))
    else:
        tags.append(html.Span("User", className="tag unknown"))

    action = html.Button("Locked", className="svc-btn", disabled=True) if not entry.get("manageable", True) else html.Button(
        "Delete", id={"type": "alias-delete-btn", "alias": alias}, className="svc-btn stop"
    )

    return html.Div(className="list-row", children=[
        html.Div(className="list-main", children=[
            html.Button(
                className="alias-select-btn list-title",
                id={"type": "alias-select-btn", "alias": alias},
                children=[
                    html.Span(alias, className="mono"),
                    html.Span(tags, className="inline-tags"),
                ],
            ),
            html.Div(_describe_alias(entry), className="list-desc"),
            html.Div([html.Span(pill, className="meta-pill") for pill in _meta_pills(entry)], className="list-meta"),
        ]),
        action,
    ])


def _render_inventory(entries: list[dict[str, Any]], selected_alias: str) -> list[Any]:
    if not entries:
        return [html.P("No aliases match the current filter.", className="alias-empty")]
    return [html.Div(className="list-rows", children=[_inventory_row(entry, selected_alias) for entry in entries])]


def _inventory_tabs(entries: list[dict[str, Any]], active_tab: str) -> list[Any]:
    counts = {
        "all": len(entries),
        "system": sum(1 for row in entries if row.get("system_managed")),
        "user": sum(1 for row in entries if not row.get("system_managed")),
    }
    labels = {"all": "All", "system": "System", "user": "User"}
    return [
        html.Button(
            f"{labels[key]} ({counts[key]})",
            id={"type": "alias-tab-btn", "tab": key},
            className=f"tab{' active' if active_tab == key else ''}",
        )
        for key in ALIAS_TABS
    ]


def _selected_alias(entries: list[dict[str, Any]], requested: str) -> dict[str, Any] | None:
    if not entries:
        return None
    if requested:
        for entry in entries:
            if entry.get("alias") == requested:
                return entry
    for entry in entries:
        if entry.get("alias") == "soc-alerts":
            return entry
    return entries[0]


def _all_indices_tab(all_indices: list[dict]) -> html.Div:
    def _health_dot(h: str) -> html.Span:
        cls = {"green": "dot green", "yellow": "dot yellow", "red": "dot red"}.get(h, "dot")
        return html.Span(className=cls, style={"flexShrink": "0"})

    if not all_indices:
        return html.P("No indices found.", className="alias-empty")

    header = html.Thead(html.Tr([
        html.Th(""),
        html.Th("Index"),
        html.Th("Docs", style={"textAlign": "right"}),
        html.Th("Size", style={"textAlign": "right"}),
    ]), style={"position": "sticky", "top": "0", "background": "#fff", "zIndex": "1"})

    rows = []
    for idx in all_indices:
        name = idx.get("index", "")
        docs = idx.get("docs.count") or "—"
        size = idx.get("store.size") or "—"
        health = idx.get("health", "")
        rows.append(html.Tr([
            html.Td(_health_dot(health), style={"width": "16px", "padding": "8px 4px 8px 12px"}),
            html.Td(name, className="mono", style={"fontSize": "12px", "paddingLeft": "4px"}),
            html.Td(docs, style={"textAlign": "right", "fontSize": "12px", "color": "#888780"}),
            html.Td(size, style={"textAlign": "right", "fontSize": "12px", "color": "#888780"}),
        ]))

    return html.Div(
        html.Table([header, html.Tbody(rows)], className="tbl"),
        className="detail-card-scroll",
    )


def _detail_card(entry: dict[str, Any] | None, active_tab: str, all_indices: list[dict] | None = None) -> html.Div:
    def _tabs(alias_label: str) -> html.Div:
        return html.Div(style={"display": "flex", "alignItems": "center", "gap": "10px"}, children=[
            html.Span(alias_label, className="mono card-title") if alias_label else html.Span(),
            html.Div(style={"display": "flex"}, children=[
                html.Button("Summary", id="alias-detail-summary-btn", className=f"page-btn{' active' if active_tab == 'summary' else ''}"),
                html.Button("All indices", id="alias-detail-indices-btn", className=f"page-btn{' active' if active_tab == 'indices' else ''}"),
            ]),
        ])

    if not entry:
        return html.Div(className="card", children=[
            html.Div(className="card-header", children=[_tabs(""), html.Span()]),
            html.P("No alias matches the current filter.", className="alias-empty") if active_tab == "summary"
            else _all_indices_tab(all_indices or []),
        ])

    patterns = entry.get("patterns", [])
    indices = entry.get("indices", [])
    badge = html.Span("System", className="tag blue") if entry.get("system_managed") else html.Span("User", className="tag unknown")
    backing_desc = "No current backing indices attached." if not indices else f"{len(indices)} explicit backing index{'es' if len(indices) != 1 else ''} attached now: {', '.join(indices[:3])}"
    wildcard_desc = patterns[0] if patterns else "No wildcard template attached"

    if active_tab == "indices":
        body = _all_indices_tab(all_indices or [])
    else:
        body = html.Div(className="alias-card-body", children=[
            html.Div(className="setting-row", children=[
                html.Div(className="setting-label", children=[html.Div("Name", className="setting-name"), html.Div(entry.get("alias", ""), className="setting-desc mono")]),
                html.Button("Locked" if not entry.get("manageable", True) else "Managed", className="svc-btn", disabled=not entry.get("manageable", True)),
            ]),
            html.Div(className="setting-row", children=[html.Div(className="setting-label", children=[html.Div("Current backing indices", className="setting-name"), html.Div(backing_desc, className="setting-desc")])]),
            html.Div(className="setting-row", children=[html.Div(className="setting-label", children=[html.Div("Future wildcard coverage", className="setting-name"), html.Div(wildcard_desc, className="setting-desc mono")])]),
        ])

    return html.Div(className="card", children=[
        html.Div(className="card-header", children=[_tabs(entry.get("alias", "")), badge]),
        body,
    ])


def _templates_card(templates: list[dict[str, Any]]) -> html.Div:
    lines = []
    for row in templates:
        lines.append(f"{row.get('template', '')}\n  alias: {row.get('alias', '')}\n  pattern: {row.get('pattern', '')}\n")
    content = "\n".join(lines) if lines else "No managed alias templates."
    return html.Div(className="card fill-card", style={"padding": "12px 14px"}, children=[
        html.Div(style={"display": "flex", "justifyContent": "space-between", "alignItems": "center", "marginBottom": "10px"}, children=[
            html.Span("Managed templates", style={"fontSize": "13px", "fontWeight": "500"}),
            html.Span("Elasticsearch index templates", style={"fontSize": "11px", "color": "#888780"}),
        ]),
        html.Div(content, className="terminal fill", style={"fontSize": "11px", "whiteSpace": "pre-wrap"}),
    ])


def _create_form() -> html.Div:
    return html.Div(className="card", children=[
        html.Div(className="card-header", children=[html.Span("Create alias", className="card-title"), html.Span("Planned flow", className="tag warning")]),
        html.Div(className="alias-card-body", children=[
            html.Div(className="setting-row", children=[
                html.Div(className="setting-label", children=[html.Div("Alias name", className="setting-name"), html.Div("Short name used in queries and dashboards.", className="setting-desc")]),
                dcc.Input(id="alias-name-input", placeholder="Alias name", className="setting-input", value=""),
            ]),
            html.Div(className="setting-row", children=[
                html.Div(className="setting-label", children=[html.Div("Sources", className="setting-name"), html.Div("Space-separated indices or wildcard patterns.", className="setting-desc")]),
                dcc.Input(id="alias-sources-input", placeholder="suricata-* elastalert2_alerts", className="setting-input wide", value=""),
            ]),
            html.Div(className="setting-row", children=[
                html.Div(className="setting-label", children=[html.Div("Filter mode", className="setting-name"), html.Div("Optionally restrict which documents are visible.", className="setting-desc")]),
                html.Div(className="pages", children=[
                    html.Button("Query string", id="alias-filter-query-btn", className="page-btn active"),
                    html.Button("JSON DSL", id="alias-filter-json-btn", className="page-btn"),
                ]),
            ]),
            html.Div(className="setting-row", children=[
                html.Div(className="setting-label", children=[html.Div("Filter", className="setting-name"), html.Div("Leave blank for no filter.", className="setting-desc")]),
                dcc.Input(id="alias-filter-input", placeholder="event.dataset:suricata.alert", className="setting-input wide", value=""),
            ]),
            html.Div(style={"display": "flex", "justifyContent": "flex-end"}, children=[
                html.Button([html.I(className="ti ti-plus", style={"fontSize": "13px"}), " Create alias"], id="alias-create-btn", className="topbar-btn primary")
            ]),
        ]),
        html.Div(id="alias-form-status", style={"marginTop": "8px"}),
    ])


def layout() -> html.Div:
    data = api_get("/api/aliases")
    entries = _grouped_aliases(data)
    selected = _selected_alias(entries, "soc-alerts")
    return html.Div([
        dcc.Store(id="aliases-data-store", data=data),
        dcc.Store(id="alias-selected-store", data=(selected or {}).get("alias", "")),
        dcc.Store(id="alias-filter-mode-store", data="query_string"),
        dcc.Store(id="alias-tab-store", data="all"),
        dcc.Store(id="alias-detail-tab-store", data="summary"),
        topbar(
            "Aliases",
            html.Button([html.I(className="ti ti-refresh", style={"fontSize": "13px"}), " Refresh"], id="aliases-refresh-btn", className="topbar-btn"),
        ),
        html.Div(className="content", children=[
            html.Div(id="aliases-banner"),
            html.Div(id="aliases-metrics", className="metrics cols3"),
            html.Div(className="alias-layout", children=[
                html.Div(className="alias-stack", children=[
                    html.Div(className="card inventory-card", children=[
                        html.Div(className="card-header", children=[html.Span("Alias inventory", className="card-title"), html.Span("auto-refresh", className="card-action")]),
                        html.Div(id="alias-tabs", className="tabs"),
                        html.Div(className="inventory-toolbar", children=[
                            dcc.Input(id="alias-search-input", className="search-input", placeholder="Search aliases, sources, or tags", value="", debounce=False),
                        ]),
                        html.Div(id="aliases-inventory-list", className="inventory-scroll"),
                    ]),
                    _create_form(),
                ]),
                html.Div(className="alias-stack", children=[
                    html.Div(id="aliases-detail-card"),
                    html.Div(id="aliases-templates-card", className="fill-card-wrapper"),
                ]),
            ]),
        ]),
    ])


@callback(
    Output("alias-filter-mode-store", "data"),
    Output("alias-filter-query-btn", "className"),
    Output("alias-filter-json-btn", "className"),
    Input("alias-filter-query-btn", "n_clicks"),
    Input("alias-filter-json-btn", "n_clicks"),
    prevent_initial_call=False,
)
def _set_filter_mode(_query_clicks, _json_clicks):
    trigger = dash.ctx.triggered_id
    mode = "json" if trigger == "alias-filter-json-btn" else "query_string"
    return mode, f"page-btn{' active' if mode == 'query_string' else ''}", f"page-btn{' active' if mode == 'json' else ''}"


@callback(
    Output("alias-tab-store", "data"),
    Input({"type": "alias-tab-btn", "tab": dash.ALL}, "n_clicks"),
    State("alias-tab-store", "data"),
    prevent_initial_call=True,
)
def _set_inventory_tab(_clicks, current_tab):
    trigger = dash.ctx.triggered_id
    if isinstance(trigger, dict):
        return trigger.get("tab", current_tab or "all")
    return current_tab or "all"


@callback(
    Output("alias-selected-store", "data"),
    Input({"type": "alias-select-btn", "alias": dash.ALL}, "n_clicks"),
    State("alias-selected-store", "data"),
    prevent_initial_call=True,
)
def _set_selected_alias(_clicks, current_alias):
    trigger = dash.ctx.triggered_id
    if isinstance(trigger, dict):
        return trigger.get("alias", current_alias or "")
    return current_alias or ""


@callback(
    Output("alias-detail-tab-store", "data"),
    Input("alias-detail-summary-btn", "n_clicks"),
    Input("alias-detail-indices-btn", "n_clicks"),
    prevent_initial_call=True,
)
def _set_detail_tab(_summary_clicks, _indices_clicks):
    return "indices" if dash.ctx.triggered_id == "alias-detail-indices-btn" else "summary"


@callback(
    Output("aliases-banner", "children"),
    Output("alias-form-status", "children"),
    Output("aliases-data-store", "data"),
    Input("alias-create-btn", "n_clicks"),
    Input({"type": "alias-delete-btn", "alias": dash.ALL}, "n_clicks"),
    Input("aliases-refresh-btn", "n_clicks"),
    State("alias-name-input", "value"),
    State("alias-sources-input", "value"),
    State("alias-filter-mode-store", "data"),
    State("alias-filter-input", "value"),
    prevent_initial_call=True,
)
def _handle_alias_actions(_create, _deletes, _refresh, alias_name, sources_raw, filter_mode, filter_value):
    trigger = dash.ctx.triggered_id
    banner: list[Any] = []
    form_status: list[Any] = []
    data = api_get("/api/aliases")

    if trigger == "alias-create-btn":
        if not alias_name or not sources_raw:
            form_status = [error_banner("Alias name and at least one source are required.")]
        else:
            body = {
                "alias": alias_name,
                "sources": sources_raw.strip().split(),
                "filter_mode": filter_mode or "query_string",
                "filter_value": (filter_value or "").strip(),
            }
            result = api_post("/api/aliases", body)
            if result.get("error"):
                form_status = [error_banner(f"Error: {result['error']}")]
            else:
                banner = [html.Div([html.I(className="ti ti-circle-check"), f" Alias '{result.get('alias', alias_name)}' created successfully."], className="banner ok")]
            data = api_get("/api/aliases")
    elif isinstance(trigger, dict) and trigger.get("type") == "alias-delete-btn":
        alias_to_delete = trigger.get("alias", "")
        result = api_delete(f"/api/aliases/{alias_to_delete}")
        if result.get("error"):
            banner = [error_banner(f"Error: {result['error']}")]
        else:
            banner = [html.Div([html.I(className="ti ti-circle-check"), f" Alias '{alias_to_delete}' deleted."], className="banner ok")]
        data = api_get("/api/aliases")
    elif trigger == "aliases-refresh-btn":
        data = api_get("/api/aliases")

    return banner, form_status, data


@callback(
    Output("aliases-metrics", "children"),
    Output("alias-tabs", "children"),
    Output("aliases-inventory-list", "children"),
    Output("aliases-detail-card", "children"),
    Output("aliases-templates-card", "children"),
    Input("aliases-data-store", "data"),
    Input("alias-search-input", "value"),
    Input("alias-tab-store", "data"),
    Input("alias-detail-tab-store", "data"),
    Input("alias-selected-store", "data"),
    prevent_initial_call=False,
)
def _render_aliases(data, search_value, active_tab, detail_tab, selected_alias):  # noqa: PLR0913
    if isinstance(data, dict) and data.get("error"):
        err = [error_banner(f"Elasticsearch unavailable: {data['error']}")]
    else:
        err = []

    entries = _grouped_aliases(data)
    filtered = _filter_aliases(entries, search_value or "", active_tab or "all")
    summary = _summary(data)
    selected_entry = _selected_alias(filtered, selected_alias or "") if filtered else None
    selected_name = (selected_entry or {}).get("alias", "")

    all_indices: list[dict] = []
    if detail_tab == "indices":
        resp = api_get("/api/indices?all=true")
        all_indices = resp if isinstance(resp, list) else []

    metrics = [
        *err,
        _summary_metric("Visible aliases", summary.get("visible_aliases", len(entries)), f"{summary.get('system_aliases', 0)} system-managed, {summary.get('user_aliases', 0)} user-facing", "blue"),
        _summary_metric("Wildcard templates", summary.get("wildcard_templates", 0), "future daily indices auto-attach", "amber"),
        _summary_metric("Data views synced", summary.get("data_views_synced", 0), "Discover stays aligned with alias names", "green"),
    ]
    tabs = _inventory_tabs(entries, active_tab or "all")
    inventory = _render_inventory(filtered, selected_name)
    detail = _detail_card(selected_entry, detail_tab or "summary", all_indices)
    templates = _templates_card(_managed_templates(data))
    return metrics, tabs, inventory, detail, templates
