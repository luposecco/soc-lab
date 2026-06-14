from __future__ import annotations

from datetime import datetime, timezone

import dash
from dash import Input, Output, State, callback, ctx, dcc, html

from ui.helpers import api_get, api_post, colorize_log, error_banner, lpanel, ltable, topbar

dash.register_page(__name__, path="/capture/live")

_PROTO_COLORS = {"tcp": "#185FA5", "udp": "#639922", "icmp": "#BA7517", "dns": "#6B9DD8"}


# ── helpers ───────────────────────────────────────────────────────────────────

def _live_status_tag(running: bool, stopping: bool = False) -> html.Span:
    if stopping:
        return html.Span("Stopping…", className="tag warning")
    return html.Span("Running", className="tag running") if running else html.Span("Idle", className="tag unknown")


def _dur_str(started_at: str | None, stopped_at: str | None = None) -> str:
    if not started_at:
        return "—"
    try:
        start = datetime.fromisoformat(started_at)
        end = datetime.fromisoformat(stopped_at) if stopped_at else datetime.now(timezone.utc)
        secs = int((end - start).total_seconds())
        return f"{secs // 60}m {secs % 60}s"
    except Exception:
        return "—"


def _ts_str(started_at: str | None) -> str:
    if not started_at:
        return "—"
    try:
        dt = datetime.fromisoformat(started_at).astimezone()
        return dt.strftime("%b %d %H:%M")
    except Exception:
        return "—"


def _active_session(sessions: list[dict]) -> dict:
    for s in sessions:
        if s.get("status") == "running":
            return s
    return sessions[0] if sessions else {}


# ── metrics row ───────────────────────────────────────────────────────────────

def _metrics_row(sessions: list[dict], running: bool) -> html.Div:
    s = _active_session(sessions) if running else {}
    duration = _dur_str(s.get("started_at")) if s else "—"
    segs = s.get("segments_replayed", 0) if s else 0
    docs = s.get("suricata_docs", 0) if s else 0
    alerts = s.get("soc_alerts_docs", 0) if s else 0
    rotation = s.get("rotation_secs", "—") if s else "—"

    def _metric(label: str, val: str, sub: str, color: str = "") -> html.Div:
        return html.Div(className="metric", children=[
            html.Div(label, className="metric-label"),
            html.Div(val, className=f"metric-val {color}".strip()),
            html.Div(sub, className="metric-sub"),
        ])

    return html.Div(id="live-metrics", className="metrics", style={"flexShrink": "0"}, children=[
        _metric("Session duration", duration, "current session", "blue"),
        _metric("Segments replayed", f"{segs:,}" if segs else "—", f"{rotation}s rotation" if segs else "—"),
        _metric("Suricata docs", f"{docs:,}" if docs else "—", "+N last segment"),
        _metric("Alerts triggered", f"{alerts:,}" if alerts else "—", "in soc-alerts", "red" if alerts else ""),
    ])


# ── current session stats card ────────────────────────────────────────────────

def _sparkline(history: list[int], width: int = 7, gap: int = 2) -> html.Div:
    """Bar chart of per-segment doc deltas."""
    if not history:
        return html.Div(style={"height": "32px"})
    max_val = max(history) or 1
    bars = []
    for i, val in enumerate(history):
        pct = max(4, int(val / max_val * 100))
        is_now = i == len(history) - 1
        bars.append(html.Div(
            className=f"sparkbar{'  now' if is_now else ''}",
            style={"width": f"{width}px", "height": f"{pct}%"},
        ))
    return html.Div(
        className="sparkbar-wrap",
        style={"height": "32px", "gap": f"{gap}px"},
        children=bars,
    )


def _proto_bars(by_proto: dict) -> list:
    if not by_proto:
        return [html.Div("No flow data.", style={"fontSize": "12px", "color": "#888780"})]
    total = sum(by_proto.values()) or 1
    rows = []
    for proto, count in sorted(by_proto.items(), key=lambda x: -x[1])[:5]:
        pct = count / total * 100
        color = _PROTO_COLORS.get(proto.lower(), "#b0afac")
        rows.append(html.Div(
            style={"display": "flex", "alignItems": "center", "gap": "7px", "fontSize": "12px"},
            children=[
                html.Span(proto.upper(), style={"width": "32px", "fontWeight": "500"}),
                html.Div(className="proto-bar-bg", children=[
                    html.Div(className="proto-bar-fill", style={"width": f"{pct:.0f}%", "background": color}),
                ]),
                html.Span(f"{pct:.0f}%", style={"width": "28px", "textAlign": "right", "color": "#888780"}),
            ],
        ))
    return rows


