from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AliasCreateRequest(BaseModel):
    alias: str
    sources: list[str] = Field(default_factory=list)
    filter_mode: str = ""
    filter_value: str = ""


class CaptureReplayRequest(BaseModel):
    pcap: str
    keep: bool = False
    now: bool = False
    content: str = ""  # base64 data-URL if uploading via browser


class CaptureUploadRequest(BaseModel):
    # File already on disk
    file_path: str = ""
    batch: bool = False
    folder: str = ""
    # File content from browser upload (base64, data-URL format)
    content: str = ""
    filename: str = ""
    # Options
    keep: bool = False
    now: bool = False
    index: str = ""
    type: str = ""
    build_pipeline: bool = False
    llm_ram_mode: str = "none"


class EnrichRunRequest(BaseModel):
    cluster: str = ""
    dry_run: bool = False
    params: dict[str, Any] = Field(default_factory=dict)


class RuleFileWriteRequest(BaseModel):
    path: str
    content: str


class RuleValidateRequest(BaseModel):
    content: str
    type: str = ""  # "suricata", "sigma", "elastalert", or "" for auto-detect


class LiveCaptureStartRequest(BaseModel):
    iface: str = "en0"
    rotation: int = 10
    keep: bool = False


class PipelineUploadRequest(BaseModel):
    filename: str
    content: str  # base64 data-URL from dcc.Upload


class HealthResponse(BaseModel):
    elasticsearch_url: str
    kibana_url: str
    services: list[dict]
