from __future__ import annotations

from typing import Any

import dash
from dash import Input, Output, State, callback, ctx, dcc, html

from ui.helpers import api_get, api_post, error_banner, topbar

dash.register_page(__name__, path="/logs")


def _results_table(results: list[dict[str, Any]]) -> html.Div:
    if not results:
        return html.Div("No upload results yet.", style={"fontSize": "12px", "color": "#888780", "padding": "12px 0"})
    rows = []
    for r in results:
        ok = not r.get("error")
        rows.append(html.Tr([
            html.Td(r.get("file", r.get("filename", "—")), className="mono",
                    style={"maxWidth": "160px", "overflow": "hidden", "textOverflow": "ellipsis", "whiteSpace": "nowrap"}),
            html.Td(r.get("index", "—"), className="mono", style={"fontSize": "11px"}),
            html.Td(f'{r.get("docs", 0):,}', style={"textAlign": "right", "fontWeight": "500"}),
            html.Td(r.get("pipeline", "none"), style={"fontSize": "11px", "color": "#888780"}),
            html.Td(html.Span("OK", className="tag running") if ok else html.Span("Error", className="tag stopped")),
        ]))
        if r.get("error"):
            rows.append(html.Tr([
                html.Td(r["error"], colSpan=5, style={"fontSize": "11px", "color": "#A32D2D", "paddingLeft": "12px"}),
            ]))
    header = html.Thead(html.Tr([
        html.Th("File"), html.Th("Index"), html.Th("Docs", style={"textAlign": "right"}),
        html.Th("Pipeline"), html.Th("Status"),
    ]))
    return html.Div(html.Table([header, html.Tbody(rows)], className="tbl"))


def _category_tag(cat: str) -> html.Span:
    cls_map = {
        "Network": "blue", "Cloud": "blue", "Windows": "blue", "Security Ops": "blue",
        "Endpoint": "stopped", "Threat Intel": "warning", "Email": "warning",
        "Identity": "purple", "Database": "purple",
        "Linux": "running", "DevOps/Web": "running",
        "Other": "unknown",
    }
    return html.Span(cat, className=f"tag {cls_map.get(cat, 'unknown')}")


def _vendors_table(vendors: list[dict]) -> html.Table | html.Div:
    if not vendors:
        return html.Div("No pipelines found.", style={"fontSize": "12px", "color": "#888780", "padding": "12px 0"})
    header = html.Thead(html.Tr([html.Th("Vendor"), html.Th("Category"), html.Th("Pipelines", style={"textAlign": "right"})]))
    rows = [html.Tr([
        html.Td(v["vendor"], style={"fontWeight": "500", "fontSize": "13px"}),
        html.Td(_category_tag(v["category"])),
        html.Td(str(v["count"]), style={"textAlign": "right", "fontSize": "12px", "color": "#888780"}),
    ]) for v in vendors]
    return html.Table([header, html.Tbody(rows)], className="tbl")


def _pipeline_options(pipelines: list[dict]) -> list[dict]:
    opts = [{"label": "None (auto-detect)", "value": ""}]
    for p in pipelines:
        opts.append({"label": f"{p['name']} [{p['category']}]", "value": p["name"]})
    return opts


def _folder_file_row(name: str, size_human: str) -> html.Div:
    return html.Div(
        style={"display": "flex", "alignItems": "center", "gap": "8px", "padding": "6px 0",
               "borderBottom": "0.5px solid rgba(0,0,0,0.06)"},
        children=[
            html.I(className="ti ti-file-text", style={"fontSize": "13px", "color": "#888780", "flexShrink": "0"}),
            html.Span(name, className="mono",
                      style={"fontSize": "12px", "flex": "1", "overflow": "hidden",
                             "textOverflow": "ellipsis", "whiteSpace": "nowrap"}),
            html.Span(size_human, style={"fontSize": "11px", "color": "#888780", "flexShrink": "0"}),
            html.Button("Select", id={"type": "logs-folder-pick", "name": name},
                        className="rule-btn", n_clicks=0),
        ],
    )


def _log_folder_preview(log_files: list[dict]) -> html.Div:
    if not log_files:
        return html.Div(
            "No files in data/ingest/ — drop files there or upload above.",
            style={"fontSize": "12px", "color": "#888780", "padding": "6px 0"},
        )
    rows = [_folder_file_row(f["name"], f.get("size_human", "")) for f in log_files[:3]]
    return html.Div(rows)


