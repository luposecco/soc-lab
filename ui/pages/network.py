from __future__ import annotations

from typing import Any

import dash
from dash import Input, Output, callback, dcc, html

from ui.helpers import api_get, error_banner, metric_card, topbar

dash.register_page(__name__, path="/network")

_PROTO_OPTIONS = [
    {"label": "All protocols", "value": ""},
    {"label": "TCP", "value": "tcp"},
    {"label": "UDP", "value": "udp"},
    {"label": "ICMP", "value": "icmp"},
]


def _fmt_ts(ts: str) -> str:
    return ts[:19].replace("T", " ") if ts else "—"


def _fmt_bytes(b: Any) -> str:
    if b is None:
        return "—"
    try:
        n = int(b)
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024:
                return f"{n} {unit}"
            n //= 1024
        return f"{n} GB"
    except Exception:
        return str(b)


def _flow_row(flow: dict[str, Any]) -> html.Tr:
    src_ip = flow.get("source", {}).get("ip") or flow.get("source.ip") or "—"
    src_port = flow.get("source", {}).get("port") or flow.get("source.port") or ""
    dst_ip = flow.get("destination", {}).get("ip") or flow.get("destination.ip") or "—"
    dst_port = flow.get("destination", {}).get("port") or flow.get("destination.port") or ""
    proto = flow.get("network", {}).get("transport") or flow.get("network.transport") or "—"
    bytes_total = flow.get("network", {}).get("bytes") or flow.get("network.bytes")
    bytes_ts = flow.get("flow", {}).get("bytes_toserver") or flow.get("flow.bytes_toserver")
    bytes_tc = flow.get("flow", {}).get("bytes_toclient") or flow.get("flow.bytes_toclient")

    if bytes_total is None and bytes_ts is not None:
        try:
            bytes_total = int(bytes_ts or 0) + int(bytes_tc or 0)
        except Exception:
            pass

    src_str = f"{src_ip}:{src_port}" if src_port else src_ip
    dst_str = f"{dst_ip}:{dst_port}" if dst_port else dst_ip

    return html.Tr([
        html.Td(_fmt_ts(flow.get("@timestamp", "")), className="mono", style={"whiteSpace": "nowrap", "fontSize": "11px"}),
        html.Td(src_str, className="mono"),
        html.Td("→", style={"color": "#888780", "padding": "0 4px"}),
        html.Td(dst_str, className="mono"),
        html.Td(proto.upper(), style={"fontSize": "11px"}),
        html.Td(_fmt_bytes(bytes_total), style={"textAlign": "right", "fontSize": "11px", "color": "#888780"}),
    ])


def _flows_table(flows: list[dict[str, Any]]) -> html.Div:
    if not flows:
        return html.Div(
            "No flow events found. Run a PCAP replay to generate network flows.",
            style={"fontSize": "12px", "color": "#888780", "padding": "12px 0"},
        )
    header = html.Thead(html.Tr([
        html.Th("Timestamp"),
        html.Th("Source"),
        html.Th(""),
        html.Th("Destination"),
        html.Th("Proto"),
        html.Th("Bytes", style={"textAlign": "right"}),
    ]))
    return html.Div(html.Table([header, html.Tbody([_flow_row(f) for f in flows])], className="tbl"))


def _net_metrics(data: dict[str, Any]) -> html.Div:
    total = data.get("total", 0)
    unique_src = data.get("unique_src", 0)
    unique_dst = data.get("unique_dst", 0)
    by_proto = data.get("by_proto", {})
    top_proto = max(by_proto, key=by_proto.get, default="—") if by_proto else "—"  # type: ignore[arg-type]
    return html.Div(className="metrics", children=[
        metric_card("Total flows", f"{total:,}", "suricata flow events", "blue"),
        metric_card("Unique sources", str(unique_src), "distinct source IPs", "green"),
        metric_card("Unique destinations", str(unique_dst), "distinct dest IPs", "amber"),
        metric_card("Top protocol", top_proto.upper() if top_proto != "—" else "—", "most common", "blue"),
    ])


def layout() -> html.Div:
    data = api_get("/api/network/flows?size=100")
    if isinstance(data, dict) and data.get("error"):
        data = {"total": 0, "flows": [], "unique_src": 0, "unique_dst": 0, "by_proto": {}}

    return html.Div([
        topbar(
            "Network flows",
            dcc.Interval(id="net-poll", interval=30_000, n_intervals=0),
            html.Button([html.I(className="ti ti-refresh", style={"fontSize": "13px"}), " Refresh"], id="net-refresh-btn", className="topbar-btn"),
        ),
        html.Div(className="content", children=[
            html.Div(id="net-metrics", children=_net_metrics(data)),
            html.Div(className="card", children=[
                html.Div(className="card-header", children=[
                    html.Span("Flow table", className="card-title"),
                    html.Div(style={"display": "flex", "gap": "8px"}, children=[
                        dcc.Input(id="net-search", placeholder="Search IPs…", className="search-input", style={"width": "200px", "paddingLeft": "10px"}),
                        dcc.Dropdown(id="net-proto-filter", options=_PROTO_OPTIONS, value="", clearable=False,
                                     style={"width": "160px", "fontSize": "12px"}, className="select"),
                    ]),
                ]),
                html.Div(id="net-table", children=_flows_table(data.get("flows", []))),
                html.Div(
                    f"Showing {len(data.get('flows', []))} of {data.get('total', 0):,} flows",
                    id="net-footer",
                    style={"fontSize": "11px", "color": "#888780", "paddingTop": "8px"},
                ),
            ]),
        ]),
    ])


@callback(
    Output("net-metrics", "children"),
    Output("net-table", "children"),
    Output("net-footer", "children"),
    Input("net-poll", "n_intervals"),
    Input("net-refresh-btn", "n_clicks"),
    Input("net-search", "value"),
    Input("net-proto-filter", "value"),
    prevent_initial_call=False,
)
def _refresh_network(_poll, _refresh, search, proto):
    params = "?size=100"
    if search:
        params += f"&q={search}"
    if proto:
        params += f"&proto={proto}"

    data = api_get(f"/api/network/flows{params}")
    if isinstance(data, dict) and data.get("error"):
        return _net_metrics({}), error_banner(f"Error: {data['error']}"), ""

    flows = data.get("flows", [])
    total = data.get("total", 0)
    return _net_metrics(data), _flows_table(flows), f"Showing {len(flows)} of {total:,} flows"
