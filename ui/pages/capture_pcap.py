from __future__ import annotations

from pathlib import Path
from typing import Any

import dash
from dash import Input, Output, State, callback, ctx, dcc, html

from ui.helpers import api_get, api_post, colorize_log, error_banner, topbar

dash.register_page(__name__, path="/capture")


# ── replay output card ─────────────────────────────────────────────────────────

def _terminal_children(lines: list[str] | None = None) -> list:
    if lines is None:
        return [html.Span("Run a replay to see output…", style={"color": "#6e7681", "fontStyle": "italic"})]
    if not lines:
        return []
    return colorize_log(lines)


def _replay_stats(stats: dict) -> list:
    if not stats:
        return []
    return [html.Div(style={"display": "flex", "gap": "20px", "marginTop": "10px"}, children=[
        html.Div([html.Span("Suricata docs: ", style={"fontSize": "12px", "color": "#888780"}),
                  html.B(f'+{stats.get("suricata_docs", 0):,}' if stats.get("suricata_docs") else "—")]),
        html.Div([html.Span("soc-alerts: ", style={"fontSize": "12px", "color": "#888780"}),
                  html.B(f'+{stats.get("soc_alerts_docs", 0)}' if stats.get("soc_alerts_docs") else "—",
                         style={"color": "#A32D2D"} if stats.get("soc_alerts_docs") else {})]),
    ])]


def _replay_output_card_static() -> html.Div:
    """Static card wrapper — never re-rendered after page load."""
    return html.Div(className="card", style={"flex": "1", "display": "flex", "flexDirection": "column", "minHeight": "0"}, children=[
        html.Div(className="card-header", style={"flexShrink": "0"}, children=[
            html.Span(["Replay output", html.Span(id="pcap-live-badge")], className="card-title"),
            html.Button("Clear", id="pcap-clear-btn", className="rule-btn", n_clicks=0),
        ]),
        html.Div(
            id="pcap-output-terminal",
            className="terminal fill",
            children=[html.Span("Run a replay to see output…", style={"color": "#6e7681", "fontStyle": "italic"})],
        ),
        html.Div(id="pcap-output-stats", style={"flexShrink": "0"}),
    ])


def _loaded_file_placeholder() -> html.Div:
    return html.Div(style={"textAlign": "center", "padding": "28px 0", "color": "#b0afac"}, children=[
        html.I(className="ti ti-file-off", style={"fontSize": "28px", "display": "block", "marginBottom": "6px"}),
        html.Div("No file loaded", style={"fontSize": "12px"}),
    ])


def _info_row(label: str, value: Any) -> html.Tr:
    return html.Tr([
        html.Td(label, style={"color": "#888780", "fontSize": "11px", "whiteSpace": "nowrap",
                               "paddingRight": "10px", "paddingBottom": "5px", "verticalAlign": "top"}),
        html.Td(value, style={"fontSize": "12px", "paddingBottom": "5px"}),
    ])


