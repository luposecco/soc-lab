from __future__ import annotations

import dash
from dash import Input, Output, State, callback, ctx, dcc, html

from ui.helpers import api_get, api_post, colorize_log, error_banner, topbar

dash.register_page(__name__, path="/capture/live")


def _live_status_tag(running: bool, stopping: bool = False) -> html.Span:
    if stopping:
        return html.Span("Stopping…", className="tag warning")
    return html.Span("Running", className="tag running") if running else html.Span("Idle", className="tag unknown")


def _sessions_table(sessions: list[dict]) -> html.Div:
    if not sessions:
        return html.Div("No sessions yet.", style={"fontSize": "12px", "color": "#888780", "padding": "12px 0"})

    def _dur(s: dict) -> str:
        try:
            from datetime import datetime, timezone
            start = datetime.fromisoformat(s["started_at"])
            end_str = s.get("stopped_at")
            end = datetime.fromisoformat(end_str) if end_str else datetime.now(timezone.utc)
            secs = int((end - start).total_seconds())
            return f"{secs // 60}m {secs % 60}s"
        except Exception:
            return "—"

    def _ts(s: dict) -> str:
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(s["started_at"]).astimezone()
            return dt.strftime("%b %d %H:%M")
        except Exception:
            return "—"

    header = html.Thead(html.Tr([
        html.Th("Interface"),
        html.Th("Duration"),
        html.Th("Rotation", style={"textAlign": "right"}),
        html.Th("Keep", style={"textAlign": "center"}),
        html.Th("Docs", style={"textAlign": "right"}),
        html.Th("Alerts", style={"textAlign": "right"}),
        html.Th("Date"),
        html.Th("Status"),
    ]), style={"position": "sticky", "top": "0", "background": "#fff", "zIndex": "1"})

    rows = []
    for s in sessions[:15]:
        status = s.get("status", "stopped")
        tag = html.Span("Running", className="tag running") if status == "running" else html.Span("Done", className="tag unknown")
        rotation = s.get("rotation_secs")
        rotation_str = f"{rotation}s" if rotation else "—"
        keep_icon = html.I(className="ti ti-check", style={"color": "#3B6D11"}) if s.get("keep") else html.Span("—", style={"color": "#b0afac"})
        sd = s.get("suricata_docs")
        sa = s.get("soc_alerts_docs")
        docs_str = f"{sd:,}" if sd else "—"
        alerts_str = html.B(f"{sa:,}", style={"color": "#A32D2D"}) if sa else html.Span("—", style={"color": "#b0afac"})
        rows.append(html.Tr([
            html.Td(s.get("interface", "—"), style={"fontWeight": "500", "fontSize": "13px"}),
            html.Td(_dur(s), style={"fontSize": "12px", "color": "#888780"}),
            html.Td(rotation_str, style={"fontSize": "11px", "color": "#888780", "textAlign": "right"}),
            html.Td(keep_icon, style={"textAlign": "center"}),
            html.Td(docs_str, style={"fontSize": "12px", "textAlign": "right", "fontWeight": "500"}),
            html.Td(alerts_str, style={"fontSize": "12px", "textAlign": "right"}),
            html.Td(_ts(s), style={"fontSize": "11px", "color": "#888780", "whiteSpace": "nowrap"}),
            html.Td(tag),
        ]))

    return html.Div(
        html.Table([header, html.Tbody(rows)], className="tbl"),
        style={"overflowY": "auto", "maxHeight": "260px"},
    )