def _logs_overlay(files: list[dict]) -> html.Div:
    rows = [_folder_file_row(f["name"], f.get("size_human", "")) for f in files]
    return html.Div(
        id="logs-overlay",
        style={"display": "none", "position": "fixed", "inset": "0", "zIndex": "1000",
               "background": "rgba(0,0,0,0.35)", "alignItems": "center", "justifyContent": "center"},
        children=[
            html.Div(
                style={"background": "#fff", "borderRadius": "12px", "padding": "20px",
                       "width": "560px", "maxWidth": "90vw", "maxHeight": "80vh",
                       "display": "flex", "flexDirection": "column", "gap": "12px",
                       "boxShadow": "0 8px 32px rgba(0,0,0,0.18)"},
                children=[
                    html.Div(style={"display": "flex", "alignItems": "center"}, children=[
                        html.Span("Log files — data/ingest/",
                                  style={"fontWeight": "600", "fontSize": "14px", "flex": "1"}),
                        html.Button("✕", id="logs-overlay-close", className="rule-btn", n_clicks=0),
                    ]),
                    dcc.Input(id="logs-overlay-search", placeholder="Search…", debounce=False,
                              className="setting-input",
                              style={"width": "100%", "boxSizing": "border-box"}),
                    html.Div(id="logs-overlay-list",
                             style={"overflowY": "auto", "flex": "1", "minHeight": "0"},
                             children=rows),
                    dcc.Store(id="logs-overlay-files", data=files),
                ],
            ),
        ],
    )


