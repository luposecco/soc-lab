from __future__ import annotations

from pathlib import Path
from typing import Any

import dash
from dash import Input, Output, State, callback, ctx, dcc, html

from ui.helpers import api_get, api_post, colorize_log, error_banner, lcol, lpanel, lrow, ltable, topbar
from ui.pages.capture_pcap_parts import (
    file_placeholder as _file_placeholder,
    folder_file_row as _folder_file_row,
    history_table as _history_table,
    loaded_file_badge as _file_loaded_badge,
    loaded_file_placeholder as _loaded_file_placeholder,
    overlay as _overlay,
    pcap_folder_preview as _pcap_folder_preview,
    replay_stats as _replay_stats,
)

dash.register_page(__name__, path="/capture")


def _info_row(label: str, value: Any) -> html.Tr:
    return html.Tr([
        html.Td(label, style={"color": "#888780", "fontSize": "11px", "whiteSpace": "nowrap", "paddingRight": "10px", "paddingBottom": "5px", "verticalAlign": "top"}),
        html.Td(value, style={"fontSize": "12px", "paddingBottom": "5px"}),
    ])


def _loaded_file_card_body(name: str, source: str, info: dict, status: str) -> html.Div:
    def _dur(secs: float) -> str:
        secs = int(secs)
        return f"{secs // 60}m {secs % 60}s" if secs >= 60 else f"{secs}s"

    def _size(num: int) -> str:
        for unit in ("B", "KB", "MB", "GB"):
            if num < 1024:
                return f"{num:.1f} {unit}"
            num /= 1024
        return f"{num:.1f} TB"

    tags = {
        "idle": html.Span("Ready", className="tag running"),
        "running": html.Span("Replaying…", className="tag blue"),
        "done": html.Span("Done", className="tag running"),
        "error": html.Span("Error", className="tag unknown"),
    }
    rows = [_info_row("Source", source), _info_row("Status", tags.get(status, tags["idle"]))]
    if info.get("packets"):
        rows.append(_info_row("Packets", f"{info['packets']:,}"))
    if info.get("duration_secs"):
        rows.append(_info_row("Duration", _dur(info["duration_secs"])))
    if info.get("size_bytes"):
        rows.append(_info_row("Size", _size(info["size_bytes"])))
    if info.get("protocols"):
        rows.append(_info_row("Protocols", ", ".join(info["protocols"][:6])))

    progress: list[Any] = []
    if status == "running":
        progress = [html.Div(style={"marginTop": "14px"}, children=[html.Div("Replay progress", style={"fontSize": "11px", "color": "#888780", "marginBottom": "2px"}), html.Div(className="progress-bar", children=[html.Div(className="progress-fill progress-indeterminate")])])]
    elif status == "done":
        progress = [html.Div(style={"marginTop": "14px"}, children=[html.Div(style={"display": "flex", "justifyContent": "space-between", "fontSize": "11px", "color": "#888780", "marginBottom": "2px"}, children=[html.Span("Replay progress"), html.Span("100%")]), html.Div(className="progress-bar", children=[html.Div(className="progress-fill", style={"width": "100%"})])])]

    return html.Div(children=[
        html.Div(style={"display": "flex", "alignItems": "flex-start", "gap": "8px", "marginBottom": "12px"}, children=[html.I(className="ti ti-file", style={"fontSize": "18px", "color": "#3B6D11", "marginTop": "1px", "flexShrink": "0"}), html.Div(name, className="mono", style={"fontSize": "12px", "fontWeight": "500", "wordBreak": "break-all", "lineHeight": "1.4"})]),
        html.Table(className="tbl", children=html.Tbody(rows)),
        *progress,
    ])