def _loaded_file_card_body(name: str, source: str, info: dict, status: str) -> html.Div:
    def _dur(secs: float) -> str:
        s = int(secs)
        return f"{s // 60}m {s % 60}s" if s >= 60 else f"{s}s"

    def _sz(b: int) -> str:
        for unit in ("B", "KB", "MB", "GB"):
            if b < 1024:
                return f"{b:.1f} {unit}"
            b /= 1024
        return f"{b:.1f} TB"

    tag_map = {
        "idle": html.Span("Ready", className="tag running"),
        "running": html.Span("Replaying…", className="tag blue"),
        "done": html.Span("Done", className="tag running"),
        "error": html.Span("Error", className="tag unknown"),
    }

    rows = [
        _info_row("Source", source),
        _info_row("Status", tag_map.get(status, tag_map["idle"])),
    ]
    if info.get("packets"):
        rows.append(_info_row("Packets", f"{info['packets']:,}"))
    if info.get("duration_secs"):
        rows.append(_info_row("Duration", _dur(info["duration_secs"])))
    if info.get("size_bytes"):
        rows.append(_info_row("Size", _sz(info["size_bytes"])))
    if info.get("protocols"):
        rows.append(_info_row("Protocols", ", ".join(info["protocols"][:6])))

    progress: list = []
    if status == "running":
        progress = [html.Div(style={"marginTop": "14px"}, children=[
            html.Div("Replay progress", style={"fontSize": "11px", "color": "#888780", "marginBottom": "2px"}),
            html.Div(className="progress-bar", children=[html.Div(className="progress-fill progress-indeterminate")]),
        ])]
    elif status == "done":
        progress = [html.Div(style={"marginTop": "14px"}, children=[
            html.Div(style={"display": "flex", "justifyContent": "space-between",
                            "fontSize": "11px", "color": "#888780", "marginBottom": "2px"}, children=[
                html.Span("Replay progress"), html.Span("100%"),
            ]),
            html.Div(className="progress-bar", children=[html.Div(className="progress-fill", style={"width": "100%"})]),
        ])]

    return html.Div(children=[
        html.Div(style={"display": "flex", "alignItems": "flex-start", "gap": "8px", "marginBottom": "12px"}, children=[
            html.I(className="ti ti-file", style={"fontSize": "18px", "color": "#3B6D11", "marginTop": "1px", "flexShrink": "0"}),
            html.Div(name, className="mono", style={"fontSize": "12px", "fontWeight": "500", "wordBreak": "break-all", "lineHeight": "1.4"}),
        ]),
        html.Table(className="tbl", children=html.Tbody(rows)),
        *progress,
    ])


# ── folder picker overlay ──────────────────────────────────────────────────────

def _folder_file_row(name: str, size_human: str, btn_id: dict) -> html.Div:
    return html.Div(
        style={"display": "flex", "alignItems": "center", "gap": "8px", "padding": "6px 0",
               "borderBottom": "0.5px solid rgba(0,0,0,0.06)"},
        children=[
            html.I(className="ti ti-file", style={"fontSize": "13px", "color": "#888780", "flexShrink": "0"}),
            html.Span(name, className="mono",
                      style={"fontSize": "12px", "flex": "1", "overflow": "hidden",
                             "textOverflow": "ellipsis", "whiteSpace": "nowrap"}),
            html.Span(size_human, style={"fontSize": "11px", "color": "#888780", "flexShrink": "0"}),
            html.Button("Select", id=btn_id, className="rule-btn", n_clicks=0),
        ],
    )


def _pcap_folder_preview(files: list[dict]) -> html.Div:
    if not files:
        return html.Div("No PCAP files in data/pcap/ — drop files there or upload above.",
                        style={"fontSize": "12px", "color": "#888780", "padding": "6px 0"})
    rows = [_folder_file_row(f["name"], f.get("size_human", ""),
                             {"type": "pcap-folder-pick", "name": f["name"]})
            for f in files[:3]]
    return html.Div(rows)


def _overlay(overlay_id: str, title: str, files: list[dict], btn_type: str) -> html.Div:
    rows = [_folder_file_row(f["name"], f.get("size_human", ""),
                             {"type": btn_type, "name": f["name"]})
            for f in files]
    return html.Div(
        id=overlay_id,
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
                        html.Span(title, style={"fontWeight": "600", "fontSize": "14px", "flex": "1"}),
                        html.Button("✕", id=f"{overlay_id}-close", className="rule-btn", n_clicks=0),
                    ]),
                    dcc.Input(id=f"{overlay_id}-search", placeholder="Search…", debounce=False,
                              className="setting-input",
                              style={"width": "100%", "boxSizing": "border-box"}),
                    html.Div(id=f"{overlay_id}-list",
                             style={"overflowY": "auto", "flex": "1", "minHeight": "0"},
                             children=rows),
                    dcc.Store(id=f"{overlay_id}-files", data=files),
                ],
            ),
        ],
    )


