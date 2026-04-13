import logging
import threading
import time
from typing import Any

from flask import Flask, jsonify, request

from src.clients.evolution_api import EvolutionApiClient
from src.clients.event_types import WebhookEventType
from src.configs.admin import create_admin_blueprint
from src.configs.config import build_webhook_callback_url, load_settings
from src.configs.contracts import create_contract_blueprint
from src.configs.push_event_config import enabled_events
from src.configs.webhook import create_webhook_blueprint
from src.middleware.server_uptime_filter import init_server_uptime_filter
from src.services.contract_store import ContractStore
from src.services.session_manager import SessionManager


logger = logging.getLogger(__name__)


def sync_webhooks_for_all_instances(
	api_client: EvolutionApiClient,
	callback_url: str,
	events: list[WebhookEventType | str],
) -> dict[str, Any]:
	"""Fetch all instances and bind webhooks to each one."""
	event_names = [event.value if isinstance(event, WebhookEventType) else str(event) for event in events]
	try:
		instances = api_client.fetch_all_instances()
		logger.debug("Fetched %d instances", len(instances))
	except Exception as exc:
		logger.exception("Failed to fetch instances")
		return {
			"success": False,
			"error": f"Failed to fetch instances: {exc}",
		}

	results = []
	for instance_item in instances:
		# The API returns instances directly (not wrapped in {"instance": {...}})
		instance = instance_item if isinstance(instance_item, dict) else None
		if not instance:
			logger.debug("Skipping non-dict instance: %s", instance_item)
			continue

		# Try both possible field names for instance identifier
		instance_name = instance.get("name") or instance.get("instanceName")
		if not instance_name:
			logger.debug("Skipping instance with no name: %s", instance)
			continue

		logger.debug("Configuring webhook for instance: %s", instance_name)
		try:
			result = api_client.set_webhook_for_instance(
				instance_name,
				url=callback_url,
				events=events,
				enabled=True,
			)
			logger.debug("Webhook set response: %s", result)
			results.append({"instance": instance_name, "success": True})
		except Exception as exc:
			logger.debug("Failed to configure webhook for %s: %s", instance_name, exc)
			results.append({"instance": instance_name, "success": False, "error": str(exc)})

	return {
		"success": True,
		"callback_url": callback_url,
		"events": event_names,
		"total_instances": len(instances),
		"configured": len([r for r in results if r.get("success")]),
		"results": results,
	}


def _sync_webhooks_with_retries(
	api_client: EvolutionApiClient,
	callback_url: str,
	events: list[WebhookEventType | str],
	max_attempts: int = 12,
	initial_delay_seconds: float = 2.0,
) -> None:
	delay_seconds = initial_delay_seconds
	for attempt in range(1, max_attempts + 1):
		sync_result = sync_webhooks_for_all_instances(api_client, callback_url, events)
		if sync_result.get("success") and sync_result.get("total_instances", 0) > 0:
			configured_count = sync_result.get("configured", 0)
			total_count = sync_result.get("total_instances", 0)
			logger.info(
				"Webhook sync completed on attempt %d: configured %d/%d instances",
				attempt,
				configured_count,
				total_count,
			)
			return

		logger.warning(
			"Webhook sync attempt %d/%d not ready yet; retrying in %.1f seconds",
			attempt,
			max_attempts,
			delay_seconds,
		)
		time.sleep(delay_seconds)
		delay_seconds = min(delay_seconds * 1.5, 15.0)

	logger.error("Webhook sync did not complete after %d attempts", max_attempts)


def create_app() -> Flask:
	settings = load_settings()

	logging.basicConfig(
		level=getattr(logging, settings.log_level, logging.INFO),
		format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
	)

	logger = logging.getLogger("whatsapp-automation")
	app = Flask(__name__)
	
	# Initialize server uptime filter middleware
	init_server_uptime_filter(app)
	
	# Reduce Flask/Werkzeug debug noise if log level is not DEBUG
	if settings.log_level != "DEBUG":
		logging.getLogger("werkzeug").setLevel(logging.WARNING)

	api_client = EvolutionApiClient(settings)
	contract_store = ContractStore(settings.contract_db_path)
	session_manager = SessionManager(
		api_client,
		contract_base_url=settings.contract_public_base_url,
		contract_store=contract_store,
	)

	callback_url = build_webhook_callback_url(settings)
	configured_events = enabled_events()

	logger.info("Webhook endpoint ready at %s", callback_url)
	logger.info("Subscribed events: %s", ", ".join(configured_events))

	# Auto-bind webhooks to all instances with retries so startup order does not matter.
	threading.Thread(
		target=_sync_webhooks_with_retries,
		args=(api_client, callback_url, configured_events),
		name="webhook-sync-retry",
		daemon=True,
	).start()

	@app.before_request
	def log_request() -> None:
		logger.debug(
			"→ %s %s from %s",
			request.method,
			request.path,
			request.remote_addr,
		)

	app.register_blueprint(create_webhook_blueprint(session_manager, settings.authentication_api_key))
	app.register_blueprint(
		create_admin_blueprint(
			session_manager=session_manager,
			auth_key=settings.authentication_api_key,
		)
	)
	app.register_blueprint(create_contract_blueprint(session_manager, settings.contract_public_base_url))

	@app.get("/health")
	def health() -> tuple[Any, int]:
		return jsonify({"ok": True, "service": "whatsapp-automation"}), 200

	return app


app = create_app()


if __name__ == "__main__":
	settings = load_settings()
	app.run(host=settings.flask_host, port=settings.flask_port, debug=settings.flask_debug)