def _docs_per_min(sessions: list[dict], running: bool) -> str:
    s = _active_session(sessions) if running else {}
    if not s:
        return "—"
    docs = s.get("suricata_docs", 0) or 0
    started_at = s.get("started_at")
    if not docs or not started_at:
        return "—"
    try:
        secs = (datetime.now(timezone.utc) - datetime.fromisoformat(started_at)).total_seconds()
        if secs < 1:
            return "—"
        rate = docs / (secs / 60)
        return f"{rate:,.0f}"
    except Exception:
        return "—"


def _session_stats_card(sessions: list[dict], running: bool, by_proto: dict) -> html.Div:
    s = _active_session(sessions) if running else {}
    history = s.get("segment_docs_history", []) if s else []
    seg_label = f"seg #{s.get('segments_replayed', 0)} · {s.get('interface', '—')}" if s else "—"
    docs_rate = _docs_per_min(sessions, running)

    return html.Div(id="live-session-stats", className="card", style={**lpanel(min_h=180, shrink=True)}, children=[
        html.Div(className="card-header", style={"marginBottom": "12px"}, children=[
            html.Span("Current session", className="card-title"),
            html.Span(seg_label, style={"fontSize": "11px", "color": "#888780"}),
        ]),
        html.Div(style={"display": "flex", "alignItems": "stretch", "gap": "0"}, children=[

            # Docs rate + sparkline
            html.Div(style={"flex": "1", "paddingRight": "16px", "borderRight": "0.5px solid rgba(0,0,0,0.08)"}, children=[
                html.Div("Docs / min", style={"fontSize": "11px", "color": "#888780", "marginBottom": "4px", "textTransform": "uppercase", "letterSpacing": "0.05em"}),
                html.Div(docs_rate, style={"fontSize": "24px", "fontWeight": "600", "letterSpacing": "-0.02em", "color": "#185FA5", "lineHeight": "1"}),
                html.Div("avg this session", style={"fontSize": "11px", "color": "#888780", "marginBottom": "8px"}),
                html.Div("Docs per segment", style={"fontSize": "10px", "color": "#b0afac", "marginBottom": "4px", "textTransform": "uppercase", "letterSpacing": "0.04em"}),
                _sparkline(history),
            ]),

            # Segment count + alerts rate
            html.Div(style={"flex": "1", "padding": "0 16px", "borderRight": "0.5px solid rgba(0,0,0,0.08)"}, children=[
                html.Div("Total docs", style={"fontSize": "11px", "color": "#888780", "marginBottom": "4px", "textTransform": "uppercase", "letterSpacing": "0.05em"}),
                html.Div(
                    f'{s.get("suricata_docs", 0):,}' if s and s.get("suricata_docs") else "—",
                    style={"fontSize": "24px", "fontWeight": "600", "letterSpacing": "-0.02em", "lineHeight": "1"},
                ),
                html.Div("suricata events indexed", style={"fontSize": "11px", "color": "#888780", "marginBottom": "14px"}),
                html.Div("Alerts", style={"fontSize": "11px", "color": "#888780", "marginBottom": "4px", "textTransform": "uppercase", "letterSpacing": "0.05em"}),
                html.Div(
                    f'{s.get("soc_alerts_docs", 0):,}' if s and s.get("soc_alerts_docs") else "—",
                    style={
                        "fontSize": "20px", "fontWeight": "600", "letterSpacing": "-0.02em", "lineHeight": "1",
                        "color": "#A32D2D" if (s and s.get("soc_alerts_docs")) else "inherit",
                    },
                ),
                html.Div("in soc-alerts", style={"fontSize": "11px", "color": "#888780"}),
            ]),

            # Protocol breakdown
            html.Div(style={"flex": "1", "paddingLeft": "16px"}, children=[
                html.Div("Protocols", style={"fontSize": "11px", "color": "#888780", "marginBottom": "8px", "textTransform": "uppercase", "letterSpacing": "0.05em"}),
                html.Div(style={"display": "flex", "flexDirection": "column", "gap": "6px"}, children=_proto_bars(by_proto)),
            ]),

        ]),
    ])


