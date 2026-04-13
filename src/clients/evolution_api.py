import logging
from collections.abc import Iterable
from typing import Any

import requests

from src.clients.event_types import WebhookEventType
from src.configs.config import Settings


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

    def _resolve_instance_name(self, instance_name: str | None = None) -> str:
        if isinstance(instance_name, str) and instance_name.strip():
            return instance_name.strip()
        return self._settings.evolution_instance

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
            response_text = None
            if isinstance(exc, requests.HTTPError) and getattr(exc, "response", None) is not None:
                response_text = exc.response.text

            if response_text:
                raise RuntimeError(f"Evolution API request failed for {endpoint}: {exc}; response={response_text}") from exc

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

    def send_message(
        self,
        number: str,
        text: str,
        instance_name: str | None = None,
        **options: Any,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "number": number,
            "text": text,
        }
        payload.update(options)
        resolved_instance = self._resolve_instance_name(instance_name)
        return self._post(f"/message/sendText/{resolved_instance}", payload)

    def send_location(
        self,
        number: str,
        name: str,
        address: str,
        latitude: float,
        longitude: float,
        instance_name: str | None = None,
        **options: Any,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "number": number,
            "name": name,
            "address": address,
            "latitude": latitude,
            "longitude": longitude,
        }
        payload.update(options)
        resolved_instance = self._resolve_instance_name(instance_name)
        return self._post(f"/message/sendLocation/{resolved_instance}", payload)

    def find_messages(
        self,
        remote_jid: str,
        limit: int | None = None,
        instance_name: str | None = None,
    ) -> Any:
        payload = {
            "where": {
                "key": {
                    "remoteJid": remote_jid,
                }
            }
        }
        resolved_instance = self._resolve_instance_name(instance_name)
        response = self._post(f"/chat/findMessages/{resolved_instance}", payload)

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

    def _serialize_webhook_events(self, events: Iterable[WebhookEventType | str]) -> list[str]:
        serialized: list[str] = []
        for event in events:
            if isinstance(event, WebhookEventType):
                serialized.append(event.value)
                continue

            if isinstance(event, str) and event.strip():
                serialized.append(event.strip().upper())

        return serialized

    def set_webhook(
        self,
        url: str,
        events: Iterable[WebhookEventType | str],
        enabled: bool = True,
    ) -> dict[str, Any]:
        payload = {
            "enabled": enabled,
            "url": url,
            "webhookByEvents": self._settings.webhook_by_events,
            "webhookBase64": self._settings.webhook_base64,
            "events": self._serialize_webhook_events(events),
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
        events: Iterable[WebhookEventType | str],
        enabled: bool = True,
    ) -> dict[str, Any]:
        """Set webhook for a specific instance."""
        payload = {
            "webhook": {
                "enabled": enabled,
                "url": url,
                "webhookByEvents": self._settings.webhook_by_events,
                "webhookBase64": self._settings.webhook_base64,
                "events": self._serialize_webhook_events(events),
            }
        }
        return self._post(f"/webhook/set/{instance_name}", payload)