def layout() -> html.Div:
    pipelines_data = api_get("/api/capture/pipelines")
    pipelines = pipelines_data.get("pipelines", []) if isinstance(pipelines_data, dict) else []
    vendors_data = api_get("/api/capture/pipelines/vendors")
    vendors = vendors_data.get("vendors", []) if isinstance(vendors_data, dict) else []
    log_files_resp = api_get("/api/capture/logs/files")
    log_files = log_files_resp.get("files", []) if isinstance(log_files_resp, dict) else []

    return html.Div([
        topbar("Log upload"),
        html.Div(id="logs-banner"),
        _logs_overlay(log_files),
        html.Div(
            className="content",
            children=[
                html.Div(
                    className="row2",
                    children=[

                        # ── left col ────────────────────────────────────────
                        html.Div(className="col", children=[

                            # file drop + folder pick card
                            html.Div(className="card", style={"flexShrink": "0"}, children=[
                                html.Div(className="card-header", children=[html.Span("Log file", className="card-title")]),

                                dcc.Upload(
                                    id="logs-upload-zone",
                                    children=html.Div([
                                        html.Div(html.I(className="ti ti-file-import", style={"fontSize": "24px", "color": "#888780"}), className="upload-icon"),
                                        html.Div("Drop a log file or click to browse", className="upload-title"),
                                        html.Div(".log .json .csv .cef .txt .gz .zip .evtx", className="upload-sub"),
                                    ], className="upload-zone"),
                                    multiple=False,
                                ),
                                html.Div(id="logs-file-name", style={"marginTop": "10px"}, children=_file_placeholder()),

                                html.Div(style={"borderTop": "0.5px solid rgba(0,0,0,0.07)", "margin": "14px 0"}),
                                html.Div(style={"display": "flex", "alignItems": "center", "justifyContent": "space-between", "marginBottom": "8px"}, children=[
                                    html.Span("From data/ingest/", style={"fontSize": "11px", "fontWeight": "600", "color": "#888780",
                                                                           "textTransform": "uppercase", "letterSpacing": "0.05em"}),
                                    html.Button([html.I(className="ti ti-refresh", style={"fontSize": "11px"}), " Refresh"],
                                                id="logs-folder-refresh-btn", className="rule-btn", n_clicks=0),
                                ]),
                                html.Div(id="logs-folder-list", children=_log_folder_preview(log_files)),
                                html.Button(
                                    [html.I(className="ti ti-folder-open",
                                            style={"fontSize": "13px", "verticalAlign": "middle", "marginRight": "5px"}),
                                     html.Span("Show all files", style={"verticalAlign": "middle"})],
                                    id="logs-show-all-btn", className="rule-btn",
                                    style={"marginTop": "8px", "width": "100%", "justifyContent": "center",
                                           "display": "none" if len(log_files) <= 3 else "inline-flex",
                                           "alignItems": "center", "lineHeight": "1"},
                                    n_clicks=0,
                                ),

                                html.Div(style={"borderTop": "0.5px solid rgba(0,0,0,0.07)", "margin": "14px 0"}),

                                # pipeline compact upload
                                html.Div(style={"display": "flex", "alignItems": "center", "justifyContent": "space-between", "marginBottom": "8px"}, children=[
                                    html.Span("Pipeline file", style={"fontSize": "11px", "fontWeight": "600", "color": "#888780",
                                                                       "textTransform": "uppercase", "letterSpacing": "0.05em"}),
                                    html.Span("optional", className="tag blue"),
                                ]),
                                dcc.Upload(
                                    id="logs-pipeline-upload",
                                    children=html.Div(style={"display": "flex", "alignItems": "center", "gap": "10px", "padding": "10px 12px",
                                                              "border": "1px dashed #c0bfbb", "borderRadius": "8px", "cursor": "pointer"}, children=[
                                        html.I(className="ti ti-code-plus", style={"fontSize": "18px", "color": "#888780", "flexShrink": "0"}),
                                        html.Span("Drop .yml / .json pipeline definition here", style={"fontSize": "12px", "color": "#888780", "flex": "1"}),
                                        html.Button("Browse", className="rule-btn", style={"flexShrink": "0"}),
                                    ]),
                                    multiple=False,
                                ),
                                html.Div(id="logs-pipeline-name", style={"fontSize": "11px", "color": "#3B6D11", "marginTop": "6px"}),
                            ]),

                            # upload options — compact, no overflow needed
                            html.Div(className="card", style={"flexShrink": "0"}, children=[
                                html.Div(className="card-header", children=[html.Span("Upload options", className="card-title")]),
                                html.Div(style={"display": "flex", "flexDirection": "column", "gap": "12px"}, children=[
                                    html.Div([
                                        html.Div("Ingest pipeline", style={"fontSize": "11px", "color": "#888780", "marginBottom": "4px"}),
                                        dcc.Dropdown(id="logs-pipeline", options=_pipeline_options(pipelines), value="",
                                                     clearable=False, style={"fontSize": "12px"}, placeholder="None (auto-detect)"),
                                    ]),
                                    html.Label(style={"display": "flex", "alignItems": "center", "gap": "10px", "cursor": "pointer"}, children=[
                                        dcc.Checklist(id="logs-opt-ai", options=[{"label": "", "value": "ai"}], value=[], inline=True),
                                        html.Div([
                                            html.Div("Build pipeline with AI", className="setting-name"),
                                            html.Div("Auto-generate grok pipeline via local Ollama model", className="setting-desc"),
                                        ]),
                                    ]),
                                    html.Label(style={"display": "flex", "alignItems": "center", "gap": "10px", "cursor": "pointer"}, children=[
                                        dcc.Checklist(id="logs-opt-keep", options=[{"label": "", "value": "keep"}], value=[], inline=True),
                                        html.Div([
                                            html.Div("Keep mode", className="setting-name"),
                                            html.Div("Preserve existing indexed data", className="setting-desc"),
                                        ]),
                                    ]),
                                    html.Label(style={"display": "flex", "alignItems": "center", "gap": "10px", "cursor": "pointer"}, children=[
                                        dcc.Checklist(id="logs-opt-now", options=[{"label": "", "value": "now"}], value=[], inline=True),
                                        html.Div([
                                            html.Div("Shift timestamps to now", className="setting-name"),
                                            html.Div("Rebase event timestamps to current time", className="setting-desc"),
                                        ]),
                                    ]),
                                    html.Div([
                                        html.Div("Index prefix (optional)", style={"fontSize": "11px", "color": "#888780", "marginBottom": "4px"}),
                                        dcc.Input(id="logs-index-input", placeholder="e.g. custom-logs",
                                                  className="setting-input", style={"width": "100%"}),
                                    ]),
                                    html.Button(
                                        [html.I(className="ti ti-upload", style={"fontSize": "14px"}), " Upload & ingest"],
                                        id="logs-upload-btn", className="topbar-btn primary",
                                        style={"width": "100%", "justifyContent": "center", "padding": "10px", "fontSize": "13px"},
                                        n_clicks=0,
                                    ),
                                ]),
                            ]),
                        ]),

                        # ── right col ────────────────────────────────────────
                        html.Div(className="col", children=[

                            # results card — fixed height, scrollable
                            html.Div(className="card", style={"height": "274px", "display": "flex", "flexDirection": "column"}, children=[
                                html.Div(className="card-header", style={"flexShrink": "0"}, children=[
                                    html.Span("Upload results", className="card-title"),
                                    html.Span(id="logs-result-count", style={"fontSize": "11px", "color": "#888780"}),
                                ]),
                                html.Div(id="logs-results", children=_results_table([]),
                                         style={"flex": "1", "minHeight": "0", "overflowY": "auto"}),
                            ]),

                            # available pipelines — fixed height, vendors table scrolls inside
                            html.Div(className="card", style={"height": "628.5px", "display": "flex", "flexDirection": "column"}, children=[
                                html.Div(className="card-header", children=[
                                    html.Span("Available pipelines", className="card-title"),
                                    html.Span("by vendor", style={"fontSize": "11px", "color": "#888780"}),
                                ]),
                                dcc.Input(
                                    id="logs-vendor-search", placeholder="Search vendors…",
                                    debounce=True, className="setting-input",
                                    style={"width": "100%", "boxSizing": "border-box", "padding": "8px 12px",
                                           "fontSize": "13px", "marginBottom": "10px"},
                                ),
                                html.Div(id="logs-vendors-table", children=_vendors_table(vendors),
                                         style={"flex": "1", "minHeight": "0", "overflowY": "auto"}),
                            ]),
                        ]),
                    ],
                ),
            ],
        ),
        dcc.Store(id="logs-file-store", data=None),
        dcc.Store(id="logs-pipeline-store", data=None),
        dcc.Store(id="logs-all-vendors", data=vendors),
    ])


