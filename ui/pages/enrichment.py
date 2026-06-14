from __future__ import annotations

import dash
from dash import html

from ui.helpers import topbar

dash.register_page(__name__, path="/enrichment")


def layout() -> html.Div:
    return html.Div([
        topbar("Enrichment"),
        html.Div(className="content", style={"alignItems": "center", "justifyContent": "center"}, children=[
            html.Div(style={"textAlign": "center", "color": "#888780", "paddingBottom": "40px"}, children=[
                html.I(className="ti ti-microscope", style={"fontSize": "48px", "marginBottom": "16px", "display": "block"}),
                html.Div("Work in Progress", style={"fontSize": "18px", "fontWeight": "600", "color": "#3d3c38", "marginBottom": "8px"}),
                html.Div("Enrichment pipelines are under development.", style={"fontSize": "13px"}),
            ]),
        ]),
    ])
