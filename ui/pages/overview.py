from __future__ import annotations

from typing import Any

import dash
from dash import Input, Output, State, callback, ctx, dcc, html

from ui.helpers import api_get, error_banner, lcol, lpanel, lrow, ltable, metric_card, sev_badge, topbar

dash.register_page(__name__, path="/")

_TIME_OPTS = [("Live", "live"), ("1h", "1h"), ("6h", "6h"), ("24h", "24h")]
_SEV_COLORS = {"high": "#E24B4A", "medium": "#BA7517", "low": "#378ADD"}


def _severity_label(alert: dict[str, Any]) -> str:
    value = alert.get("event", {}).get("severity_label") or alert.get("event.severity_label")
    label = str(value or "").lower()
    if label in ("high", "medium", "low"):
        return label
    sev = alert.get("alert", {}).get("severity") or alert.get("alert.severity")
    try:
        return {1: "high", 2: "high", 3: "medium", 4: "low"}.get(int(sev), "info")
    except Exception:
        return "info"


def _timeline_bars(buckets: list[dict]) -> html.Div:
    if not buckets:
        bars = [html.Div(style={"flex": "1", "height": "20%", "background": "#B5D4F4", "borderRadius": "2px 2px 0 0"}) for _ in range(12)]
    else:
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
    return html.Div(bars, className="timeline-chart", style={"height": "70px"})


def _service_row(card: dict) -> html.Tr:
    tag = card.get("tag", {})
    icon = card.get("icon", "")
    icon_class = card.get("icon_class", "")
    return html.Tr([
        html.Td(html.Div([
            html.Div(html.I(className=icon), className=f"service-icon {icon_class}",
                     style={"width": "28px", "height": "28px", "fontSize": "14px"}),
            html.Span(card.get("title", ""), style={"fontSize": "13px", "fontWeight": "500"}),
        ], style={"display": "flex", "alignItems": "center", "gap": "8px"})),
        html.Td(html.Span(tag.get("label", "—"), className=f"tag {tag.get('class', 'warning')}")),
        html.Td(card.get("meta", "—"), style={"fontSize": "12px", "color": "#888780", "textAlign": "right"}),
    ])


def _recent_alert_row(a: dict) -> html.Tr:
    sev_str = _severity_label(a)
    sig = a.get("alert", {}).get("signature") or a.get("alert.signature") or a.get("rule", {}).get("name") or "—"
    src = a.get("source", {}).get("ip") or a.get("source.ip") or "—"
    dst = a.get("destination", {}).get("ip") or a.get("destination.ip") or "—"
    dst_port = a.get("destination", {}).get("port") or a.get("destination.port") or ""
    dataset = a.get("event", {}).get("dataset") or a.get("event.dataset") or "—"
    ts = (a.get("@timestamp") or "")[:19].replace("T", " ")
    dst_str = f"{dst}:{dst_port}" if dst_port else dst
    return html.Tr([
        html.Td(ts, className="mono", style={"whiteSpace": "nowrap", "fontSize": "11px"}),
        html.Td(sev_badge(sev_str)),
        html.Td(sig, style={"fontSize": "12px", "fontWeight": "500", "maxWidth": "220px",
                             "overflow": "hidden", "textOverflow": "ellipsis", "whiteSpace": "nowrap"}),
        html.Td(f"{src} → {dst_str}", className="mono"),
        html.Td(html.Span(dataset, className="tag blue")),
    ])


