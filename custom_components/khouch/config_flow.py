"""Config flow: Khouch server URL + login, then pick a profile.

After the URL/username/password validate (a live login), we fetch the account's
profiles and let the user choose which one to browse as — Khouch scopes search
results (kid-blocking, language filters) to the selected profile. The URL/login
and the profile are both editable later via the integration's **Reconfigure**
action, so a changed hostname or a different profile needs no remove/re-add.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .api import KhouchAuthError, KhouchClient, KhouchError
from .const import (
    CONF_PASSWORD,
    CONF_PROFILE,
    CONF_URL,
    CONF_USERNAME,
    DOMAIN,
)


def _creds_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    d = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_URL, default=d.get(CONF_URL, "")): str,
            vol.Required(CONF_USERNAME, default=d.get(CONF_USERNAME, "")): str,
            vol.Required(CONF_PASSWORD): str,
        }
    )


class KhouchConfigFlow(ConfigFlow, domain=DOMAIN):
    """URL/username/password (validated by login) → pick a profile."""

    VERSION = 1

    def __init__(self) -> None:
        self._creds: dict[str, Any] = {}
        self._profiles: list[dict[str, Any]] = []

    async def _login_and_list(self, data: dict[str, Any]) -> dict[str, str]:
        """Validate creds and load profiles. Returns form errors (empty == ok)."""
        client = KhouchClient(data[CONF_URL], data[CONF_USERNAME], data[CONF_PASSWORD])
        try:
            await client.login()
            self._profiles = await client.get_profiles()
        except KhouchAuthError:
            return {"base": "invalid_auth"}
        except KhouchError:
            return {"base": "cannot_connect"}
        finally:
            await client.close()
        return {}

    def _profile_options(self) -> dict[str, str]:
        return {
            p["id"]: (
                f"{p.get('nick') or p['id']}"
                + (" (kid)" if p.get("kidsBirthYear") else "")
            )
            for p in self._profiles
        }

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input[CONF_URL] = user_input[CONF_URL].strip().rstrip("/")
            errors = await self._login_and_list(user_input)
            if not errors:
                self._creds = user_input
                await self.async_set_unique_id(user_input[CONF_URL])
                self._abort_if_unique_id_configured()
                return await self.async_step_profile()
        return self.async_show_form(
            step_id="user", data_schema=_creds_schema(user_input), errors=errors
        )

    async def async_step_profile(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        options = self._profile_options()
        if len(options) <= 1:
            profile_id = next(iter(options), None)
            return self.async_create_entry(
                title="Khouch", data={**self._creds, CONF_PROFILE: profile_id}
            )
        if user_input is not None:
            return self.async_create_entry(
                title="Khouch",
                data={**self._creds, CONF_PROFILE: user_input[CONF_PROFILE]},
            )
        return self.async_show_form(
            step_id="profile",
            data_schema=vol.Schema({vol.Required(CONF_PROFILE): vol.In(options)}),
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input[CONF_URL] = user_input[CONF_URL].strip().rstrip("/")
            errors = await self._login_and_list(user_input)
            if not errors:
                self._creds = user_input
                return await self.async_step_reconfigure_profile()
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_creds_schema(user_input or dict(entry.data)),
            errors=errors,
        )

    async def async_step_reconfigure_profile(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        options = self._profile_options()
        if len(options) <= 1 or user_input is not None:
            profile_id = (
                user_input[CONF_PROFILE]
                if user_input
                else next(iter(options), entry.data.get(CONF_PROFILE))
            )
            return self.async_update_reload_and_abort(
                entry, data_updates={**self._creds, CONF_PROFILE: profile_id}
            )
        return self.async_show_form(
            step_id="reconfigure_profile",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_PROFILE,
                        default=entry.data.get(CONF_PROFILE),
                    ): vol.In(options)
                }
            ),
        )
