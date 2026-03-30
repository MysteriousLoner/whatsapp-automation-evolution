from __future__ import annotations

import logging
from typing import Any

from src.models.session import WhatsAppSession


logger = logging.getLogger(__name__)


def on_message_received(
    session: WhatsAppSession,
    message_payload: dict[str, Any],
    extracted_text: str,
) -> dict[str, Any]:
    """Central entrypoint for message-received business logic."""
    key = message_payload.get("key") if isinstance(message_payload, dict) else None
    from_me = bool(key.get("fromMe")) if isinstance(key, dict) else False
    message_id = key.get("id") if isinstance(key, dict) else None

    # if from_me:
    #     return {
    #         "handled": False,
    #         "reason": "from_me",
    #         "jid": session.jid,
    #         "message_id": message_id,
    #     }

    if not extracted_text.strip():
        return {
            "handled": False,
            "reason": "empty_text",
            "jid": session.jid,
            "message_id": message_id,
        }

    # Place your custom bot logic here.
    logger.info("on_message_received: jid=%s message_id=%s", session.jid, message_id)
    session.send_message(f"Echo: {extracted_text[:100]}")  # Echo back the received text (truncated to 100 chars)

    return {
        "handled": True,
        "jid": session.jid,
        "message_id": message_id,
        "message": extracted_text,
    }
