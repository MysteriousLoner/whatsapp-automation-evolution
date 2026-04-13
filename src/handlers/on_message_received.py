from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.models.session import WhatsAppSession
from src.services.query_llm import QueryLLM


logger = logging.getLogger(__name__)

UNITS_FILE = Path(__file__).resolve().parents[1] / "static resources" / "units.json"

SYSTEM_PROMPT = (
    "You are a Malaysian property rental assistant. "
    "Your job is to understand the client's needs and recommend the most suitable property from the provided units data. "
    "Always highlight owner red lines from the property's not_allowed field before confirmation. "
    "When user clearly confirms a property choice, set client_confirmed=true. "
    "Respond in valid JSON only with keys: assistant_reply (string), selected_property_index (integer or null), client_confirmed (boolean)."
    "always stir the conversation back to the topic of rental if the user is going off topics."
)


def _load_units() -> list[dict[str, Any]]:
    with UNITS_FILE.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("units.json must be a JSON array")
    return [item for item in data if isinstance(item, dict)]


def _history_as_text(history: list[dict[str, str]]) -> str:
    lines: list[str] = []
    for item in history:
        role = item.get("role", "unknown")
        content = item.get("content", "")
        lines.append(f"{role.upper()}: {content}")
    return "\n".join(lines)


def _parse_llm_json(content: str) -> dict[str, Any] | None:
    content = content.strip()
    if not content:
        return None

    try:
        parsed = json.loads(content)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    if "```" in content:
        blocks = content.split("```")
        for block in blocks:
            cleaned = block.strip()
            if cleaned.startswith("json"):
                cleaned = cleaned[4:].strip()
            if not cleaned:
                continue
            try:
                parsed = json.loads(cleaned)
                return parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                continue

    return None


def _build_contract_url(token: str) -> str:
    return f"http://localhost:8080/contract/{token}"


def on_message_received(
    session: WhatsAppSession,
    message_payload: dict[str, Any],
    extracted_text: str,
) -> dict[str, Any]:
    """Central entrypoint for message-received business logic."""
    key = message_payload.get("key") if isinstance(message_payload, dict) else None
    from_me = bool(key.get("fromMe")) if isinstance(key, dict) else False
    message_id = key.get("id") if isinstance(key, dict) else None

    # Keep processing even when fromMe is true because some deployments
    # (for example self-chat or mirrored device flows) still need automation.

    allowed_jids = {
        "60146600828@s.whatsapp.net",
        "60123226431@s.whatsapp.net",
    }
    if session.jid not in allowed_jids:
        return {
            "handled": False,
            "reason": "jid_not_allowed",
            "jid": session.jid,
            "message_id": message_id,
        }

    if not extracted_text.strip():
        return {
            "handled": False,
            "reason": "empty_text",
            "jid": session.jid,
            "message_id": message_id,
        }
    
    logger.info("on_message_received: jid=%s message_id=%s", session.jid, message_id)
    session.add_chat_entry("user", extracted_text)

    if session.awaiting_contract_signature and session.contract_token:
        contract_url = _build_contract_url(session.contract_token)
        reminder = (
            "Your selected property is pending signature. "
            f"Please complete the contract here: {contract_url}"
        )
        session.send_message(reminder)
        session.add_chat_entry("assistant", reminder)
        return {
            "handled": True,
            "jid": session.jid,
            "message_id": message_id,
            "message": extracted_text,
            "state": "awaiting_signature",
        }

    units = _load_units()
    history_text = _history_as_text(session.chat_history)

    llm = QueryLLM()
    user_prompt = (
        "Conversation history:\n"
        f"{history_text}\n\n"
        "Units data:\n"
        f"{json.dumps(units, ensure_ascii=False)}\n\n"
        "Decide the best next assistant reply based on user intent. "
        "Return strict JSON only."
    )
    llm_result = llm.query(
        user_input=user_prompt,
        system_prompt=SYSTEM_PROMPT,
        temperature=0.2,
        max_tokens=500,
    )

    if not llm_result.get("ok"):
        error_reply = "I could not process your request at the moment. Please try again shortly."
        session.send_message(error_reply)
        session.add_chat_entry("assistant", error_reply)
        return {
            "handled": False,
            "reason": "llm_error",
            "jid": session.jid,
            "message_id": message_id,
        }

    content = llm_result.get("content")
    parsed = _parse_llm_json(content) if isinstance(content, str) else None

    assistant_reply = ""
    selected_property_index: int | None = None
    client_confirmed = False

    if parsed is not None:
        reply_value = parsed.get("assistant_reply")
        if isinstance(reply_value, str):
            assistant_reply = reply_value.strip()

        selected_raw = parsed.get("selected_property_index")
        if isinstance(selected_raw, int):
            selected_property_index = selected_raw

        confirmed_raw = parsed.get("client_confirmed")
        if isinstance(confirmed_raw, bool):
            client_confirmed = confirmed_raw

    if not assistant_reply:
        assistant_reply = content.strip() if isinstance(content, str) and content.strip() else "Could you share more details about your preferred location and budget?"

    if selected_property_index is not None and 0 <= selected_property_index < len(units):
        session.selected_property = units[selected_property_index]

    session.send_message(assistant_reply)
    session.add_chat_entry("assistant", assistant_reply)

    if client_confirmed and session.selected_property is not None:
        session.contract_token = session.contract_token or uuid4().hex
        session.awaiting_contract_signature = True

        not_allowed = session.selected_property.get("not_allowed", [])
        red_lines = ", ".join(not_allowed) if isinstance(not_allowed, list) else "Not specified"
        contract_url = _build_contract_url(session.contract_token)
        contract_message = (
            "Great, I have locked your selected property. "
            f"Owner red lines (not allowed): {red_lines}. "
            f"Please review and sign your booking contract here: {contract_url}"
        )
        session.send_message(contract_message)
        session.add_chat_entry("assistant", contract_message)

        return {
            "handled": True,
            "jid": session.jid,
            "message_id": message_id,
            "message": extracted_text,
            "state": "awaiting_signature",
            "selected_property": session.selected_property,
            "contract_url": contract_url,
        }

    return {
        "handled": True,
        "jid": session.jid,
        "message_id": message_id,
        "message": extracted_text,
        "state": "conversation_active",
    }