def _build(summary: dict, stats: dict, alerts: dict, svc_data: dict, rules_data: dict, timeline: dict) -> html.Div:
    if err := summary.get("error"):
        return html.Div(className="content", style={}, children=[error_banner(f"Could not reach API: {err}")])

    # metrics
    total_svc = summary.get("service_count", 0)
    running_svc = summary.get("running_services", 0)
    indices = summary.get("indices", [])
    total_docs = sum(int(idx.get("docs.count") or 0) for idx in indices)
    active_alerts = stats.get("total", 0)
    high = stats.get("by_severity", {}).get("high", 0)
    svc_color = "green" if running_svc == total_svc and total_svc > 0 else "amber" if running_svc > 0 else "red"
    alert_color = "red" if high > 0 else "amber" if active_alerts > 0 else "green"

    metrics = html.Div(className="metrics cols5", style={"flexShrink": "0"}, children=[
        metric_card("Active alerts", str(active_alerts), f"{high} high", alert_color),
        metric_card("Flow events", "—", "network flows", "blue"),
        metric_card("Suricata docs", f"{total_docs:,}", "total indexed", "blue"),
        metric_card("Services", f"{running_svc}/{total_svc}", "running", svc_color),
        metric_card("Indices", str(len(indices)), "managed", "blue"),
    ])

    # timeline + services
    timeline_buckets = timeline.get("buckets", [])
    timeline_card = html.Div(className="card", style=lpanel(min_h=180, shrink=True), children=[
        html.Div(className="card-header", style={"marginBottom": "8px"}, children=[
            html.Span("Alert timeline", className="card-title"),
            html.Span("last 60 min · 5-min buckets", style={"fontSize": "11px", "color": "#888780"}),
        ]),
        _timeline_bars(timeline_buckets),
        html.Div(style={"display": "flex", "justifyContent": "space-between", "marginTop": "6px", "fontSize": "11px", "color": "#888780"},
                 children=[html.Span("60m ago"), html.Span("now")]),
        html.Div(style={"display": "flex", "gap": "14px", "marginTop": "12px"}, children=[
            html.Div([html.Div(style={"width": "10px", "height": "10px", "background": _SEV_COLORS["high"], "borderRadius": "2px", "display": "inline-block", "marginRight": "6px"}), html.Span("High", style={"fontSize": "12px", "color": "#888780"})]),
            html.Div([html.Div(style={"width": "10px", "height": "10px", "background": _SEV_COLORS["medium"], "borderRadius": "2px", "display": "inline-block", "marginRight": "6px"}), html.Span("Medium", style={"fontSize": "12px", "color": "#888780"})]),
            html.Div([html.Div(style={"width": "10px", "height": "10px", "background": _SEV_COLORS["low"], "borderRadius": "2px", "display": "inline-block", "marginRight": "6px"}), html.Span("Low", style={"fontSize": "12px", "color": "#888780"})]),
        ]),
    ])

    cards = [c for c in svc_data.get("cards", []) if c.get("service") != "logstash"]
    svc_table = html.Div(className="card", style=ltable(min_h=220), children=[
        html.Div(className="card-header", children=[
            html.Span("Services", className="card-title"),
            html.A("View all →", href="/stack", className="card-action"),
        ]),
        html.Div(html.Table(html.Tbody([_service_row(c) for c in cards]), className="tbl"), className="table-panel-body"),
    ])

    # recent alerts (3 only)
    recent = alerts.get("alerts", [])[:3]
    recent_alerts_card = html.Div(className="card", style={**ltable(min_h=160), "flexShrink": "0"}, children=[
        html.Div(className="card-header", children=[
            html.Span("Recent alerts", className="card-title"),
            html.A("View all →", href="/alerts", className="card-action"),
        ]),
        html.Div(html.Table([
            html.Thead(html.Tr([html.Th("Time"), html.Th("Sev"), html.Th("Signature"), html.Th("Src → Dst"), html.Th("Dataset")])),
            html.Tbody([_recent_alert_row(a) for a in recent] if recent else
                       [html.Tr(html.Td("No recent alerts", colSpan=5, style={"color": "#888780", "fontSize": "12px", "padding": "12px 0"}))]),
        ], className="tbl"), className="table-panel-body"),
    ])

    # indices & aliases
    aliases = summary.get("aliases", [])
    alias_names = list({r.get("alias") for r in aliases})[:3]
    indices_card = html.Div(className="card", style=ltable(fill=True, min_h=200), children=[
        html.Div(className="card-header", children=[
            html.Span("Indices & aliases", className="card-title"),
            html.A("Aliases →", href="/aliases", className="card-action"),
        ]),
        html.Div(html.Table(html.Tbody([
            *[html.Tr([
                html.Td(idx.get("index", "—"), className="mono", style={"fontSize": "12px"}),
                html.Td(f'{int(idx.get("docs.count") or 0):,} docs', style={"textAlign": "right", "fontSize": "12px", "fontWeight": "500"}),
                html.Td(html.Span("Active", className="tag running")),
            ]) for idx in indices[:4]],
            *[html.Tr([
                html.Td(alias, className="mono", style={"fontSize": "12px"}),
                html.Td("alias", style={"textAlign": "right", "fontSize": "12px", "color": "#888780"}),
                html.Td(html.Span("Alias", className="tag blue")),
            ]) for alias in alias_names],
        ]), className="tbl"), className="table-panel-body"),
    ])

    # rules status
    suri = rules_data.get("suricata", {}) if rules_data.get("exists") else {}
    sigma = rules_data.get("sigma", {}) if rules_data.get("exists") else {}
    rules_card = html.Div(className="card", style=lpanel(fill=True, min_h=200), children=[
        html.Div(className="card-header", children=[
            html.Span("Rules status", className="card-title"),
            html.A("Manage →", href="/rules", className="card-action"),
        ]),
        html.Div(style={"display": "flex", "flexDirection": "column", "gap": "8px", "flex": "1", "justifyContent": "center"}, children=[
            html.Div(style={"display": "flex", "justifyContent": "space-between", "alignItems": "center", "fontSize": "13px"}, children=[
                html.Span("Suricata", style={"color": "#888780"}),
                html.Span("OK" if suri.get("status") == "ok" else "—", className=f"tag {'running' if suri.get('status') == 'ok' else 'warning'}"),
            ]),
            html.Div(style={"display": "flex", "justifyContent": "space-between", "alignItems": "center", "fontSize": "13px"}, children=[
                html.Span("Sigma", style={"color": "#888780"}),
                html.Span(f"{sigma.get('ok_count', '—')} / {sigma.get('loaded_rules', '—')} loaded", style={"fontWeight": "500"}),
            ]),
        ]),
    ])

    return html.Div(className="content", style={}, children=[
        metrics,
        html.Div(style={**lrow(shrink=True), "gridTemplateColumns": "2fr 3fr"}, children=[timeline_card, svc_table]),
        recent_alerts_card,
        html.Div(style={**lrow(fill=False), "marginBottom": "20px"}, children=[indices_card, rules_card]),
    ])


