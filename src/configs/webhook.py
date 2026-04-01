from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, jsonify, request

from src.configs.push_event_config import dispatch_event
from src.middleware.server_uptime_filter import should_skip_processing
from src.services.session_manager import SessionManager


logger = logging.getLogger(__name__)


def _is_authorized(header_value: str | None, expected_key: str) -> bool:
    if not header_value:
        return False
    return header_value.strip() == expected_key


def create_webhook_blueprint(session_manager: SessionManager, auth_key: str) -> Blueprint:
    webhook_bp = Blueprint("webhook", __name__)

    @webhook_bp.post("/webhook")
    def receive_webhook() -> tuple[Any, int]:
        logger.debug("Webhook request received from %s", request.remote_addr)
        logger.debug("Request headers: %s", dict(request.headers))
        
        # Check if request was made before server start time
        if should_skip_processing():
            logger.debug("Webhook request skipped: message received before server startup")
            return jsonify({"ok": True, "result": {"handled": False, "reason": "message_before_server_start"}}), 200
        
        # Note: API key is NOT required for webhook receipts since the webhook URL registration
        # itself is authenticated. Once registered, any requests to this URL are trusted.
        # Uncomment below if you want to enforce per-request API key validation.
        # provided_key = request.headers.get("apikey") or request.headers.get("x-api-key")
        # if not _is_authorized(provided_key, auth_key):
        #     logger.warning("Webhook request rejected: unauthorized (missing or invalid API key)")
        #     return jsonify({"ok": False, "error": "Unauthorized"}), 401

        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            logger.warning("Webhook request rejected: invalid JSON payload (not a dict)")
            return jsonify({"ok": False, "error": "Invalid JSON payload"}), 400

        logger.debug("Webhook payload event/type: event=%s, type=%s", payload.get("event"), payload.get("type"))
        
        result = dispatch_event(payload, session_manager)
        if result.get("handled"):
            logger.info(
                "Webhook received and processed: event=%s, jid=%s",
                result.get("event"),
                result.get("jid"),
            )
            return jsonify({"ok": True, "result": result}), 200

        logger.debug("Webhook received but not handled: %s", result)
        return jsonify({"ok": True, "result": result}), 200

    return webhook_bp
