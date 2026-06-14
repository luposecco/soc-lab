from __future__ import annotations

from typing import Any

import httpx
from dash import html

from core.settings import api_url


def api_get(path: str) -> Any:
    try:
        response = httpx.get(f"{api_url()}{path}", timeout=8.0)
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        return {"error": str(exc)}


def api_post(path: str, body: dict[str, Any] | None = None) -> Any:
    try:
        response = httpx.post(f"{api_url()}{path}", json=body or {}, timeout=15.0)
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        return {"error": str(exc)}


def api_delete(path: str) -> Any:
    try:
        response = httpx.delete(f"{api_url()}{path}", timeout=8.0)
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        return {"error": str(exc)}


# ── Layout helpers ─────────────────────────────────────────────────────────────
# These return style dicts. All layout lives here in Python; CSS handles only
# visual properties (colors, borders, radius, shadows, hover, animations).

_G = "14px"   # standard gap
_MW = "300px" # min column width for auto-fit grids


def lrow(
    min_col: str = _MW,
    gap: str = _G,
    fill: bool = False,
    shrink: bool = False,
    cols: int | None = None,
) -> dict:
    """
    Auto-fit grid row. Columns wrap to next row when they hit min_col.
    fill=True: grows to fill remaining flex height and distributes that
               height to rows via grid-auto-rows, so cards inside fill too.
    shrink=True: flexShrink:0 — stays at natural height, doesn't squish.
    cols=N: force exactly N equal columns instead of auto-fit.
    """
    template = (
        f"repeat({cols}, 1fr)"
        if cols
        else f"repeat(auto-fit, minmax({min_col}, 1fr))"
    )
    s: dict = {"display": "grid", "gridTemplateColumns": template, "gap": gap, "alignItems": "stretch"}
    if fill:
        s |= {"flex": "1", "minHeight": "0", "gridAutoRows": "minmax(0, 1fr)"}
    elif shrink:
        s["flexShrink"] = "0"
    return s


def lcol(gap: str = _G, fill: bool = False, min_w: str = _MW) -> dict:
    """Flex column for stacking cards vertically inside a grid cell."""
    s: dict = {
        "display": "flex",
        "flexDirection": "column",
        "gap": gap,
        "minWidth": min_w,
        "minHeight": "0",
        "overflow": "hidden",
    }
    if fill:
        s["flex"] = "1"
    return s


def lpanel(min_h: int = 200, fill: bool = False, shrink: bool = False) -> dict:
    """
    Layout for a general card panel (flex column so children can fill it).
    Use as style= alongside className="card".
    """
    s: dict = {"display": "flex", "flexDirection": "column", "minHeight": f"{min_h}px"}
    if fill:
        s["flex"] = "1"
    if shrink:
        s["flexShrink"] = "0"
    return s


def ltable(min_h: int = 260, fill: bool = False, shrink: bool = False) -> dict:
    """
    Layout for a table card panel — overflow hidden so .table-panel-body scrolls.
    Use as style= alongside className="card".
    """
    s: dict = {
        "display": "flex",
        "flexDirection": "column",
        "minHeight": f"{min_h}px",
        "overflow": "hidden",
    }
    if fill:
        s["flex"] = "1"
    if shrink:
        s["flexShrink"] = "0"
    return s


def lterm(fill: bool = False, height: int = 200, min_h: int = 140) -> dict:
    """Height/flex for .terminal elements."""
    if fill:
        return {"flex": "1", "minHeight": "300px"}
    return {"height": f"{height}px", "minHeight": f"{min_h}px"}


# ── UI helpers ─────────────────────────────────────────────────────────────────

def topbar(title: str, *extra: Any) -> html.Div:
    return html.Div(
        className="topbar",
        children=[html.Span(title, className="page-title"), *extra],
    )


def sev_badge(level: str) -> html.Span:
    cls_map = {"critical": "crit", "high": "high", "medium": "med", "low": "low", "info": "info"}
    cls = cls_map.get(level.lower(), "info")
    return html.Span(level.title(), className=f"sev {cls}")


def tag(label: str, variant: str = "blue") -> html.Span:
    return html.Span(label, className=f"tag {variant}")


def health_dot(status: str) -> html.Div:
    cls_map = {"green": "green", "yellow": "yellow", "red": "red", "running": "green", "stopped": "red", "warning": "yellow"}
    color = cls_map.get(status.lower(), "yellow")
    return html.Div(className=f"dot {color}")


