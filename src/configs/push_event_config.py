import hashlib
import json
import logging
import time
from typing import Any, Callable

from src.clients.event_types import WebhookEventType
from src.handlers.gym_message_receiver import on_message_received as on_gym_message_received
from src.handlers.on_message_received import on_message_received
from src.services.session_manager import SessionManager


logger = logging.getLogger(__name__)

MODE_PROPERTY = "property"
MODE_GYM = "gym"
MODE_COMMANDS = {"/property": MODE_PROPERTY, "/gym": MODE_GYM}


def _mode_selection_prompt() -> str:
    return (
        "Please select a demo mode before we continue:\n"
        "- /property for Property Consultant mode\n"
        "- /gym for Gym mode\n"
        "\n"
        "You can switch anytime with /property or /gym. Send /cancel to reset session."
    )


def _normalize_command(text: str) -> str | None:
    stripped = text.strip()
    if not stripped.startswith("/"):
        return None
    return stripped.split()[0].lower()


def _extract_event(payload: dict[str, Any]) -> str | None:
    event = payload.get("event") or payload.get("type")
    if isinstance(event, str) and event.strip():
        normalized = event.strip().upper().replace(".", "_").replace("-", "_")
        return normalized
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


def _extract_instance_name(payload: dict[str, Any], session_manager: SessionManager) -> str | None:
    direct_instance = payload.get("instance")
    if isinstance(direct_instance, str) and direct_instance.strip():
        return direct_instance.strip()

    instance_id = payload.get("instanceId")
    if isinstance(instance_id, str) and instance_id.strip():
        resolved_instance = session_manager.resolve_instance_name(instance_id=instance_id.strip())
        if resolved_instance:
            return resolved_instance

    data = payload.get("data")
    if isinstance(data, dict):
        nested_instance = data.get("instance") or data.get("instanceName")
        if isinstance(nested_instance, str) and nested_instance.strip():
            return nested_instance.strip()

    return None


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


def _looks_like_self_message(message_payload: dict[str, Any], key: dict[str, Any]) -> bool:
    """Detect bot-originated events using Evolution's authoritative flag only.

    Heuristics based on source/pushName/message ID can misclassify genuine inbound user messages.
    """
    return key.get("fromMe") is True