# ── store uploaded log file ────────────────────────────────────────────────────

@callback(
    Output("logs-file-store", "data"),
    Output("logs-file-name", "children"),
    Input("logs-upload-zone", "contents"),
    State("logs-upload-zone", "filename"),
    prevent_initial_call=True,
)
def _store_upload(contents, filename):
    if not contents:
        return None, _file_placeholder()
    return {"content": contents, "filename": filename}, _file_loaded_badge(filename, "uploaded")


# ── folder pick ────────────────────────────────────────────────────────────────

def _file_loaded_badge(name: str, sub: str) -> html.Div:
    return html.Div(style={"display": "flex", "alignItems": "center", "gap": "8px", "padding": "8px 10px",
                            "background": "#F1F5F9", "borderRadius": "6px"}, children=[
        html.I(className="ti ti-file-check", style={"fontSize": "15px", "color": "#3B6D11"}),
        html.Div(style={"flex": "1"}, children=[
            html.Div(name, style={"fontSize": "12px", "fontWeight": "500"}),
            html.Div(sub, style={"fontSize": "11px", "color": "#888780"}),
        ]),
    ])


def _file_placeholder() -> html.Div:
    return html.Div(style={"display": "flex", "alignItems": "center", "gap": "8px", "padding": "8px 10px",
                            "background": "#F9F9F8", "borderRadius": "6px",
                            "border": "1px dashed #DDDCDA"}, children=[
        html.I(className="ti ti-file-off", style={"fontSize": "15px", "color": "#c0bfbb", "flexShrink": "0"}),
        html.Div(style={"flex": "1"}, children=[
            html.Div("No file selected", style={"fontSize": "12px", "fontWeight": "500", "color": "#888780"}),
            html.Div("Drop a file above or select from folder below", style={"fontSize": "11px", "color": "#b0afac"}),
        ]),
    ])


