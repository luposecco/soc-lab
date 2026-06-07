from __future__ import annotations

from typing import Any
from urllib.parse import quote as _url_quote

import dash
from dash import ALL, Input, Output, State, callback, ctx, dcc, html
from dash_ace import DashAceEditor

from ui.helpers import api_delete, api_get, api_post, error_banner, metric_card, topbar

dash.register_page(__name__, path="/rules")

_TYPE_OPTS = [
    {"label": "All types", "value": ""},
    {"label": "Sigma", "value": "sigma"},
    {"label": "Suricata", "value": "suricata"},
    {"label": "ElastAlert", "value": "elastalert"},
]
_STATUS_OPTS = [
    {"label": "All statuses", "value": ""},
    {"label": "Enabled", "value": "enabled"},
    {"label": "Disabled", "value": "disabled"},
    {"label": "Error", "value": "error"},
]
_SOURCE_OPTS = [
    {"label": "All sources", "value": ""},
    {"label": "Local", "value": "local"},
    {"label": "ET / imported", "value": "docker"},
]
_GUI_SURI_DIR = "data/rules/suricata/gui"
_GUI_SIGMA_DIR = "data/rules/sigma/gui"


def _type_tag(t: str) -> html.Span:
    cls = {"sigma": "blue", "suricata": "running", "elastalert": "warning"}.get(t, "unknown")
    return html.Span(t.capitalize(), className=f"tag {cls}")


def _source_tag(source: str) -> html.Span | None:
    if source == "docker":
        return html.Span("ET", className="tag purple")
    return None


def _rule_row(f: dict[str, Any]) -> html.Tr:
    file_path = f.get("file", "")
    source = f.get("source", "local")
    is_docker = source == "docker"
    is_suricata = f.get("type") == "suricata"

    if file_path.startswith("docker:suricata:"):
        base = file_path.split("#")[0]
        display_path = base.split("/")[-1] if "/" in base else base
    elif "#" in file_path:
        display_path = file_path.split("#")[0].split("/")[-1]
    else:
        display_path = file_path

    tags = [_type_tag(f.get("type", ""))]
    src_tag = _source_tag(source)
    if src_tag:
        tags.append(src_tag)

    btn_icon = "ti ti-eye" if is_docker else "ti ti-pencil"
    btn_label = " View" if is_docker else " Edit"

    sid = f.get("sid", "")
    status = f.get("status", "enabled")
    if status == "disabled":
        status_tag = html.Span("Disabled", className="tag warning")
    elif status == "error":
        status_tag = html.Span("Error", className="tag stopped")
    else:
        status_tag = html.Span("Enabled", className="tag running")

    name_cell = html.Div([
        html.Span(f.get("name", f.get("stem", "—")), style={"fontWeight": "500", "fontSize": "13px", "lineHeight": "1.3"}),
        html.Div([
            status_tag,
            *tags,
            html.Span(display_path, className="mono", style={"fontSize": "10px", "color": "#888780"}),
            html.Span(f"sid:{sid}", style={"fontSize": "10px", "color": "#aaa89e", "fontFamily": "monospace"}) if sid and is_suricata else None,
        ], style={"display": "flex", "alignItems": "center", "gap": "5px", "marginTop": "4px", "flexWrap": "wrap"}),
    ])

    return html.Tr([
        html.Td(name_cell, style={"width": "100%"}),
        html.Td(
            html.Button([html.I(className=btn_icon, style={"fontSize": "11px"}), btn_label],
                        id={"type": "rules-edit-btn", "file": file_path},
                        className="rule-btn", n_clicks=0),
            style={"whiteSpace": "nowrap"},
        ),
    ])


def _rules_table(files: list[dict], total: int | None = None) -> list:
    if not files:
        return [html.Div("No rules found.", style={"fontSize": "12px", "color": "#888780", "padding": "12px 0"})]
    header = html.Thead(html.Tr([
        html.Th("Name"), html.Th(""),
    ]))
    rows = [html.Table([header, html.Tbody([_rule_row(f) for f in files])], className="tbl")]
    if total is not None and total > len(files):
        rows.append(html.Div(f"Showing {len(files)} of {total:,} · search to filter",
                             style={"fontSize": "11px", "color": "#888780", "padding": "8px 0",
                                    "textAlign": "center", "flexShrink": "0"}))
    return rows


