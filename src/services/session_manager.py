import threading
from typing import Any

from src.clients.evolution_api import EvolutionApiClient
from src.models.session import WhatsAppSession
from src.services.contract_store import ContractStore


class SessionManager:
    def __init__(
        self,
        api_client: EvolutionApiClient,
        contract_base_url: str,
        contract_store: ContractStore,
    ) -> None:
        self._api_client = api_client
        self._contract_base_url = contract_base_url
        self._contract_store = contract_store
        self._sessions: dict[str, WhatsAppSession] = {}
        self._lock = threading.Lock()
        self._processed_message_ids: set[str] = set()  # Global set of processed message IDs to handle JID variants

    def create_or_update_session(
        self,
        jid: str,
        message_payload: dict[str, Any],
        instance_name: str | None = None,
    ) -> WhatsAppSession:
        with self._lock:
            session = self._sessions.get(jid)
            if session is None:
                session = WhatsAppSession(
                    jid=jid,
                    latest_message=message_payload,
                    api_client=self._api_client,
                    instance_name=instance_name.strip() if instance_name and instance_name.strip() else None,
                    destroy_callback=self.destroy_session,
                    contract_base_url=self._contract_base_url,
                    contract_store=self._contract_store,
                )
                self._sessions[jid] = session
            else:
                session.update_message(message_payload, instance_name=instance_name)

            return session

    def get_session(self, jid: str) -> WhatsAppSession | None:
        with self._lock:
            return self._sessions.get(jid)

    def get_session_by_contract_token(self, token: str) -> WhatsAppSession | None:
        with self._lock:
            for session in self._sessions.values():
                if session.contract_token == token:
                    return session
            return None

    def resolve_instance_name(
        self,
        instance_id: str | None = None,
        instance_name: str | None = None,
    ) -> str | None:
        if isinstance(instance_name, str) and instance_name.strip():
            return instance_name.strip()

        if not isinstance(instance_id, str) or not instance_id.strip():
            return None

        try:
            instances = self._api_client.fetch_all_instances()
        except Exception:
            return None

        for instance in instances:
            if not isinstance(instance, dict):
                continue

            candidate_id = instance.get("id") or instance.get("instanceId")
            candidate_name = instance.get("name") or instance.get("instanceName")
            if candidate_id == instance_id and isinstance(candidate_name, str) and candidate_name.strip():
                return candidate_name.strip()

        return None

    def destroy_session(self, jid: str) -> bool:
        with self._lock:
            return self._sessions.pop(jid, None) is not None

    def list_sessions(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "jid": session.jid,
                    "instance_name": session.instance_name,
                    "chat_history_count": len(session.chat_history),
                    "active_mode": session.active_mode,
                    "awaiting_contract_signature": session.awaiting_contract_signature,
                    "contract_token": session.contract_token,
                    "selected_property": session.selected_property,
                    "created_at": session.created_at.isoformat(),
                    "updated_at": session.updated_at.isoformat(),
                    "latest_message": session.latest_message,
                }
                for session in self._sessions.values()
            ]

    @property
    def contract_store(self) -> ContractStore:
        return self._contract_store

    def is_message_already_processed(self, jid: str, message_id: str) -> bool:
        """Check if a message with this ID has already been processed (globally)."""
        with self._lock:
            return message_id in self._processed_message_ids

    def mark_message_as_processed(self, jid: str, message_id: str) -> None:
        """Mark a message as processed to prevent duplicate handling (globally)."""
        with self._lock:
            self._processed_message_ids.add(message_id)
            # Keep set bounded to ~10k recent messages to prevent unbounded memory growth
            if len(self._processed_message_ids) > 10000:
                # Remove oldest items (simple approach: clear and continue)
                # In production, use a deque or LRU cache for better O(1) removal
                self._processed_message_ids.clear()
