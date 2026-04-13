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


def _resolve_api_key(expected_key: str) -> str | None:
    from flask import request

    return (
        request.headers.get("apikey")
        or request.headers.get("x-api-key")
        or request.args.get("apikey")
    )


def create_admin_blueprint(
    session_manager: SessionManager,
    auth_key: str,
) -> Blueprint:
    admin_bp = Blueprint("admin", __name__)

    @admin_bp.get("/admin/sessions")
    def list_sessions() -> tuple[Any, int]:
        provided_key = _resolve_api_key(auth_key)
        if not _is_authorized(provided_key, auth_key):
            return jsonify({"ok": False, "error": "Unauthorized"}), 401

        return jsonify({"ok": True, "sessions": session_manager.list_sessions()}), 200

    @admin_bp.delete("/admin/sessions/<path:jid>")
    def destroy_session(jid: str) -> tuple[Any, int]:
        provided_key = _resolve_api_key(auth_key)
        if not _is_authorized(provided_key, auth_key):
            return jsonify({"ok": False, "error": "Unauthorized"}), 401

        removed = session_manager.destroy_session(jid)
        if not removed:
            return jsonify({"ok": False, "error": "Session not found", "jid": jid}), 404

        return jsonify({"ok": True, "jid": jid, "destroyed": True}), 200

        @admin_bp.get("/admin/contracts")
        def contracts_dashboard() -> tuple[str, int]:
                provided_key = _resolve_api_key(auth_key)
                if not _is_authorized(provided_key, auth_key):
                        return ("Unauthorized", 401)

                html = """
<!doctype html>
<html lang='en'>
<head>
    <meta charset='utf-8'>
    <meta name='viewport' content='width=device-width, initial-scale=1'>
    <title>Contracts Dashboard</title>
    <style>
        :root {
            --bg: #f6f8fb;
            --surface: #ffffff;
            --text: #1f2937;
            --muted: #6b7280;
            --border: #dfe4ea;
            --pending: #b45309;
            --signed: #047857;
            --cancelled: #b91c1c;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: linear-gradient(180deg, #eef3ff 0%, var(--bg) 55%);
            color: var(--text);
            margin: 0;
            padding: 20px;
        }

        .container {
            max-width: 1100px;
            margin: 0 auto;
        }

        .card {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 14px;
            padding: 16px;
            box-shadow: 0 10px 30px rgba(15, 23, 42, 0.08);
        }

        h1 {
            margin: 0 0 8px;
            font-size: 28px;
        }

        .meta {
            color: var(--muted);
            margin-bottom: 14px;
            font-size: 14px;
        }

        .controls {
            display: flex;
            gap: 8px;
            margin-bottom: 12px;
            flex-wrap: wrap;
        }

        button {
            border: 1px solid var(--border);
            background: #fff;
            border-radius: 8px;
            padding: 8px 12px;
            cursor: pointer;
            font-weight: 600;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 14px;
        }

        th, td {
            border-bottom: 1px solid var(--border);
            text-align: left;
            padding: 10px 8px;
            vertical-align: top;
        }

        th {
            color: var(--muted);
            font-weight: 600;
            white-space: nowrap;
        }

        .badge {
            display: inline-block;
            border-radius: 999px;
            padding: 2px 10px;
            font-size: 12px;
            font-weight: 700;
            background: #f3f4f6;
        }

        .pending { color: var(--pending); }
        .signed { color: var(--signed); }
        .cancelled { color: var(--cancelled); }

        .token { font-family: Menlo, Monaco, monospace; font-size: 12px; }

        @media (max-width: 900px) {
            table { font-size: 12px; }
            .hide-mobile { display: none; }
        }
    </style>
</head>
<body>
    <div class='container'>
        <div class='card'>
            <h1>Contracts Dashboard</h1>
            <div class='meta'>Live view of pending/signed/cancelled contracts.</div>
            <div class='controls'>
                <button id='refreshBtn' type='button'>Refresh</button>
                <button id='autoBtn' type='button'>Auto Refresh: Off</button>
            </div>
            <div style='overflow-x:auto;'>
                <table>
                    <thead>
                        <tr>
                            <th>Status</th>
                            <th>Mode</th>
                            <th>JID</th>
                            <th class='hide-mobile'>Address</th>
                            <th class='hide-mobile'>Signer</th>
                            <th class='hide-mobile'>Signed At</th>
                            <th>Link</th>
                            <th>Token</th>
                        </tr>
                    </thead>
                    <tbody id='contractsBody'></tbody>
                </table>
            </div>
        </div>
    </div>

    <script>
        const bodyEl = document.getElementById('contractsBody');
        const refreshBtn = document.getElementById('refreshBtn');
        const autoBtn = document.getElementById('autoBtn');
        let timer = null;

        function fmt(value) {
            return value ? String(value) : '-';
        }

        function statusClass(status) {
            if (status === 'signed') return 'signed';
            if (status === 'cancelled') return 'cancelled';
            return 'pending';
        }

        async function loadContracts() {
            const response = await fetch('/admin/contracts/data' + window.location.search);
            const data = await response.json();
            if (!data.ok) {
                bodyEl.innerHTML = '<tr><td colspan="8">Failed to load contracts.</td></tr>';
                return;
            }

            const rows = data.contracts || [];
            if (!rows.length) {
                bodyEl.innerHTML = '<tr><td colspan="8">No contracts found.</td></tr>';
                return;
            }

            bodyEl.innerHTML = rows.map((item) => {
                const sClass = statusClass(item.status);
                const url = fmt(item.contract_url);
                const token = fmt(item.token);
                return `
                    <tr>
                        <td><span class="badge ${sClass}">${fmt(item.status)}</span></td>
                        <td>${fmt(item.mode)}</td>
                        <td>${fmt(item.jid)}</td>
                        <td class="hide-mobile">${fmt(item.property_address)}</td>
                        <td class="hide-mobile">${fmt(item.signed_by)}</td>
                        <td class="hide-mobile">${fmt(item.signed_at)}</td>
                        <td>${url === '-' ? '-' : `<a href="${url}" target="_blank" rel="noopener">open</a>`}</td>
                        <td class="token">${token}</td>
                    </tr>
                `;
            }).join('');
        }

        refreshBtn.addEventListener('click', () => { loadContracts(); });
        autoBtn.addEventListener('click', () => {
            if (timer) {
                clearInterval(timer);
                timer = null;
                autoBtn.textContent = 'Auto Refresh: Off';
            } else {
                timer = setInterval(loadContracts, 5000);
                autoBtn.textContent = 'Auto Refresh: On';
            }
        });

        loadContracts();
    </script>
</body>
</html>
                """
                return html, 200

        @admin_bp.get("/admin/contracts/data")
        def list_contracts() -> tuple[Any, int]:
                provided_key = _resolve_api_key(auth_key)
                if not _is_authorized(provided_key, auth_key):
                        return jsonify({"ok": False, "error": "Unauthorized"}), 401

                contracts = session_manager.contract_store.list_contracts(limit=300)
                return jsonify({"ok": True, "contracts": contracts}), 200

    return admin_bp