# ── sessions table ────────────────────────────────────────────────────────────

def _sessions_table(sessions: list[dict]) -> html.Div:
    if not sessions:
        return html.Div("No sessions yet.", style={"fontSize": "12px", "color": "#888780", "padding": "12px 0"})

    header = html.Thead(html.Tr([
        html.Th("Interface"),
        html.Th("Duration"),
        html.Th("Rotation", style={"textAlign": "right"}),
        html.Th("Keep", style={"textAlign": "center"}),
        html.Th("Segments", style={"textAlign": "right"}),
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
        keep_icon = html.I(className="ti ti-check", style={"color": "#3B6D11"}) if s.get("keep") else html.Span("—", style={"color": "#b0afac"})
        sd = s.get("suricata_docs")
        sa = s.get("soc_alerts_docs")
        segs = s.get("segments_replayed")
        rows.append(html.Tr([
            html.Td(s.get("interface", "—"), style={"fontWeight": "500", "fontSize": "13px"}),
            html.Td(_dur_str(s.get("started_at"), s.get("stopped_at")), style={"fontSize": "12px", "color": "#888780"}),
            html.Td(f"{rotation}s" if rotation else "—", style={"fontSize": "11px", "color": "#888780", "textAlign": "right"}),
            html.Td(keep_icon, style={"textAlign": "center"}),
            html.Td(f"{segs:,}" if segs else "—", style={"fontSize": "12px", "textAlign": "right", "fontWeight": "500"}),
            html.Td(f"{sd:,}" if sd else "—", style={"fontSize": "12px", "textAlign": "right", "fontWeight": "500"}),
            html.Td(html.B(f"{sa:,}", style={"color": "#A32D2D"}) if sa else html.Span("—", style={"color": "#b0afac"}), style={"fontSize": "12px", "textAlign": "right"}),
            html.Td(_ts_str(s.get("started_at")), style={"fontSize": "11px", "color": "#888780", "whiteSpace": "nowrap"}),
            html.Td(tag),
        ]))

    return html.Table([header, html.Tbody(rows)], className="tbl")


# ── layout ────────────────────────────────────────────────────────────────────

def layout() -> html.Div:
    live_resp = api_get("/api/capture/live/status")
    live = live_resp if isinstance(live_resp, dict) else {}
    ifaces_resp = api_get("/api/capture/interfaces")
    interfaces = ifaces_resp.get("interfaces", []) if isinstance(ifaces_resp, dict) else []
    sessions_resp = api_get("/api/capture/live/sessions")
    sessions = sessions_resp.get("sessions", []) if isinstance(sessions_resp, dict) else []
    net_resp = api_get("/api/network/flows")
    by_proto = net_resp.get("by_proto", {}) if isinstance(net_resp, dict) else {}

    running = live.get("running", False)

    topbar_children: list = [
        dcc.Interval(id="live-poll", interval=15_000, n_intervals=0),
        html.Button(
            [html.I(className="ti ti-refresh", style={"fontSize": "13px"}), " Refresh"],
            id="live-refresh-btn", className="topbar-btn", n_clicks=0,
        ),
    ]
    if running:
        iface = live.get("iface") or (sessions[0].get("interface") if sessions else "")
        topbar_children.insert(0, html.Div(
            className="live-badge",
            children=[html.Span(className="dot green pulse"), f"Running — {iface}"],
        ))

    return html.Div([
        topbar("Live capture", *topbar_children),
        html.Div(id="live-banner"),
        html.Div(className="content", style={"display": "flex", "flexDirection": "column", "gap": "14px", "flex": "1", "paddingBottom": "20px"}, children=[

            # Metrics row
            _metrics_row(sessions, running),

            html.Div(style={"display": "flex", "gap": "14px", "flexShrink": "0"}, children=[

                # Left: capture options
                html.Div(className="card", style={**lpanel(min_h=394), "flexBasis": "280px", "flexShrink": "0"}, children=[
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

                # Right: session stats + sessions table stacked
                html.Div(style={"flex": "1", "display": "flex", "flexDirection": "column", "gap": "14px", "minWidth": "0"}, children=[

                    _session_stats_card(sessions, running, by_proto),

                    html.Div(className="card", style=ltable(fill=True, min_h=200), children=[
                        html.Div(className="card-header", style={"flexShrink": "0"}, children=[
                            html.Span("Capture sessions", className="card-title"),
                            html.Span(id="live-sessions-count", style={"fontSize": "11px", "color": "#888780"}),
                        ]),
                        html.Div(id="live-sessions-table", children=_sessions_table(sessions), className="table-panel-body"),
                    ]),
                ]),
            ]),

            # Live output terminal
            html.Div(className="card", style={**lpanel(fill=True, min_h=300), "overflow": "hidden"}, children=[
                html.Div(className="card-header", style={"flexShrink": "0"}, children=[
                    html.Span("Live output", className="card-title"),
                    html.Div(style={"display": "flex", "gap": "8px", "alignItems": "center"}, children=[
                        html.Span(id="live-seg-label", style={"fontSize": "11px", "color": "#888780"}),
                        html.Button("Clear", id="live-clear-btn", className="rule-btn", n_clicks=0),
                    ]),
                ]),
                html.Div(
                    id="live-output-terminal",
                    className="terminal fill",
                    style={"minHeight": "0"},
                    children=[html.Span("Start a capture to see live output…",
                                        style={"color": "#6e7681", "fontStyle": "italic"})],
                ),
            ]),
        ]),

        dcc.Store(id="live-stopping", data=False),
        dcc.Interval(id="live-log-poll", interval=3000, n_intervals=0),
    ])


# ── callbacks ─────────────────────────────────────────────────────────────────

@callback(
    Output("live-iface", "options"),
    Output("live-iface", "value"),
    Input("live-iface-refresh-btn", "n_clicks"),
    prevent_initial_call=True,
)
def _refresh_live_ifaces(_n):
    resp = api_get("/api/capture/interfaces")
    ifaces = resp.get("interfaces", []) if isinstance(resp, dict) else []
    return [{"label": i, "value": i} for i in ifaces], (ifaces[0] if ifaces else None)


@callback(
    Output("live-start-btn", "disabled"),
    Output("live-stop-btn", "disabled"),
    Output("live-status-tag", "children"),
    Output("live-stopping", "data"),
    Output("live-sessions-table", "children"),
    Output("live-sessions-count", "children"),
    Output("live-metrics", "children"),
    Output("live-session-stats", "children"),
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

    net_resp = api_get("/api/network/flows")
    by_proto = net_resp.get("by_proto", {}) if isinstance(net_resp, dict) else {}

    metrics_children = _metrics_row(sessions, running).children
    stats_children = _session_stats_card(sessions, running, by_proto).children

    return (
        running, not running,
        _live_status_tag(running, stopping),
        stopping,
        _sessions_table(sessions),
        count,
        metrics_children,
        stats_children,
        banner,
    )


@callback(
    Output("live-output-terminal", "children"),
    Output("live-seg-label", "children"),
    Input("live-log-poll", "n_intervals"),
    Input("live-poll", "n_intervals"),
    Input("live-clear-btn", "n_clicks"),
    prevent_initial_call=False,
)
def _poll_live_log(_log_poll, _cap_poll, _clear):
    if ctx.triggered_id == "live-clear-btn":
        api_post("/api/capture/live/clear")
        return [html.Span("Start a capture to see live output…", style={"color": "#6e7681", "fontStyle": "italic"})], ""

    log = api_get("/api/capture/live/log")
    text = log.get("log", "") if isinstance(log, dict) else ""
    status = api_get("/api/capture/live/status")
    running = status.get("running", False) if isinstance(status, dict) else False

    # Build seg label from sessions
    sessions_resp = api_get("/api/capture/live/sessions")
    sessions = sessions_resp.get("sessions", []) if isinstance(sessions_resp, dict) else []
    s = _active_session(sessions) if running else {}
    segs = s.get("segments_replayed", 0) if s else 0
    seg_label = f"seg #{segs} · replaying…" if running and segs else ""

    if not text:
        if not running:
            return [html.Span("Start a capture to see live output…", style={"color": "#6e7681", "fontStyle": "italic"})], ""
        return [html.Span("Capture starting…", style={"color": "#6e7681", "fontStyle": "italic"})], seg_label

    return colorize_log(text.splitlines()), seg_label
