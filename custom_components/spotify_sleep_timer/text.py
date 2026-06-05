from __future__ import annotations

from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SpotifySleepTimerManager
from .const import DATA_MANAGER, DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Spotify Sleep Timer text entities."""
    manager: SpotifySleepTimerManager = hass.data[DOMAIN][DATA_MANAGER]
    async_add_entities(
        [
            SpotifySleepTimerPlaylistNameText(manager),
            SpotifySleepTimerPlaylistUriText(manager),
        ]
    )


class SpotifySleepTimerPlaylistNameText(TextEntity):
    """Text entity for the playlist name draft."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:playlist-edit"
    _attr_name = "Playlist name"
    _attr_should_poll = False
    _attr_suggested_object_id = f"{DOMAIN}_playlist_name"
    _attr_unique_id = f"{DOMAIN}_playlist_name"

    def __init__(self, manager: SpotifySleepTimerManager) -> None:
        self._manager = manager
        self._remove_listener = None

    async def async_added_to_hass(self) -> None:
        """Subscribe to draft changes."""
        self._remove_listener = self._manager.async_add_listener(
            self.async_write_ha_state
        )

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe from draft changes."""
        if self._remove_listener is not None:
            self._remove_listener()
            self._remove_listener = None

    @property
    def native_value(self) -> str | None:
        """Return the draft playlist name."""
        return self._manager.draft_playlist_name

    async def async_set_value(self, value: str) -> None:
        """Set the draft playlist name."""
        await self._manager.async_set_draft_playlist_name(value)


class SpotifySleepTimerPlaylistUriText(TextEntity):
    """Text entity for the playlist URI draft."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:link-variant"
    _attr_name = "Playlist URL"
    _attr_should_poll = False
    _attr_suggested_object_id = f"{DOMAIN}_playlist_url"
    _attr_unique_id = f"{DOMAIN}_playlist_url"

    def __init__(self, manager: SpotifySleepTimerManager) -> None:
        self._manager = manager
        self._remove_listener = None

    async def async_added_to_hass(self) -> None:
        """Subscribe to draft changes."""
        self._remove_listener = self._manager.async_add_listener(
            self.async_write_ha_state
        )

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe from draft changes."""
        if self._remove_listener is not None:
            self._remove_listener()
            self._remove_listener = None

    @property
    def native_value(self) -> str | None:
        """Return the draft playlist URI."""
        return self._manager.draft_playlist_uri

    async def async_set_value(self, value: str) -> None:
        """Set the draft playlist URI."""
        await self._manager.async_set_draft_playlist_uri(value)