def _replay_state_view(status: dict[str, Any]) -> tuple[list[Any], list[Any], list[Any], bool, str]:
    lines = status.get("lines", []) if isinstance(status, dict) else []
    result = status.get("result") or {}
    error = status.get("error") if isinstance(status, dict) else None
    done = bool(status.get("done")) if isinstance(status, dict) else True
    running = bool(status.get("running")) if isinstance(status, dict) else False
    if error and done:
        lines = list(lines) + [f"[ERROR] {error}"]
    stats = {}
    if result:
        stats = {"suricata_docs": result.get("suricata_docs"), "soc_alerts_docs": result.get("soc_alerts_docs")}
    terminal = colorize_log(lines) if lines else [html.Span("Run a replay to see output…", style={"color": "#6e7681", "fontStyle": "italic"})]
    badge = [html.Span(" ● Live", style={"fontSize": "11px", "color": "#3B6D11", "fontWeight": "400"})] if running else []
    replay_status = "running" if running else ("error" if error else ("done" if lines or result else "idle"))
    return terminal, _replay_stats(stats), badge, running, replay_status


def layout() -> html.Div:
    history_resp = api_get("/api/capture/history")
    pcap_files_resp = api_get("/api/capture/pcap/files")
    replay_status_resp = api_get("/api/capture/replay/status")
    history = history_resp.get("history", []) if isinstance(history_resp, dict) else []
    pcap_files = pcap_files_resp.get("files", []) if isinstance(pcap_files_resp, dict) else []
    replay_terminal, replay_stats, replay_badge, replay_running, replay_state = _replay_state_view(replay_status_resp if isinstance(replay_status_resp, dict) else {})
    return html.Div([
        topbar("Packet replay", dcc.Interval(id="pcap-poll", interval=15_000, n_intervals=0), html.Button([html.I(className="ti ti-refresh", style={"fontSize": "13px"}), " Refresh"], id="pcap-refresh-btn", className="topbar-btn", n_clicks=0)),
        html.Div(id="pcap-banner"),
        html.Div(className="content", style={"display": "flex", "flexDirection": "column", "gap": "14px", "flex": "1"}, children=[
            html.Div(style=lrow(shrink=True), children=[
                html.Div(style=lcol(), children=[html.Div(className="card", style=lpanel(fill=True, min_h=394), children=[
                    html.Div(className="card-header", children=[html.Span("PCAP file", className="card-title")]),
                    dcc.Upload(id="pcap-upload-zone", children=html.Div([html.Div(html.I(className="ti ti-file-upload", style={"fontSize": "24px", "color": "#888780"}), className="upload-icon"), html.Div("Drop a .pcap / .pcapng file or click to browse", className="upload-title"), html.Div("Max 2 GB — replayed through Suricata IDS", className="upload-sub")], className="upload-zone"), multiple=False),
                    html.Div(id="pcap-file-loaded", style={"marginTop": "10px"}, children=_file_placeholder()),
                    html.Div(style={"borderTop": "0.5px solid rgba(0,0,0,0.07)", "margin": "14px 0"}),
                    html.Div(style={"display": "flex", "alignItems": "center", "justifyContent": "space-between", "marginBottom": "8px"}, children=[html.Span("From data/pcap/", style={"fontSize": "11px", "fontWeight": "600", "color": "#888780", "textTransform": "uppercase", "letterSpacing": "0.05em"}), html.Button([html.I(className="ti ti-refresh", style={"fontSize": "11px"}), " Refresh"], id="pcap-folder-refresh-btn", className="rule-btn", n_clicks=0)]),
                    html.Div(id="pcap-folder-list", children=_pcap_folder_preview(pcap_files)),
                    html.Button([html.I(className="ti ti-folder-open", style={"fontSize": "13px", "verticalAlign": "middle", "marginRight": "5px"}), html.Span("Show all files", style={"verticalAlign": "middle"})], id="pcap-show-all-btn", className="rule-btn", style={"marginTop": "8px", "width": "100%", "justifyContent": "center", "display": "none" if len(pcap_files) <= 3 else "inline-flex", "alignItems": "center", "lineHeight": "1"}, n_clicks=0),
                ])]),
                html.Div(style=lcol(), children=[
                    html.Div(className="card", style=lpanel(min_h=200, shrink=True), children=[
                        html.Div(className="card-header", children=[html.Span("Replay options", className="card-title")]),
                        html.Div(style={"display": "flex", "flexDirection": "column", "gap": "14px"}, children=[
                            html.Label(style={"display": "flex", "alignItems": "center", "gap": "12px", "cursor": "pointer"}, children=[dcc.Checklist(id="pcap-opt-keep", options=[{"label": "", "value": "keep"}], value=[], inline=True), html.Div([html.Div("Keep mode", style={"fontSize": "13px", "fontWeight": "500"}), html.Div("Preserve existing indexed data and alerts", style={"fontSize": "11px", "color": "#888780"})])]),
                            html.Label(style={"display": "flex", "alignItems": "center", "gap": "12px", "cursor": "pointer"}, children=[dcc.Checklist(id="pcap-opt-now", options=[{"label": "", "value": "now"}], value=[], inline=True), html.Div([html.Div("Shift timestamps to now", style={"fontSize": "13px", "fontWeight": "500"}), html.Div("Rebase event timestamps to current time", style={"fontSize": "11px", "color": "#888780"})])]),
                            html.Button([html.I(className="ti ti-player-play", style={"fontSize": "14px"}), " Replay"], id="pcap-replay-btn", className="topbar-btn primary", style={"width": "100%", "justifyContent": "center", "padding": "10px", "marginTop": "4px"}, n_clicks=0),
                        ]),
                    ]),
                    html.Div(className="card", style=ltable(fill=True, min_h=180), children=[
                        html.Div(className="card-header", style={"flexShrink": "0"}, children=[html.Span("Recent replays", className="card-title"), html.Span(id="pcap-history-count", children=f"{len(history)} replays", style={"fontSize": "11px", "color": "#888780"})]),
                        html.Div(id="pcap-history-table", children=_history_table(history), className="table-panel-body"),
                    ]),
                ]),
            ]),
            html.Div(style={"display": "flex", "gap": "14px", "flex": "1", "minHeight": "0", "marginBottom": "20px"}, children=[
                html.Div(className="card", style={**lpanel(fill=True, min_h=300), "overflow": "hidden"}, children=[
                    html.Div(className="card-header", style={"flexShrink": "0"}, children=[html.Span(["Replay output", html.Span(id="pcap-live-badge", children=replay_badge)], className="card-title"), html.Button("Clear", id="pcap-clear-btn", className="rule-btn", n_clicks=0)]),
                    html.Div(id="pcap-output-terminal", className="terminal fill", style={"minHeight": "0"}, children=replay_terminal),
                    html.Div(id="pcap-output-stats", style={"flexShrink": "0"}, children=replay_stats),
                ]),
                html.Div(className="card", style={**lpanel(min_h=300), "flexBasis": "350px", "flexShrink": "0"}, children=[
                    html.Div(className="card-header", children=[html.Span("Loaded file", className="card-title")]),
                    html.Div(id="pcap-loaded-file-info", children=_loaded_file_placeholder()),
                ]),
            ]),
        ]),
        _overlay("pcap-overlay", "PCAP files — data/pcap/", pcap_files, "pcap-folder-pick"),
        dcc.Store(id="pcap-file-store", data=None), dcc.Store(id="pcap-file-info", data=None), dcc.Store(id="pcap-replay-running", data=replay_running), dcc.Store(id="pcap-replay-status", data=replay_state), dcc.Interval(id="pcap-replay-poll", interval=1500, n_intervals=0, disabled=not replay_running),
    ])


