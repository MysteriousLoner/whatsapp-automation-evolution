import logging
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

	# Auto-bind webhooks to all instances on startup
	try:
		sync_result = sync_webhooks_for_all_instances(api_client, callback_url, configured_events)
		if sync_result.get("success"):
			configured_count = sync_result.get("configured", 0)
			total_count = sync_result.get("total_instances", 0)
			logger.info(
				"Webhooks configured for %d/%d instances",
				configured_count,
				total_count,
			)
			if configured_count < total_count:
				for result in sync_result.get("results", []):
					if not result.get("success"):
						logger.warning(
							"Failed to configure webhook for instance %s: %s",
							result.get("instance"),
							result.get("error"),
						)
		else:
			logger.warning("Webhook sync failed: %s", sync_result.get("error"))
	except Exception:
		logger.exception("Failed to sync webhooks during startup")
		if settings.startup_fail_fast:
			raise

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
