"""Config flow: Khouch server URL + username + password.

The URL is editable later via the integration's **Reconfigure** action (so a
changed Khouch hostname doesn't require removing and re-adding the integration).
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .api import KhouchAuthError, KhouchClient, KhouchError
from .const import CONF_PASSWORD, CONF_URL, CONF_USERNAME, DOMAIN


def _schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    d = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_URL, default=d.get(CONF_URL, "")): str,
            vol.Required(CONF_USERNAME, default=d.get(CONF_USERNAME, "")): str,
            vol.Required(CONF_PASSWORD): str,
        }
    )


async def _validate(hass, data: dict[str, Any]) -> dict[str, str]:
    """Try logging in; return a dict of form errors (empty == ok)."""
    client = KhouchClient(data[CONF_URL], data[CONF_USERNAME], data[CONF_PASSWORD])
    try:
        await client.login()
    except KhouchAuthError:
        return {"base": "invalid_auth"}
    except KhouchError:
        return {"base": "cannot_connect"}
    finally:
        await client.close()
    return {}


class KhouchConfigFlow(ConfigFlow, domain=DOMAIN):
    """URL/username/password, validated by a live login."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input[CONF_URL] = user_input[CONF_URL].strip().rstrip("/")
            errors = await _validate(self.hass, user_input)
            if not errors:
                await self.async_set_unique_id(user_input[CONF_URL])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="Khouch", data=user_input)
        return self.async_show_form(
            step_id="user", data_schema=_schema(user_input), errors=errors
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input[CONF_URL] = user_input[CONF_URL].strip().rstrip("/")
            errors = await _validate(self.hass, user_input)
            if not errors:
                return self.async_update_reload_and_abort(
                    entry, data_updates=user_input
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_schema(user_input or dict(entry.data)),
            errors=errors,
        )
