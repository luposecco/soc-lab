from __future__ import annotations

from typing import Any

import dash
from dash import Input, Output, State, ALL, callback, ctx, dcc, html

from ui.helpers import api_get, api_post as _api_post_helper, colorize_log

dash.register_page(__name__, path="/stack")


def _api_post(path: str) -> dict[str, Any]:
    return _api_post_helper(path)


def _topbar() -> html.Div:
    return html.Div(
        className="topbar",
        children=[
            html.Span("Stack management", className="page-title"),
            html.Button([html.I(className="ti ti-refresh", style={"fontSize": "13px"}), " Refresh"], id="stack-refresh-btn", className="topbar-btn"),
            html.Button([html.I(className="ti ti-player-stop", style={"fontSize": "13px"}), " Stop all"], id="stack-stop-all-btn", className="topbar-btn danger"),
            html.Button([html.I(className="ti ti-player-play", style={"fontSize": "13px"}), " Start all"], id="stack-start-all-btn", className="topbar-btn success"),
        ],
    )


def _service_card(card: dict[str, Any]) -> html.Div:
    stats = []
    for stat in card.get("stats", []):
        classes = "sstat-val"
        if stat.get("tone") == "red":
            classes += " red"
        elif stat.get("tone") == "amber":
            classes += " amber"
        stats.append(
            html.Div(
                className="sstat",
                children=[html.Div(stat.get("label", ""), className="sstat-label"), html.Div(stat.get("value", "—"), className=classes)],
            )
        )
    primary_action = card.get("primary_action", "stop")
    primary_label = "Stop" if primary_action == "stop" else "Start"
    primary_class = "svc-btn stop" if primary_action == "stop" else "svc-btn start"
    exists = card.get("exists", True)
    return html.Div(
        className="service-card",
        children=[
            html.Div(
                className="service-header",
                children=[
                    html.Div(html.I(className=card.get("icon", "")), className=f"service-icon {card.get('icon_class', '')}"),
                    html.Div([html.Div(card.get("title", ""), className="service-name"), html.Div(card.get("meta", ""), className="service-meta")]),
                    html.Span(card.get("tag", {}).get("label", "Unknown"), className=f"tag {card.get('tag', {}).get('class', 'warning')}", style={"marginLeft": "auto"}),
                ],
            ),
            html.Div(className="service-stats", children=stats),
            html.Div(
                className="service-actions",
                children=[
                    html.Button(primary_label, id={"type": "stack-service-action", "action": primary_action, "service": card.get("service", "")}, className=primary_class),
                    html.Button("Restart", id={"type": "stack-service-action", "action": "restart", "service": card.get("service", "")}, className="svc-btn", disabled=not exists),
                    html.Button("Logs", id={"type": "stack-service-action", "action": "logs", "service": card.get("service", "")}, className="svc-btn", disabled=not exists),
                ],
            ),
        ],
    )


def _future_dev_card() -> html.Div:
    return html.Div(
        className="service-card",
        style={"border": "1.5px dashed #DDDCDA", "background": "#FAFAF9", "opacity": "0.7"},
        children=[
            html.Div(className="service-header", children=[
                html.Div(html.I(className="ti ti-plus"), className="service-icon"),
                html.Div([
                    html.Div("Future development", className="service-name"),
                    html.Div("Zeek · Snort · YARA and other tools", className="service-meta"),
                ]),
            ]),
            html.Div(style={"fontSize": "12px", "color": "#888780", "marginTop": "8px", "fontStyle": "italic"},
                     children="Additional tools will be added here in future releases."),
        ],
    )


def _watcher_card(watcher: dict[str, Any]) -> html.Div:
    running = watcher.get("running", False)
    pid = watcher.get("pid")
    status_text = f"Running (PID {pid})" if running else "Stopped"
    return html.Div(className="card", children=[
        html.Div(className="card-header", children=[
            html.Span("Rules watcher", className="card-title"),
            html.Span(status_text, className=f"tag {'running' if running else 'warning'}"),
        ]),
        html.Div(style={"display": "flex", "alignItems": "center", "gap": "10px"}, children=[
            html.Div(className=f"dot {'green' if running else 'amber'}"),
            html.Span(
                "Watching rules/ for changes — auto-compiles on modification." if running
                else "Start the watcher to auto-compile rules when files change.",
                style={"fontSize": "12px", "color": "#5f5e5a"},
            ),
            html.Button(
                "Stop watcher" if running else "Start watcher",
                id="stack-watcher-btn",
                className="svc-btn stop" if running else "svc-btn start",
                style={"marginLeft": "auto"},
            ),
        ]),
        html.Div(id="stack-watcher-log", style={"marginTop": "10px", "overflow": "hidden"}),
    ])


def _live_output(selected_service: str, logs: str) -> html.Div:
    lines = logs.splitlines() if logs else []
    terminal_children = colorize_log(lines) if lines else [
        html.Span("Click 'Logs' on a service card to view output…", style={"color": "#6e7681", "fontStyle": "italic"})
    ]
    return html.Div(
        className="card",
        style={"flex": "1", "display": "flex", "flexDirection": "column", "minHeight": "0", "overflow": "hidden"},
        children=[
            html.Div(
                className="card-header",
                style={"flexShrink": "0"},
                children=[html.Span([html.Span("Service logs", className="card-title"),
                                     html.Span(f" — {selected_service}", style={"fontSize": "11px", "color": "#888780", "fontWeight": "400"})])],
            ),
            html.Div(terminal_children, className="terminal fill"),
        ],
    )