# ── history ────────────────────────────────────────────────────────────────────

def _history_table(history: list[dict]) -> html.Div:
    if not history:
        return html.Div("No replays yet.", style={"fontSize": "12px", "color": "#888780", "padding": "12px 0"})
    header = html.Thead(html.Tr([
        html.Th("", style={"width": "16px", "padding": "7px 4px 7px 12px"}),
        html.Th("PCAP file"),
        html.Th("Docs", style={"textAlign": "right"}),
        html.Th("Date", style={"whiteSpace": "nowrap"}),
        html.Th(""),
    ]), style={"position": "sticky", "top": "0", "background": "#fff", "zIndex": "1"})
    rows = []
    for h in history[:10]:
        ts = h.get("timestamp", "")[:16].replace("T", " ") if h.get("timestamp") else "—"
        sd = h.get("suricata_docs") or 0
        sa = h.get("soc_alerts_docs") or 0
        docs = f"+{sd:,}" if sd or sa else "—"
        status = h.get("status", "done")
        dot_cls = "dot green" if status == "done" else "dot red"
        pcap_name = h.get("pcap", "")
        rows.append(html.Tr([
            html.Td(html.Div(className=dot_cls), style={"width": "16px", "padding": "10px 4px 10px 12px"}),
            html.Td(pcap_name or "—", className="mono", style={"maxWidth": "140px", "overflow": "hidden",
                                                                 "textOverflow": "ellipsis", "whiteSpace": "nowrap",
                                                                 "paddingLeft": "4px"}),
            html.Td(docs, style={"textAlign": "right", "fontWeight": "500"}),
            html.Td(ts, style={"fontSize": "11px", "color": "#888780", "whiteSpace": "nowrap"}),
            html.Td(
                html.Button(
                    [html.I(className="ti ti-player-play", style={"fontSize": "11px"}), " Replay"],
                    id={"type": "history-replay-btn", "name": pcap_name},
                    className="rule-btn", n_clicks=0,
                ) if pcap_name else "",
                style={"paddingLeft": "6px"},
            ),
        ]))
    return html.Div(
        html.Table([header, html.Tbody(rows)], className="tbl"),
        style={"maxHeight": "162px", "overflowY": "auto"},
    )


# ── layout ─────────────────────────────────────────────────────────────────────

