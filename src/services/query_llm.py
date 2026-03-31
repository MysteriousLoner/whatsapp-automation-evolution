from __future__ import annotations

import logging
import os
from typing import Any

import requests


logger = logging.getLogger(__name__)


class QueryLLM:
	"""Simple DeepSeek chat-completions client.

	Reads API key from `DEEP_SEEK_API_KEY` in environment variables.
	"""

	def __init__(
		self,
		api_key: str | None = None,
		base_url: str = "https://api.deepseek.com",
		timeout_seconds: int = 30,
		default_model: str = "deepseek-chat",
	) -> None:
		resolved_key = api_key or os.getenv("DEEP_SEEK_API_KEY", "").strip()
		if not resolved_key:
			raise ValueError("Missing DeepSeek API key. Set DEEP_SEEK_API_KEY in environment.")

		self._api_key = resolved_key
		self._base_url = base_url.rstrip("/")
		self._timeout_seconds = timeout_seconds
		self._default_model = default_model
		self._session = requests.Session()

	def query(
		self,
		user_input: str,
		*,
		model: str | None = None,
		system_prompt: str | None = None,
		temperature: float | None = None,
		max_tokens: int | None = None,
		top_p: float | None = None,
		frequency_penalty: float | None = None,
		presence_penalty: float | None = None,
		stream: bool = False,
		extra_params: dict[str, Any] | None = None,
	) -> dict[str, Any]:
		"""Query DeepSeek with user-provided parameters and return parsed response."""
		if not user_input or not user_input.strip():
			return {"ok": False, "error": "user_input cannot be empty"}

		messages: list[dict[str, str]] = []
		if system_prompt and system_prompt.strip():
			messages.append({"role": "system", "content": system_prompt.strip()})
		messages.append({"role": "user", "content": user_input.strip()})

		payload: dict[str, Any] = {
			"model": model or self._default_model,
			"messages": messages,
			"stream": stream,
		}

		if temperature is not None:
			payload["temperature"] = temperature
		if max_tokens is not None:
			payload["max_tokens"] = max_tokens
		if top_p is not None:
			payload["top_p"] = top_p
		if frequency_penalty is not None:
			payload["frequency_penalty"] = frequency_penalty
		if presence_penalty is not None:
			payload["presence_penalty"] = presence_penalty
		if extra_params:
			payload.update(extra_params)

		headers = {
			"Authorization": f"Bearer {self._api_key}",
			"Content-Type": "application/json",
		}

		endpoint = f"{self._base_url}/chat/completions"
		try:
			response = self._session.post(
				endpoint,
				json=payload,
				headers=headers,
				timeout=self._timeout_seconds,
			)
			response.raise_for_status()
		except requests.RequestException as exc:
			logger.exception("DeepSeek request failed")
			return {"ok": False, "error": f"DeepSeek request failed: {exc}"}

		try:
			data = response.json()
		except ValueError:
			logger.warning("DeepSeek returned non-JSON response")
			return {"ok": False, "error": "DeepSeek returned non-JSON response", "raw": response.text}

		choices = data.get("choices")
		if isinstance(choices, list) and choices:
			first = choices[0]
			if isinstance(first, dict):
				message = first.get("message")
				if isinstance(message, dict):
					content = message.get("content")
					if isinstance(content, str):
						return {
							"ok": True,
							"model": data.get("model"),
							"content": content,
							"usage": data.get("usage", {}),
							"raw": data,
						}

		return {"ok": True, "raw": data}