@callback(
    Output("logs-file-store", "data", allow_duplicate=True),
    Output("logs-file-name", "children", allow_duplicate=True),
    Output("logs-overlay", "style", allow_duplicate=True),
    Input({"type": "logs-folder-pick", "name": dash.ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def _pick_log_from_folder(n_clicks):
    if not any(n_clicks):
        return dash.no_update, dash.no_update, dash.no_update
    trigger = ctx.triggered_id
    if not trigger:
        return dash.no_update, dash.no_update, dash.no_update
    name = trigger.get("name", "")
    return ({"filename": name, "from_folder": True},
            _file_loaded_badge(name, "selected from data/ingest/"),
            {"display": "none"})


@callback(
    Output("logs-folder-list", "children"),
    Output("logs-overlay-files", "data"),
    Output("logs-show-all-btn", "style"),
    Output("logs-show-all-btn", "children"),
    Input("logs-folder-refresh-btn", "n_clicks"),
    prevent_initial_call=False,
)
def _refresh_log_folder_list(_n):
    resp = api_get("/api/capture/logs/files")
    files = resp.get("files", []) if isinstance(resp, dict) else []
    btn_style = {"marginTop": "8px", "width": "100%", "justifyContent": "center",
                 "display": "none" if len(files) <= 3 else "flex"}
    btn_label = [html.I(className="ti ti-folder-open",
                        style={"fontSize": "13px", "verticalAlign": "middle", "marginRight": "5px"}),
                 html.Span(f"Show all {len(files)} files", style={"verticalAlign": "middle"})]
    return _log_folder_preview(files), files, btn_style, btn_label


@callback(
    Output("logs-overlay", "style"),
    Input("logs-show-all-btn", "n_clicks"),
    prevent_initial_call=True,
)
def _open_logs_overlay(_n):
    return {"display": "flex", "position": "fixed", "inset": "0", "zIndex": "1000",
            "background": "rgba(0,0,0,0.35)", "alignItems": "center", "justifyContent": "center"}


@callback(
    Output("logs-overlay", "style", allow_duplicate=True),
    Input("logs-overlay-close", "n_clicks"),
    prevent_initial_call=True,
)
def _close_logs_overlay(_n):
    return {"display": "none"}


@callback(
    Output("logs-overlay-list", "children"),
    Input("logs-overlay-search", "value"),
    State("logs-overlay-files", "data"),
    prevent_initial_call=False,
)
def _search_logs_overlay(query, files):
    files = files or []
    q = (query or "").lower()
    if q:
        files = [f for f in files if q in f["name"].lower()]
    return [_folder_file_row(f["name"], f.get("size_human", "")) for f in files]


# ── store pipeline upload ──────────────────────────────────────────────────────

@callback(
    Output("logs-pipeline-store", "data"),
    Output("logs-pipeline-name", "children"),
    Input("logs-pipeline-upload", "contents"),
    State("logs-pipeline-upload", "filename"),
    prevent_initial_call=True,
)
def _store_pipeline_upload(contents, filename):
    if not contents or not filename:
        return None, ""
    result = api_post("/api/capture/pipeline/upload", {"filename": filename, "content": contents})
    if result.get("error"):
        return None, f"Error: {result['error']}"
    return {"filename": filename}, f"Pipeline uploaded: {filename}"


# ── vendor search filter ──────────────────────────────────────────────────────

@callback(
    Output("logs-vendors-table", "children"),
    Input("logs-vendor-search", "value"),
    State("logs-all-vendors", "data"),
    prevent_initial_call=False,
)
def _filter_vendors(search, vendors):
    vendors = vendors or []
    q = (search or "").lower()
    if q:
        vendors = [v for v in vendors if q in v["vendor"].lower() or q in v["category"].lower()]
    return _vendors_table(vendors)


# ── do upload ─────────────────────────────────────────────────────────────────

@callback(
    Output("logs-results", "children"),
    Output("logs-result-count", "children"),
    Output("logs-banner", "children"),
    Input("logs-upload-btn", "n_clicks"),
    State("logs-file-store", "data"),
    State("logs-pipeline", "value"),
    State("logs-opt-ai", "value"),
    State("logs-opt-keep", "value"),
    State("logs-opt-now", "value"),
    State("logs-index-input", "value"),
    prevent_initial_call=True,
)
def _do_upload(_n, file_data, pipeline, ai_val, keep_val, now_val, index_prefix):
    if not file_data:
        return _results_table([]), "", [error_banner("No file selected — drop a file in the upload zone first")]

    build_ai = "ai" in (ai_val or [])
    keep = "keep" in (keep_val or [])
    now = "now" in (now_val or [])

    if pipeline and build_ai:
        return _results_table([]), "", [error_banner("Choose either a pipeline or Build pipeline with AI, not both")]

    body: dict = {
        "filename": file_data["filename"],
        "type": pipeline or "",
        "build_pipeline": build_ai,
        "keep": keep,
        "now": now,
        "index": index_prefix or "",
    }
    if not file_data.get("from_folder"):
        body["content"] = file_data.get("content", "")
    result = api_post("/api/capture/upload", body)
    if result.get("error"):
        return _results_table([]), "", [error_banner(f"Upload failed: {result['error']}")]

    results = result.get("results", [])
    if not results:
        return _results_table([]), "", [error_banner("No results returned")]

    total_docs = sum(r.get("docs", 0) for r in results if isinstance(r, dict))
    banner = [html.Div(
        f"Upload complete — {total_docs:,} documents indexed",
        className="banner ok",
    )]
    count = f"{len(results)} uploads"
    return _results_table(results), count, banner