@callback(Output("pcap-file-store", "data"), Output("pcap-file-loaded", "children"), Input("pcap-upload-zone", "contents"), State("pcap-upload-zone", "filename"), prevent_initial_call=True)
def _store_pcap(contents, filename):
    if not contents:
        return None, _file_placeholder()
    return {"content": contents, "filename": filename}, _file_loaded_badge(filename, "uploaded")


@callback(Output("pcap-file-info", "data"), Input("pcap-file-store", "data"), prevent_initial_call=True)
def _load_pcap_info(file_data):
    if not file_data or not file_data.get("from_folder"):
        return None
    resp = api_get(f"/api/capture/pcap/info?file={file_data.get('filename', '')}")
    return resp if not resp.get("error") else None


@callback(Output("pcap-loaded-file-info", "children"), Input("pcap-file-store", "data"), Input("pcap-file-info", "data"), Input("pcap-replay-status", "data"))
def _update_loaded_file(file_data, file_info, replay_status):
    if not file_data:
        return _loaded_file_placeholder()
    return _loaded_file_card_body(file_data.get("filename", "—"), "data/pcap/" if file_data.get("from_folder") else "uploaded", file_info or {}, replay_status or "idle")


@callback(Output("pcap-file-store", "data", allow_duplicate=True), Output("pcap-file-loaded", "children", allow_duplicate=True), Output("pcap-overlay", "style", allow_duplicate=True), Input({"type": "pcap-folder-pick", "name": dash.ALL}, "n_clicks"), prevent_initial_call=True)
def _pick_pcap_from_folder(n_clicks):
    if not any(n_clicks) or not ctx.triggered_id:
        return dash.no_update, dash.no_update, dash.no_update
    name = ctx.triggered_id.get("name", "")
    return {"filename": name, "from_folder": True}, _file_loaded_badge(name, "selected from data/pcap/"), {"display": "none"}


