from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_point_in_time, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_DURATION,
    ATTR_MEDIA_PLAYER,
    CONF_DEFAULT_MEDIA_PLAYER,
    CONF_DEFAULT_NOTIFY_SERVICE,
    CONF_SPOTIFY_CONFIG_ENTRY_ID,
    CURRENT_QUEUE_OPTION,
    ATTR_NOTIFY_SERVICE,
    ATTR_PLAYLIST_URI,
    ATTR_TIMER_ID,
    DATA_MANAGER,
    DATA_NOTIFY_SERVICE,
    DATA_SPOTIFY_MEDIA_PLAYER,
    DEFAULT_TIMER_ID,
    DOMAIN,
    MAX_PLAYLIST_HISTORY,
    PLATFORMS,
    SPOTIFY_DOMAIN,
    STORAGE_KEY,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)

START_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_MEDIA_PLAYER): cv.entity_id,
        vol.Optional(ATTR_PLAYLIST_URI): cv.string,
        vol.Required(ATTR_DURATION): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Optional(ATTR_NOTIFY_SERVICE): cv.string,
        vol.Optional(ATTR_TIMER_ID, default=DEFAULT_TIMER_ID): cv.string,
    }
)

CANCEL_SERVICE_SCHEMA = vol.Schema(
    {vol.Optional(ATTR_TIMER_ID, default=DEFAULT_TIMER_ID): cv.string}
)


@dataclass
class SleepTimer:
    """State for an active sleep timer."""

    timer_id: str
    media_player: str
    playlist_uri: str | None
    notify_service: str
    started_at: datetime
    ends_at: datetime
    duration: int
    cancel_stop: Callable[[], None]
    cancel_tick: Callable[[], None]

    @property
    def remaining_seconds(self) -> int:
        """Return remaining seconds, clamped to zero."""
        return max(0, int((self.ends_at - dt_util.utcnow()).total_seconds()))


