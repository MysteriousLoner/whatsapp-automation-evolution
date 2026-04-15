from __future__ import annotations

import logging
import os
from typing import Any

import requests


logger = logging.getLogger(__name__)


class QueryLLM:
	"""Simple Gemini generateContent client.

	Reads API key from `GEMINI_API_KEY` in environment variables.
	"""

	def __init__(
		self,
		api_key: str | None = None,
		base_url: str = "https://generativelanguage.googleapis.com/v1beta",
		timeout_seconds: int = 30,
		default_model: str = "gemini-2.5-flash",
	) -> None:
		resolved_key = api_key or os.getenv("GEMINI_API_KEY", "").strip()
		resolved_model = os.getenv("GEMINI_MODEL", "").strip() or default_model
		if not resolved_key:
			raise ValueError("Missing Gemini API key. Set GEMINI_API_KEY in environment.")

		self._api_key = resolved_key
		self._base_url = base_url.rstrip("/")
		self._timeout_seconds = timeout_seconds
		self._default_model = resolved_model
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
		"""Query Gemini with user-provided parameters and return parsed response."""
		if not user_input or not user_input.strip():
			return {"ok": False, "error": "user_input cannot be empty"}

		model_name = model or self._default_model
		combined_prompt = user_input.strip()
		if system_prompt and system_prompt.strip():
			combined_prompt = f"System instructions:\n{system_prompt.strip()}\n\nUser request:\n{combined_prompt}"

		generation_config: dict[str, Any] = {}
		if temperature is not None:
			generation_config["temperature"] = temperature
		if max_tokens is not None:
			generation_config["maxOutputTokens"] = max_tokens
		if top_p is not None:
			generation_config["topP"] = top_p

		payload: dict[str, Any] = {
			"contents": [
				{
					"parts": [{"text": combined_prompt}],
				}
			],
		}
		if generation_config:
			payload["generationConfig"] = generation_config
		if extra_params:
			payload.update(extra_params)

		headers = {"Content-Type": "application/json"}
		endpoint = f"{self._base_url}/models/{model_name}:generateContent?key={self._api_key}"
		try:
			response = self._session.post(
				endpoint,
				json=payload,
				headers=headers,
				timeout=self._timeout_seconds,
			)
			response.raise_for_status()
		except requests.RequestException as exc:
			logger.exception("Gemini request failed")
			return {"ok": False, "error": f"Gemini request failed: {exc}"}

		try:
			data = response.json()
		except ValueError:
			logger.warning("Gemini returned non-JSON response")
			return {"ok": False, "error": "Gemini returned non-JSON response", "raw": response.text}

		candidates = data.get("candidates")
		if isinstance(candidates, list) and candidates:
			first = candidates[0]
			if isinstance(first, dict):
				content_obj = first.get("content")
				if isinstance(content_obj, dict):
					parts = content_obj.get("parts")
					if isinstance(parts, list):
						text_chunks: list[str] = []
						for part in parts:
							if isinstance(part, dict) and isinstance(part.get("text"), str):
								text_chunks.append(part["text"])
						if text_chunks:
							return {
								"ok": True,
								"model": model_name,
								"content": "\n".join(text_chunks),
								"usage": data.get("usageMetadata", {}),
								"raw": data,
							}

		return {"ok": True, "raw": data}
