from __future__ import annotations

from typing import Any

import dash
from dash import Input, Output, callback, dcc, html

from ui.helpers import api_get, error_banner, lpanel, ltable, metric_card, sev_badge, topbar

dash.register_page(__name__, path="/alerts")

_SEV_OPTIONS = [
    {"label": "All severities", "value": ""},
    {"label": "High", "value": "high"},
    {"label": "Medium", "value": "medium"},
    {"label": "Low", "value": "low"},
]
_DATASET_OPTIONS = [
    {"label": "All datasets", "value": ""},
    {"label": "suricata.alert", "value": "suricata.alert"},
    {"label": "alert", "value": "alert"},
]


def _fmt_ts(ts: str) -> str:
    return ts[:19].replace("T", " ") if ts else "—"


def _severity_label(alert: dict[str, Any]) -> str:
    value = alert.get("event", {}).get("severity_label") or alert.get("event.severity_label")
    label = str(value or "").lower()
    if label in ("high", "medium", "low"):
        return label
    sev = alert.get("alert", {}).get("severity") or alert.get("alert.severity")
    try:
        return {1: "high", 2: "high", 3: "medium", 4: "low"}.get(int(sev), "info")
    except Exception:
        return str(sev).lower() if sev else "info"


def _alert_row(alert: dict[str, Any]) -> html.Tr:
    sev_str = _severity_label(alert)
    sig = alert.get("alert", {}).get("signature") or alert.get("alert.signature") or alert.get("rule", {}).get("name") or "—"
    src = alert.get("source", {}).get("ip") or alert.get("source.ip") or "—"
    dst = alert.get("destination", {}).get("ip") or alert.get("destination.ip") or "—"
    dst_port = alert.get("destination", {}).get("port") or alert.get("destination.port") or ""
    proto = alert.get("network", {}).get("transport") or alert.get("network.transport") or ""
    action = alert.get("alert", {}).get("action") or alert.get("alert.action") or "—"
    dataset = alert.get("event", {}).get("dataset") or alert.get("event.dataset") or "—"
    dst_str = f"{dst}:{dst_port}" if dst_port else dst
    return html.Tr([
        html.Td(_fmt_ts(alert.get("@timestamp", "")), className="mono", style={"whiteSpace": "nowrap", "fontSize": "11px"}),
        html.Td(sev_badge(sev_str)),
        html.Td(sig, style={"maxWidth": "260px", "overflow": "hidden", "textOverflow": "ellipsis",
                             "whiteSpace": "nowrap", "fontSize": "12px", "fontWeight": "500"}),
        html.Td(f"{src} → {dst_str}", className="mono"),
        html.Td(proto.upper() if proto else "—", style={"fontSize": "11px", "color": "#888780"}),
        html.Td(action, style={"fontSize": "11px"}),
        html.Td(html.Span(dataset, className="tag blue"), style={"textAlign": "right"}),
    ])


_SEV_COLORS = {"high": "#E24B4A", "medium": "#BA7517", "low": "#378ADD"}


def _timeline_bars(buckets: list[dict]) -> html.Div:
    if not buckets:
        return html.Div(className="timeline-chart", style={"height": "64px"})
    max_c = max((b.get("count", 0) for b in buckets), default=1) or 1
    bars = []
    for b in buckets:
        pct = max(4, int(b.get("count", 0) / max_c * 100))
        by_sev = b.get("by_severity", {}) or {}
        total = sum(int(by_sev.get(sev, 0) or 0) for sev in ("high", "medium", "low")) or b.get("count", 0) or 1
        segments = []
        for sev in ("low", "medium", "high"):
            val = int(by_sev.get(sev, 0) or 0)
            if val:
                segments.append(html.Div(style={"height": f"{val / total * 100:.1f}%", "background": _SEV_COLORS[sev]}))
        if not segments:
            segments = [html.Div(style={"height": "100%", "background": "#378ADD"})]
        bars.append(html.Div(segments, style={"flex": "1", "height": f"{pct}%", "borderRadius": "2px 2px 0 0", "overflow": "hidden", "display": "flex", "flexDirection": "column-reverse"}))
    return html.Div(bars, className="timeline-chart", style={"height": "64px"})


def _alerts_table(alerts: list[dict]) -> html.Table | html.Div:
    if not alerts:
        return html.Div("No alerts found.", style={"fontSize": "12px", "color": "#888780", "padding": "12px 0"})
    header = html.Thead(html.Tr([
        html.Th("Timestamp", style={"whiteSpace": "nowrap"}),
        html.Th("Sev"), html.Th("Signature"), html.Th("Src → Dst"),
        html.Th("Proto"), html.Th("Action"), html.Th("Dataset", style={"textAlign": "right"}),
    ]))
    return html.Table([header, html.Tbody([_alert_row(a) for a in alerts])], className="tbl")


def _stats_metrics(stats: dict) -> html.Div:
    total = stats.get("total", 0)
    by_sev = stats.get("by_severity", {})
    high = by_sev.get("high", 0)
    med = by_sev.get("medium", 0)
    low = by_sev.get("low", 0)
    return html.Div(className="metrics", children=[
        metric_card("Total alerts", f"{total:,}", "in soc-alerts", "blue"),
        metric_card("High", str(high), "event.severity_label", "red" if high > 0 else "blue"),
        metric_card("Medium", str(med), "event.severity_label", "amber" if med > 0 else "blue"),
        metric_card("Low", str(low), "event.severity_label", "green"),
    ])