def layout() -> html.Div:
    summary = api_get("/api/overview/summary")
    stats = api_get("/api/alerts/stats")
    alerts = api_get("/api/alerts?size=5")
    svc_data = api_get("/api/stack/services")
    rules_data = api_get("/api/rules/status")
    timeline = api_get("/api/alerts/timeline")
    for d in (stats, alerts, svc_data, rules_data, timeline):
        if isinstance(d, dict) and d.get("error"):
            pass  # tolerate errors
    if not isinstance(stats, dict): stats = {}
    if not isinstance(alerts, dict): alerts = {}
    if not isinstance(svc_data, dict): svc_data = {}
    if not isinstance(rules_data, dict): rules_data = {}
    if not isinstance(timeline, dict): timeline = {}

    return html.Div([
        topbar(
            "Overview",
            dcc.Interval(id="overview-poll", interval=30_000, n_intervals=0),
            html.Div(className="pages", children=[
                html.Span("Live", id="overview-time-live", className="page-btn active", n_clicks=0),
                html.Span("1h", id="overview-time-1h", className="page-btn", n_clicks=0),
                html.Span("6h", id="overview-time-6h", className="page-btn", n_clicks=0),
                html.Span("24h", id="overview-time-24h", className="page-btn", n_clicks=0),
            ]),
            html.Button([html.I(className="ti ti-refresh", style={"fontSize": "13px"}), " Refresh"],
                        id="overview-refresh-btn", className="topbar-btn", n_clicks=0),
        ),
        html.Div(id="overview-content", children=_build(summary, stats, alerts, svc_data, rules_data, timeline)),
    ])


@callback(
    Output("overview-content", "children"),
    Input("overview-poll", "n_intervals"),
    Input("overview-refresh-btn", "n_clicks"),
    prevent_initial_call=True,
)
def _refresh(_n, _r):
    summary = api_get("/api/overview/summary")
    stats = api_get("/api/alerts/stats")
    alerts = api_get("/api/alerts?size=5")
    svc_data = api_get("/api/stack/services")
    rules_data = api_get("/api/rules/status")
    timeline = api_get("/api/alerts/timeline")
    for d in (stats, alerts, svc_data, rules_data, timeline):
        if not isinstance(d, dict):
            d = {}
    return _build(summary, stats or {}, alerts or {}, svc_data or {}, rules_data or {}, timeline or {})
