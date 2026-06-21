from __future__ import annotations

import warnings
warnings.filterwarnings("ignore", message=".*urllib3.*", category=UserWarning)
warnings.filterwarnings("ignore", message=".*LibreSSL.*", category=UserWarning)

from pathlib import Path

import dash
from dash import Dash, Input, Output, callback, dcc, html, page_container

from ui.helpers import api_get

PAGES_DIR = Path(__file__).resolve().parent / "pages"

app = Dash(
    __name__,
    use_pages=True,
    pages_folder=str(PAGES_DIR),
    suppress_callback_exceptions=True,
    external_stylesheets=["https://cdn.jsdelivr.net/npm/@tabler/icons-webfont@latest/tabler-icons.min.css"],
)
server = app.server


NAV_ITEMS = [
    ("nav-overview",    "Overview",      "/",           "ti ti-layout-dashboard", "Monitor", None),
    ("nav-alerts",      "Alerts",        "/alerts",     "ti ti-bell-ringing",     None,      html.Span(id="nav-alerts-badge", className="badge")),
    ("nav-network",     "Network graph", "/network",    "ti ti-network",          None,      None),
    ("nav-logs",        "Log upload",    "/logs",         "ti ti-file-import",    "Ingest",  None),
    ("nav-capture",     "Packet replay", "/capture",      "ti ti-radar",          None,      None),
    ("nav-live",        "Live capture",  "/capture/live", "ti ti-radio",          None,      None),
    ("nav-rules",       "Rules",         "/rules",      "ti ti-adjustments",      "Detect",  None),
    ("nav-enrichment",  "Enrichment",    "/enrichment", "ti ti-microscope",       None,      None),
    ("nav-stack",       "Stack",         "/stack",      "ti ti-server",           "System",  None),
    ("nav-aliases",     "Aliases",       "/aliases",    "ti ti-link",             None,      None),
    ("nav-settings",    "Settings",      "/settings",   "ti ti-settings",         None,      None),
]


def nav_link(link_id: str, label: str, href: str, icon: str, badge: html.Span | None = None) -> dcc.Link:
    children = [html.I(className=icon), label]
    if badge is not None:
        children.append(badge)
    return dcc.Link(children=children, href=href, id=link_id, className="nav-item")


def sidebar_sections() -> list[html.Div]:
    sections: list[html.Div] = []
    current_group: str | None = None
    for link_id, label, href, icon, group, badge in NAV_ITEMS:
        if group:
            sections.append(html.Div(group, className="nav-section"))
            current_group = group
        elif current_group is None:
            current_group = "Investigate"
        sections.append(nav_link(link_id, label, href, icon, badge))
    return sections


app.layout = html.Div(
    className="app",
    children=[
        dcc.Location(id="url"),
        dcc.Interval(id="sidebar-health-poll", interval=15000, n_intervals=0),
        html.Div(
            className="sidebar",
            children=[
                dcc.Link(
                    className="sidebar-logo",
                    href="/",
                    children=[html.Div(html.I(className="ti ti-shield-bolt"), className="logo-icon"), html.Span("soc-lab", className="logo-text")],
                ),
                *sidebar_sections(),
                html.Div(className="sidebar-bottom", children=[html.Div(id="sidebar-health", className="stack-status")]),
            ],
        ),
        html.Div(className="main", children=[page_container]),
    ],
)


@callback(
    [Output(link_id, "className") for link_id, *_ in NAV_ITEMS],
    Input("url", "pathname"),
)
def update_active_nav(pathname: str | None):
    pathname = pathname or "/"
    classes = []
    for _link_id, _label, href, *_rest in NAV_ITEMS:
        active = pathname == href
        if href == "/" and pathname == "/":
            active = True
        classes.append("nav-item active" if active else "nav-item")
    return classes


@callback(Output("nav-alerts-badge", "children"), Input("sidebar-health-poll", "n_intervals"))
def update_alerts_badge(_n: int):
    data = api_get("/api/alerts/stats")
    if isinstance(data, dict) and not data.get("error"):
        total = data.get("total", 0)
        high = data.get("by_severity", {}).get("high", 0)
        count = high if high > 0 else total
        return str(count) if count > 0 else ""
    return ""


@callback(Output("sidebar-health", "children"), Input("sidebar-health-poll", "n_intervals"))
def update_sidebar_health(_n: int):
    data = api_get("/api/stack/services")
    cards = data.get("cards", []) if isinstance(data, dict) else []
    if not cards:
        return [html.Div("Stack health", className="stack-title"), html.Div("No data", className="stack-row")]
    children = [html.Div("Stack health", className="stack-title")]
    for card in cards[:4]:
        tag_class = card.get("tag", {}).get("class", "warning")
        dot_class = "green" if tag_class == "running" else "yellow" if tag_class == "warning" else "red"
        children.append(html.Div([html.Div(className=f"dot {dot_class}"), card.get("title", "")], className="stack-row"))
    return children


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8050, debug=True, dev_tools_ui=False, dev_tools_props_check=False)
