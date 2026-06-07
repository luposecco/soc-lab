from __future__ import annotations

import warnings
warnings.filterwarnings("ignore", message=".*urllib3.*", category=UserWarning)
warnings.filterwarnings("ignore", message=".*LibreSSL.*", category=UserWarning)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.settings import es_url, kibana_url
from core.stack.docker import list_services
from api.models import HealthResponse
from api.routes import alerts, capture, enrichment, indices, network, overview, rules, stack

app = FastAPI(title="SOC Lab API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8050", "http://localhost:8050"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for _router in (stack.router, overview.router, indices.router, rules.router,
                capture.router, alerts.router, network.router, enrichment.router):
    app.include_router(_router)


@app.get("/api/health", response_model=HealthResponse)
def api_health() -> HealthResponse:
    return HealthResponse(elasticsearch_url=es_url(), kibana_url=kibana_url(), services=list_services())
