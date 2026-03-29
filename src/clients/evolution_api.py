import logging
from typing import Any

import requests

from src.config import Settings


class EvolutionApiClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._logger = logging.getLogger(self.__class__.__name__)
        self._session = requests.Session()

    def _build_url(self, endpoint: str) -> str:
        endpoint = endpoint if endpoint.startswith("/") else f"/{endpoint}"
        return f"{self._settings.evolution_base_url}{endpoint}"

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "apikey": self._settings.evolution_api_key,
        }

    def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = self._build_url(endpoint)
        try:
            response = self._session.post(
                url,
                json=payload,
                headers=self._headers(),
                timeout=self._settings.request_timeout_seconds,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(f"Evolution API request failed for {endpoint}: {exc}") from exc

        if not response.text:
            return {}

        try:
            return response.json()
        except ValueError:
            self._logger.warning("Evolution API returned non-JSON response for %s", endpoint)
            return {"raw": response.text}

    def _get(self, endpoint: str) -> dict[str, Any] | list[Any]:
        url = self._build_url(endpoint)
        try:
            response = self._session.get(
                url,
                headers=self._headers(),
                timeout=self._settings.request_timeout_seconds,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(f"Evolution API request failed for {endpoint}: {exc}") from exc

        if not response.text:
            return {}

        try:
            return response.json()
        except ValueError:
            self._logger.warning("Evolution API returned non-JSON response for %s", endpoint)
            return {"raw": response.text}

    def send_message(self, number: str, text: str, **options: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "number": number,
            "text": text,
        }
        payload.update(options)
        return self._post(f"/message/sendText/{self._settings.evolution_instance}", payload)

    def find_messages(self, remote_jid: str, limit: int | None = None) -> Any:
        payload = {
            "where": {
                "key": {
                    "remoteJid": remote_jid,
                }
            }
        }
        response = self._post(f"/chat/findMessages/{self._settings.evolution_instance}", payload)

        if limit is None:
            return response

        if isinstance(response, list):
            return response[:limit]

        messages = response.get("messages")
        if isinstance(messages, list):
            copied = dict(response)
            copied["messages"] = messages[:limit]
            return copied

        return response

    def set_webhook(self, url: str, events: list[str], enabled: bool = True) -> dict[str, Any]:
        payload = {
            "enabled": enabled,
            "url": url,
            "webhookByEvents": self._settings.webhook_by_events,
            "webhookBase64": self._settings.webhook_base64,
            "events": events,
        }
        return self._post(f"/webhook/set/{self._settings.evolution_instance}", payload)

    def clear_webhook_bindings(self, url: str) -> dict[str, Any]:
        # Evolution API can be reset by disabling webhook and clearing event subscriptions.
        payload = {
            "enabled": False,
            "url": url,
            "webhookByEvents": self._settings.webhook_by_events,
            "webhookBase64": self._settings.webhook_base64,
            "events": [],
        }
        return self._post(f"/webhook/set/{self._settings.evolution_instance}", payload)

    def fetch_all_instances(self) -> list[dict[str, Any]]:
        """Fetch all active instances from Evolution API."""
        response = self._get("/instance/fetchInstances")
        
        if isinstance(response, list):
            return response
        
        if isinstance(response, dict) and "instances" in response:
            instances = response.get("instances")
            if isinstance(instances, list):
                return instances
        
        self._logger.warning("Unexpected response format from fetchInstances: %s", type(response))
        return []

    def set_webhook_for_instance(
        self,
        instance_name: str,
        url: str,
        events: list[str],
        enabled: bool = True,
    ) -> dict[str, Any]:
        """Set webhook for a specific instance."""
        payload = {
            "webhook": {
                "enabled": enabled,
                "url": url,
                "webhookByEvents": self._settings.webhook_by_events,
                "webhookBase64": self._settings.webhook_base64,
                "events": events,
            }
        }
        return self._post(f"/webhook/set/{instance_name}", payload)
