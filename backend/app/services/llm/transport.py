"""Shared HTTP transport used by translation and connection probes."""

from __future__ import annotations

import threading
from typing import Any

import requests


class RequestsTransport:
    """Own sessions with explicit and stable environment-proxy semantics."""

    def __init__(self) -> None:
        self._local = threading.local()

    def _sessions(self) -> tuple[requests.Session, requests.Session]:
        sessions = getattr(self._local, "sessions", None)
        if sessions is None:
            direct = requests.Session()
            direct.trust_env = False
            environment = requests.Session()
            environment.trust_env = True
            sessions = (direct, environment)
            self._local.sessions = sessions
        return sessions

    def request(
        self,
        method: str,
        url: str,
        *,
        use_system_proxy: bool,
        **kwargs: Any,
    ) -> requests.Response:
        direct, environment = self._sessions()
        session = environment if use_system_proxy else direct
        # Proxy behavior belongs to ``Session.trust_env``. Do not pass the old
        # {http: None, https: None} mapping because ALL_PROXY still survives it.
        kwargs.pop("proxies", None)
        return session.request(method=method, url=url, **kwargs)


shared_transport = RequestsTransport()
