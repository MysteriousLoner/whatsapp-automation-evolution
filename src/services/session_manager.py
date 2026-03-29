import threading
from typing import Any

from src.clients.evolution_api import EvolutionApiClient
from src.models.session import WhatsAppSession


class SessionManager:
    def __init__(self, api_client: EvolutionApiClient) -> None:
        self._api_client = api_client
        self._sessions: dict[str, WhatsAppSession] = {}
        self._lock = threading.Lock()

    def create_or_update_session(self, jid: str, message_payload: dict[str, Any]) -> WhatsAppSession:
        with self._lock:
            session = self._sessions.get(jid)
            if session is None:
                session = WhatsAppSession(
                    jid=jid,
                    latest_message=message_payload,
                    api_client=self._api_client,
                    destroy_callback=self.destroy_session,
                )
                self._sessions[jid] = session
            else:
                session.update_message(message_payload)

            return session

    def get_session(self, jid: str) -> WhatsAppSession | None:
        with self._lock:
            return self._sessions.get(jid)

    def destroy_session(self, jid: str) -> bool:
        with self._lock:
            return self._sessions.pop(jid, None) is not None

    def list_sessions(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "jid": session.jid,
                    "created_at": session.created_at.isoformat(),
                    "updated_at": session.updated_at.isoformat(),
                    "latest_message": session.latest_message,
                }
                for session in self._sessions.values()
            ]
