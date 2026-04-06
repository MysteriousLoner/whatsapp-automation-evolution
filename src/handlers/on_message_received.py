from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from src.models.session import WhatsAppSession
from src.services.query_llm import QueryLLM


logger = logging.getLogger(__name__)

GYM_INFO_FILE = Path(__file__).resolve().parents[1] / "static resources" / "information.json"

DEFAULT_TIMEZONE = "Asia/Kuala_Lumpur"


def _load_gym_info() -> dict[str, Any]:
    with GYM_INFO_FILE.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("information.json must be a JSON object")
    return data


def _current_request_time() -> datetime:
    return datetime.now(ZoneInfo(DEFAULT_TIMEZONE))


def _parse_opening_hours(opening_hours: str) -> tuple[int, int] | None:
    # Supports hour formats like "7:00AM to 10.30PM daily".
    match = re.search(
        r"(\d{1,2}[:.]\d{2}\s*[APMapm]{2})\s*to\s*(\d{1,2}[:.]\d{2}\s*[APMapm]{2})",
        opening_hours,
    )
    if not match:
        return None

    def _to_minutes(token: str) -> int:
        normalized = token.strip().upper().replace(".", ":")
        dt = datetime.strptime(normalized, "%I:%M%p")
        return dt.hour * 60 + dt.minute

    try:
        return (_to_minutes(match.group(1)), _to_minutes(match.group(2)))
    except ValueError:
        return None


def _is_gym_open(request_time: datetime, opening_hours: str) -> bool | None:
    parsed = _parse_opening_hours(opening_hours)
    if parsed is None:
        return None

    start_minutes, end_minutes = parsed
    current_minutes = request_time.hour * 60 + request_time.minute
    return start_minutes <= current_minutes <= end_minutes


def _extract_coordinates_from_maps_url(url: str) -> tuple[float, float] | None:
    # Google Maps links commonly include coordinates after '@' like '@2.714794,101.9128369'.
    match = re.search(r"@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)", url)
    if not match:
        return None

    try:
        return (float(match.group(1)), float(match.group(2)))
    except ValueError:
        return None


def _should_send_location(user_text: str) -> bool:
    normalized = user_text.lower()
    triggers = (
        "location",
        "where",
        "address",
        "map",
        "maps",
        "direction",
        "directions",
        "located",
    )
    return any(token in normalized for token in triggers)


def _build_system_prompt(
    gym_info: dict[str, Any],
    request_time: datetime,
    is_first_user_message: bool,
    is_gym_closed: bool,
) -> str:
    gym_name = str(gym_info.get("name", "Maximus Gym")).strip() or "Maximus Gym"
    opening_hours = str(gym_info.get("opening_hours", "Not provided")).strip() or "Not provided"
    location = str(gym_info.get("location", "Not provided")).strip() or "Not provided"
    facebook = str(gym_info.get("facebook", "Not provided")).strip() or "Not provided"
    price_per_entry = str(gym_info.get("price_per_entry", "Not provided")).strip() or "Not provided"
    member_price_per_month = str(gym_info.get("member_price_per_month", "Not provided")).strip() or "Not provided"
    request_time_text = request_time.strftime("%Y-%m-%d %I:%M %p (%Z)")

    first_message_rules: list[str] = []
    if is_first_user_message and is_gym_closed:
        first_message_rules.append(
            "Because this is the customer's first message and the gym is currently closed, "
            "start your reply by reminding them the gym is closed now and share opening hours. "
        )
    if is_first_user_message:
        first_message_rules.append(
            "Because this is the customer's first message, include opening hours, walk-in fee, and monthly membership fee, "
            "then ask if they want to apply for membership. "
        )
    first_message_rule_text = "".join(first_message_rules)

    return (
        f"You are a friendly and concise customer service assistant for {gym_name}. "
        "Answer only with information that is grounded in the provided gym details and conversation context. "
        "Format with proper spacing, add emojis if needed, you are using whatsapp."
        "If the customer asks something unknown, be transparent and suggest contacting the gym Facebook page. "
        "Match the customer's language from their message (English, Bahasa Melayu, or Chinese) whenever possible. "
        f"Current request time context: {request_time_text}. "
        f"Gym details: name={gym_name}; opening_hours={opening_hours}; location={location}; facebook={facebook}; "
        f"price_per_entry={price_per_entry}; member_price_per_month={member_price_per_month}. "
        f"{first_message_rule_text}"
        "Respond in valid JSON only with this schema: {\"assistant_reply\": string}."
    )


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

    if not extracted_text.strip():
        return {
            "handled": False,
            "reason": "empty_text",
            "jid": session.jid,
            "message_id": message_id,
        }
 
    allowed_jids = {
        "60122201096@s.whatsapp.net",
        "60123226431@s.whatsapp.net",
    }
    if session.jid not in allowed_jids:
        return {
            "handled": False,
            "reason": "jid_not_allowed",
            "jid": session.jid,
            "message_id": message_id,
        }
    
    logger.info("on_message_received: jid=%s message_id=%s", session.jid, message_id)
    is_first_user_message = not any(entry.get("role") == "user" for entry in session.chat_history)
    session.add_chat_entry("user", extracted_text)

    gym_info = _load_gym_info()
    request_time = _current_request_time()
    opening_hours = str(gym_info.get("opening_hours", "")).strip()
    gym_open = _is_gym_open(request_time, opening_hours)
    is_gym_closed = gym_open is False

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

    history_text = _history_as_text(session.chat_history)
    llm = QueryLLM()
    system_prompt = _build_system_prompt(
        gym_info=gym_info,
        request_time=request_time,
        is_first_user_message=is_first_user_message,
        is_gym_closed=is_gym_closed,
    )
    request_time_text = request_time.strftime("%Y-%m-%d %I:%M %p (%Z)")
    user_prompt = (
        "Conversation history:\n"
        f"{history_text}\n\n"
        "Gym information:\n"
        f"{json.dumps(gym_info, ensure_ascii=False)}\n\n"
        f"Request time context: {request_time_text}\n\n"
        "Write the best next customer-service reply based on user intent. "
        "Return strict JSON only."
    )
    llm_result = llm.query(
        user_input=user_prompt,
        system_prompt=system_prompt,
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
        assistant_reply = content.strip() if isinstance(content, str) and content.strip() else "Thanks for reaching out to Maximus Gym. How can I help you today?"

    if is_first_user_message and is_gym_closed and opening_hours:
        closed_reminder = (
            f"Quick note: Maximus Gym is currently closed now. Opening hours are {opening_hours}."
        )
        if "closed" not in assistant_reply.lower():
            assistant_reply = f"{closed_reminder} {assistant_reply}"

    if selected_property_index is not None:
        logger.debug("selected_property_index ignored for gym flow: %s", selected_property_index)

    session.send_message(assistant_reply)
    session.add_chat_entry("assistant", assistant_reply)

    if _should_send_location(extracted_text):
        gym_name = str(gym_info.get("name", "Maximus Gym")).strip() or "Maximus Gym"
        location_value = str(gym_info.get("location", "")).strip()
        coordinates = _extract_coordinates_from_maps_url(location_value)

        if coordinates is not None:
            latitude, longitude = coordinates
            try:
                session.send_location(
                    name=gym_name,
                    address=gym_name,
                    latitude=latitude,
                    longitude=longitude,
                )
            except Exception:
                logger.exception("Failed to send location pin for jid=%s", session.jid)

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
