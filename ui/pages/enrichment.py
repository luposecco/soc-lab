from __future__ import annotations

from typing import Any

import dash
from dash import Input, Output, State, callback, dcc, html

from ui.helpers import api_get, api_post, error_banner, metric_card, topbar

dash.register_page(__name__, path="/enrichment")


def _status_dot(ok: bool) -> html.Div:
    return html.Div(className=f"dot {'green' if ok else 'red'}")


def _cluster_row(c: dict[str, Any]) -> html.Tr:
    name = c.get("name", "—")
    mode = c.get("mode", "—")
    ok = c.get("ok")
    latency = c.get("latency_ms")
    version = c.get("version", "")
    error = c.get("error", "")

    if ok is None:
        status_cell = html.Td(html.Span("pending", className="tag warning"))
    elif ok:
        status_cell = html.Td(html.Span("online", className="tag running"))
    else:
        status_cell = html.Td(html.Span("offline", className="tag stopped"))

    latency_str = f"{latency} ms" if latency is not None else "—"
    detail = version if ok else (error[:60] + "…" if len(error) > 60 else error)

    return html.Tr([
        html.Td(name, className="mono"),
        html.Td(html.Span(mode, className="tag blue"), style={"fontSize": "11px"}),
        status_cell,
        html.Td(latency_str, style={"textAlign": "right", "fontSize": "11px", "color": "#888780"}),
        html.Td(detail, style={"fontSize": "11px", "color": "#888780"}),
    ])


def _clusters_table(clusters: list[dict[str, Any]]) -> html.Div:
    if not clusters:
        return html.Div("No clusters configured.", style={"fontSize": "12px", "color": "#888780", "padding": "12px 0"})
    header = html.Thead(html.Tr([
        html.Th("Name"), html.Th("Mode"), html.Th("Status"),
        html.Th("Latency", style={"textAlign": "right"}), html.Th("Detail"),
    ]))
    return html.Div(html.Table([header, html.Tbody([_cluster_row(c) for c in clusters])], className="tbl"))


def _enrichment_card(e: dict[str, Any]) -> html.Div:
    enrichment_name = e.get("name", "—")
    name = e.get("display_name") or enrichment_name
    script = e.get("script", "—")
    targets = ", ".join(e.get("targets", [])) or "—"
    enrichment_type = e.get("type", "play_batch")
    description = e.get("description", "")
    enabled = e.get("enabled", True)
    schedule = e.get("schedule") or {}
    schedule_text = schedule.get("every", "—") if schedule else "—"
    return html.Div(className="card", style={"marginBottom": "8px"}, children=[
        html.Div(className="card-header", children=[
            html.Div(children=[
                html.Span(name, className="card-title"),
                html.Div(description, style={"fontSize": "11px", "color": "#888780", "marginTop": "4px"}) if description else None,
            ]),
            html.Div(style={"display": "flex", "gap": "8px"}, children=[
                html.Button(
                    [html.I(className="ti ti-player-play", style={"fontSize": "12px"}), " Run"],
                    id={"type": "enrich-run-btn", "name": enrichment_name},
                    className="topbar-btn primary",
                    style={"padding": "4px 10px", "fontSize": "11px"},
                    disabled=not enabled,
                ),
                html.Button(
                    [html.I(className="ti ti-player-play", style={"fontSize": "12px"}), " Dry run"],
                    id={"type": "enrich-dry-btn", "name": enrichment_name},
                    className="topbar-btn",
                    style={"padding": "4px 10px", "fontSize": "11px"},
                    disabled=not enabled,
                ),
            ]),
        ]),
        html.Div(style={"display": "flex", "gap": "24px", "fontSize": "11px", "color": "#888780"}, children=[
            html.Span([html.Span("Script: ", style={"color": "#5f5e5a"}), script], className="mono"),
            html.Span([html.Span("Type: "), enrichment_type]),
            html.Span([html.Span("Targets: "), targets]),
            html.Span([html.Span("Schedule: "), schedule_text]) if enrichment_type == "play_periodic" else None,
        ]),
    ])


