from __future__ import annotations

import dash
from dash import Input, Output, callback, dcc, html

from ui.helpers import api_get, lpanel, lrow, ltable, topbar

dash.register_page(__name__, path="/network")

_PROTO_COLORS = {"tcp": "#185FA5", "udp": "#639922", "icmp": "#BA7517", "dns": "#6B9DD8"}


def _human_bytes(n: int | float | None) -> str:
    if not n:
        return "—"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def _proto_bars(by_proto: dict) -> html.Div:
    if not by_proto:
        return html.Div("No flow data yet.", style={"fontSize": "12px", "color": "#888780"})
    total = sum(by_proto.values()) or 1
    rows = []
    for proto, count in sorted(by_proto.items(), key=lambda x: -x[1])[:6]:
        pct = count / total * 100
        color = _PROTO_COLORS.get(proto.lower(), "#b0afac")
        rows.append(html.Div(style={"display": "flex", "alignItems": "center", "gap": "8px", "fontSize": "12px"}, children=[
            html.Span(proto.upper(), style={"width": "36px", "fontWeight": "500"}),
            html.Div(className="proto-bar-bg", children=[
                html.Div(className="proto-bar-fill", style={"width": f"{pct:.0f}%", "background": color}),
            ]),
            html.Span(f"{pct:.0f}%", style={"width": "32px", "textAlign": "right", "color": "#888780"}),
        ]))
    return html.Div(rows, style={"display": "flex", "flexDirection": "column", "gap": "6px"})


def _top_src_table(top_src: list[dict]) -> html.Div:
    if not top_src:
        return html.Div("No data.", style={"fontSize": "12px", "color": "#888780"})
    header = html.Thead(html.Tr([
        html.Th("Source IP"), html.Th("Flows", style={"textAlign": "right"}), html.Th("Bytes", style={"textAlign": "right"}),
    ]))
    rows = [html.Tr([
        html.Td(r["ip"], className="mono"),
        html.Td(f'{r["flows"]:,}', style={"textAlign": "right", "fontSize": "12px"}),
        html.Td(_human_bytes(r["bytes"]), style={"textAlign": "right", "fontSize": "12px", "fontWeight": "500"}),
    ]) for r in top_src]
    return html.Table([header, html.Tbody(rows)], className="tbl")


def _top_dst_table(top_dst: list[dict]) -> html.Div:
    if not top_dst:
        return html.Div("No data.", style={"fontSize": "12px", "color": "#888780"})
    header = html.Thead(html.Tr([
        html.Th("Destination"), html.Th("Flows", style={"textAlign": "right"}), html.Th("Port"),
    ]))
    rows = [html.Tr([
        html.Td(r["ip"], className="mono"),
        html.Td(f'{r["flows"]:,}', style={"textAlign": "right", "fontSize": "12px"}),
        html.Td(str(r["port"]) if r.get("port") else "—", style={"fontSize": "11px", "color": "#888780"}),
    ]) for r in top_dst]
    return html.Table([header, html.Tbody(rows)], className="tbl")


def _flow_table(flows: list[dict]) -> html.Div:
    if not flows:
        return html.Div("No flow events found. Run a capture or replay to generate data.",
                        style={"fontSize": "12px", "color": "#888780", "padding": "12px 0"})

    def _ts(f: dict) -> str:
        ts = f.get("@timestamp", "")
        return ts[:19].replace("T", " ") if ts else "—"

    def _addr(ip: str | None, port: int | None) -> str:
        if not ip:
            return "—"
        return f"{ip}:{port}" if port else ip

    def _fmt_bytes(n: int | None) -> str:
        return _human_bytes(n) if n else "—"

    header = html.Thead(html.Tr([
        html.Th("Timestamp"),
        html.Th("Source"),
        html.Th("", style={"padding": "0 4px"}),
        html.Th("Destination"),
        html.Th("Proto"),
        html.Th("Pkts →", style={"textAlign": "right"}),
        html.Th("Pkts ←", style={"textAlign": "right"}),
        html.Th("Bytes", style={"textAlign": "right"}),
    ]), style={"position": "sticky", "top": "0", "background": "#fff", "zIndex": "1"})

    rows = []
    for f in flows:
        src = _addr(f.get("source", {}).get("ip"), f.get("source", {}).get("port"))
        dst = _addr(f.get("destination", {}).get("ip"), f.get("destination", {}).get("port"))
        proto = (f.get("network", {}).get("transport") or "").upper()
        pkts_to = f.get("flow", {}).get("pkts_toserver") or f.get("network", {}).get("packets")
        pkts_from = f.get("flow", {}).get("pkts_toclient")
        nbytes = (
            f.get("network", {}).get("bytes")
            or ((f.get("client", {}).get("ip_bytes") or 0) + (f.get("server", {}).get("ip_bytes") or 0))
            or ((f.get("flow", {}).get("bytes_toserver") or 0) + (f.get("flow", {}).get("bytes_toclient") or 0))
            or None
        )
        rows.append(html.Tr([
            html.Td(_ts(f), className="mono", style={"whiteSpace": "nowrap", "fontSize": "11px"}),
            html.Td(src, className="mono"),
            html.Td("→", style={"color": "#888780", "padding": "0 4px"}),
            html.Td(dst, className="mono"),
            html.Td(proto, style={"fontSize": "11px"}),
            html.Td(f"{pkts_to:,}" if pkts_to else "—", style={"textAlign": "right", "fontSize": "11px", "color": "#888780"}),
            html.Td(f"{pkts_from:,}" if pkts_from else "—", style={"textAlign": "right", "fontSize": "11px", "color": "#888780"}),
            html.Td(_fmt_bytes(nbytes), style={"textAlign": "right", "fontSize": "11px", "color": "#888780"}),
        ]))

    return html.Table([header, html.Tbody(rows)], className="tbl")


