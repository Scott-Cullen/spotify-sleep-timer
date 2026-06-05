from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SpotifySleepTimerManager
from .const import DATA_MANAGER, DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Spotify Sleep Timer select entities."""
    manager: SpotifySleepTimerManager = hass.data[DOMAIN][DATA_MANAGER]
    async_add_entities([SpotifySleepTimerPlaylistSelect(manager)])


class SpotifySleepTimerPlaylistSelect(SelectEntity):
    """Select a recent playlist or current Spotify queue."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:playlist-music"
    _attr_name = "Playlist"
    _attr_should_poll = False
    _attr_suggested_object_id = f"{DOMAIN}_playlist"
    _attr_unique_id = f"{DOMAIN}_playlist"

    def __init__(self, manager: SpotifySleepTimerManager) -> None:
        self._manager = manager
        self._remove_listener = None

    async def async_added_to_hass(self) -> None:
        """Subscribe to playlist history changes."""
        self._remove_listener = self._manager.async_add_listener(
            self.async_write_ha_state
        )

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe from playlist history changes."""
        if self._remove_listener is not None:
            self._remove_listener()
            self._remove_listener = None

    @property
    def options(self) -> list[str]:
        """Return available playlist options."""
        return self._manager.playlist_options

    @property
    def current_option(self) -> str:
        """Return the current playlist option."""
        return self._manager.selected_playlist_option

    async def async_select_option(self, option: str) -> None:
        """Select a playlist option."""
        try:
            await self._manager.async_select_playlist(option)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return selected playlist details."""
        entry = self._manager.playlist_entry_by_uri(
            self._manager.selected_playlist_uri
        )
        if entry is None:
            return {"playlist_uri": None}
        return {
            "playlist_name": entry.name,
            "playlist_uri": entry.uri,
            "playlists": [
                {"name": playlist.name, "uri": playlist.uri}
                for playlist in self._manager.playlist_history
            ],
        }