def metric_card(label: str, value: str, sub: str = "", color: str = "blue") -> html.Div:
    return html.Div(
        className="metric",
        children=[
            html.Div(label, className="metric-label"),
            html.Div(value, className=f"metric-val {color}"),
            html.Div(sub, className="metric-sub") if sub else None,
        ],
    )


def card(title: str, children: list[Any], action_label: str = "", action_href: str = "") -> html.Div:
    header_children: list[Any] = [html.Span(title, className="card-title")]
    if action_label:
        link = html.A(action_label, href=action_href, className="card-action") if action_href else html.Span(action_label, className="card-action")
        header_children.append(link)
    return html.Div(
        className="card",
        children=[html.Div(className="card-header", children=header_children), *children],
    )


def page_layout(title: str, content: list[Any]) -> html.Div:
    return html.Div([
        topbar(title),
        html.Div(className="content", children=content),
    ])


def placeholder_card(title: str, text: str) -> html.Div:
    return html.Div(className="card", children=[
        html.Div(className="card-header", children=[html.Span(title, className="card-title")]),
        html.P(text, style={"fontSize": "12px", "color": "#888780"}),
    ])


def colorize_log(lines: list[str] | str) -> list:
    """Convert log lines to colored Dash children for a terminal div."""
    import re
    if isinstance(lines, str):
        lines = lines.splitlines()

    _noise_re = re.compile(r"NotOpenSSLWarning|warnings\.warn|site-packages|^\s+$")
    _ts_re = re.compile(
        r"^(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?|\[\d{2}:\d{2}:\d{2}\])"
    )

    result = []
    for line in lines:
        if not line.strip():
            continue
        if _noise_re.search(line):
            result.append(html.Div(html.Span(line, className="t-gray")))
            continue

        children: list = []
        rest = line
        m = _ts_re.match(rest)
        if m:
            children.append(html.Span(m.group(0) + " ", className="t-gray"))
            rest = rest[m.end():].lstrip()

        up = rest.upper()

        if rest.startswith("[*]"):
            children.append(html.Span("[*]", className="t-blue"))
            rest = rest[3:]
        elif rest.startswith("[INFO]") or rest.startswith("[info]"):
            children.append(html.Span("[INFO]", className="t-green"))
            rest = rest[6:]
        elif up.startswith("[WARN"):
            end = rest.find("]") + 1
            children.append(html.Span(rest[:end], className="t-yellow"))
            rest = rest[end:]
        elif up.startswith("[ERR") or up.startswith("[CRIT"):
            end = rest.find("]") + 1
            children.append(html.Span(rest[:end], className="t-red"))
            rest = rest[end:]
        elif up.startswith("[DEBUG"):
            children.append(html.Span("[DEBUG]", className="t-gray"))
            rest = rest[7:]
        elif re.match(r"^(INFO|WARNING|ERROR|DEBUG|CRITICAL)\b", up):
            lvl = re.match(r"^(\w+)", rest).group(1)
            cls = {"INFO": "t-green", "WARNING": "t-yellow", "WARN": "t-yellow",
                   "ERROR": "t-red", "CRITICAL": "t-red", "DEBUG": "t-gray"}.get(lvl.upper(), "")
            children.append(html.Span(lvl, className=cls))
            rest = rest[len(lvl):]
        elif " - INFO - " in rest or " - INFO " in rest:
            children.append(html.Span(rest, className="t-green"))
            rest = ""
        elif " - WARNING" in rest or " - WARN" in rest:
            children.append(html.Span(rest, className="t-yellow"))
            rest = ""
        elif " - ERROR" in rest or " - CRITICAL" in rest:
            children.append(html.Span(rest, className="t-red"))
            rest = ""
        elif re.match(r"^(Successfully|Success|Done|OK\b)", rest, re.I):
            children.append(html.Span(rest, className="t-green"))
            rest = ""
        elif re.match(r"^(Error|Failed|Exception|Traceback)", rest, re.I):
            children.append(html.Span(rest, className="t-red"))
            rest = ""

        if rest:
            children.append(rest)
        result.append(html.Div(children))

    return result or [html.Span("No output yet…", className="t-gray")]


def error_banner(msg: str) -> html.Div:
    return html.Div(
        msg,
        style={"background": "#FCEBEB", "color": "#A32D2D", "borderRadius": "8px", "padding": "10px 14px", "fontSize": "12px"},
    )
