"""Тонкий клиент к Keitaro Admin API v1.

Документация: в админке Keitaro → Обслуживание → Admin API.
Все запросы идут с заголовком Api-Key.
"""

import httpx

from app.config import settings


class KeitaroError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(f"Keitaro {status}: {message}")
        self.status = status
        self.message = message


class KeitaroClient:
    def __init__(self, base_url: str | None = None, api_key: str | None = None, transport=None):
        self._client = httpx.Client(
            base_url=(base_url or settings.keitaro_url).rstrip("/") + "/admin_api/v1",
            headers={"Api-Key": api_key or settings.keitaro_api_key},
            timeout=30,
            transport=transport,  # в тестах подставляем фейковый транспорт
        )

    def _request(self, method: str, path: str, **kwargs):
        response = self._client.request(method, path, **kwargs)
        if response.status_code >= 400:
            try:
                detail = response.json()
            except ValueError:
                detail = response.text
            raise KeitaroError(response.status_code, str(detail))
        if not response.content:
            return None
        return response.json()

    # --- справочники ---
    def domains(self) -> list[dict]:
        return self._request("GET", "/domains")

    def campaign_groups(self) -> list[dict]:
        return self._request("GET", "/groups", params={"type": "campaigns"})

    def traffic_sources(self) -> list[dict]:
        return self._request("GET", "/traffic_sources")

    def offers(self) -> list[dict]:
        return self._request("GET", "/offers")

    # --- кампании и потоки ---
    def campaign(self, campaign_id: int) -> dict:
        return self._request("GET", f"/campaigns/{campaign_id}")

    def create_campaign(self, payload: dict) -> dict:
        return self._request("POST", "/campaigns", json=payload)

    def streams(self, campaign_id: int) -> list[dict]:
        return self._request("GET", f"/campaigns/{campaign_id}/streams")

    def create_stream(self, payload: dict) -> dict:
        return self._request("POST", "/streams", json=payload)

    def update_stream(self, stream_id: int, payload: dict) -> dict:
        return self._request("PUT", f"/streams/{stream_id}", json=payload)


def get_keitaro() -> KeitaroClient:
    """FastAPI-зависимость; в тестах подменяется через dependency_overrides."""
    return KeitaroClient()
