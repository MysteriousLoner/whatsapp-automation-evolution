import logging
from typing import Any, Callable

from src.services.session_manager import SessionManager


logger = logging.getLogger(__name__)


def _extract_event(payload: dict[str, Any]) -> str | None:
    event = payload.get("event") or payload.get("type")
    if isinstance(event, str) and event.strip():
        return event.strip().upper()
    return None


def _dig_message_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    candidates: list[Any] = []

    data = payload.get("data")
    if isinstance(data, dict):
        candidates.append(data)
    elif isinstance(data, list):
        candidates.extend(item for item in data if isinstance(item, dict))

    if isinstance(payload.get("message"), dict):
        candidates.append(payload["message"])

    candidates.append(payload)

    for candidate in candidates:
        key = candidate.get("key")
        if isinstance(key, dict) and isinstance(key.get("remoteJid"), str):
            return candidate

    return {}


def _extract_text(message_payload: dict[str, Any]) -> str:
    message = message_payload.get("message")
    if not isinstance(message, dict):
        return ""

    if isinstance(message.get("conversation"), str):
        return message["conversation"]

    extended = message.get("extendedTextMessage")
    if isinstance(extended, dict) and isinstance(extended.get("text"), str):
        return extended["text"]

    image = message.get("imageMessage")
    if isinstance(image, dict) and isinstance(image.get("caption"), str):
        return image["caption"]

    return ""


def handle_messages_upsert(payload: dict[str, Any], session_manager: SessionManager) -> dict[str, Any]:
    message_payload = _dig_message_from_payload(payload)
    key = message_payload.get("key") if isinstance(message_payload, dict) else None

    if not isinstance(key, dict):
        logger.warning("MESSAGES_UPSERT ignored: missing message key")
        return {"handled": False, "reason": "missing_message_key"}

    jid = key.get("remoteJid")
    if not isinstance(jid, str) or not jid.strip():
        logger.warning("MESSAGES_UPSERT ignored: missing remoteJid")
        return {"handled": False, "reason": "missing_remote_jid"}

    session = session_manager.create_or_update_session(jid.strip(), message_payload)
    extracted_text = _extract_text(message_payload)

    logger.info(
        "Message received from %s: '%s'",
        session.jid,
        extracted_text[:100] if extracted_text else "(no text)",
    )

    return {
        "handled": True,
        "event": "MESSAGES_UPSERT",
        "jid": session.jid,
        "message": extracted_text,
    }


EVENT_HANDLERS: dict[str, Callable[[dict[str, Any], SessionManager], dict[str, Any]]] = {
    "MESSAGES_UPSERT": handle_messages_upsert,
}


def enabled_events() -> list[str]:
    return sorted(EVENT_HANDLERS.keys())


def dispatch_event(payload: dict[str, Any], session_manager: SessionManager) -> dict[str, Any]:
    event = _extract_event(payload)
    if event is None:
        return {"handled": False, "reason": "missing_event"}

    handler = EVENT_HANDLERS.get(event)
    if handler is None:
        logger.info("Ignoring unmapped webhook event: %s", event)
        return {"handled": False, "reason": "unmapped_event", "event": event}

    return handler(payload, session_manager)