_SURI_ACTIONS = {"alert", "pass", "drop", "reject", "rejectsrc", "rejectdst", "rejectboth"}


def _ace_mode(path: str, content: str) -> str:
    if path.endswith(".rules"):
        return "snort"
    if not path and content:
        first = content.lstrip().split(None, 1)
        if first and first[0] in _SURI_ACTIONS:
            return "snort"
    return "yaml"


def _editor_card(path: str = "", name: str = "", content: str = "", readonly: bool = False) -> html.Div:
    if not path:
        status_el = html.Span("Empty", className="tag warning")
    elif readonly:
        status_el = html.Span("Read-only · ET", className="tag purple")
    else:
        status_el = html.Span("Loaded", className="tag running")
    mode = _ace_mode(path, content)
    return html.Div(className="card", style={"display": "flex", "flexDirection": "column",
                                              "height": "100%", "overflow": "hidden"}, children=[
        html.Div(className="card-header", children=[
            html.Span("Rule editor", className="card-title"),
            status_el,
        ]),
        html.Div(style={"display": "flex", "flexDirection": "column", "gap": "10px", "flex": "1", "minHeight": "0"}, children=[
            dcc.Input(id="rules-editor-name", value=name, placeholder="Rule name / title",
                      className="setting-input", style={"width": "100%", "boxSizing": "border-box"},
                      disabled=readonly),
            html.Div(style={"display": "flex", "gap": "8px", "alignItems": "center", "flexWrap": "wrap"}, children=[
                html.Button([html.I(className="ti ti-check", style={"fontSize": "12px"}), " Validate"],
                            id="rules-validate-btn", className="topbar-btn", n_clicks=0),
                html.Button([html.I(className="ti ti-device-floppy", style={"fontSize": "12px"}), " Save"],
                            id="rules-save-btn", className="topbar-btn primary", n_clicks=0,
                            style={"display": "none" if readonly else "flex"}),
                html.Button(html.I(className="ti ti-trash", style={"fontSize": "12px"}),
                            id="rules-delete-btn", className="topbar-btn danger", n_clicks=0,
                            style={"marginLeft": "auto", "display": "none" if readonly else "flex"}),
                html.Span("Built-in ET rule — read only",
                          style={"fontSize": "11px", "color": "#888780",
                                 "display": "block" if readonly else "none"}),
            ]),
            DashAceEditor(
                id="rules-editor-content",
                value=content,
                mode=mode,
                theme="tomorrow_night",
                tabSize=2,
                fontSize=12,
                enableBasicAutocompletion=False,
                enableLiveAutocompletion=False,
                enableSnippets=False,
                wrapEnabled=True,
                readOnly=readonly,
                showGutter=True,
                showPrintMargin=False,
                highlightActiveLine=False,
                placeholder="Paste or write rule YAML / Suricata rule here…",
                className="rule-ace-editor",
                style={"flex": "1", "minHeight": "0", "width": "100%"},
            ),
            html.Div(path or "No file selected", id="rules-editor-path",
                     style={"fontSize": "10px", "color": "#888780", "fontFamily": "monospace"}),
        ]),
    ])


def _load_sigma_elastalert() -> dict[str, list]:
    result: dict[str, list] = {}
    for t in ("sigma", "elastalert"):
        resp = api_get(f"/api/rules/files?type={t}")
        result[t] = resp.get("files", []) if isinstance(resp, dict) else []
    return result


