"""The Khouch IPTV integration.

Khouch is a self-hosted IPTV player (an Xtream Codes web UI). This integration is
a thin, self-contained client over its API — it owns all of the IPTV specifics
(URL, credentials, catalog, cast URLs). Any conversation agent or automation
drives it purely through the two exposed services (typically via a small wrapper
script): reason over the ``khouch.search`` candidates, confirm the right one,
then call ``khouch.play``. Nothing else needs to know how Khouch works.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    HomeAssistantError,
)
from homeassistant.helpers import config_validation as cv

from .api import KhouchAuthError, KhouchClient, KhouchError
from .const import (
    CONF_PASSWORD,
    CONF_PROFILE,
    CONF_URL,
    CONF_USERNAME,
    DEFAULT_SEARCH_LIMIT,
    DOMAIN,
    MODES,
    REF_SEP,
    SERVICE_PLAY,
    SERVICE_SEARCH,
)


@dataclass
class KhouchRuntime:
    client: KhouchClient


KhouchConfigEntry = ConfigEntry[KhouchRuntime]


def _client(hass: HomeAssistant) -> KhouchClient:
    """The active Khouch client (a home has one Khouch server)."""
    entries: dict[str, KhouchRuntime] = hass.data[DOMAIN]
    if not entries:
        raise HomeAssistantError("Khouch is not configured.")
    return next(iter(entries.values())).client


def _ext_for(mode: str, item: dict[str, Any]) -> str:
    """The extension Khouch's /api/stream expects for this item."""
    if mode == "live":
        return "m3u8"
    return str(item.get("container") or item.get("container_extension") or "mp4")


def _candidate(mode: str, item: dict[str, Any]) -> dict[str, Any]:
    """Shape one search hit for the caller/model to reason over."""
    item_id = item.get("id") or item.get("stream_id")
    name = item.get("name") or item.get("title") or ""
    out: dict[str, Any] = {
        "ref": f"{mode}{REF_SEP}{item_id}{REF_SEP}{_ext_for(mode, item)}",
        "title": name,
        "kind": mode,
    }
    if item.get("year"):
        out["year"] = item["year"]
    if item.get("category") or item.get("category_name"):
        out["category"] = item.get("category") or item.get("category_name")
    return out


def _content_type(url: str) -> str:
    return "application/x-mpegURL" if ".m3u8" in url.split("?")[0] else "video/mp4"


_SEARCH_SCHEMA = vol.Schema(
    {
        vol.Required("query"): cv.string,
        vol.Optional("kind"): vol.In(MODES),
        vol.Optional("limit", default=DEFAULT_SEARCH_LIMIT): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=60)
        ),
    }
)

_PLAY_SCHEMA = vol.Schema(
    {
        vol.Required("ref"): cv.string,
        vol.Required(ATTR_ENTITY_ID): cv.entities_domain("media_player"),
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: KhouchConfigEntry) -> bool:
    """Set up Khouch from a config entry."""
    client = KhouchClient(
        entry.data[CONF_URL],
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
        entry.data.get(CONF_PROFILE),
    )
    try:
        await client.login()
    except KhouchAuthError as err:
        await client.close()
        raise ConfigEntryAuthFailed(str(err)) from err
    except KhouchError as err:
        await client.close()
        raise ConfigEntryNotReady(str(err)) from err

    entry.runtime_data = KhouchRuntime(client)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = entry.runtime_data
    entry.async_on_unload(lambda: hass.async_create_task(client.close()))

    _register_services(hass)
    entry.async_on_unload(entry.add_update_listener(_reload))
    return True


async def _reload(hass: HomeAssistant, entry: KhouchConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: KhouchConfigEntry) -> bool:
    """Unload a config entry."""
    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if not hass.data.get(DOMAIN):
        for service in (SERVICE_SEARCH, SERVICE_PLAY):
            hass.services.async_remove(DOMAIN, service)
    return True


def _register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_SEARCH):
        return

    async def _search(call: ServiceCall) -> ServiceResponse:
        client = _client(hass)
        query = call.data["query"]
        kind = call.data.get("kind")
        limit = call.data["limit"]
        try:
            results = await client.search(query, limit)
        except KhouchError as err:
            raise HomeAssistantError(f"Khouch search failed: {err}") from err

        modes = [kind] if kind else list(MODES)
        candidates: list[dict[str, Any]] = []
        for mode in modes:
            for item in results.get(mode) or []:
                candidates.append(_candidate(mode, item))
        return {"query": query, "count": len(candidates), "results": candidates}

    async def _play(call: ServiceCall) -> ServiceResponse:
        client = _client(hass)
        ref = call.data["ref"]
        entity_ids = call.data[ATTR_ENTITY_ID]
        try:
            mode, item_id, ext = ref.split(REF_SEP, 2)
        except ValueError as err:
            raise HomeAssistantError(
                f"Invalid ref '{ref}'; expected '<mode>:<id>:<ext>' from khouch.search."
            ) from err
        if mode not in MODES:
            raise HomeAssistantError(f"Unknown mode '{mode}' in ref.")
        try:
            url = await client.resolve_url(mode, item_id, ext)
        except KhouchError as err:
            raise HomeAssistantError(f"Khouch could not resolve stream: {err}") from err

        await hass.services.async_call(
            "media_player",
            "play_media",
            {
                ATTR_ENTITY_ID: entity_ids,
                "media_content_id": url,
                "media_content_type": _content_type(url),
            },
            blocking=True,
        )
        return {"played_ref": ref, "entity_id": entity_ids}

    hass.services.async_register(
        DOMAIN, SERVICE_SEARCH, _search, _SEARCH_SCHEMA, SupportsResponse.ONLY
    )
    hass.services.async_register(
        DOMAIN, SERVICE_PLAY, _play, _PLAY_SCHEMA, SupportsResponse.OPTIONAL
    )