def _run_row(r: dict[str, Any]) -> html.Tr:
    run_id = r.get("run_id", "—")
    enrichment = r.get("enrichment", "—")
    cluster = r.get("cluster", "—")
    ops = r.get("operations", 0)
    ts = r.get("timestamp", "")
    ts_str = ts[:19].replace("T", " ") if ts else "—"
    return html.Tr([
        html.Td(ts_str, className="mono", style={"fontSize": "11px", "whiteSpace": "nowrap"}),
        html.Td(enrichment),
        html.Td(cluster),
        html.Td(f"{ops:,}", style={"textAlign": "right", "fontSize": "11px"}),
        html.Td(
            html.Button(
                [html.I(className="ti ti-rotate-clockwise", style={"fontSize": "11px"}), " Rollback"],
                id={"type": "enrich-rollback-btn", "run_id": run_id},
                className="svc-btn stop",
                style={"padding": "3px 8px", "fontSize": "11px"},
            )
        ),
        html.Td(run_id, className="mono", style={"fontSize": "10px", "color": "#888780"}),
    ])


def _runs_table(runs: list[dict[str, Any]]) -> html.Div:
    if not runs:
        return html.Div("No enrichment runs yet.", style={"fontSize": "12px", "color": "#888780", "padding": "12px 0"})
    header = html.Thead(html.Tr([
        html.Th("Timestamp"), html.Th("Enrichment"), html.Th("Cluster"),
        html.Th("Ops", style={"textAlign": "right"}), html.Th(""), html.Th("Run ID"),
    ]))
    return html.Div(html.Table([header, html.Tbody([_run_row(r) for r in runs])], className="tbl"))


def _enrich_metrics(clusters: list[dict[str, Any]], enrichments: list[dict[str, Any]], runs: list[dict[str, Any]]) -> html.Div:
    online = sum(1 for c in clusters if c.get("ok"))
    total_c = len(clusters)
    color = "green" if online == total_c and total_c > 0 else ("amber" if online > 0 else "red")
    return html.Div(className="metrics", children=[
        metric_card("Clusters", f"{online}/{total_c}", "online", color),
        metric_card("Enrichments", str(len(enrichments)), "configured", "blue"),
        metric_card("Runs", str(len(runs)), "in history", "blue"),
        metric_card("Total ops", f"{sum(r.get('operations', 0) for r in runs):,}", "audit records", "amber"),
    ])


def layout() -> html.Div:
    clusters_raw = api_get("/api/enrich/clusters")
    clusters = clusters_raw.get("clusters", []) if isinstance(clusters_raw, dict) else []
    enrichments_raw = api_get("/api/enrich/enrichments")
    enrichments = enrichments_raw.get("enrichments", []) if isinstance(enrichments_raw, dict) else []
    runs_raw = api_get("/api/enrich/runs")
    runs = runs_raw.get("runs", []) if isinstance(runs_raw, dict) else []

    return html.Div([
        topbar(
            "Enrichment",
            dcc.Interval(id="enrich-poll", interval=60_000, n_intervals=0),
            html.Button([html.I(className="ti ti-refresh", style={"fontSize": "13px"}), " Refresh"], id="enrich-refresh-btn", className="topbar-btn"),
            html.Button([html.I(className="ti ti-network", style={"fontSize": "13px"}), " Ping all"], id="enrich-ping-btn", className="topbar-btn"),
        ),
        html.Div(id="enrich-banner"),
        html.Div(className="content", children=[
            html.Div(id="enrich-metrics", children=_enrich_metrics(clusters, enrichments, runs)),
            html.Div(className="card", style={"marginBottom": "12px"}, children=[
                html.Div(className="card-header", children=[html.Span("Clusters", className="card-title")]),
                html.Div(id="enrich-clusters-table", children=_clusters_table(clusters)),
            ]),
            html.Div(className="card", style={"marginBottom": "12px"}, children=[
                html.Div(className="card-header", children=[html.Span("Enrichments", className="card-title")]),
                html.Div(id="enrich-list", children=[_enrichment_card(e) for e in enrichments] if enrichments else [
                    html.Div("No enrichments configured.", style={"fontSize": "12px", "color": "#888780"})
                ]),
            ]),
            html.Div(className="card", children=[
                html.Div(className="card-header", children=[html.Span("Run history", className="card-title")]),
                html.Div(id="enrich-runs-table", children=_runs_table(runs)),
            ]),
        ]),
        dcc.Store(id="enrich-last-run-id", data=""),
    ])