def _snapshot(selected_service: str = "elastalert2") -> tuple[list[dict[str, Any]], str, str]:
    data = api_get("/api/stack/services")
    all_cards = data.get("cards", []) if isinstance(data, dict) else []
    # exclude logstash — not in use
    cards = [c for c in all_cards if c.get("service") != "logstash"]
    logs_resp = api_get(f"/api/stack/logs/{selected_service}")
    logs = logs_resp.get("logs", "") if isinstance(logs_resp, dict) else ""
    return cards, selected_service, logs


def layout() -> html.Div:
    cards, selected_service, logs = _snapshot()
    watcher = api_get("/api/rules/watcher")
    if isinstance(watcher, dict) and watcher.get("error"):
        watcher = {"running": False}

    service_children = [_service_card(card) for card in cards] + [_future_dev_card()]

    return html.Div([
        _topbar(),
        html.Div(className="content", style={"display": "flex", "flexDirection": "column"}, children=[
            html.Div(id="stack-status-banner"),
            dcc.Store(id="stack-selected-service", data=selected_service),
            dcc.Interval(id="stack-poll", interval=15000, n_intervals=0),
            html.Div(id="stack-cards", className="row3", style={"flexShrink": "0"}, children=service_children),
            html.Div(id="stack-watcher-wrap", style={"flexShrink": "0"}, children=_watcher_card(watcher)),
            html.Div(id="stack-live-output",
                     style={"flex": "1", "display": "flex", "flexDirection": "column", "minHeight": "200px"},
                     children=_live_output(selected_service, logs)),
        ]),
    ])


@callback(
    Output("stack-cards", "children"),
    Output("stack-live-output", "children"),
    Output("stack-selected-service", "data"),
    Output("stack-status-banner", "children"),
    Output("stack-watcher-wrap", "children"),
    Input("stack-poll", "n_intervals"),
    Input("stack-refresh-btn", "n_clicks"),
    Input("stack-start-all-btn", "n_clicks"),
    Input("stack-stop-all-btn", "n_clicks"),
    Input({"type": "stack-service-action", "action": ALL, "service": ALL}, "n_clicks"),
    Input("stack-watcher-btn", "n_clicks"),
    State("stack-selected-service", "data"),
    prevent_initial_call=False,
)
def refresh_stack_page(_poll, _refresh, _start_all, _stop_all, _service_clicks, _watcher_click, selected_service):
    selected_service = selected_service or "elastalert2"
    banner = []
    trigger = ctx.triggered_id

    if trigger == "stack-start-all-btn":
        result = _api_post("/api/stack/start")
        banner = [html.Div(result.get("error", "Stack start triggered"), className="card")] if result.get("error") else [html.Div("Stack started", className="card")]
    elif trigger == "stack-stop-all-btn":
        result = _api_post("/api/stack/stop")
        banner = [html.Div(result.get("error", "Stack stop triggered"), className="card")] if result.get("error") else [html.Div("Stack stopped", className="card")]
    elif trigger == "stack-watcher-btn":
        watcher_now = api_get("/api/rules/watcher")
        if isinstance(watcher_now, dict) and watcher_now.get("running"):
            _api_post("/api/rules/watcher/stop")
        else:
            _api_post("/api/rules/watcher/start")
    elif isinstance(trigger, dict):
        action = trigger.get("action")
        service = trigger.get("service")
        if action == "logs":
            selected_service = service
        elif action == "stop":
            result = _api_post(f"/api/stack/services/{service}/stop")
            banner = [html.Div(result.get("error", f"{service} stop triggered"), className="card")]
        elif action == "start":
            result = _api_post(f"/api/stack/services/{service}/start")
            banner = [html.Div(result.get("error", f"{service} start triggered"), className="card")]
            selected_service = service
        elif action == "restart":
            result = _api_post(f"/api/stack/services/{service}/restart")
            banner = [html.Div(result.get("error", f"{service} restart triggered"), className="card")]
            selected_service = service

    cards, selected_service, logs = _snapshot(selected_service)
    watcher = api_get("/api/rules/watcher")
    if isinstance(watcher, dict) and watcher.get("error"):
        watcher = {"running": False}

    service_children = [_service_card(card) for card in cards] + [_future_dev_card()]
    return service_children, _live_output(selected_service, logs), selected_service, banner, _watcher_card(watcher)


@callback(
    Output("stack-watcher-log", "children"),
    Input("stack-poll", "n_intervals"),
    Input("stack-watcher-btn", "n_clicks"),
)
def _load_watcher_log(_poll, _click):
    log = api_get("/api/rules/log/watcher")
    text = log.get("log", "") if isinstance(log, dict) else ""
    if not text:
        return None
    lines = text.splitlines()[-30:]  # last 30 lines
    return html.Div(colorize_log(lines), className="terminal short")