def layout() -> html.Div:
    stats = api_get("/api/alerts/stats")
    if not isinstance(stats, dict) or stats.get("error"): stats = {}
    data = api_get("/api/alerts?size=50")
    if not isinstance(data, dict) or data.get("error"): data = {"total": 0, "alerts": []}
    timeline = api_get("/api/alerts/timeline")
    if not isinstance(timeline, dict): timeline = {}

    return html.Div([
        topbar(
            "Alerts",
            dcc.Interval(id="alerts-poll", interval=30_000, n_intervals=0),
            # inline filter bar
            html.Div(className="filterbar", style={"flex": "1", "maxWidth": "580px"}, children=[
                dcc.Input(id="alerts-search", placeholder="Search signature, IP, rule ID…",
                          debounce=True, className="search-input", style={"flex": "1"}),
                dcc.Dropdown(id="alerts-sev-filter", options=_SEV_OPTIONS, value="", clearable=False,
                             style={"width": "150px", "fontSize": "12px"}, placeholder="All severities"),
                dcc.Dropdown(id="alerts-dataset-filter", options=_DATASET_OPTIONS, value="", clearable=False,
                             style={"width": "160px", "fontSize": "12px"}, placeholder="All datasets"),
            ]),
            html.Button([html.I(className="ti ti-refresh", style={"fontSize": "13px"}), " Refresh"],
                        id="alerts-refresh-btn", className="topbar-btn", n_clicks=0),
        ),
        html.Div(className="content", style={}, children=[
            html.Div(id="alerts-metrics", children=_stats_metrics(stats), style={"flexShrink": "0"}),

            html.Div(className="card", style={**lpanel(min_h=140, shrink=True)}, children=[
                html.Div(className="card-header", style={"marginBottom": "8px"}, children=[
                    html.Span("Alert volume", className="card-title"),
                    html.Span("by event.severity_label · 5-min buckets", style={"fontSize": "11px", "color": "#888780"}),
                ]),
                html.Div(id="alerts-timeline", children=_timeline_bars(timeline.get("buckets", []))),
                html.Div(style={"display": "flex", "justifyContent": "space-between", "marginTop": "5px",
                                 "fontSize": "11px", "color": "#888780"},
                         children=[html.Span("60m ago"), html.Span("now")]),
                html.Div(style={"display": "flex", "gap": "14px", "marginTop": "8px", "fontSize": "11px", "color": "#888780"}, children=[
                    html.Span([html.Span(style={"display": "inline-block", "width": "9px", "height": "9px", "borderRadius": "2px", "background": _SEV_COLORS["high"], "marginRight": "5px"}), "High"]),
                    html.Span([html.Span(style={"display": "inline-block", "width": "9px", "height": "9px", "borderRadius": "2px", "background": _SEV_COLORS["medium"], "marginRight": "5px"}), "Medium"]),
                    html.Span([html.Span(style={"display": "inline-block", "width": "9px", "height": "9px", "borderRadius": "2px", "background": _SEV_COLORS["low"], "marginRight": "5px"}), "Low"]),
                ]),
            ]),

            html.Div(className="card", style={**ltable(fill=True, min_h=300), "marginBottom": "20px"}, children=[
                html.Div(className="card-header", children=[
                    html.Span("Alert feed", className="card-title"),
                    html.Span(id="alerts-footer",
                              children=f"Showing {len(data.get('alerts', []))} of {data.get('total', 0):,} alerts",
                              style={"fontSize": "12px", "color": "#888780"}),
                ]),
                html.Div(id="alerts-table", children=_alerts_table(data.get("alerts", [])), className="table-panel-body"),
            ]),
        ]),
    ])


@callback(
    Output("alerts-metrics", "children"),
    Output("alerts-table", "children"),
    Output("alerts-footer", "children"),
    Output("alerts-timeline", "children"),
    Input("alerts-poll", "n_intervals"),
    Input("alerts-refresh-btn", "n_clicks"),
    Input("alerts-search", "value"),
    Input("alerts-sev-filter", "value"),
    Input("alerts-dataset-filter", "value"),
    prevent_initial_call=True,
)
def _refresh_alerts(_poll, _refresh, search, severity, dataset):
    params = "?size=100"
    if search:
        params += f"&q={search}"
    if severity:
        params += f"&severity={severity}"
    if dataset:
        params += f"&dataset={dataset}"

    stats = api_get("/api/alerts/stats")
    if not isinstance(stats, dict) or stats.get("error"): stats = {}
    data = api_get(f"/api/alerts{params}")
    if not isinstance(data, dict) or data.get("error"):
        return _stats_metrics(stats), error_banner("Error loading alerts"), "", _timeline_bars([])

    timeline = api_get("/api/alerts/timeline")
    if not isinstance(timeline, dict): timeline = {}

    alerts = data.get("alerts", [])
    total = data.get("total", 0)
    footer = f"Showing {len(alerts)} of {total:,} alerts"
    return _stats_metrics(stats), _alerts_table(alerts), footer, _timeline_bars(timeline.get("buckets", []))
