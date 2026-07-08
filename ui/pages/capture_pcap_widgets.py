from __future__ import annotations

from typing import Any

from dash import dcc, html

from ui.helpers import colorize_log


def terminal_children(lines: list[str] | None = None) -> list:
    if lines is None:
        return [html.Span("Run a replay to see output…", style={"color": "#6e7681", "fontStyle": "italic"})]
    if not lines:
        return []
    return colorize_log(lines)


def replay_stats(stats: dict) -> list:
    if not stats:
        return []
    return [html.Div(style={"display": "flex", "gap": "20px", "marginTop": "10px"}, children=[
        html.Div([html.Span("Suricata docs: ", style={"fontSize": "12px", "color": "#888780"}),
                  html.B(f'+{stats.get("suricata_docs", 0):,}' if stats.get("suricata_docs") else "—")]),
        html.Div([html.Span("soc-alerts: ", style={"fontSize": "12px", "color": "#888780"}),
                  html.B(f'+{stats.get("soc_alerts_docs", 0)}' if stats.get("soc_alerts_docs") else "—",
                         style={"color": "#A32D2D"} if stats.get("soc_alerts_docs") else {})]),
    ])]


def replay_output_card_static() -> html.Div:
    return html.Div(className="card", style={"display": "flex", "flexDirection": "column", "flex": "1", "minHeight": "240px"}, children=[
        html.Div(className="card-header", style={"flexShrink": "0"}, children=[
            html.Span(["Replay output", html.Span(id="pcap-live-badge")], className="card-title"),
            html.Button("Clear", id="pcap-clear-btn", className="rule-btn", n_clicks=0),
        ]),
        html.Div(id="pcap-output-terminal", className="terminal fill", children=terminal_children()),
        html.Div(id="pcap-output-stats", style={"flexShrink": "0"}),
    ])


def loaded_file_placeholder() -> html.Div:
    return html.Div(style={"textAlign": "center", "padding": "28px 0", "color": "#b0afac"}, children=[
        html.I(className="ti ti-file-off", style={"fontSize": "28px", "display": "block", "marginBottom": "6px"}),
        html.Div("No file loaded", style={"fontSize": "12px"}),
    ])


def loaded_file_badge(name: str, sub: str) -> html.Div:
    return html.Div(style={"display": "flex", "alignItems": "center", "gap": "8px", "padding": "8px 10px",
                            "background": "#F1F5F9", "borderRadius": "6px"}, children=[
        html.I(className="ti ti-file-check", style={"fontSize": "15px", "color": "#3B6D11", "flexShrink": "0"}),
        html.Div(style={"flex": "1"}, children=[
            html.Div(name, style={"fontSize": "13px", "fontWeight": "500"}),
            html.Div(sub, style={"fontSize": "11px", "color": "#888780"}),
        ]),
    ])


def file_placeholder(sub: str = "Drop a file above or select from folder below") -> html.Div:
    return html.Div(style={"display": "flex", "alignItems": "center", "gap": "8px", "padding": "8px 10px",
                            "background": "#F9F9F8", "borderRadius": "6px", "border": "1px dashed #DDDCDA"}, children=[
        html.I(className="ti ti-file-off", style={"fontSize": "15px", "color": "#c0bfbb", "flexShrink": "0"}),
        html.Div(style={"flex": "1"}, children=[
            html.Div("No file selected", style={"fontSize": "13px", "fontWeight": "500", "color": "#888780"}),
            html.Div(sub, style={"fontSize": "11px", "color": "#b0afac"}),
        ]),
    ])


