"""Thin async client for the Khouch (iptv-webui) server API.

Cookie-session auth: ``POST /api/login`` sets ``khouch_session``; we keep an
isolated aiohttp session with its own cookie jar so Khouch cookies never mix
with Home Assistant's shared client session. A 401 on any call triggers one
re-login + retry.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import aiohttp

_LOGGER = logging.getLogger(__name__)


class KhouchError(Exception):
    """Khouch is unreachable or returned an error."""


class KhouchAuthError(KhouchError):
    """Login was rejected (bad username/password)."""


class KhouchClient:
    """Minimal client: login, search, resolve a stream URL."""

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        profile_id: str | None = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._user = username
        self._pass = password
        self._profile_id = profile_id
        self._session: aiohttp.ClientSession | None = None

    @property
    def base_url(self) -> str:
        return self._base

    def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            # Own cookie jar — keeps the khouch_session cookie isolated.
            self._session = aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar())
        return self._session

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()

    async def login(self) -> None:
        """Authenticate, then select the configured profile.

        Catalog endpoints are profile-gated: a session cookie alone gets a
        ``401 profile required``. So after login we POST the chosen profile to
        set the ``khouch_profile`` cookie. ``/api/profiles`` itself is not
        profile-gated, so it works on the bare session.
        """
        session = self._ensure_session()
        try:
            async with session.post(
                f"{self._base}/api/login",
                json={"username": self._user, "password": self._pass},
                headers={"Accept": "application/json"},
            ) as resp:
                if resp.status == 401:
                    raise KhouchAuthError("Wrong username or password")
                if resp.status != 200:
                    raise KhouchError(f"login returned HTTP {resp.status}")
                data = await resp.json()
                if not data.get("ok"):
                    raise KhouchAuthError(str(data.get("error", "login failed")))
        except aiohttp.ClientError as err:
            raise KhouchError(f"cannot reach Khouch at {self._base}: {err}") from err

        if self._profile_id:
            await self._select_profile(self._profile_id)

    async def get_profiles(self) -> list[dict[str, Any]]:
        """List the logged-in account's profiles (id, nick, kidsBirthYear…)."""
        data = await self._get_json("/api/profiles", _retry=False)
        return data.get("profiles", []) if isinstance(data, dict) else []

    async def _select_profile(self, profile_id: str) -> None:
        session = self._ensure_session()
        try:
            async with session.post(
                f"{self._base}/api/profile/select",
                json={"id": profile_id},
                headers={"Accept": "application/json"},
            ) as resp:
                if resp.status != 200:
                    raise KhouchError(
                        f"could not select profile '{profile_id}' (HTTP {resp.status})"
                    )
        except aiohttp.ClientError as err:
            raise KhouchError(f"profile select failed: {err}") from err

    async def _get_json(self, path: str, *, _retry: bool = True) -> Any:
        session = self._ensure_session()
        try:
            async with session.get(
                f"{self._base}{path}", headers={"Accept": "application/json"}
            ) as resp:
                if resp.status == 401 and _retry:
                    await self.login()
                    return await self._get_json(path, _retry=False)
                if resp.status != 200:
                    raise KhouchError(f"GET {path} returned HTTP {resp.status}")
                return await resp.json()
        except aiohttp.ClientError as err:
            raise KhouchError(f"GET {path} failed: {err}") from err

    async def search(self, query: str, limit: int) -> dict[str, list[dict[str, Any]]]:
        """Cross-catalog search → ``{live:[…], movie:[…], series:[…], disk:[…]}``."""
        data = await self._get_json(f"/api/search/all?q={quote(query)}&limit={int(limit)}")
        return data if isinstance(data, dict) else {}

    async def resolve_url(self, mode: str, item_id: str | int, ext: str) -> str:
        """Resolve a catalog item to an absolute, cast-ready stream URL.

        Khouch returns ``{direct, proxy, transcode, url, …}`` where ``url`` is its
        recommended choice (direct panel HLS, or a signed same-origin transcode
        URL for codec-incompatible content). Same-origin paths are made absolute.
        """
        data = await self._get_json(f"/api/stream/{mode}/{item_id}.{ext}")
        if not isinstance(data, dict):
            raise KhouchError("unexpected stream response")
        url = data.get("url") or data.get("direct") or data.get("transcode")
        if not url:
            raise KhouchError("no playable URL in stream response")
        if url.startswith("/"):
            url = f"{self._base}{url}"
        return url