@callback(
    Output("enrich-clusters-table", "children"),
    Output("enrich-metrics", "children"),
    Output("enrich-banner", "children"),
    Input("enrich-ping-btn", "n_clicks"),
    Input("enrich-refresh-btn", "n_clicks"),
    Input("enrich-poll", "n_intervals"),
    prevent_initial_call=False,
)
def _refresh_clusters(_ping, _refresh, _poll):
    from dash import ctx
    trigger = ctx.triggered_id

    if trigger == "enrich-ping-btn":
        result = api_post("/api/enrich/clusters/ping")
        clusters = result.get("clusters", []) if isinstance(result, dict) else []
    else:
        result = api_get("/api/enrich/clusters")
        clusters = result.get("clusters", []) if isinstance(result, dict) else []

    enrichments_raw = api_get("/api/enrich/enrichments")
    enrichments = enrichments_raw.get("enrichments", []) if isinstance(enrichments_raw, dict) else []
    runs_raw = api_get("/api/enrich/runs")
    runs = runs_raw.get("runs", []) if isinstance(runs_raw, dict) else []

    if isinstance(result, dict) and result.get("error"):
        banner = [error_banner(f"Error: {result['error']}")]
    else:
        banner = []

    return _clusters_table(clusters), _enrich_metrics(clusters, enrichments, runs), banner


@callback(
    Output("enrich-runs-table", "children"),
    Output("enrich-banner", "children", allow_duplicate=True),
    Output("enrich-last-run-id", "data"),
    Input({"type": "enrich-run-btn", "name": dash.ALL}, "n_clicks"),
    Input({"type": "enrich-dry-btn", "name": dash.ALL}, "n_clicks"),
    Input({"type": "enrich-rollback-btn", "run_id": dash.ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def _handle_actions(run_clicks, dry_clicks, rollback_clicks):
    from dash import ctx
    trigger = ctx.triggered_id
    if not trigger:
        runs_raw = api_get("/api/enrich/runs")
        runs = runs_raw.get("runs", []) if isinstance(runs_raw, dict) else []
        return _runs_table(runs), [], ""

    if isinstance(trigger, dict):
        t_type = trigger.get("type", "")

        if t_type == "enrich-run-btn":
            name = trigger["name"]
            result = api_post(f"/api/enrich/run/{name}", {"dry_run": False})
            runs_raw = api_get("/api/enrich/runs")
            runs = runs_raw.get("runs", []) if isinstance(runs_raw, dict) else []
            if result.get("error"):
                return _runs_table(runs), [error_banner(f"Run failed: {result['error']}")], ""
            run_id = result.get("run_id", "")
            results = result.get("results", [])
            ok_count = sum(1 for r in results if r.get("ok"))
            banner = [html.Div(
                f"Run complete — {run_id} — {ok_count}/{len(results)} clusters OK",
                style={"background": "#EAF3DE", "color": "#3B6D11", "borderRadius": "8px", "padding": "10px 14px", "fontSize": "12px"},
            )]
            return _runs_table(runs), banner, run_id

        if t_type == "enrich-dry-btn":
            name = trigger["name"]
            result = api_post(f"/api/enrich/run/{name}", {"dry_run": True})
            runs_raw = api_get("/api/enrich/runs")
            runs = runs_raw.get("runs", []) if isinstance(runs_raw, dict) else []
            if result.get("error"):
                return _runs_table(runs), [error_banner(f"Dry run failed: {result['error']}")], ""
            banner = [html.Div(
                f"Dry run complete — {result.get('run_id', '')} (no changes written)",
                style={"background": "#E6F1FB", "color": "#185FA5", "borderRadius": "8px", "padding": "10px 14px", "fontSize": "12px"},
            )]
            return _runs_table(runs), banner, ""

        if t_type == "enrich-rollback-btn":
            run_id = trigger["run_id"]
            result = api_post(f"/api/enrich/rollback/{run_id}")
            runs_raw = api_get("/api/enrich/runs")
            runs = runs_raw.get("runs", []) if isinstance(runs_raw, dict) else []
            if result.get("error"):
                return _runs_table(runs), [error_banner(f"Rollback failed: {result['error']}")], ""
            reverted = result.get("reverted", 0)
            banner = [html.Div(
                f"Rollback complete — {reverted} documents reverted",
                style={"background": "#EAF3DE", "color": "#3B6D11", "borderRadius": "8px", "padding": "10px 14px", "fontSize": "12px"},
            )]
            return _runs_table(runs), banner, ""

    runs_raw = api_get("/api/enrich/runs")
    runs = runs_raw.get("runs", []) if isinstance(runs_raw, dict) else []
    return _runs_table(runs), [], ""
