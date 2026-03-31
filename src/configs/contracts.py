from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from flask import Blueprint, Response, request

from src.services.session_manager import SessionManager


CONTRACT_PUBLIC_BASE_URL = "http://localhost:8081"


def _build_contract_html(
    token: str,
    jid: str,
    property_data: dict[str, Any],
    webhook_public_url: str,
    error: str | None = None,
) -> str:
    facilities = property_data.get("facilities", []) if isinstance(property_data, dict) else []
    not_allowed = property_data.get("not_allowed", []) if isinstance(property_data, dict) else []
    facilities_html = "".join(f"<li>{item}</li>" for item in facilities)
    not_allowed_html = "".join(f"<li>{item}</li>" for item in not_allowed)
    sign_action = f"{CONTRACT_PUBLIC_BASE_URL}/contract/{token}/sign"

    error_html = f"<p style='color: #b42318;'><strong>{error}</strong></p>" if error else ""

    return f"""
<!doctype html>
<html lang='en'>
<head>
  <meta charset='utf-8'>
  <meta name='viewport' content='width=device-width, initial-scale=1'>
  <title>Property Booking Contract</title>
</head>
<body style='font-family: Arial, sans-serif; max-width: 780px; margin: 2rem auto; line-height: 1.5;'>
  <h1>Property Booking Contract</h1>
  <p><strong>Session JID:</strong> {jid}</p>
  <h2>Selected Property</h2>
  <p><strong>Location:</strong> {property_data.get('location', '-')}</p>
  <p><strong>Address:</strong> {property_data.get('address', '-')}</p>
  <p><strong>Monthly Rent:</strong> RM {property_data.get('price_per_month_myr', '-')}</p>
  <p><strong>Type:</strong> {property_data.get('property_type', '-')}</p>
  <p><strong>Owner Remarks:</strong> {property_data.get('owner_remarks', '-')}</p>

  <h3>Facilities</h3>
  <ul>{facilities_html or '<li>Not specified</li>'}</ul>

  <h3>Not Allowed (Owner Red Lines)</h3>
  <ul>{not_allowed_html or '<li>Not specified</li>'}</ul>

  <hr>
  {error_html}
  <form method='post' action='{sign_action}'>
    <label for='signer_name'><strong>Full Name</strong></label><br>
    <input id='signer_name' name='signer_name' required style='width: 100%; padding: 8px; margin: 8px 0 12px;'>

    <label>
      <input type='checkbox' name='agree' value='yes' required>
      I confirm that I agree to the above terms and owner red lines.
    </label><br><br>

    <button type='submit' style='padding: 10px 14px;'>Sign and Confirm Booking</button>
  </form>
</body>
</html>
"""


def create_contract_blueprint(session_manager: SessionManager, webhook_public_url: str) -> Blueprint:
    contract_bp = Blueprint("contract", __name__)

    @contract_bp.get("/contract/<token>")
    def view_contract(token: str) -> Response:
        session = session_manager.get_session_by_contract_token(token)
        if session is None or session.selected_property is None:
            return Response("Contract session not found or expired.", status=404, mimetype="text/plain")

        html = _build_contract_html(
            token=token,
            jid=session.jid,
            property_data=session.selected_property,
            webhook_public_url=webhook_public_url,
        )
        return Response(html, mimetype="text/html")

    @contract_bp.post("/contract/<token>/sign")
    def sign_contract(token: str) -> Response:
        session = session_manager.get_session_by_contract_token(token)
        if session is None or session.selected_property is None:
            return Response("Contract session not found or expired.", status=404, mimetype="text/plain")

        signer_name = (request.form.get("signer_name") or "").strip()
        agreed = (request.form.get("agree") or "").strip().lower() == "yes"

        if not signer_name or not agreed:
            html = _build_contract_html(
                token=token,
                jid=session.jid,
                property_data=session.selected_property,
                webhook_public_url=webhook_public_url,
                error="Please provide your name and accept the terms before signing.",
            )
            return Response(html, status=400, mimetype="text/html")

        session.signed_by = signer_name
        session.awaiting_contract_signature = False
        signed_at = datetime.now(timezone.utc).isoformat()
        property_address = session.selected_property.get("address", "the selected property")

        session.send_message(
            f"Booking confirmed for {property_address}. "
            f"Signed by {signer_name} at {signed_at}. Our team will contact you shortly."
        )
        session.destroy()

        return Response(
            "Booking confirmed successfully. You may close this page.",
            mimetype="text/plain",
        )

    return contract_bp