def history_table(history: list[dict]) -> html.Table | html.Div:
    if not history:
        return html.Div("No replays yet.", style={"fontSize": "12px", "color": "#888780", "padding": "12px 0"})
    header = html.Thead(html.Tr([
        html.Th("", style={"width": "16px", "padding": "7px 4px 7px 12px"}),
        html.Th("PCAP file"), html.Th("Docs", style={"textAlign": "right"}),
        html.Th("Date", style={"whiteSpace": "nowrap"}), html.Th(""),
    ]), style={"position": "sticky", "top": "0", "background": "#fff", "zIndex": "1"})
    rows = []
    for item in history[:10]:
        ts = item.get("timestamp", "")[:16].replace("T", " ") if item.get("timestamp") else "—"
        sd = item.get("suricata_docs") or 0
        sa = item.get("soc_alerts_docs") or 0
        docs = f"+{sd:,}" if sd or sa else "—"
        dot_cls = "dot green" if item.get("status", "done") == "done" else "dot red"
        pcap_name = item.get("pcap", "")
        rows.append(html.Tr([
            html.Td(html.Div(className=dot_cls), style={"width": "16px", "padding": "10px 4px 10px 12px"}),
            html.Td(pcap_name or "—", className="mono", style={"maxWidth": "140px", "overflow": "hidden", "textOverflow": "ellipsis", "whiteSpace": "nowrap", "paddingLeft": "4px"}),
            html.Td(docs, style={"textAlign": "right", "fontWeight": "500"}),
            html.Td(ts, style={"fontSize": "11px", "color": "#888780", "whiteSpace": "nowrap"}),
            html.Td(html.Button([html.I(className="ti ti-player-play", style={"fontSize": "11px"}), " Replay"], id={"type": "history-replay-btn", "name": pcap_name}, className="rule-btn", n_clicks=0) if pcap_name else "", style={"paddingLeft": "6px"}),
        ]))
    return html.Table([header, html.Tbody(rows)], className="tbl")


def folder_file_row(name: str, size_human: str, btn_id: dict) -> html.Div:
    return html.Div(style={"display": "flex", "alignItems": "center", "gap": "8px", "padding": "6px 0", "borderBottom": "0.5px solid rgba(0,0,0,0.06)"}, children=[
        html.I(className="ti ti-file", style={"fontSize": "13px", "color": "#888780", "flexShrink": "0"}),
        html.Span(name, className="mono", style={"fontSize": "12px", "flex": "1", "overflow": "hidden", "textOverflow": "ellipsis", "whiteSpace": "nowrap"}),
        html.Span(size_human, style={"fontSize": "11px", "color": "#888780", "flexShrink": "0"}),
        html.Button("Select", id=btn_id, className="rule-btn", n_clicks=0),
    ])


def pcap_folder_preview(files: list[dict]) -> html.Div:
    if not files:
        return html.Div("No PCAP files in data/pcap/ — drop files there or upload above.", style={"fontSize": "12px", "color": "#888780", "padding": "6px 0"})
    return html.Div([folder_file_row(f["name"], f.get("size_human", ""), {"type": "pcap-folder-pick", "name": f["name"]}) for f in files[:5]])


def overlay(overlay_id: str, title: str, files: list[dict], btn_type: str) -> html.Div:
    rows = [folder_file_row(f["name"], f.get("size_human", ""), {"type": btn_type, "name": f["name"]}) for f in files]
    return html.Div(id=overlay_id, style={"display": "none", "position": "fixed", "inset": "0", "zIndex": "1000", "background": "rgba(0,0,0,0.35)", "alignItems": "center", "justifyContent": "center"}, children=[
        html.Div(style={"background": "#fff", "borderRadius": "12px", "padding": "20px", "width": "560px", "maxWidth": "90vw", "maxHeight": "80vh", "display": "flex", "flexDirection": "column", "gap": "12px", "boxShadow": "0 8px 32px rgba(0,0,0,0.18)"}, children=[
            html.Div(style={"display": "flex", "alignItems": "center"}, children=[
                html.Span(title, style={"fontWeight": "600", "fontSize": "14px", "flex": "1"}),
                html.Button("✕", id=f"{overlay_id}-close", className="rule-btn", n_clicks=0),
            ]),
            dcc.Input(id=f"{overlay_id}-search", placeholder="Search…", debounce=False, className="setting-input", style={"width": "100%", "boxSizing": "border-box"}),
            html.Div(id=f"{overlay_id}-list", style={"overflowY": "auto", "flex": "1", "minHeight": "0"}, children=rows),
            dcc.Store(id=f"{overlay_id}-files", data=files),
        ]),
    ])
