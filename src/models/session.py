from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from src.clients.evolution_api import EvolutionApiClient


@dataclass
class WhatsAppSession:
    jid: str
    latest_message: dict[str, Any]
    api_client: EvolutionApiClient
    instance_name: str | None = None
    destroy_callback: Callable[[str], bool] | None = None
    chat_history: list[dict[str, str]] = field(default_factory=list)
    selected_property: dict[str, Any] | None = None
    awaiting_contract_signature: bool = False
    contract_token: str | None = None
    signed_by: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def update_message(self, message_payload: dict[str, Any], instance_name: str | None = None) -> None:
        self.latest_message = message_payload
        if instance_name and instance_name.strip():
            self.instance_name = instance_name.strip()
        self.updated_at = datetime.now(timezone.utc)

    def get_chat_history(self, limit: int | None = None, instance_name: str | None = None) -> Any:
        resolved_instance = instance_name if instance_name else self.instance_name
        return self.api_client.find_messages(self.jid, limit=limit, instance_name=resolved_instance)

    def send_message(self, text: str, **options: Any) -> dict[str, Any]:
        resolved_instance = options.pop("instance_name", self.instance_name)
        return self.api_client.send_message(self.jid, text, instance_name=resolved_instance, **options)

    def add_chat_entry(self, role: str, content: str) -> None:
        self.chat_history.append({"role": role, "content": content})
        self.updated_at = datetime.now(timezone.utc)

    def destroy(self) -> bool:
        if self.destroy_callback is None:
            return False
        return self.destroy_callback(self.jid)
