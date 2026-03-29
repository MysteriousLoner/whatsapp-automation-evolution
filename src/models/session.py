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
    destroy_callback: Callable[[str], bool] | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def update_message(self, message_payload: dict[str, Any]) -> None:
        self.latest_message = message_payload
        self.updated_at = datetime.now(timezone.utc)

    def get_chat_history(self, limit: int | None = None) -> Any:
        return self.api_client.find_messages(self.jid, limit=limit)

    def send_message(self, text: str, **options: Any) -> dict[str, Any]:
        return self.api_client.send_message(self.jid, text, **options)

    def destroy(self) -> bool:
        if self.destroy_callback is None:
            return False
        return self.destroy_callback(self.jid)
