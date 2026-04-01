"""Middleware to filter webhook requests made before server start time.

Prevents Evolution API's backlog flush from triggering unwanted automation
when the server restarts. Only processes messages received after server startup.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from flask import Flask, request


logger = logging.getLogger(__name__)


# Server start timestamp (Unix seconds)
_SERVER_START_TIME: float | None = None


def init_server_uptime_filter(app: Flask) -> None:
	"""Initialize server uptime tracking and register the before_request hook.
	
	Call this after creating the Flask app but before registering routes.
	"""
	global _SERVER_START_TIME
	_SERVER_START_TIME = time.time()
	logger.info("Server started at Unix timestamp: %.2f", _SERVER_START_TIME)

	@app.before_request
	def check_request_uptime() -> None:
		"""Filter webhook requests made before server start time."""
		if request.method != "POST" or request.path != "/webhook":
			return

		payload = request.get_json(silent=True) or {}
		if not isinstance(payload, dict):
			return

		# Extract message timestamp from payload
		message_timestamp_ms = _extract_message_timestamp_ms(payload)
		if message_timestamp_ms is None:
			logger.debug(
				"Webhook request has no detectable timestamp; processing anyway. payload keys: %s",
				list(payload.keys()),
			)
			return

		message_timestamp_s = message_timestamp_ms / 1000.0
		if _SERVER_START_TIME is None:
			logger.warning("Server start time not initialized; allowing request")
			return

		if message_timestamp_s < _SERVER_START_TIME:
			logger.info(
				"Ignoring webhook request made before server start. "
				"Message time: %.2f, Server start: %.2f (delta: %.2f seconds)",
				message_timestamp_s,
				_SERVER_START_TIME,
				_SERVER_START_TIME - message_timestamp_s,
			)
			# Store a flag on the request object so handlers can skip processing
			request.skip_processing = True
		else:
			logger.debug(
				"Webhook request is after server start. "
				"Message time: %.2f, Server start: %.2f (delta: %.2f seconds)",
				message_timestamp_s,
				_SERVER_START_TIME,
				message_timestamp_s - _SERVER_START_TIME,
			)


def _extract_message_timestamp_ms(payload: dict[str, Any]) -> int | None:
	"""Extract message timestamp (in milliseconds) from Evolution API webhook payload.
	
	Looks for messageTimestamp in payload.data, which is in Unix seconds.
	Converts to milliseconds for internal consistency.
	"""
	# Try payload.data (most common location for Evolution API messages.upsert)
	data = payload.get("data")
	if isinstance(data, dict):
		# messageTimestamp is in seconds in Evolution API
		timestamp_s = data.get("messageTimestamp")
		if isinstance(timestamp_s, (int, float, str)) and str(timestamp_s).strip():
			try:
				timestamp_s_float = float(timestamp_s)
				if timestamp_s_float > 0:
					# Convert seconds to milliseconds
					return int(timestamp_s_float * 1000)
			except (ValueError, TypeError):
				pass

	return None


def should_skip_processing() -> bool:
	"""Check if current request should be skipped due to uptime filter.
	
	Use this in handlers to conditionally skip processing.
	Example:
		if should_skip_processing():
			return {"handled": False, "reason": "message_before_server_start"}
	"""
	return getattr(request, "skip_processing", False)