def layout() -> html.Div:
    live_resp = api_get("/api/capture/live/status")
    live = live_resp if isinstance(live_resp, dict) else {}
    ifaces_resp = api_get("/api/capture/interfaces")
    interfaces = ifaces_resp.get("interfaces", []) if isinstance(ifaces_resp, dict) else []
    sessions_resp = api_get("/api/capture/live/sessions")
    sessions = sessions_resp.get("sessions", []) if isinstance(sessions_resp, dict) else []

    running = live.get("running", False)

    return html.Div([
        topbar(
            "Live capture",
            dcc.Interval(id="live-poll", interval=15_000, n_intervals=0),
            html.Button(
                [html.I(className="ti ti-refresh", style={"fontSize": "13px"}), " Refresh"],
                id="live-refresh-btn", className="topbar-btn", n_clicks=0,
            ),
        ),
        html.Div(id="live-banner"),
        html.Div(className="content", style={"display": "flex", "flexDirection": "column", "gap": "14px", "flex": "1"}, children=[

            html.Div(style={"display": "flex", "gap": "14px"}, children=[

                # left: capture options
                html.Div(className="card", style={"width": "300px", "flexShrink": "0"}, children=[
                    html.Div(className="card-header", children=[
                        html.Span("Capture options", className="card-title"),
                        html.Div(id="live-status-tag", children=_live_status_tag(running)),
                    ]),
                    html.Div(style={"display": "flex", "flexDirection": "column", "gap": "12px"}, children=[

                        html.Div([
                            html.Div(style={"display": "flex", "alignItems": "center", "justifyContent": "space-between", "marginBottom": "5px"}, children=[
                                html.Div("Network interface", style={"fontSize": "11px", "color": "#888780"}),
                                html.Button([html.I(className="ti ti-refresh", style={"fontSize": "11px"}), " Refresh"],
                                            id="live-iface-refresh-btn", className="rule-btn", n_clicks=0),
                            ]),
                            dcc.Dropdown(
                                id="live-iface",
                                options=[{"label": iface, "value": iface} for iface in interfaces],
                                value=interfaces[0] if interfaces else None,
                                placeholder="Select interface…",
                                clearable=False,
                                style={"fontSize": "13px"},
                            ),
                        ]),

                        html.Div(style={"borderTop": "0.5px solid rgba(0,0,0,0.07)"}),

                        html.Div([
                            html.Div("File rotation (seconds)", style={"fontSize": "11px", "color": "#888780", "marginBottom": "5px"}),
                            dcc.Input(id="live-rotation", type="number", value=10, className="setting-input",
                                      style={"width": "100%", "boxSizing": "border-box"}),
                        ]),

                        html.Label(style={"display": "flex", "alignItems": "center", "gap": "12px", "cursor": "pointer"}, children=[
                            dcc.Checklist(id="live-opt-keep", options=[{"label": "", "value": "keep"}], value=[], inline=True),
                            html.Div([
                                html.Div("Keep mode", style={"fontSize": "13px", "fontWeight": "500"}),
                                html.Div("Preserve existing data between captures", style={"fontSize": "11px", "color": "#888780"}),
                            ]),
                        ]),

                        html.Div(
                            style={"padding": "10px 12px", "background": "#F1F5F9", "borderRadius": "8px",
                                   "fontSize": "12px", "color": "#5f5e5a"},
                            children=[
                                html.I(className="ti ti-info-circle", style={"verticalAlign": "-2px", "marginRight": "6px", "color": "#6B9DD8"}),
                                "dumpcap → auto-replays each segment through Suricata IDS",
                            ],
                        ),

                        html.Div(style={"display": "flex", "gap": "8px"}, children=[
                            html.Button(
                                [html.I(className="ti ti-player-record", style={"fontSize": "14px"}), " Start capture"],
                                id="live-start-btn", className="topbar-btn success",
                                style={"flex": "1", "justifyContent": "center", "padding": "10px"},
                                disabled=running, n_clicks=0,
                            ),
                            html.Button(
                                [html.I(className="ti ti-player-stop", style={"fontSize": "14px"}), " Stop"],
                                id="live-stop-btn", className="topbar-btn danger",
                                style={"flex": "1", "justifyContent": "center", "padding": "10px"},
                                disabled=not running, n_clicks=0,
                            ),
                        ]),
                    ]),
                ]),

                # right: capture sessions
                html.Div(className="card", style={"flex": "1", "display": "flex", "flexDirection": "column", "minWidth": "0"}, children=[
                    html.Div(className="card-header", style={"flexShrink": "0"}, children=[
                        html.Span("Capture sessions", className="card-title"),
                        html.Span(id="live-sessions-count", style={"fontSize": "11px", "color": "#888780"}),
                    ]),
                    html.Div(id="live-sessions-table", children=_sessions_table(sessions),
                             style={"flex": "1", "minHeight": "0", "overflowY": "auto"}),
                ]),
            ]),

            # live output — full width
            html.Div(className="card", style={"flex": "1", "display": "flex", "flexDirection": "column", "minHeight": "0"}, children=[
                html.Div(className="card-header", style={"flexShrink": "0"}, children=[
                    html.Span("Live output", className="card-title"),
                    html.Button("Clear", id="live-clear-btn", className="rule-btn", n_clicks=0),
                ]),
                html.Div(
                    id="live-output-terminal",
                    className="terminal fill",
                    children=[html.Span("Start a capture to see live output…",
                                        style={"color": "#6e7681", "fontStyle": "italic"})],
                ),
            ]),
        ]),

        dcc.Store(id="live-stopping", data=False),
        dcc.Interval(id="live-log-poll", interval=3000, n_intervals=0),
    ])


