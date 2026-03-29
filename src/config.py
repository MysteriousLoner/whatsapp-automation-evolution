import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class Settings:
    authentication_api_key: str
    evolution_api_key: str
    evolution_base_url: str
    evolution_instance: str
    flask_host: str
    flask_port: int
    flask_debug: bool
    request_timeout_seconds: int
    webhook_public_url: str
    webhook_path: str
    webhook_by_events: bool
    webhook_base64: bool
    startup_fail_fast: bool
    log_level: str


class ConfigurationError(ValueError):
    pass


def _parse_bool(raw_value: str | None, default: bool = False) -> bool:
    if raw_value is None:
        return default

    value = raw_value.strip().lower()
    if value in {"1", "true", "yes", "y", "on"}:
        return True
    if value in {"0", "false", "no", "n", "off"}:
        return False

    raise ConfigurationError(f"Invalid boolean value: {raw_value}")


def _require_env(name: str, *, allow_empty: bool = False) -> str:
    value = os.getenv(name)
    if value is None:
        raise ConfigurationError(f"Missing required environment variable: {name}")

    if not allow_empty and not value.strip():
        raise ConfigurationError(f"Environment variable cannot be empty: {name}")

    return value.strip()


def _optional_env(name: str, default: str) -> str:
    value = os.getenv(name)
    return value.strip() if value is not None else default


def _normalize_url(url: str) -> str:
    return url.rstrip("/")


def _normalize_path(path: str) -> str:
    path = path.strip()
    if not path:
        return "/webhook"
    return path if path.startswith("/") else f"/{path}"


def _parse_port(raw_port: str) -> int:
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise ConfigurationError(f"Invalid FLASK_PORT value: {raw_port}") from exc

    if port < 1 or port > 65535:
        raise ConfigurationError("FLASK_PORT must be between 1 and 65535")

    return port


def _parse_timeout(raw_timeout: str) -> int:
    try:
        timeout = int(raw_timeout)
    except ValueError as exc:
        raise ConfigurationError(f"Invalid REQUEST_TIMEOUT_SECONDS value: {raw_timeout}") from exc

    if timeout <= 0:
        raise ConfigurationError("REQUEST_TIMEOUT_SECONDS must be a positive integer")

    return timeout


def load_settings() -> Settings:
    authentication_api_key = _require_env("AUTHENTICATION_API_KEY")
    evolution_api_key = os.getenv("EVOLUTION_API_KEY", authentication_api_key).strip()
    evolution_base_url = _normalize_url(_optional_env("EVOLUTION_BASE_URL", "http://localhost:8081"))
    evolution_instance = _optional_env("EVOLUTION_INSTANCE", "default")

    flask_host = _optional_env("FLASK_HOST", "0.0.0.0")
    flask_port = _parse_port(_optional_env("FLASK_PORT", "5000"))
    flask_debug = _parse_bool(os.getenv("FLASK_DEBUG"), default=False)
    request_timeout_seconds = _parse_timeout(_optional_env("REQUEST_TIMEOUT_SECONDS", "15"))

    webhook_public_url = _normalize_url(_require_env("WEBHOOK_PUBLIC_URL"))
    webhook_path = _normalize_path(_optional_env("WEBHOOK_PATH", "/webhook"))
    webhook_by_events = _parse_bool(os.getenv("WEBHOOK_BY_EVENTS"), default=True)
    webhook_base64 = _parse_bool(os.getenv("WEBHOOK_BASE64"), default=True)

    startup_fail_fast = _parse_bool(os.getenv("STARTUP_FAIL_FAST"), default=True)
    log_level = _optional_env("LOG_LEVEL", "INFO").upper()

    return Settings(
        authentication_api_key=authentication_api_key,
        evolution_api_key=evolution_api_key,
        evolution_base_url=evolution_base_url,
        evolution_instance=evolution_instance,
        flask_host=flask_host,
        flask_port=flask_port,
        flask_debug=flask_debug,
        request_timeout_seconds=request_timeout_seconds,
        webhook_public_url=webhook_public_url,
        webhook_path=webhook_path,
        webhook_by_events=webhook_by_events,
        webhook_base64=webhook_base64,
        startup_fail_fast=startup_fail_fast,
        log_level=log_level,
    )


def build_webhook_callback_url(settings: Settings) -> str:
    return f"{settings.webhook_public_url}{settings.webhook_path}"
