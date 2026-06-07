from __future__ import annotations

from typing import Any

import httpx

from core.settings import kibana_url


class KibanaClient:
    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or kibana_url()).rstrip("/")
        self.client = httpx.Client(timeout=5.0)

    def is_available(self) -> bool:
        try:
            response = self.client.get(f"{self.base_url}/api/status")
            return response.is_success
        except httpx.HTTPError:
            return False

    def list_data_views(self) -> list[dict[str, Any]]:
        response = self.client.get(f"{self.base_url}/api/data_views")
        response.raise_for_status()
        return response.json().get("data_view", [])

    def ensure_data_view(self, title: str, time_field: str = "@timestamp", name: str | None = None) -> None:
        if not self.is_available():
            return
        existing = self.list_data_views()
        if any(view.get("title") == title for view in existing):
            return
        payload = {"data_view": {"title": title, "timeFieldName": time_field, "name": name or title}}
        response = self.client.post(
            f"{self.base_url}/api/data_views/data_view",
            headers={"kbn-xsrf": "true", "Content-Type": "application/json"},
            json=payload,
        )
        response.raise_for_status()

    def delete_data_view(self, title: str) -> None:
        if not self.is_available():
            return
        for view in self.list_data_views():
            if view.get("title") == title or view.get("name") == title:
                response = self.client.delete(
                    f"{self.base_url}/api/data_views/data_view/{view['id']}",
                    headers={"kbn-xsrf": "true"},
                )
                response.raise_for_status()