def layout() -> html.Div:
    history_resp = api_get("/api/capture/history")
    history = history_resp.get("history", []) if isinstance(history_resp, dict) else []
    pcap_files_resp = api_get("/api/capture/pcap/files")
    pcap_files = pcap_files_resp.get("files", []) if isinstance(pcap_files_resp, dict) else []

    return html.Div([
        topbar(
            "Packet replay",
            dcc.Interval(id="pcap-poll", interval=15_000, n_intervals=0),
            html.Button(
                [html.I(className="ti ti-refresh", style={"fontSize": "13px"}), " Refresh"],
                id="pcap-refresh-btn", className="topbar-btn", n_clicks=0,
            ),
        ),
        html.Div(id="pcap-banner"),
        html.Div(className="content", style={"display": "flex", "flexDirection": "column", "gap": "14px", "flex": "1"}, children=[

            html.Div(className="row2", children=[

                # left: PCAP file upload + folder picker
                html.Div(className="col", children=[
                    html.Div(className="card", style={"flex": "1"}, children=[
                        html.Div(className="card-header", children=[html.Span("PCAP file", className="card-title")]),
                        dcc.Upload(
                            id="pcap-upload-zone",
                            children=html.Div([
                                html.Div(html.I(className="ti ti-file-upload", style={"fontSize": "24px", "color": "#888780"}), className="upload-icon"),
                                html.Div("Drop a .pcap / .pcapng file or click to browse", className="upload-title"),
                                html.Div("Max 2 GB — replayed through Suricata IDS", className="upload-sub"),
                            ], className="upload-zone"),
                            multiple=False,
                        ),
                        html.Div(id="pcap-file-loaded", style={"marginTop": "10px"}, children=_file_placeholder()),
                        html.Div(style={"borderTop": "0.5px solid rgba(0,0,0,0.07)", "margin": "14px 0"}),
                        html.Div(style={"display": "flex", "alignItems": "center", "justifyContent": "space-between", "marginBottom": "8px"}, children=[
                            html.Span("From data/pcap/", style={"fontSize": "11px", "fontWeight": "600", "color": "#888780",
                                                                  "textTransform": "uppercase", "letterSpacing": "0.05em"}),
                            html.Button([html.I(className="ti ti-refresh", style={"fontSize": "11px"}), " Refresh"],
                                        id="pcap-folder-refresh-btn", className="rule-btn", n_clicks=0),
                        ]),
                        html.Div(id="pcap-folder-list", children=_pcap_folder_preview(pcap_files)),
                        html.Button(
                            [html.I(className="ti ti-folder-open",
                                    style={"fontSize": "13px", "verticalAlign": "middle", "marginRight": "5px"}),
                             html.Span("Show all files", style={"verticalAlign": "middle"})],
                            id="pcap-show-all-btn", className="rule-btn",
                            style={"marginTop": "8px", "width": "100%", "justifyContent": "center",
                                   "display": "none" if len(pcap_files) <= 3 else "inline-flex",
                                   "alignItems": "center", "lineHeight": "1"},
                            n_clicks=0,
                        ),
                    ]),
                ]),

                # right: replay options + recent replays
                html.Div(className="col", children=[
                    html.Div(className="card", style={"flexShrink": "0"}, children=[
                        html.Div(className="card-header", children=[html.Span("Replay options", className="card-title")]),
                        html.Div(style={"display": "flex", "flexDirection": "column", "gap": "14px"}, children=[
                            html.Label(style={"display": "flex", "alignItems": "center", "gap": "12px", "cursor": "pointer"}, children=[
                                dcc.Checklist(id="pcap-opt-keep", options=[{"label": "", "value": "keep"}], value=[], inline=True),
                                html.Div([
                                    html.Div("Keep mode", style={"fontSize": "13px", "fontWeight": "500"}),
                                    html.Div("Preserve existing indexed data and alerts", style={"fontSize": "11px", "color": "#888780"}),
                                ]),
                            ]),
                            html.Label(style={"display": "flex", "alignItems": "center", "gap": "12px", "cursor": "pointer"}, children=[
                                dcc.Checklist(id="pcap-opt-now", options=[{"label": "", "value": "now"}], value=[], inline=True),
                                html.Div([
                                    html.Div("Shift timestamps to now", style={"fontSize": "13px", "fontWeight": "500"}),
                                    html.Div("Rebase event timestamps to current time", style={"fontSize": "11px", "color": "#888780"}),
                                ]),
                            ]),
                            html.Button(
                                [html.I(className="ti ti-player-play", style={"fontSize": "14px"}), " Replay"],
                                id="pcap-replay-btn", className="topbar-btn primary",
                                style={"width": "100%", "justifyContent": "center", "padding": "10px", "marginTop": "4px"},
                                n_clicks=0,
                            ),
                        ]),
                    ]),

                    html.Div(className="card", style={"flex": "1", "minHeight": "0", "display": "flex", "flexDirection": "column"}, children=[
                        html.Div(className="card-header", style={"flexShrink": "0"}, children=[
                            html.Span("Recent replays", className="card-title"),
                            html.Span(id="pcap-history-count", children=f"{len(history)} replays",
                                      style={"fontSize": "11px", "color": "#888780"}),
                        ]),
                        html.Div(id="pcap-history-table", children=_history_table(history),
                                 style={"overflowY": "auto", "flex": "1", "minHeight": "0"}),
                    ]),
                ]),

            ]),

            # bottom row: replay output + loaded file info
            html.Div(style={"display": "flex", "gap": "14px", "flex": "1", "minHeight": "0"}, children=[
                _replay_output_card_static(),
                html.Div(className="card", style={"width": "300px", "flexShrink": "0"}, children=[
                    html.Div(className="card-header", children=[html.Span("Loaded file", className="card-title")]),
                    html.Div(id="pcap-loaded-file-info", children=_loaded_file_placeholder()),
                ]),
            ]),
        ]),

        # overlays
        _overlay("pcap-overlay", "PCAP files — data/pcap/", pcap_files, "pcap-folder-pick"),

        dcc.Store(id="pcap-file-store", data=None),
        dcc.Store(id="pcap-file-info", data=None),
        dcc.Store(id="pcap-replay-running", data=False),
        dcc.Store(id="pcap-replay-status", data="idle"),
        dcc.Interval(id="pcap-replay-poll", interval=1500, n_intervals=0, disabled=True),
    ])