def handle_messages_upsert(payload: dict[str, Any], session_manager: SessionManager) -> dict[str, Any]:
    message_payload = _dig_message_from_payload(payload)
    key = message_payload.get("key") if isinstance(message_payload, dict) else None

    if not isinstance(key, dict):
        logger.warning("MESSAGES_UPSERT ignored: missing message key")
        return {"handled": False, "reason": "missing_message_key"}

    # Ignore messages sent by the bot itself to prevent feedback loops.
    if _looks_like_self_message(message_payload, key):
        logger.debug(
            "MESSAGES_UPSERT ignored: self message detected (fromMe=%s source=%s pushName=%s id=%s)",
            key.get("fromMe"),
            message_payload.get("source"),
            message_payload.get("pushName"),
            key.get("id"),
        )
        return {"handled": False, "reason": "bot_sent_message"}

    raw_jid = key.get("remoteJid")
    jid = session_manager.normalize_jid(raw_jid if isinstance(raw_jid, str) else "")
    if not isinstance(jid, str) or not jid.strip():
        logger.warning("MESSAGES_UPSERT ignored: missing remoteJid")
        return {"handled": False, "reason": "missing_remote_jid"}

    message_id = key.get("id") if isinstance(key.get("id"), str) else ""
    message_timestamp = message_payload.get("messageTimestamp", 0)
    if not isinstance(message_timestamp, int):
        message_timestamp = int(message_timestamp) if isinstance(message_timestamp, (int, float)) else 0
    if message_timestamp <= 0:
        # Fall back to current unix time so logical dedupe still works.
        message_timestamp = int(time.time())

    extracted_text_temp = _extract_text(message_payload)
    fingerprint_seed = "|".join(
        [
            jid,
            str(message_timestamp),
            message_id.strip(),
            extracted_text_temp.strip(),
        ]
    )
    fingerprint = hashlib.sha1(fingerprint_seed.encode("utf-8")).hexdigest()

    logical_key_seed = "|".join(
        [
            jid,
            _normalize_command(extracted_text_temp) or "",
            extracted_text_temp.strip().lower(),
        ]
    )
    logical_key = hashlib.sha1(logical_key_seed.encode("utf-8")).hexdigest()

    logger.debug(
        "Webhook identity: raw_jid=%s remoteJidAlt=%s addressingMode=%s normalized_jid=%s msg_id=%s ts=%s source=%s status=%s text=%r fingerprint=%s logical_key=%s",
        raw_jid,
        key.get("remoteJidAlt"),
        key.get("addressingMode"),
        jid,
        message_id,
        message_timestamp,
        message_payload.get("source"),
        message_payload.get("status"),
        extracted_text_temp[:80],
        fingerprint,
        logical_key,
    )

    if session_manager.is_fingerprint_seen(fingerprint):
        logger.debug(
            "MESSAGES_UPSERT ignored: duplicate fingerprint=%s raw_jid=%s msg_id=%s",
            fingerprint,
            raw_jid,
            message_id,
        )
        return {"handled": False, "reason": "duplicate_message"}

    if session_manager.is_recent_message_key(logical_key, message_timestamp):
        logger.debug(
            "MESSAGES_UPSERT ignored: duplicate logical key=%s raw_jid=%s msg_id=%s ts=%s",
            logical_key,
            raw_jid,
            message_id,
            message_timestamp,
        )
        session_manager.mark_fingerprint_seen(fingerprint)
        return {"handled": False, "reason": "duplicate_logical_message"}

    session_manager.mark_fingerprint_seen(fingerprint)
    session_manager.remember_message_key(logical_key, message_timestamp)

    instance_name = _extract_instance_name(payload, session_manager)
    session = session_manager.create_or_update_session(
        jid.strip(),
        message_payload,
        instance_name=instance_name,
    )
    extracted_text = _extract_text(message_payload)

    logger.info(
        "Message received from %s (instance=%s): '%s' [msg_id=%s fingerprint=%s raw_jid=%s]",
        session.jid,
        session.instance_name,
        extracted_text[:100] if extracted_text else "(no text)",
        message_id,
        fingerprint,
        raw_jid,
    )

    command = _normalize_command(extracted_text)
    if command == "/cancel":
        if session.awaiting_contract_signature and session.contract_token and session.contract_store is not None:
            session.contract_store.mark_cancelled(session.contract_token)
        session.reset_state(clear_mode=True)
        cancel_message = (
            "Session cleared successfully.\n"
            "Please choose a mode to continue:\n"
            "- /property\n"
            "- /gym"
        )
        session.send_message(cancel_message)
        session.add_chat_entry("assistant", cancel_message)
        return {
            "handled": True,
            "event": WebhookEventType.MESSAGES_UPSERT.value,
            "jid": session.jid,
            "instance_name": session.instance_name,
            "state": "session_reset",
        }

    selected_mode = MODE_COMMANDS.get(command or "")
    if selected_mode is not None:
        session.reset_state(clear_mode=False)
        session.active_mode = selected_mode
        switch_message = (
            "Switched to Property Consultant mode. Ask me your preferred area and budget."
            if selected_mode == MODE_PROPERTY
            else "Switched to Gym mode. Ask me anything about the gym services, fees, or location."
        )
        session.send_message(switch_message)
        session.add_chat_entry("assistant", switch_message)
        return {
            "handled": True,
            "event": WebhookEventType.MESSAGES_UPSERT.value,
            "jid": session.jid,
            "instance_name": session.instance_name,
            "state": f"mode_switched_{selected_mode}",
            "mode": selected_mode,
        }

    if session.active_mode is None:
        prompt = _mode_selection_prompt()
        session.send_message(prompt)
        session.add_chat_entry("assistant", prompt)
        return {
            "handled": True,
            "event": WebhookEventType.MESSAGES_UPSERT.value,
            "jid": session.jid,
            "instance_name": session.instance_name,
            "state": "mode_selection_required",
        }

    try:
        handler = on_message_received if session.active_mode == MODE_PROPERTY else on_gym_message_received
        logic_result = handler(session=session, message_payload=message_payload, extracted_text=extracted_text)
    except Exception:
        logger.exception("Error while running on_message_received for jid=%s", session.jid)
        return {
            "handled": False,
            "event": WebhookEventType.MESSAGES_UPSERT.value,
            "reason": "handler_exception",
            "jid": session.jid,
            "instance_name": session.instance_name,
        }

    if not logic_result.get("handled"):
        return {
            "handled": False,
            "event": WebhookEventType.MESSAGES_UPSERT.value,
            **logic_result,
        }

    return {
        "handled": True,
        "event": WebhookEventType.MESSAGES_UPSERT.value,
        "jid": session.jid,
        "instance_name": session.instance_name,
        "message": extracted_text,
        "mode": session.active_mode,
        **logic_result,
    }


EVENT_HANDLERS: dict[WebhookEventType, Callable[[dict[str, Any], SessionManager], dict[str, Any]]] = {
    WebhookEventType.MESSAGES_UPSERT: handle_messages_upsert,
}


def enabled_events() -> list[str]:
    return sorted(event_type.value for event_type in EVENT_HANDLERS.keys())


def dispatch_event(payload: dict[str, Any], session_manager: SessionManager) -> dict[str, Any]:
    event = _extract_event(payload)
    if event is None:
        return {"handled": False, "reason": "missing_event"}

    event_type = WebhookEventType.from_raw(event)
    if event_type is None:
        logger.info("Ignoring unmapped webhook event: %s", event)
        return {"handled": False, "reason": "unmapped_event", "event": event}

    handler = EVENT_HANDLERS.get(event_type)
    if handler is None:
        logger.info("Ignoring unhandled webhook event: %s", event_type.value)
        return {"handled": False, "reason": "unmapped_event", "event": event_type.value}

    return handler(payload, session_manager)