class SpotifySleepTimerManager:
    """Manage Spotify playback timers and notifications."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.timers: dict[str, SleepTimer] = {}
        self.playlist_history: list[str] = []
        self.selected_playlist_uri: str | None = None
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._listeners: set[Callable[[], None]] = set()

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Register a listener for timer state changes."""
        self._listeners.add(listener)

        @callback
        def remove_listener() -> None:
            self._listeners.discard(listener)

        return remove_listener

    @callback
    def async_notify_listeners(self) -> None:
        """Notify entities that timer state changed."""
        for listener in self._listeners:
            listener()

    @property
    def primary_timer(self) -> SleepTimer | None:
        """Return the timer that expires soonest."""
        if not self.timers:
            return None
        return min(self.timers.values(), key=lambda timer: timer.ends_at)

    @property
    def playlist_options(self) -> list[str]:
        """Return the playlist options shown by the select entity."""
        return [CURRENT_QUEUE_OPTION, *self.playlist_history]

    @property
    def selected_playlist_option(self) -> str:
        """Return the current select option."""
        return self.selected_playlist_uri or CURRENT_QUEUE_OPTION

    async def async_load(self) -> None:
        """Load persisted playlist history."""
        data = await self._store.async_load() or {}
        playlist_history = data.get("playlist_history", [])
        if isinstance(playlist_history, list):
            self.playlist_history = [
                playlist
                for playlist in playlist_history[:MAX_PLAYLIST_HISTORY]
                if isinstance(playlist, str)
            ]

        selected_playlist_uri = data.get("selected_playlist_uri")
        if (
            isinstance(selected_playlist_uri, str)
            and selected_playlist_uri in self.playlist_history
        ):
            self.selected_playlist_uri = selected_playlist_uri

    async def async_select_playlist(self, option: str) -> None:
        """Select a playlist option."""
        if option == CURRENT_QUEUE_OPTION:
            self.selected_playlist_uri = None
        elif option in self.playlist_history:
            self.selected_playlist_uri = option
        else:
            raise ValueError(f"Unknown playlist option: {option}")

        await self.async_save_playlist_history()
        self.async_notify_listeners()

    async def async_save_playlist_history(self) -> None:
        """Persist playlist history."""
        await self._store.async_save(
            {
                "playlist_history": self.playlist_history,
                "selected_playlist_uri": self.selected_playlist_uri,
            }
        )

    async def async_remember_playlist(self, playlist_uri: str) -> None:
        """Remember the playlist URI used by the sleep timer."""
        self.playlist_history = [
            playlist
            for playlist in self.playlist_history
            if playlist != playlist_uri
        ]
        self.playlist_history.insert(0, playlist_uri)
        self.playlist_history = self.playlist_history[:MAX_PLAYLIST_HISTORY]
        self.selected_playlist_uri = playlist_uri
        await self.async_save_playlist_history()

    async def async_start(
        self,
        timer_id: str,
        media_player: str,
        playlist_uri: str | None,
        duration: int,
        notify_service: str,
    ) -> None:
        """Start Spotify playback and schedule a sleep timer."""
        playlist_uri = playlist_uri or self.selected_playlist_uri

        if timer_id in self.timers:
            await self.async_cancel(timer_id, send_notification=False)

        if playlist_uri:
            await self.async_remember_playlist(playlist_uri)
            await self.hass.services.async_call(
                "media_player",
                "play_media",
                {
                    ATTR_ENTITY_ID: media_player,
                    "media_content_id": playlist_uri,
                    "media_content_type": "playlist",
                },
                blocking=False,
            )
        else:
            await self.hass.services.async_call(
                "media_player",
                "media_play",
                {ATTR_ENTITY_ID: media_player},
                blocking=False,
            )

        now = dt_util.utcnow()
        ends_at = now + timedelta(seconds=duration)

        async def async_finish(_: datetime) -> None:
            await self.hass.services.async_call(
                "media_player",
                "media_stop",
                {ATTR_ENTITY_ID: media_player},
                blocking=False,
            )
            await self.async_send_notification(
                notify_service,
                timer_id,
                "Spotify sleep timer finished",
                "Playback has been stopped.",
            )
            self.async_remove_timer(timer_id)

        async def async_tick(_: datetime) -> None:
            timer = self.timers.get(timer_id)
            if timer is None:
                return
            await self.async_send_notification(
                timer.notify_service,
                timer.timer_id,
                "Spotify sleep timer",
                f"{format_duration(timer.remaining_seconds)} remaining.",
            )
            self.async_notify_listeners()

        cancel_stop = async_track_point_in_time(self.hass, async_finish, ends_at)
        cancel_tick = async_track_time_interval(
            self.hass, async_tick, timedelta(minutes=1)
        )

        self.timers[timer_id] = SleepTimer(
            timer_id=timer_id,
            media_player=media_player,
            playlist_uri=playlist_uri,
            notify_service=notify_service,
            started_at=now,
            ends_at=ends_at,
            duration=duration,
            cancel_stop=cancel_stop,
            cancel_tick=cancel_tick,
        )

        await self.async_send_notification(
            notify_service,
            timer_id,
            "Spotify sleep timer",
            f"{format_duration(duration)} remaining.",
        )
        self.async_notify_listeners()

    async def async_cancel(
        self, timer_id: str, send_notification: bool = True
    ) -> None:
        """Cancel a timer if it exists."""
        timer = self.timers.get(timer_id)
        if timer is None:
            return

        notify_service = timer.notify_service
        self.async_remove_timer(timer_id)

        if send_notification:
            await self.async_send_notification(
                notify_service,
                timer_id,
                "Spotify sleep timer cancelled",
                "The sleep timer was cancelled.",
            )

    @callback
    def async_remove_timer(self, timer_id: str) -> None:
        """Remove a timer and cancel scheduled callbacks."""
        timer = self.timers.pop(timer_id, None)
        if timer is None:
            return
        timer.cancel_stop()
        timer.cancel_tick()
        self.async_notify_listeners()

    async def async_send_notification(
        self, notify_service: str, timer_id: str, title: str, message: str
    ) -> None:
        """Send or replace a Home Assistant notification."""
        if "." not in notify_service:
            _LOGGER.warning("Invalid notify service: %s", notify_service)
            return

        domain, service = notify_service.split(".", 1)
        if domain == "notify" and not self.hass.services.has_service(
            domain, service
        ):
            if not self.hass.services.has_service("notify", "send_message"):
                _LOGGER.warning("Notify entity service is not available")
                return
            await self.hass.services.async_call(
                "notify",
                "send_message",
                {
                    ATTR_ENTITY_ID: notify_service,
                    "title": title,
                    "message": message,
                },
                blocking=False,
            )
            return

        await self.hass.services.async_call(
            domain,
            service,
            {
                "title": title,
                "message": message,
                "data": {
                    "tag": timer_id,
                    "notification_icon": "mdi:timer-sand",
                },
            },
            blocking=False,
        )