@callback(Output("pcap-folder-list", "children"), Output("pcap-overlay-files", "data"), Output("pcap-show-all-btn", "style"), Output("pcap-show-all-btn", "children"), Input("pcap-folder-refresh-btn", "n_clicks"), Input("pcap-poll", "n_intervals"), prevent_initial_call=False)
def _refresh_pcap_folder(_refresh, _poll):
    resp = api_get("/api/capture/pcap/files")
    files = resp.get("files", []) if isinstance(resp, dict) else []
    btn_style = {"marginTop": "8px", "width": "100%", "justifyContent": "center", "display": "none" if len(files) <= 3 else "flex"}
    btn_label = [html.I(className="ti ti-folder-open", style={"fontSize": "13px", "verticalAlign": "middle", "marginRight": "5px"}), html.Span(f"Show all {len(files)} files", style={"verticalAlign": "middle"})]
    return _pcap_folder_preview(files), files, btn_style, btn_label


@callback(Output("pcap-overlay", "style", allow_duplicate=True), Input("pcap-show-all-btn", "n_clicks"), prevent_initial_call=True)
def _open_pcap_overlay(_n):
    return {"display": "flex", "position": "fixed", "inset": "0", "zIndex": "1000", "background": "rgba(0,0,0,0.35)", "alignItems": "center", "justifyContent": "center"}


@callback(Output("pcap-overlay", "style", allow_duplicate=True), Input("pcap-overlay-close", "n_clicks"), prevent_initial_call=True)
def _close_pcap_overlay(_n):
    return {"display": "none"}


@callback(Output("pcap-overlay-list", "children"), Input("pcap-overlay-search", "value"), State("pcap-overlay-files", "data"), prevent_initial_call=False)
def _search_pcap_overlay(query, files):
    rows = files or []
    if query:
        rows = [item for item in rows if query.lower() in item["name"].lower()]
    return [_folder_file_row(item["name"], item.get("size_human", ""), {"type": "pcap-folder-pick", "name": item["name"]}) for item in rows]


@callback(Output("pcap-file-store", "data", allow_duplicate=True), Output("pcap-file-loaded", "children", allow_duplicate=True), Input({"type": "history-replay-btn", "name": dash.ALL}, "n_clicks"), prevent_initial_call=True)
def _history_quick_select(n_clicks):
    if not any(n_clicks) or not ctx.triggered_id:
        return dash.no_update, dash.no_update
    name = ctx.triggered_id.get("name", "")
    return {"filename": name, "from_folder": True}, _file_loaded_badge(name, "selected from history")