def _metrics_row(
    sigma_n: int,
    suricata_total: int,
    elastalert_n: int,
    status_data: dict[str, Any] | None = None,
    suricata_rule_error: bool = False,
) -> html.Div:
    status_data = status_data or {}
    suricata_error = status_data.get("suricata", {}).get("status") == "fail" or suricata_rule_error
    sigma_error = status_data.get("sigma", {}).get("status") == "fail"
    elastalert_error = sigma_error
    total_error = suricata_error or sigma_error or elastalert_error
    suri_label = f"{suricata_total:,}" if suricata_total is not None else "…"
    total = sigma_n + suricata_total + elastalert_n
    total_label = f"{total:,}" if suricata_total is not None else "…"
    return html.Div(className="metrics", children=[
        metric_card("Total rules", total_label, "all types", "red" if total_error else "blue"),
        metric_card("Sigma", str(sigma_n), "detection rules", "red" if sigma_error else "blue"),
        metric_card("Suricata", suri_label, "IDS rules", "red" if suricata_error else "blue"),
        metric_card("ElastAlert", str(elastalert_n), "alert rules", "red" if elastalert_error else "blue"),
    ])


def layout() -> html.Div:
    # Return immediately — callback with prevent_initial_call=False populates data
    all_items: list[dict] = []

    return html.Div([
        topbar(
            "Rules",
            dcc.Interval(id="rules-poll", interval=60_000, n_intervals=0),
            html.Button([html.I(className="ti ti-refresh", style={"fontSize": "13px"}), " Refresh"],
                        id="rules-refresh-btn", className="topbar-btn", n_clicks=0),
            html.Button([html.I(className="ti ti-player-play", style={"fontSize": "13px"}), " Compile"],
                        id="rules-compile-btn", className="topbar-btn primary", n_clicks=0),
        ),
        html.Div(id="rules-banner"),
        html.Div(className="content", children=[
            html.Div(id="rules-metrics", children=_metrics_row(0, 0, 0), style={"flexShrink": "0"}),  # populated by callback

            # filter bar
            html.Div(className="filterbar", style={"marginBottom": "4px", "flexShrink": "0"}, children=[
                html.I(className="ti ti-search", style={"fontSize": "14px", "color": "#888780", "flexShrink": "0"}),
                dcc.Input(id="rules-search", placeholder="Search rules…", debounce=True,
                          className="search-input", style={"flex": "1"}),
                dcc.Dropdown(id="rules-type-filter", options=_TYPE_OPTS, value="", clearable=False,
                             style={"width": "140px", "fontSize": "12px"}, placeholder="All types"),
                dcc.Dropdown(id="rules-status-filter", options=_STATUS_OPTS, value="", clearable=False,
                             style={"width": "140px", "fontSize": "12px"}, placeholder="All statuses"),
                dcc.Dropdown(id="rules-source-filter", options=_SOURCE_OPTS, value="", clearable=False,
                             style={"width": "150px", "fontSize": "12px"}, placeholder="All sources"),
                dcc.Upload(
                    id="rules-import-upload",
                    children=html.Button([html.I(className="ti ti-file-import", style={"fontSize": "12px"}), " Import"],
                                         className="topbar-btn"),
                    multiple=False,
                ),
                html.Button([html.I(className="ti ti-plus", style={"fontSize": "12px"}), " New rule"],
                            id="rules-new-btn", className="topbar-btn primary", n_clicks=0),
            ]),

            # main split — 50/50, both cards fill remaining viewport height
            html.Div(className="row2", style={"flex": "1", "minHeight": "300px"}, children=[

                # left: rule list
                html.Div(className="card", style={"display": "flex", "flexDirection": "column",
                                                    "overflow": "hidden", "minHeight": "300px"}, children=[
                    html.Div(className="card-header", children=[
                        html.Span("Rules", className="card-title"),
                        html.Span(id="rules-count-label", style={"fontSize": "11px", "color": "#888780"}),
                    ]),
                    html.Div(id="rules-list", children=_rules_table(all_items),
                             style={"flex": "1", "overflowY": "auto", "minHeight": "0"}),
                ]),

                # right: editor — fills same height as left card via grid stretch
                html.Div(id="rules-editor-wrap", children=_editor_card()),
            ]),
        ]),

        dcc.Store(id="rules-selected-path", data=""),
        dcc.Store(id="rules-active-tab", data=""),
    ])


