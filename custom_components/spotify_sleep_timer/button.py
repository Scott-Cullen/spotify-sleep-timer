from __future__ import annotations

from collections.abc import Callable

from homeassistant.components.button import ButtonEntity
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
    """Set up Spotify Sleep Timer button entities."""
    manager: SpotifySleepTimerManager = hass.data[DOMAIN][DATA_MANAGER]
    async_add_entities(
        [
            SpotifySleepTimerSavePlaylistButton(manager),
            SpotifySleepTimerRemovePlaylistButton(manager),
        ]
    )


class SpotifySleepTimerButton(ButtonEntity):
    """Base class for Spotify Sleep Timer buttons."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, manager: SpotifySleepTimerManager) -> None:
        self._manager = manager
        self._remove_listener: Callable[[], None] | None = None

    async def async_added_to_hass(self) -> None:
        """Subscribe to playlist changes."""
        self._remove_listener = self._manager.async_add_listener(
            self.async_write_ha_state
        )

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe from playlist changes."""
        if self._remove_listener is not None:
            self._remove_listener()
            self._remove_listener = None


class SpotifySleepTimerSavePlaylistButton(SpotifySleepTimerButton):
    """Button that saves the playlist draft to the selector."""

    _attr_icon = "mdi:playlist-plus"
    _attr_name = "Save playlist"
    _attr_suggested_object_id = f"{DOMAIN}_save_playlist"
    _attr_unique_id = f"{DOMAIN}_save_playlist"

    @property
    def available(self) -> bool:
        """Return whether the playlist draft can be saved."""
        return (
            self._manager.draft_playlist_name is not None
            and self._manager.draft_playlist_uri is not None
        )

    async def async_press(self) -> None:
        """Save the playlist draft."""
        playlist_name = self._manager.draft_playlist_name
        playlist_uri = self._manager.draft_playlist_uri
        if playlist_name is None or playlist_uri is None:
            raise HomeAssistantError(
                "Enter a playlist name and playlist URL before saving"
            )
        await self._manager.async_remember_playlist(playlist_uri, playlist_name)


class SpotifySleepTimerRemovePlaylistButton(SpotifySleepTimerButton):
    """Button that removes the selected playlist from the selector."""

    _attr_icon = "mdi:playlist-remove"
    _attr_name = "Remove playlist"
    _attr_suggested_object_id = f"{DOMAIN}_remove_playlist"
    _attr_unique_id = f"{DOMAIN}_remove_playlist"

    @property
    def available(self) -> bool:
        """Return whether a saved playlist is selected."""
        return self._manager.selected_playlist_uri is not None

    async def async_press(self) -> None:
        """Remove the selected playlist."""
        await self._manager.async_remove_playlist()
