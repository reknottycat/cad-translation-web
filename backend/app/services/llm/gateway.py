"""Protocol adapters, probes, fallback selection, and request scheduling."""

from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any

import requests

from .rate_limit import TokenBucket


class LLMGatewayMixin:
    def _retry_delay_seconds(
        self,
        attempt: int,
        status_code: int | None = None,
        retry_after: float | None = None,
    ) -> float:
        if retry_after is not None and retry_after > 0:
            return min(30.0, max(1.0, float(retry_after)))
        if status_code == 429:
            return min(30.0, 2 ** (attempt - 1))
        return min(1.5, 0.4 * attempt)

    @staticmethod
    def _should_retry_http_status(status_code: int) -> bool:
        return status_code == 429 or status_code >= 500

    def _wait_interruptibly(self, seconds: float) -> None:
        deadline = time.monotonic() + max(0.0, seconds)
        while True:
            self._ensure_not_cancelled()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(0.1, remaining))

    def _parse_extra_body(self, raw: str) -> dict[str, Any]:
        text = (raw or "").strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            self._logger.warning("llm_extra_body_invalid_json", raw=text[:300])
            return {}
        if not isinstance(parsed, dict):
            self._logger.warning("llm_extra_body_not_object", raw=text[:300])
            return {}
        return parsed

    def _proxy_for(self, cfg: dict[str, Any]) -> dict[str, str] | None:
        """Compatibility helper; actual behavior is Session.trust_env."""
        return None if bool(cfg.get("use_system_proxy", False)) else {}

    @staticmethod
    def _parse_tpm(value: str) -> int:
        text = (value or "").strip().lower()
        if not text:
            return 0
        multiplier = 1000 if text.endswith("k") else 1
        if multiplier > 1:
            text = text[:-1]
        try:
            return int(float(text) * multiplier)
        except ValueError:
            return 0

    def _throttle(self, cfg: dict[str, Any], cost: int = 1) -> None:
        self._ensure_not_cancelled()
        rpm = int(cfg.get("rpm") or 0)
        tpm = self._parse_tpm(cfg.get("tpm") or "")
        if rpm <= 0 and tpm <= 0:
            return
        endpoint = (cfg["provider"], cfg["base_url"], cfg["model"])
        with self._rate_lock:
            waits: list[float] = []
            if rpm > 0:
                key = (*endpoint, "rpm", rpm)
                bucket = self._rate_buckets.get(key)
                if bucket is None:
                    bucket = TokenBucket(rpm, rpm / 60.0)
                    self._rate_buckets[key] = bucket
                waits.append(bucket.acquire(1))
            if tpm > 0:
                key = (*endpoint, "tpm", tpm)
                bucket = self._rate_buckets.get(key)
                if bucket is None:
                    bucket = TokenBucket(tpm, tpm / 60.0)
                    self._rate_buckets[key] = bucket
                waits.append(bucket.acquire(max(1, cost)))
            wait = max(waits, default=0.0)
        if wait > 0:
            self._logger.info(
                "llm_rate_limited",
                provider=cfg["provider"],
                wait_seconds=round(wait, 2),
            )
            self._wait_interruptibly(wait)

    def _request(
        self, method: str, url: str, cfg: dict[str, Any], **kwargs: Any
    ) -> requests.Response:
        """Issue one request through the common proxy-aware transport."""
        self._ensure_not_cancelled()
        return self._transport.request(
            method,
            url,
            use_system_proxy=bool(cfg.get("use_system_proxy", False)),
            **kwargs,
        )

    @staticmethod
    def _extract_message_content(data: dict[str, Any]) -> str:
        choices = data.get("choices") or []
        if not choices:
            raise ValueError("LLM response did not include choices")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("LLM response did not include text content")
        return content.strip()

    @staticmethod
    def _raise_for_llm_response(response: requests.Response) -> None:
        if response.status_code == 200:
            return
        retry_after = response.headers.get("retry-after") or response.headers.get(
            "Retry-After"
        )
        hint = f" retry_after={retry_after}" if retry_after else ""
        raise ValueError(
            f"LLM request failed: {response.status_code} {response.text[:300]}{hint}"
        )

    def _chat_openai_compatible(
        self, cfg: dict[str, Any], messages: list[dict[str, str]]
    ) -> str:
        body: dict[str, Any] = {
            "model": cfg["model"],
            "messages": messages,
            "temperature": cfg["temperature"],
            "max_tokens": cfg["max_tokens"],
        }
        if cfg["provider"] == "nvidia" and cfg.get("reasoning_enabled"):
            body["chat_template_kwargs"] = {"thinking": True}
        elif cfg.get("reasoning_enabled"):
            body["reasoning"] = {"enabled": True}
        body.update(self._parse_extra_body(cfg.get("extra_body", "")))
        headers = {
            "Authorization": f"Bearer {cfg['api_key']}",
            "Content-Type": "application/json",
        }
        if cfg["provider"] == "openrouter":
            headers["X-Title"] = self.settings.APP_NAME
        self._throttle(cfg, cost=int(cfg.get("max_tokens") or 1))
        response = self._request(
            "POST",
            f"{cfg['base_url']}/chat/completions",
            cfg,
            headers=headers,
            json=body,
            timeout=cfg["timeout"],
        )
        self._raise_for_llm_response(response)
        return self._extract_message_content(response.json())

    def _chat_anthropic(
        self, cfg: dict[str, Any], messages: list[dict[str, str]]
    ) -> str:
        system = [item["content"] for item in messages if item.get("role") == "system"]
        user_messages = [
            {
                "role": "assistant" if item.get("role") == "assistant" else "user",
                "content": item.get("content", ""),
            }
            for item in messages
            if item.get("role") != "system"
        ]
        body = {
            "model": cfg["model"],
            "system": "\n\n".join(system).strip(),
            "messages": user_messages,
            "max_tokens": cfg["max_tokens"],
            "temperature": cfg["temperature"],
        }
        body.update(self._parse_extra_body(cfg.get("extra_body", "")))
        self._throttle(cfg, cost=int(cfg.get("max_tokens") or 1))
        response = self._request(
            "POST",
            f"{cfg['base_url']}/messages",
            cfg,
            headers={
                "x-api-key": cfg["api_key"],
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=body,
            timeout=cfg["timeout"],
        )
        self._raise_for_llm_response(response)
        content = response.json().get("content") or []
        parts = [item.get("text", "") for item in content if item.get("type") == "text"]
        if not any(str(part).strip() for part in parts):
            raise ValueError("LLM response did not include text content")
        return "\n".join(part for part in parts if part).strip()

    def _chat_google(
        self, cfg: dict[str, Any], messages: list[dict[str, str]]
    ) -> str:
        prompt = "\n\n".join(
            f"{item.get('role', 'user')}: {item.get('content', '')}" for item in messages
        )
        self._throttle(cfg, cost=int(cfg.get("max_tokens") or 1))
        response = self._request(
            "POST",
            f"{cfg['base_url']}/models/{cfg['model']}:generateContent",
            cfg,
            params={"key": cfg["api_key"]},
            headers={"Content-Type": "application/json"},
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=cfg["timeout"],
        )
        self._raise_for_llm_response(response)
        candidates = response.json().get("candidates") or []
        if not candidates:
            raise ValueError("LLM response did not include candidates")
        parts = ((candidates[0].get("content") or {}).get("parts")) or []
        texts = [part.get("text", "") for part in parts if isinstance(part, dict)]
        if not any(str(text).strip() for text in texts):
            raise ValueError("LLM response did not include text content")
        return "\n".join(text for text in texts if text).strip()

    def _chat_ollama(
        self, cfg: dict[str, Any], messages: list[dict[str, str]]
    ) -> str:
        headers = {"Content-Type": "application/json"}
        if cfg["api_key"]:
            headers["Authorization"] = f"Bearer {cfg['api_key']}"
        body = {"model": cfg["model"], "messages": messages, "stream": False}
        body.update(self._parse_extra_body(cfg.get("extra_body", "")))
        self._throttle(cfg)
        response = self._request(
            "POST",
            f"{cfg['base_url'].rstrip('/')}/api/chat",
            cfg,
            headers=headers,
            json=body,
            timeout=cfg["timeout"],
        )
        self._raise_for_llm_response(response)
        content = ((response.json().get("message") or {}).get("content")) or ""
        if not str(content).strip():
            raise ValueError("LLM response did not include text content")
        return str(content).strip()

    @staticmethod
    def _credential_fingerprint(api_key: str) -> str:
        return hashlib.sha256((api_key or "").encode("utf-8")).hexdigest()

    def _probe_key(self, cfg: dict[str, Any]) -> tuple[str, str, str, str, str]:
        return (
            cfg["provider"],
            cfg["format"],
            cfg["base_url"],
            cfg["model"],
            self._credential_fingerprint(cfg.get("api_key", "")),
        )

    def _probe_network(self, cfg: dict[str, Any]) -> dict[str, Any]:
        provider = cfg["provider"]
        api_format = cfg["format"]
        headers = {"Content-Type": "application/json"}
        params = None
        if cfg.get("api_key"):
            headers["Authorization"] = f"Bearer {cfg['api_key']}"
        if api_format in {"openai_compatible", "lmstudio"}:
            endpoint = f"{cfg['base_url']}/models"
        elif api_format == "anthropic":
            endpoint = f"{cfg['base_url']}/models"
            headers = {
                "x-api-key": cfg["api_key"],
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            }
        elif api_format == "google":
            endpoint = f"{cfg['base_url']}/models"
            params = {"key": cfg["api_key"]}
        elif api_format == "ollama":
            endpoint = f"{cfg['base_url'].rstrip('/')}/api/tags"
        else:
            return self._probe_result(cfg, False, False, 0, cfg["base_url"], f"unsupported LLM format: {api_format}")
        response = self._request(
            "GET",
            endpoint,
            cfg,
            headers=headers,
            params=params,
            timeout=cfg["timeout"],
        )
        if response.status_code == 404:
            if api_format in {"openai_compatible", "lmstudio"}:
                endpoint = f"{cfg['base_url']}/chat/completions"
                body = {"model": cfg["model"], "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1}
            elif api_format == "anthropic":
                endpoint = f"{cfg['base_url']}/messages"
                body = {"model": cfg["model"], "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1}
            elif api_format == "google":
                endpoint = f"{cfg['base_url']}/models/{cfg['model']}:generateContent"
                body = {"contents": [{"role": "user", "parts": [{"text": "hi"}]}]}
            else:
                body = None
            if body is not None:
                response = self._request(
                    "POST", endpoint, cfg, headers=headers, params=params,
                    json=body, timeout=cfg["timeout"]
                )
        return self._probe_result(
            cfg,
            response.status_code == 200,
            response.status_code < 500,
            response.status_code,
            endpoint,
            "connection ok" if response.status_code == 200 else response.text[:300],
        )

    @staticmethod
    def _probe_result(
        cfg: dict[str, Any], success: bool, reachable: bool, status: int,
        endpoint: str, message: str
    ) -> dict[str, Any]:
        return {
            "success": success,
            "reachable": reachable,
            "status_code": status,
            "provider": cfg["provider"],
            "format": cfg["format"],
            "endpoint": endpoint,
            "model": cfg["model"],
            "message": message,
        }

    def _probe_candidate(
        self, cfg: dict[str, Any], *, force_refresh: bool = False
    ) -> dict[str, Any]:
        self._ensure_not_cancelled()
        key = self._probe_key(cfg)
        identity = key[:4]
        now = time.monotonic()
        owner = False
        event = None
        with self._probe_lock:
            previous_credential = self._probe_credentials.get(identity)
            if previous_credential != key[4]:
                for cached_key in list(self._probe_cache):
                    if cached_key[:4] == identity:
                        self._probe_cache.pop(cached_key, None)
                self._probe_credentials[identity] = key[4]
            cached = self._probe_cache.get(key)
            if not force_refresh and cached and now - cached[0] < self._probe_ttl_seconds:
                return cached[1]
            event = self._probe_inflight.get(key)
            if event is None:
                event = self._probe_event_factory()
                self._probe_inflight[key] = event
                owner = True
        if not owner:
            # Never wait while holding _probe_lock. The owner publishes in finally.
            deadline = time.monotonic() + float(cfg.get("timeout") or 30) + 5
            while not event.wait(timeout=0.1):
                self._ensure_not_cancelled()
                if time.monotonic() >= deadline:
                    return self._probe_result(
                        cfg, False, False, 0, cfg["base_url"], "provider probe timed out"
                    )
            with self._probe_lock:
                cached = self._probe_cache.get(key)
            if cached:
                return cached[1]
            return self._probe_result(
                cfg, False, False, 0, cfg["base_url"], "provider probe failed"
            )
        result: dict[str, Any] | None = None
        try:
            if cfg["format"] not in {"ollama", "lmstudio"} and not cfg.get("api_key"):
                result = self._probe_result(
                    cfg, False, False, 0, cfg["base_url"], "api key missing"
                )
            else:
                result = self._probe_network(cfg)
            return result
        except requests.RequestException as exc:
            result = self._probe_result(
                cfg, False, False, 0, cfg["base_url"], str(exc)
            )
            return result
        finally:
            with self._probe_lock:
                if result is not None:
                    self._probe_cache[key] = (time.monotonic(), result)
                wake = self._probe_inflight.pop(key, None)
            if wake is not None:
                wake.set()

    def _finish_probe(self, cache_key: tuple[Any, ...]) -> None:
        """Compatibility hook that safely wakes a manually registered probe."""
        with self._probe_lock:
            event = self._probe_inflight.pop(cache_key, None)
        if event is not None:
            event.set()

    def _is_retryable_chat_error(self, exc: Exception) -> bool:
        if isinstance(exc, requests.RequestException):
            return True
        match = re.search(r"LLM request failed:\s*(\d+)", str(exc))
        return bool(match and self._should_retry_http_status(int(match.group(1))))

    def _dispatch_chat(
        self, cfg: dict[str, Any], messages: list[dict[str, str]]
    ) -> str:
        self._ensure_not_cancelled()
        if cfg["format"] in {"openai_compatible", "lmstudio"}:
            return self._chat_openai_compatible(cfg, messages)
        if cfg["format"] == "anthropic":
            return self._chat_anthropic(cfg, messages)
        if cfg["format"] == "google":
            return self._chat_google(cfg, messages)
        if cfg["format"] == "ollama":
            return self._chat_ollama(cfg, messages)
        raise ValueError(f"Unsupported LLM format: {cfg['format']}")

    def _chat(self, messages: list[dict[str, str]]) -> str:
        cfg = self._active_config()
        last_error: Exception | None = None
        self._thread_local.effective_candidate = None
        for candidate in [cfg, *cfg.get("fallback_models", [])]:
            self._ensure_not_cancelled()
            if candidate["format"] not in {"ollama", "lmstudio"} and not candidate["api_key"]:
                if candidate.get("allow_demo_fallback"):
                    self._thread_local.effective_candidate = candidate
                    return "[DEMO_MODE] API key missing"
                last_error = ValueError(
                    f"No API key configured for provider {candidate['provider']}"
                )
                continue
            probe = self._probe_candidate(candidate)
            if not probe.get("success"):
                last_error = ValueError(
                    f"Provider {candidate['provider']} is unavailable: "
                    f"{probe.get('message') or 'probe failed'}"
                )
                self._logger.warning(
                    "llm_provider_probe_failed",
                    provider=candidate["provider"],
                    message=probe.get("message"),
                )
                continue
            retry_count = max(0, int(candidate.get("retry_count") or 0))
            for attempt in range(1, retry_count + 2):
                self._ensure_not_cancelled()
                try:
                    content = self._dispatch_chat(candidate, messages)
                    self._thread_local.effective_candidate = candidate
                    return content
                except (requests.RequestException, ValueError) as exc:
                    last_error = exc
                    if attempt <= retry_count and self._is_retryable_chat_error(exc):
                        status_match = re.search(r"LLM request failed:\s*(\d+)", str(exc))
                        retry_match = re.search(
                            r"retry[-_]after[:=]\s*([\d.]+)", str(exc), re.I
                        )
                        self._wait_interruptibly(
                            self._retry_delay_seconds(
                                attempt,
                                int(status_match.group(1)) if status_match else None,
                                float(retry_match.group(1)) if retry_match else None,
                            )
                        )
                        continue
                    break
            self._logger.warning(
                "llm_provider_failed_fallback",
                provider=candidate["provider"],
                error=str(last_error),
            )
        if last_error is not None:
            raise ValueError(str(last_error)) from last_error
        raise ValueError("LLM request failed without a response")

    def test_connection(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Test a supplied profile through the same transport as generation."""
        provider_keys = payload.get("provider_api_keys")
        cfg = self._resolve_candidate_config(payload, provider_keys)
        cfg.update(
            {
                "use_system_proxy": bool(payload.get("use_system_proxy", False)),
                "rpm": 0,
                "tpm": "",
                "extra_body": str(payload.get("extra_body") or ""),
                "retry_count": 0,
            }
        )
        if not cfg["base_url"]:
            raise ValueError("base_url is required")
        if cfg["format"] not in {"ollama", "lmstudio"} and not cfg["api_key"]:
            raise ValueError("api_key is required")
        return self._probe_candidate(cfg, force_refresh=True)