# ── update rule list ──────────────────────────────────────────────────────────

@callback(
    Output("rules-list", "children"),
    Output("rules-count-label", "children"),
    Output("rules-metrics", "children"),
    Output("rules-banner", "children"),
    Input("rules-poll", "n_intervals"),
    Input("rules-refresh-btn", "n_clicks"),
    Input("rules-compile-btn", "n_clicks"),
    Input("rules-search", "value"),
    Input("rules-type-filter", "value"),
    Input("rules-status-filter", "value"),
    Input("rules-source-filter", "value"),
    prevent_initial_call=False,
)
def _update_list(_poll, _refresh, _compile, search, type_filter, status_filter, source_filter):
    banner: list = []
    trigger = ctx.triggered_id

    if trigger == "rules-compile-btn" and (_compile or 0) > 0:
        result = api_post("/api/rules/compile")
        if result.get("error"):
            banner = [error_banner(f"Compile failed: {result['error']}")]
        else:
            ok = (
                result.get("suricata", {}).get("ok", False)
                and result.get("sigma", {}).get("ok", False)
                and not result.get("suricata", {}).get("error_count", 0)
            )
            banner = [html.Div("Compile successful", className="banner ok") if ok
                      else error_banner("Compile completed with errors")]

    q = (search or "").strip()
    items: list[dict] = []

    # suricata individual rules — show first 20 for display, count separately
    if not type_filter or type_filter == "suricata":
        suri_limit = 50 if q else 20
        suri_params = f"/api/rules/suricata-rules?limit={suri_limit}"
        if q:
            suri_params += f"&q={_url_quote(q, safe='')}"
        if status_filter:
            suri_params += f"&status={status_filter}"
        if source_filter:
            suri_params += f"&source={source_filter}"
        suri_resp = api_get(suri_params)
        if isinstance(suri_resp, dict) and not suri_resp.get("error"):
            items.extend(suri_resp.get("rules", []))

    # sigma + elastalert (file-level)
    sigma_files: list[dict] = []
    elastalert_files: list[dict] = []
    for t in ("sigma", "elastalert"):
        if type_filter and type_filter != t:
            continue
        if source_filter == "docker":
            continue
        resp = api_get(f"/api/rules/files?type={t}")
        files = resp.get("files", []) if isinstance(resp, dict) else []
        if q:
            files = [f for f in files if q.lower() in f.get("name", "").lower() or q.lower() in f.get("file", "").lower()]
        if source_filter:
            files = [f for f in files if f.get("source") == source_filter]
        if status_filter:
            if status_filter == "disabled":
                files = []
            else:
                files = [f for f in files if f.get("status") == status_filter]
        if t == "sigma":
            sigma_files = files
        else:
            elastalert_files = files
        items.extend(files)

    sigma_n = len(sigma_files)
    elastalert_n = len(elastalert_files)
    count_label = f"{len(items)} shown · search to filter"

    # real suricata count from count endpoint (cached 5 min on server)
    count_status = "disabled" if status_filter == "disabled" else ("error" if status_filter == "error" else ("all" if not status_filter else "enabled"))
    suri_count_resp = api_get(f"/api/rules/suricata-count?status={count_status}")
    suri_total = suri_count_resp.get("count", 0) if isinstance(suri_count_resp, dict) else 0

    # for sigma/elastalert totals when viewing all types, use unfiltered counts
    if not type_filter and not q and not status_filter and not source_filter:
        se = _load_sigma_elastalert()
        sigma_n = len(se.get("sigma", []))
        elastalert_n = len(se.get("elastalert", []))

    status_data = api_get("/api/rules/status")
    if not isinstance(status_data, dict):
        status_data = {}

    suri_error_resp = api_get("/api/rules/suricata-rules?limit=1&status=error")
    suricata_rule_error = bool(isinstance(suri_error_resp, dict) and suri_error_resp.get("rules"))

    table = _rules_table(items, total=len(items) if len(items) < suri_total else None)
    return table, count_label, _metrics_row(sigma_n, suri_total, elastalert_n, status_data, suricata_rule_error), banner


