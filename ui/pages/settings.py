from __future__ import annotations

import dash
from dash import html

from ui.helpers import topbar

dash.register_page(__name__, path="/settings")


def layout() -> html.Div:
    return html.Div([
        topbar("Settings"),
        html.Div(className="content", children=[
            html.Div(
                style={
                    "display": "flex", "flexDirection": "column", "alignItems": "center",
                    "justifyContent": "center", "height": "60vh", "gap": "12px",
                },
                children=[
                    html.I(className="ti ti-settings", style={"fontSize": "48px", "color": "#C8C5BC"}),
                    html.Div("Work in progress", style={"fontSize": "18px", "fontWeight": "600", "color": "#3D3A33"}),
                    html.Div("Settings panel is not yet available.", style={"fontSize": "13px", "color": "#888780"}),
                ],
            ),
        ]),
    ])