# ── pcap upload from browser ───────────────────────────────────────────────────

@callback(
    Output("pcap-file-store", "data"),
    Output("pcap-file-loaded", "children"),
    Input("pcap-upload-zone", "contents"),
    State("pcap-upload-zone", "filename"),
    prevent_initial_call=True,
)
def _store_pcap(contents, filename):
    if not contents:
        return None, _file_placeholder()
    loaded = _file_loaded_badge(filename, "uploaded")
    return {"content": contents, "filename": filename}, loaded


def _file_loaded_badge(name: str, sub: str) -> html.Div:
    return html.Div(style={"display": "flex", "alignItems": "center", "gap": "8px", "padding": "8px 10px",
                            "background": "#F1F5F9", "borderRadius": "6px"}, children=[
        html.I(className="ti ti-file-check", style={"fontSize": "15px", "color": "#3B6D11"}),
        html.Div(style={"flex": "1"}, children=[
            html.Div(name, style={"fontSize": "13px", "fontWeight": "500"}),
            html.Div(sub, style={"fontSize": "11px", "color": "#888780"}),
        ]),
    ])


def _file_placeholder(sub: str = "Drop a file above or select from folder below") -> html.Div:
    return html.Div(style={"display": "flex", "alignItems": "center", "gap": "8px", "padding": "8px 10px",
                            "background": "#F9F9F8", "borderRadius": "6px",
                            "border": "1px dashed #DDDCDA"}, children=[
        html.I(className="ti ti-file-off", style={"fontSize": "15px", "color": "#c0bfbb", "flexShrink": "0"}),
        html.Div(style={"flex": "1"}, children=[
            html.Div("No file selected", style={"fontSize": "13px", "fontWeight": "500", "color": "#888780"}),
            html.Div(sub, style={"fontSize": "11px", "color": "#b0afac"}),
        ]),
    ])


@callback(
    Output("pcap-file-info", "data"),
    Input("pcap-file-store", "data"),
    prevent_initial_call=True,
)
def _load_pcap_info(file_data):
    if not file_data or not file_data.get("from_folder"):
        return None
    name = file_data.get("filename", "")
    resp = api_get(f"/api/capture/pcap/info?file={name}")
    return resp if not resp.get("error") else None


@callback(
    Output("pcap-loaded-file-info", "children"),
    Input("pcap-file-store", "data"),
    Input("pcap-file-info", "data"),
    Input("pcap-replay-status", "data"),
)
def _update_loaded_file(file_data, file_info, replay_status):
    if not file_data:
        return _loaded_file_placeholder()
    name = file_data.get("filename", "—")
    source = "data/pcap/" if file_data.get("from_folder") else "uploaded"
    return _loaded_file_card_body(name, source, file_info or {}, replay_status or "idle")


# ── pcap folder pick ───────────────────────────────────────────────────────────