# ── load rule into editor ─────────────────────────────────────────────────────

@callback(
    Output("rules-editor-wrap", "children"),
    Output("rules-selected-path", "data"),
    Input({"type": "rules-edit-btn", "file": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def _load_rule(n_clicks):
    if not ctx.triggered_id or not any(n_clicks):
        return dash.no_update, dash.no_update
    path = ctx.triggered_id["file"]
    resp = api_get(f"/api/rules/file?path={_url_quote(path, safe='')}")
    if resp.get("error"):
        return _editor_card(), ""
    content = resp.get("content", "")
    readonly = resp.get("readonly", False)
    name = ""
    # extract name from content
    for line in content.splitlines():
        s = line.strip()
        if s.startswith("title:") or s.startswith("name:"):
            name = s.split(":", 1)[1].strip(); break
        if "msg:" in s:
            name = s.split("msg:", 1)[1].split(";")[0].strip().strip('"'); break
    return _editor_card(path=path, name=name, content=content, readonly=readonly), path


# ── save ──────────────────────────────────────────────────────────────────────

@callback(
    Output("rules-banner", "children", allow_duplicate=True),
    Output("rules-editor-wrap", "children", allow_duplicate=True),
    Input("rules-save-btn", "n_clicks"),
    State("rules-selected-path", "data"),
    State("rules-editor-name", "value"),
    State("rules-editor-content", "value"),
    State("rules-type-filter", "value"),
    prevent_initial_call=True,
)
def _save_rule(_n, path, name, content, type_filter):
    if not _n:
        return dash.no_update, dash.no_update
    if not content:
        return [error_banner("Editor is empty")], dash.no_update
    if path and path.startswith("docker:"):
        return [error_banner("Built-in ET rules are read-only and cannot be saved")], dash.no_update
    inferred_tab = "suricata" if path and ("#" in path or path.endswith(".rules") or "/suricata/" in path) else ""
    tab = inferred_tab or type_filter or "sigma"
    stem = (name or "new-rule").lower().replace(" ", "-").replace("/", "-")

    # Suricata individual rules use dedicated endpoint
    if tab == "suricata" and path and "#" in path:
        result = api_post("/api/rules/suricata-rule", {"path": path, "content": content})
        if result.get("error"):
            return [error_banner(f"Save failed: {result['error']}")], dash.no_update
        base_path, _, line_ref = path.partition("#")
        line_suffix = f" (line {int(line_ref) + 1})" if line_ref.isdigit() else ""
        return [html.Div(f"Updated: {base_path}{line_suffix}", className="banner ok")], _editor_card(path=path, name=name, content=content)

    if tab == "suricata":
        if not path:
            path = f"{_GUI_SURI_DIR}/{stem}.rules"
        result = api_post("/api/rules/file", {"path": path, "content": content})
        if result.get("error"):
            return [error_banner(f"Save failed: {result['error']}")], dash.no_update
        compile_result = api_post("/api/rules/compile")
        if compile_result.get("error"):
            banner = [html.Div(f"Saved — compile error: {compile_result['error']}", className="banner err")]
        else:
            ok = (
                compile_result.get("suricata", {}).get("ok", False)
                and compile_result.get("sigma", {}).get("ok", False)
                and not compile_result.get("suricata", {}).get("error_count", 0)
            )
            banner = [html.Div(f"Saved & compiled: {path}", className="banner ok" if ok else "banner err")]
        return banner, _editor_card(path=path, name=name, content=content)

    if not path:
        ext = ".yml" if tab in ("sigma", "elastalert") else ".rules"
        if tab == "sigma":
            path = f"{_GUI_SIGMA_DIR}/{stem}{ext}"
        else:
            path = f"data/rules/{tab}/{stem}{ext}"
    result = api_post("/api/rules/file", {"path": path, "content": content})
    if result.get("error"):
        return [error_banner(f"Save failed: {result['error']}")], dash.no_update
    compile_result = api_post("/api/rules/compile")
    if compile_result.get("error"):
        banner = [html.Div(f"Saved — compile error: {compile_result['error']}", className="banner err")]
    else:
        banner = [html.Div(f"Saved & compiled: {path}", className="banner ok")]
    return banner, _editor_card(path=path, name=name, content=content)


# ── validate ──────────────────────────────────────────────────────────────────

@callback(
    Output("rules-banner", "children", allow_duplicate=True),
    Input("rules-validate-btn", "n_clicks"),
    State("rules-editor-content", "value"),
    State("rules-selected-path", "data"),
    prevent_initial_call=True,
)
def _validate_rule(_n, content, path):
    if not _n:
        return dash.no_update
    if not content or not content.strip():
        return [error_banner("Editor is empty")]
    rule_type = ""
    if (path or "").endswith(".rules"):
        rule_type = "suricata"
    elif (path or "").endswith((".yml", ".yaml")):
        rule_type = "yaml"
    result = api_post("/api/rules/validate", {"content": content, "type": rule_type})
    if result.get("error"):
        return [error_banner(f"Validation error: {result['error']}")]
    if result.get("ok"):
        detected = result.get("type", rule_type or "rule")
        return [html.Div(f"Valid {detected} rule", className="banner ok")]
    errors = result.get("errors", [])
    msg = "; ".join(errors[:3]) if errors else "Validation failed"
    return [error_banner(f"Invalid: {msg}")]


# ── delete ────────────────────────────────────────────────────────────────────

@callback(
    Output("rules-banner", "children", allow_duplicate=True),
    Output("rules-editor-wrap", "children", allow_duplicate=True),
    Output("rules-selected-path", "data", allow_duplicate=True),
    Input("rules-delete-btn", "n_clicks"),
    State("rules-selected-path", "data"),
    prevent_initial_call=True,
)
def _delete_rule(_n, path):
    if not _n:
        return dash.no_update, dash.no_update, dash.no_update
    if not path:
        return [error_banner("No file selected")], dash.no_update, dash.no_update
    if path.startswith("docker:"):
        return [error_banner("Built-in ET rules cannot be deleted")], dash.no_update, dash.no_update
    base = path.split("#")[0]
    result = api_delete(f"/api/rules/file?path={_url_quote(base, safe='')}")
    if result.get("error"):
        return [error_banner(f"Delete failed: {result['error']}")], dash.no_update, path
    return [html.Div(f"Deleted: {base}", className="banner ok")], _editor_card(), ""


# ── new rule ──────────────────────────────────────────────────────────────────

@callback(
    Output("rules-editor-wrap", "children", allow_duplicate=True),
    Output("rules-selected-path", "data", allow_duplicate=True),
    Input("rules-new-btn", "n_clicks"),
    prevent_initial_call=True,
)
def _new_rule(_n):
    return _editor_card(), ""


# ── import ────────────────────────────────────────────────────────────────────

@callback(
    Output("rules-banner", "children", allow_duplicate=True),
    Output("rules-editor-wrap", "children", allow_duplicate=True),
    Output("rules-selected-path", "data", allow_duplicate=True),
    Input("rules-import-upload", "contents"),
    State("rules-import-upload", "filename"),
    State("rules-type-filter", "value"),
    prevent_initial_call=True,
)
def _import_rule(contents, filename, type_filter):
    if not contents or not filename:
        return dash.no_update, dash.no_update, dash.no_update
    import base64
    data = base64.b64decode(contents.split(",", 1)[-1]).decode("utf-8", errors="replace")
    tab = type_filter or "sigma"
    if tab == "suricata":
        path = f"{_GUI_SURI_DIR}/{filename}"
    elif tab == "sigma":
        path = f"{_GUI_SIGMA_DIR}/{filename}"
    else:
        path = f"data/rules/{tab}/{filename}"
    result = api_post("/api/rules/file", {"path": path, "content": data})
    if result.get("error"):
        return [error_banner(f"Import failed: {result['error']}")], dash.no_update, dash.no_update
    return (
        [html.Div(f"Imported: {path}", className="banner ok")],
        _editor_card(path=path, name=filename, content=data),
        path,
    )