@callback(Output("pcap-replay-running", "data"), Output("pcap-replay-poll", "disabled"), Output("pcap-output-terminal", "children"), Output("pcap-output-stats", "children"), Output("pcap-live-badge", "children"), Output("pcap-banner", "children"), Output("pcap-replay-status", "data"), Output("pcap-file-info", "data", allow_duplicate=True), Input("pcap-replay-btn", "n_clicks"), Input("pcap-clear-btn", "n_clicks"), State("pcap-file-store", "data"), State("pcap-opt-keep", "value"), State("pcap-opt-now", "value"), State("pcap-file-info", "data"), prevent_initial_call=True)
def _start_replay(_replay, _clear, file_data, keep_val, now_val, existing_info):
    if ctx.triggered_id == "pcap-clear-btn":
        api_post("/api/capture/replay/clear")
        return False, True, [html.Span("Run a replay to see output…", style={"color": "#6e7681", "fontStyle": "italic"})], [], [], [], "idle", dash.no_update
    if not file_data:
        return False, True, dash.no_update, dash.no_update, dash.no_update, [error_banner("No PCAP file loaded — drop a file or select from folder")], "idle", dash.no_update
    body: dict[str, Any] = {"keep": "keep" in (keep_val or []), "now": "now" in (now_val or []), "pcap": file_data["filename"]}
    if not file_data.get("from_folder"):
        body["content"] = file_data.get("content", "")
    result = api_post("/api/capture/replay", body)
    if result.get("error"):
        return False, True, dash.no_update, dash.no_update, dash.no_update, [error_banner(f"Replay failed: {result['error']}")], "error", dash.no_update
    new_info = existing_info
    if not existing_info:
        resp = api_get(f"/api/capture/pcap/info?file={Path(file_data.get('filename', '')).name}")
        if not resp.get("error"):
            new_info = resp
    return True, False, [], [], [html.Span(" ● Live", style={"fontSize": "11px", "color": "#3B6D11", "fontWeight": "400"})], [], "running", new_info


@callback(Output("pcap-output-terminal", "children", allow_duplicate=True), Output("pcap-output-stats", "children", allow_duplicate=True), Output("pcap-live-badge", "children", allow_duplicate=True), Output("pcap-history-table", "children", allow_duplicate=True), Output("pcap-replay-running", "data", allow_duplicate=True), Output("pcap-replay-poll", "disabled", allow_duplicate=True), Output("pcap-replay-status", "data", allow_duplicate=True), Input("pcap-replay-poll", "n_intervals"), State("pcap-replay-running", "data"), prevent_initial_call=True)
def _poll_replay(_n, running):
    if not running:
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update, False, True, dash.no_update
    status = api_get("/api/capture/replay/status")
    if not isinstance(status, dict):
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update, running, False, dash.no_update
    lines, done, result, error = status.get("lines", []), status.get("done", False), status.get("result") or {}, status.get("error")
    if error and done:
        lines = list(lines) + [f"[ERROR] {error}"]
    stats = {"suricata_docs": result.get("suricata_docs"), "soc_alerts_docs": result.get("soc_alerts_docs")} if result else {}
    terminal = colorize_log(lines) if lines else []
    if done:
        history_resp = api_get("/api/capture/history")
        history = history_resp.get("history", []) if isinstance(history_resp, dict) else []
        return terminal, _replay_stats(stats), [], _history_table(history), False, True, "error" if error else "done"
    badge = [html.Span(" ● Live", style={"fontSize": "11px", "color": "#3B6D11", "fontWeight": "400"})]
    return terminal, _replay_stats(stats), badge, dash.no_update, True, False, "running"


@callback(Output("pcap-history-table", "children", allow_duplicate=True), Output("pcap-history-count", "children"), Input("pcap-refresh-btn", "n_clicks"), Input("pcap-poll", "n_intervals"), prevent_initial_call=True)
def _refresh_history(_refresh, _poll):
    history_resp = api_get("/api/capture/history")
    history = history_resp.get("history", []) if isinstance(history_resp, dict) else []
    return _history_table(history), f"{len(history)} replays"