@callback(
    Output("pcap-file-store", "data", allow_duplicate=True),
    Output("pcap-file-loaded", "children", allow_duplicate=True),
    Output("pcap-overlay", "style", allow_duplicate=True),
    Input({"type": "pcap-folder-pick", "name": dash.ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def _pick_pcap_from_folder(n_clicks):
    if not any(n_clicks):
        return dash.no_update, dash.no_update, dash.no_update
    trigger = ctx.triggered_id
    if not trigger:
        return dash.no_update, dash.no_update, dash.no_update
    name = trigger.get("name", "")
    return ({"filename": name, "from_folder": True},
            _file_loaded_badge(name, "selected from data/pcap/"),
            {"display": "none"})


@callback(
    Output("pcap-folder-list", "children"),
    Output("pcap-overlay-files", "data"),
    Output("pcap-show-all-btn", "style"),
    Output("pcap-show-all-btn", "children"),
    Input("pcap-folder-refresh-btn", "n_clicks"),
    Input("pcap-poll", "n_intervals"),
    prevent_initial_call=False,
)
def _refresh_pcap_folder(_refresh, _poll):
    resp = api_get("/api/capture/pcap/files")
    files = resp.get("files", []) if isinstance(resp, dict) else []
    btn_style = {"marginTop": "8px", "width": "100%", "justifyContent": "center",
                 "display": "none" if len(files) <= 3 else "flex"}
    btn_label = [html.I(className="ti ti-folder-open",
                        style={"fontSize": "13px", "verticalAlign": "middle", "marginRight": "5px"}),
                 html.Span(f"Show all {len(files)} files", style={"verticalAlign": "middle"})]
    return _pcap_folder_preview(files), files, btn_style, btn_label


@callback(
    Output("pcap-overlay", "style", allow_duplicate=True),
    Input("pcap-show-all-btn", "n_clicks"),
    prevent_initial_call=True,
)
def _open_pcap_overlay(_n):
    return {"display": "flex", "position": "fixed", "inset": "0", "zIndex": "1000",
            "background": "rgba(0,0,0,0.35)", "alignItems": "center", "justifyContent": "center"}


@callback(
    Output("pcap-overlay", "style", allow_duplicate=True),
    Input("pcap-overlay-close", "n_clicks"),
    prevent_initial_call=True,
)
def _close_pcap_overlay(_n):
    return {"display": "none"}


@callback(
    Output("pcap-overlay-list", "children"),
    Input("pcap-overlay-search", "value"),
    State("pcap-overlay-files", "data"),
    prevent_initial_call=False,
)
def _search_pcap_overlay(query, files):
    files = files or []
    q = (query or "").lower()
    if q:
        files = [f for f in files if q in f["name"].lower()]
    return [_folder_file_row(f["name"], f.get("size_human", ""),
                             {"type": "pcap-folder-pick", "name": f["name"]}) for f in files]


# ── history quick-replay ───────────────────────────────────────────────────────

@callback(
    Output("pcap-file-store", "data", allow_duplicate=True),
    Output("pcap-file-loaded", "children", allow_duplicate=True),
    Input({"type": "history-replay-btn", "name": dash.ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def _history_quick_select(n_clicks):
    if not any(n_clicks):
        return dash.no_update, dash.no_update
    trigger = ctx.triggered_id
    if not trigger:
        return dash.no_update, dash.no_update
    name = trigger.get("name", "")
    return {"filename": name, "from_folder": True}, _file_loaded_badge(name, "selected from history")


# ── pcap replay ────────────────────────────────────────────────────────────────

@callback(
    Output("pcap-replay-running", "data"),
    Output("pcap-replay-poll", "disabled"),
    Output("pcap-output-terminal", "children"),
    Output("pcap-output-stats", "children"),
    Output("pcap-live-badge", "children"),
    Output("pcap-banner", "children"),
    Output("pcap-replay-status", "data"),
    Output("pcap-file-info", "data", allow_duplicate=True),
    Input("pcap-replay-btn", "n_clicks"),
    Input("pcap-clear-btn", "n_clicks"),
    State("pcap-file-store", "data"),
    State("pcap-opt-keep", "value"),
    State("pcap-opt-now", "value"),
    State("pcap-file-info", "data"),
    prevent_initial_call=True,
)
def _start_replay(_replay, _clear, file_data, keep_val, now_val, existing_info):
    no_up = dash.no_update
    trigger = ctx.triggered_id

    if trigger == "pcap-clear-btn":
        placeholder = [html.Span("Run a replay to see output…", style={"color": "#6e7681", "fontStyle": "italic"})]
        return False, True, placeholder, [], [], [], "idle", no_up

    if not file_data:
        return False, True, no_up, no_up, no_up, [error_banner("No PCAP file loaded — drop a file or select from folder")], "idle", no_up

    keep = "keep" in (keep_val or [])
    now = "now" in (now_val or [])

    body: dict[str, Any] = {"keep": keep, "now": now, "pcap": file_data["filename"]}
    if not file_data.get("from_folder"):
        body["content"] = file_data.get("content", "")

    result = api_post("/api/capture/replay", body)
    if result.get("error"):
        return False, True, no_up, no_up, no_up, [error_banner(f"Replay failed: {result['error']}")], "error", no_up

    new_info = existing_info
    if not existing_info:
        name = Path(file_data.get("filename", "")).name
        resp = api_get(f"/api/capture/pcap/info?file={name}")
        if not resp.get("error"):
            new_info = resp

    live_badge = [html.Span(" ● Live", style={"fontSize": "11px", "color": "#3B6D11", "fontWeight": "400"})]
    return True, False, [], [], live_badge, [], "running", new_info


@callback(
    Output("pcap-output-terminal", "children", allow_duplicate=True),
    Output("pcap-output-stats", "children", allow_duplicate=True),
    Output("pcap-live-badge", "children", allow_duplicate=True),
    Output("pcap-history-table", "children", allow_duplicate=True),
    Output("pcap-replay-running", "data", allow_duplicate=True),
    Output("pcap-replay-poll", "disabled", allow_duplicate=True),
    Output("pcap-replay-status", "data", allow_duplicate=True),
    Input("pcap-replay-poll", "n_intervals"),
    State("pcap-replay-running", "data"),
    prevent_initial_call=True,
)
def _poll_replay(_n, running):
    no_up = dash.no_update
    if not running:
        return no_up, no_up, no_up, no_up, False, True, no_up

    status = api_get("/api/capture/replay/status")
    if not isinstance(status, dict):
        return no_up, no_up, no_up, no_up, running, False, no_up

    lines = status.get("lines", [])
    done = status.get("done", False)
    result = status.get("result") or {}
    error = status.get("error")

    if error and done:
        lines = list(lines) + [f"[ERROR] {error}"]

    terminal = colorize_log(lines) if lines else []
    stats: dict = {}
    if result:
        stats = {"suricata_docs": result.get("suricata_docs"), "soc_alerts_docs": result.get("soc_alerts_docs")}

    if done:
        history_resp = api_get("/api/capture/history")
        history = history_resp.get("history", []) if isinstance(history_resp, dict) else []
        replay_status = "error" if error else "done"
        return terminal, _replay_stats(stats), [], _history_table(history), False, True, replay_status

    live_badge = [html.Span(" ● Live", style={"fontSize": "11px", "color": "#3B6D11", "fontWeight": "400"})]
    return terminal, _replay_stats(stats), live_badge, no_up, True, False, "running"


@callback(
    Output("pcap-history-table", "children", allow_duplicate=True),
    Output("pcap-history-count", "children"),
    Input("pcap-refresh-btn", "n_clicks"),
    Input("pcap-poll", "n_intervals"),
    prevent_initial_call=True,
)
def _refresh_history(_refresh, _poll):
    history_resp = api_get("/api/capture/history")
    history = history_resp.get("history", []) if isinstance(history_resp, dict) else []
    return _history_table(history), f"{len(history)} replays"
