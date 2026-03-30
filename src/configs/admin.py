from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, jsonify, request

from src.services.session_manager import SessionManager


logger = logging.getLogger(__name__)


def _is_authorized(header_value: str | None, expected_key: str) -> bool:
    if not header_value:
        return False
    return header_value.strip() == expected_key


def create_admin_blueprint(
    session_manager: SessionManager,
    auth_key: str,
) -> Blueprint:
    admin_bp = Blueprint("admin", __name__)

    @admin_bp.get("/admin/sessions")
    def list_sessions() -> tuple[Any, int]:
        provided_key = request.headers.get("apikey") or request.headers.get("x-api-key")
        if not _is_authorized(provided_key, auth_key):
            return jsonify({"ok": False, "error": "Unauthorized"}), 401

        return jsonify({"ok": True, "sessions": session_manager.list_sessions()}), 200

    @admin_bp.delete("/admin/sessions/<path:jid>")
    def destroy_session(jid: str) -> tuple[Any, int]:
        provided_key = request.headers.get("apikey") or request.headers.get("x-api-key")
        if not _is_authorized(provided_key, auth_key):
            return jsonify({"ok": False, "error": "Unauthorized"}), 401

        removed = session_manager.destroy_session(jid)
        if not removed:
            return jsonify({"ok": False, "error": "Session not found", "jid": jid}), 404

        return jsonify({"ok": True, "jid": jid, "destroyed": True}), 200

    return admin_bp
