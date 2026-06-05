from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_DEFAULT_MEDIA_PLAYER,
    CONF_DEFAULT_NOTIFY_SERVICE,
    CONF_SPOTIFY_CONFIG_ENTRY_ID,
    DOMAIN,
    SPOTIFY_DOMAIN,
)


def _spotify_schema(user_input: dict[str, Any] | None = None) -> vol.Schema:
    """Return the schema for selecting the Spotify integration to use."""
    user_input = user_input or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_SPOTIFY_CONFIG_ENTRY_ID,
                default=user_input.get(CONF_SPOTIFY_CONFIG_ENTRY_ID),
            ): selector.selector(
                {"config_entry": {"integration": SPOTIFY_DOMAIN}}
            ),
            vol.Required(
                CONF_DEFAULT_MEDIA_PLAYER,
                default=user_input.get(CONF_DEFAULT_MEDIA_PLAYER),
            ): selector.selector(
                {
                    "entity": {
                        "domain": "media_player",
                        "integration": SPOTIFY_DOMAIN,
                    }
                }
            ),
            vol.Required(
                CONF_DEFAULT_NOTIFY_SERVICE,
                default=user_input.get(CONF_DEFAULT_NOTIFY_SERVICE),
            ): selector.selector({"entity": {"domain": "notify"}}),
        }
    )


class SpotifySleepTimerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Spotify Sleep Timer."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Create the integration config entry."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if not self.hass.config_entries.async_entries(SPOTIFY_DOMAIN):
            return self.async_abort(reason="spotify_not_configured")

        if user_input is not None:
            return self.async_create_entry(
                title="Spotify Sleep Timer",
                data=user_input,
            )

        return self.async_show_form(
            step_id="user",
            data_schema=_spotify_schema(),
            description_placeholders={},
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return SpotifySleepTimerOptionsFlow(config_entry)


class SpotifySleepTimerOptionsFlow(config_entries.OptionsFlow):
    """Options flow for Spotify Sleep Timer."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage Spotify Sleep Timer options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = {
            CONF_SPOTIFY_CONFIG_ENTRY_ID: self._config_entry.options.get(
                CONF_SPOTIFY_CONFIG_ENTRY_ID,
                self._config_entry.data.get(CONF_SPOTIFY_CONFIG_ENTRY_ID),
            ),
            CONF_DEFAULT_MEDIA_PLAYER: self._config_entry.options.get(
                CONF_DEFAULT_MEDIA_PLAYER,
                self._config_entry.data.get(CONF_DEFAULT_MEDIA_PLAYER),
            ),
            CONF_DEFAULT_NOTIFY_SERVICE: self._config_entry.options.get(
                CONF_DEFAULT_NOTIFY_SERVICE,
                self._config_entry.data.get(CONF_DEFAULT_NOTIFY_SERVICE),
            ),
        }
        return self.async_show_form(
            step_id="init",
            data_schema=_spotify_schema(current),
        )