@callback(
    Output("live-iface", "options"),
    Output("live-iface", "value"),
    Input("live-iface-refresh-btn", "n_clicks"),
    prevent_initial_call=True,
)
def _refresh_live_ifaces(_n):
    resp = api_get("/api/capture/interfaces")
    ifaces = resp.get("interfaces", []) if isinstance(resp, dict) else []
    opts = [{"label": iface, "value": iface} for iface in ifaces]
    return opts, (ifaces[0] if ifaces else None)


@callback(
    Output("live-start-btn", "disabled"),
    Output("live-stop-btn", "disabled"),
    Output("live-status-tag", "children"),
    Output("live-stopping", "data"),
    Output("live-sessions-table", "children"),
    Output("live-sessions-count", "children"),
    Output("live-banner", "children"),
    Input("live-start-btn", "n_clicks"),
    Input("live-stop-btn", "n_clicks"),
    Input("live-poll", "n_intervals"),
    State("live-iface", "value"),
    State("live-rotation", "value"),
    State("live-opt-keep", "value"),
    State("live-stopping", "data"),
    prevent_initial_call=True,
)
def _live_controls(_start, _stop, _poll, iface, rotation, keep_val, stopping):
    trigger = ctx.triggered_id
    banner: list = []
    stopping = stopping or False

    if trigger == "live-start-btn":
        keep = "keep" in (keep_val or [])
        result = api_post("/api/capture/live/start", {
            "iface": iface or "en0",
            "rotation": int(rotation or 10),
            "keep": keep,
        })
        if result.get("error"):
            banner = [error_banner(f"Start failed: {result['error']}")]
        stopping = False
    elif trigger == "live-stop-btn":
        result = api_post("/api/capture/live/stop")
        if result.get("error"):
            banner = [error_banner(f"Stop failed: {result['error']}")]
        else:
            stopping = True

    status = api_get("/api/capture/live/status")
    running = status.get("running", False) if isinstance(status, dict) else False
    if not running:
        stopping = False

    sessions_resp = api_get("/api/capture/live/sessions")
    sessions = sessions_resp.get("sessions", []) if isinstance(sessions_resp, dict) else []
    count = f"{len(sessions)} session{'s' if len(sessions) != 1 else ''}" if sessions else ""

    return running, not running, _live_status_tag(running, stopping), stopping, _sessions_table(sessions), count, banner


@callback(
    Output("live-output-terminal", "children"),
    Input("live-log-poll", "n_intervals"),
    Input("live-poll", "n_intervals"),
    prevent_initial_call=False,
)
def _poll_live_log(_log_poll, _cap_poll):
    log = api_get("/api/capture/live/log")
    text = log.get("log", "") if isinstance(log, dict) else ""
    if not text:
        status = api_get("/api/capture/live/status")
        running = status.get("running", False) if isinstance(status, dict) else False
        if not running:
            return [html.Span("Start a capture to see live output…",
                              style={"color": "#6e7681", "fontStyle": "italic"})]
        return [html.Span("Capture starting…", style={"color": "#6e7681", "fontStyle": "italic"})]
    lines = text.splitlines()
    return colorize_log(lines)
