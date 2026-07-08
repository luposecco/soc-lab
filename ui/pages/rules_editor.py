from __future__ import annotations

from typing import Any

from dash import dcc, html
from dash_ace import DashAceEditor

from ui.helpers import lpanel, metric_card

SURI_ACTIONS = {"alert", "pass", "drop", "reject", "rejectsrc", "rejectdst", "rejectboth"}


def rules_table(files: list[dict], total: int | None = None) -> list:
    if not files:
        return [html.Div("No rules found.", style={"fontSize": "12px", "color": "#888780", "padding": "12px 0"})]
    header = html.Thead(html.Tr([html.Th("Name"), html.Th("")]))
    rows = [html.Table([header, html.Tbody([_rule_row(item) for item in files])], className="tbl")]
    if total is not None and total > len(files):
        rows.append(html.Div(f"Showing {len(files)} of {total:,} · search to filter", style={"fontSize": "11px", "color": "#888780", "padding": "8px 0", "textAlign": "center", "flexShrink": "0"}))
    return rows


def editor_card(path: str = "", name: str = "", content: str = "", readonly: bool = False) -> html.Div:
    status_el = html.Span("Empty", className="tag warning") if not path else html.Span("Read-only · ET", className="tag purple") if readonly else html.Span("Loaded", className="tag running")
    return html.Div(className="card", style={**lpanel(fill=True, min_h=500), "overflow": "hidden", "flex": "1"}, children=[
        html.Div(className="card-header", children=[html.Span("Rule editor", className="card-title"), status_el]),
        html.Div(style={"display": "flex", "flexDirection": "column", "gap": "10px", "flex": "1", "minHeight": "0"}, children=[
            dcc.Input(id="rules-editor-name", value=name, placeholder="Rule name / title", className="setting-input", style={"width": "100%", "boxSizing": "border-box"}, disabled=readonly),
            html.Div(style={"display": "flex", "gap": "8px", "alignItems": "center", "flexWrap": "wrap"}, children=[
                html.Button([html.I(className="ti ti-check", style={"fontSize": "12px"}), " Validate"], id="rules-validate-btn", className="topbar-btn", n_clicks=0),
                html.Button([html.I(className="ti ti-device-floppy", style={"fontSize": "12px"}), " Save"], id="rules-save-btn", className="topbar-btn primary", n_clicks=0, style={"display": "none" if readonly else "flex"}),
                html.Button([html.I(className="ti ti-eraser", style={"fontSize": "12px"}), " Clear draft"], id="rules-clear-draft-btn", className="topbar-btn", n_clicks=0, style={"display": "none" if readonly else "flex"}),
                html.Button(html.I(className="ti ti-trash", style={"fontSize": "12px"}), id="rules-delete-btn", className="topbar-btn danger", n_clicks=0, style={"marginLeft": "auto", "display": "none" if readonly else "flex"}),
                html.Span("Built-in ET rule — read only", style={"fontSize": "11px", "color": "#888780", "display": "block" if readonly else "none"}),
            ]),
            DashAceEditor(id="rules-editor-content", value=content, mode=_ace_mode(path, content), theme="tomorrow_night", tabSize=2, fontSize=12, enableBasicAutocompletion=False, enableLiveAutocompletion=False, enableSnippets=False, wrapEnabled=True, readOnly=readonly, showGutter=True, showPrintMargin=False, highlightActiveLine=False, placeholder="Paste or write rule YAML / Suricata rule here…", className="rule-ace-editor", style={"flex": "1", "minHeight": "300px", "width": "100%"}),
            html.Div(path or "No file selected", id="rules-editor-path", style={"fontSize": "10px", "color": "#888780", "fontFamily": "monospace"}),
        ]),
    ])


def metrics_row(sigma_n: int, suricata_total: int, elastalert_n: int, status_data: dict[str, Any] | None = None, suricata_rule_error: bool = False) -> html.Div:
    status_data = status_data or {}
    suricata_error = status_data.get("suricata", {}).get("status") == "fail" or suricata_rule_error
    sigma_error = status_data.get("sigma", {}).get("status") == "fail"
    elastalert_error = sigma_error
    total_error = suricata_error or sigma_error or elastalert_error
    total = sigma_n + suricata_total + elastalert_n
    return html.Div(className="metrics", children=[
        metric_card("Total rules", f"{total:,}" if suricata_total is not None else "…", "all types", "red" if total_error else "blue"),
        metric_card("Sigma", str(sigma_n), "detection rules", "red" if sigma_error else "blue"),
        metric_card("Suricata", f"{suricata_total:,}" if suricata_total is not None else "…", "IDS rules", "red" if suricata_error else "blue"),
        metric_card("ElastAlert", str(elastalert_n), "alert rules", "red" if elastalert_error else "blue"),
    ])


def _type_tag(rule_type: str) -> html.Span:
    cls = {"sigma": "blue", "suricata": "running", "elastalert": "warning"}.get(rule_type, "unknown")
    return html.Span(rule_type.capitalize(), className=f"tag {cls}")


def _source_tag(source: str) -> html.Span | None:
    return html.Span("ET", className="tag purple") if source == "docker" else None


def _rule_row(item: dict[str, Any]) -> html.Tr:
    file_path = item.get("file", "")
    source = item.get("source", "local")
    is_docker = source == "docker"
    is_suricata = item.get("type") == "suricata"
    display_path = file_path.split("#")[0].split("/")[-1] if file_path.startswith("docker:suricata:") or "#" in file_path else file_path
    tags = [_type_tag(item.get("type", ""))]
    src_tag = _source_tag(source)
    if src_tag:
        tags.append(src_tag)
    status = item.get("status", "enabled")
    status_tag = html.Span("Disabled", className="tag warning") if status == "disabled" else html.Span("Error", className="tag stopped") if status == "error" else html.Span("Enabled", className="tag running")
    name_cell = html.Div([html.Span(item.get("name", item.get("stem", "—")), style={"fontWeight": "500", "fontSize": "13px", "lineHeight": "1.3"}), html.Div([status_tag, *tags, html.Span(display_path, className="mono", style={"fontSize": "10px", "color": "#888780"}), html.Span(f"sid:{item.get('sid', '')}", style={"fontSize": "10px", "color": "#aaa89e", "fontFamily": "monospace"}) if item.get("sid") and is_suricata else None], style={"display": "flex", "alignItems": "center", "gap": "5px", "marginTop": "4px", "flexWrap": "wrap"})])
    icon = "ti ti-eye" if is_docker else "ti ti-pencil"
    label = " View" if is_docker else " Edit"
    return html.Tr([html.Td(name_cell, style={"width": "100%"}), html.Td(html.Button([html.I(className=icon, style={"fontSize": "11px"}), label], id={"type": "rules-edit-btn", "file": file_path}, className="rule-btn", n_clicks=0), style={"whiteSpace": "nowrap"})])


def _ace_mode(path: str, content: str) -> str:
    if path.endswith(".rules"):
        return "snort"
    if not path and content:
        first = content.lstrip().split(None, 1)
        if first and first[0] in SURI_ACTIONS:
            return "snort"
    return "yaml"