def format_duration(seconds: int) -> str:
    """Format seconds as a compact human-readable duration."""
    minutes = max(0, seconds // 60)
    if minutes < 1:
        return "less than 1 minute"
    hours, minutes = divmod(minutes, 60)
    if hours and minutes:
        return f"{hours} hr {minutes} min"
    if hours:
        return f"{hours} hr"
    return f"{minutes} min"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Spotify Sleep Timer from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][DATA_SPOTIFY_MEDIA_PLAYER] = async_get_spotify_media_player(
        hass, entry
    )
    hass.data[DOMAIN][DATA_NOTIFY_SERVICE] = async_get_default_notify_service(entry)
    manager = hass.data[DOMAIN].get(DATA_MANAGER)
    if manager is None:
        manager = SpotifySleepTimerManager(hass)
        await manager.async_load()
        hass.data[DOMAIN][DATA_MANAGER] = manager
        async_register_services(hass, manager)

    entry.async_on_unload(entry.add_update_listener(async_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options updates."""
    hass.data[DOMAIN][DATA_SPOTIFY_MEDIA_PLAYER] = async_get_spotify_media_player(
        hass, entry
    )
    hass.data[DOMAIN][DATA_NOTIFY_SERVICE] = async_get_default_notify_service(entry)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(DATA_SPOTIFY_MEDIA_PLAYER, None)
        hass.data[DOMAIN].pop(DATA_NOTIFY_SERVICE, None)
    return unload_ok


def async_get_default_notify_service(entry: ConfigEntry) -> str | None:
    """Return the configured default notify target."""
    return entry.options.get(
        CONF_DEFAULT_NOTIFY_SERVICE,
        entry.data.get(CONF_DEFAULT_NOTIFY_SERVICE),
    )


def async_get_spotify_media_player(
    hass: HomeAssistant, entry: ConfigEntry
) -> str | None:
    """Return the media player entity from the linked Spotify config entry."""
    spotify_entry_id = entry.options.get(
        CONF_SPOTIFY_CONFIG_ENTRY_ID,
        entry.data.get(CONF_SPOTIFY_CONFIG_ENTRY_ID),
    )
    if spotify_entry_id is None:
        return None

    spotify_entry = hass.config_entries.async_get_entry(spotify_entry_id)
    if spotify_entry is None or spotify_entry.domain != SPOTIFY_DOMAIN:
        raise ConfigEntryNotReady("Linked Spotify integration is not available")

    configured_media_player = entry.options.get(
        CONF_DEFAULT_MEDIA_PLAYER,
        entry.data.get(CONF_DEFAULT_MEDIA_PLAYER),
    )
    if configured_media_player is not None:
        return configured_media_player

    entity_registry = er.async_get(hass)
    spotify_entities = er.async_entries_for_config_entry(
        entity_registry, spotify_entry_id
    )
    for entity_entry in spotify_entities:
        if entity_entry.domain == "media_player":
            return entity_entry.entity_id

    raise ConfigEntryNotReady("Linked Spotify integration has no media player entity")


@callback
def async_register_services(
    hass: HomeAssistant, manager: SpotifySleepTimerManager
) -> None:
    """Register integration services."""

    async def async_handle_start(call: ServiceCall) -> None:
        data = START_SERVICE_SCHEMA(dict(call.data))
        media_player = data.get(ATTR_MEDIA_PLAYER) or hass.data[DOMAIN].get(
            DATA_SPOTIFY_MEDIA_PLAYER
        )
        if media_player is None:
            raise HomeAssistantError(
                "No Spotify media player was provided or found from the linked "
                "Spotify integration"
            )
        notify_service = data.get(ATTR_NOTIFY_SERVICE) or hass.data[DOMAIN].get(
            DATA_NOTIFY_SERVICE
        )
        if notify_service is None:
            raise HomeAssistantError(
                "No notify entity was provided or configured for Spotify Sleep Timer"
            )

        await manager.async_start(
            timer_id=data[ATTR_TIMER_ID],
            media_player=media_player,
            playlist_uri=data.get(ATTR_PLAYLIST_URI),
            duration=data[ATTR_DURATION],
            notify_service=notify_service,
        )

    async def async_handle_cancel(call: ServiceCall) -> None:
        data = CANCEL_SERVICE_SCHEMA(dict(call.data))
        await manager.async_cancel(data[ATTR_TIMER_ID])

    hass.services.async_register(
        DOMAIN,
        "start",
        async_handle_start,
        schema=START_SERVICE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        "cancel",
        async_handle_cancel,
        schema=CANCEL_SERVICE_SCHEMA,
    )