def _build_content(data: dict) -> list:
    total = data.get("total", 0)
    unique_src = data.get("unique_src", 0)
    unique_dst = data.get("unique_dst", 0)
    total_bytes = data.get("total_bytes", 0)
    by_proto = data.get("by_proto", {})
    top_proto = max(by_proto, key=by_proto.get, default="—").upper() if by_proto else "—"
    flows = data.get("flows", [])
    top_src = data.get("top_src", [])
    top_dst = data.get("top_dst", [])

    return [
        # Metrics
        html.Div(className="metrics", style={"flexShrink": "0"}, children=[
            html.Div(className="metric", children=[
                html.Div("Total flows", className="metric-label"),
                html.Div(f"{total:,}" if total else "—", className="metric-val blue"),
                html.Div("suricata flow events", className="metric-sub"),
            ]),
            html.Div(className="metric", children=[
                html.Div("Unique sources", className="metric-label"),
                html.Div(f"{unique_src:,}" if unique_src else "—", className="metric-val green"),
                html.Div("distinct source IPs", className="metric-sub"),
            ]),
            html.Div(className="metric", children=[
                html.Div("Unique destinations", className="metric-label"),
                html.Div(f"{unique_dst:,}" if unique_dst else "—", className="metric-val amber"),
                html.Div("distinct dest IPs", className="metric-sub"),
            ]),
            html.Div(className="metric", children=[
                html.Div("Total bytes", className="metric-label"),
                html.Div(_human_bytes(total_bytes), className="metric-val blue"),
                html.Div(f"top: {top_proto}", className="metric-sub"),
            ]),
        ]),

        # Protocol + top talkers + top destinations row
        html.Div(style=lrow(min_col="200px", cols=3, shrink=True), children=[

            html.Div(className="card", style=lpanel(min_h=200), children=[
                html.Div(className="card-header", style={"marginBottom": "12px"}, children=[
                    html.Span("Protocol split", className="card-title"),
                    html.Span("by flow count", style={"fontSize": "11px", "color": "#888780"}),
                ]),
                _proto_bars(by_proto),
            ]),

            html.Div(className="card", style=lpanel(min_h=200), children=[
                html.Div(className="card-header", style={"marginBottom": "10px"}, children=[
                    html.Span("Top talkers", className="card-title"),
                    html.Span("by bytes", style={"fontSize": "11px", "color": "#888780"}),
                ]),
                _top_src_table(top_src),
            ]),

            html.Div(className="card", style=lpanel(min_h=200), children=[
                html.Div(className="card-header", style={"marginBottom": "10px"}, children=[
                    html.Span("Top destinations", className="card-title"),
                    html.Span("by flows", style={"fontSize": "11px", "color": "#888780"}),
                ]),
                _top_dst_table(top_dst),
            ]),
        ]),

        # Flow table
        html.Div(className="card", style=ltable(fill=True, min_h=300), children=[
            html.Div(className="card-header", children=[
                html.Span("Flow table", className="card-title"),
                html.Div(style={"display": "flex", "gap": "8px"}, children=[
                    dcc.Input(id="net-search", placeholder="Search IPs…",
                              className="search-input", debounce=True,
                              style={"width": "200px", "paddingLeft": "35px"}),
                    dcc.Dropdown(
                        id="net-proto-filter",
                        options=[{"label": "All protocols", "value": ""}] + [
                            {"label": p.upper(), "value": p} for p in sorted(by_proto.keys())
                        ],
                        value="", clearable=False,
                        style={"width": "160px", "fontSize": "12px"},
                    ),
                ]),
            ]),
            html.Div(id="net-table", className="table-panel-body", children=_flow_table(flows)),
            html.Div(
                f"Showing {len(flows):,} of {total:,} flows" if total else "No flows.",
                id="net-footer",
                style={"fontSize": "11px", "color": "#888780", "paddingTop": "8px", "flexShrink": "0"},
            ),
        ]),
    ]


def layout() -> html.Div:
    data = api_get("/api/network/flows")
    if not isinstance(data, dict):
        data = {}

    return html.Div([
        topbar(
            "Network flows",
            dcc.Interval(id="net-poll", interval=30_000, n_intervals=0),
            html.Button([html.I(className="ti ti-refresh", style={"fontSize": "13px"}), " Refresh"],
                        id="net-refresh-btn", className="topbar-btn", n_clicks=0),
        ),
        html.Div(
            id="net-content",
            className="content",
            style={"display": "flex", "flexDirection": "column", "gap": "14px", "flex": "1", "paddingBottom": "20px"},
            children=_build_content(data),
        ),
    ])


@callback(
    Output("net-table", "children"),
    Output("net-footer", "children"),
    Input("net-search", "value"),
    Input("net-proto-filter", "value"),
    Input("net-refresh-btn", "n_clicks"),
    Input("net-poll", "n_intervals"),
    prevent_initial_call=False,
)
def _refresh_flows(q, proto, _refresh, _poll):
    params = []
    if q:
        params.append(f"q={q}")
    if proto:
        params.append(f"proto={proto}")
    qs = "&".join(params)
    data = api_get(f"/api/network/flows{'?' + qs if qs else ''}")
    if not isinstance(data, dict):
        data = {}
    flows = data.get("flows", [])
    total = data.get("total", 0)
    footer = f"Showing {len(flows):,} of {total:,} flows" if total else "No flows."
    return _flow_table(flows), footer
