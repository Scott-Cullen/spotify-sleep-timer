from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from typing import TYPE_CHECKING

import voluptuous as vol

from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_point_in_time, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

from .const import (
    ATTR_DURATION,
    ATTR_MEDIA_PLAYER,
    CONF_DEFAULT_MEDIA_PLAYER,
    CONF_DEFAULT_NOTIFY_SERVICE,
    CONF_SPOTIFY_CONFIG_ENTRY_ID,
    CURRENT_QUEUE_OPTION,
    ATTR_NOTIFY_SERVICE,
    ATTR_PLAYLIST_NAME,
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
        vol.Optional(ATTR_PLAYLIST_NAME): cv.string,
        vol.Optional(ATTR_PLAYLIST_URI): cv.string,
        vol.Required(ATTR_DURATION): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Optional(ATTR_NOTIFY_SERVICE): cv.string,
        vol.Optional(ATTR_TIMER_ID, default=DEFAULT_TIMER_ID): cv.string,
    }
)

CANCEL_SERVICE_SCHEMA = vol.Schema(
    {vol.Optional(ATTR_TIMER_ID, default=DEFAULT_TIMER_ID): cv.string}
)

SAVE_PLAYLIST_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_PLAYLIST_NAME): cv.string,
        vol.Optional(ATTR_PLAYLIST_URI): cv.string,
    }
)

REMOVE_PLAYLIST_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_PLAYLIST_NAME): cv.string,
        vol.Optional(ATTR_PLAYLIST_URI): cv.string,
    }
)


@dataclass
class PlaylistEntry:
    """A named Spotify playlist saved for the selector."""

    name: str
    uri: str


@dataclass
class SleepTimer:
    """State for an active sleep timer."""

    timer_id: str
    media_player: str
    playlist_name: str | None
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
        self.playlist_history: list[PlaylistEntry] = []
        self.selected_playlist_uri: str | None = None
        self.draft_playlist_name: str | None = None
        self.draft_playlist_uri: str | None = None
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
        return [CURRENT_QUEUE_OPTION, *[entry.name for entry in self.playlist_history]]

    @property
    def selected_playlist_option(self) -> str:
        """Return the current select option."""
        entry = self.playlist_entry_by_uri(self.selected_playlist_uri)
        return entry.name if entry is not None else CURRENT_QUEUE_OPTION

    @callback
    def playlist_entry_by_name(self, name: str) -> PlaylistEntry | None:
        """Return a playlist entry by display name."""
        for entry in self.playlist_history:
            if entry.name == name:
                return entry
        return None

    @callback
    def playlist_entry_by_uri(self, uri: str | None) -> PlaylistEntry | None:
        """Return a playlist entry by URI."""
        if uri is None:
            return None
        for entry in self.playlist_history:
            if entry.uri == uri:
                return entry
        return None

    async def async_load(self) -> None:
        """Load persisted playlist history."""
        data = await self._store.async_load() or {}
        playlist_history = data.get("playlist_history", [])
        if isinstance(playlist_history, list):
            self.playlist_history = normalize_playlist_history(playlist_history)

        selected_playlist_uri = data.get("selected_playlist_uri")
        if (
            isinstance(selected_playlist_uri, str)
            and self.playlist_entry_by_uri(selected_playlist_uri) is not None
        ):
            self.selected_playlist_uri = selected_playlist_uri

        draft_playlist_name = data.get("draft_playlist_name")
        if isinstance(draft_playlist_name, str):
            self.draft_playlist_name = draft_playlist_name

        draft_playlist_uri = data.get("draft_playlist_uri")
        if isinstance(draft_playlist_uri, str):
            self.draft_playlist_uri = draft_playlist_uri

    async def async_select_playlist(self, option: str) -> None:
        """Select a playlist option."""
        if option == CURRENT_QUEUE_OPTION:
            self.selected_playlist_uri = None
        elif (entry := self.playlist_entry_by_name(option)) is not None:
            self.selected_playlist_uri = entry.uri
        else:
            raise ValueError(f"Unknown playlist option: {option}")

        await self.async_save_playlist_history()
        self.async_notify_listeners()

    async def async_save_playlist_history(self) -> None:
        """Persist playlist history."""
        await self._store.async_save(
            {
                "playlist_history": [
                    {"name": entry.name, "uri": entry.uri}
                    for entry in self.playlist_history
                ],
                "selected_playlist_uri": self.selected_playlist_uri,
                "draft_playlist_name": self.draft_playlist_name,
                "draft_playlist_uri": self.draft_playlist_uri,
            }
        )

    async def async_set_draft_playlist_name(self, playlist_name: str) -> None:
        """Set the draft playlist name used by the dashboard."""
        self.draft_playlist_name = playlist_name.strip() or None
        await self.async_save_playlist_history()
        self.async_notify_listeners()

    async def async_set_draft_playlist_uri(self, playlist_uri: str) -> None:
        """Set the draft playlist URI used by the dashboard."""
        self.draft_playlist_uri = playlist_uri.strip() or None
        await self.async_save_playlist_history()
        self.async_notify_listeners()

    async def async_remember_playlist(
        self, playlist_uri: str, playlist_name: str | None = None
    ) -> None:
        """Remember the playlist URI used by the sleep timer."""
        playlist_name = normalize_playlist_name(playlist_name, playlist_uri)
        self.playlist_history = [
            entry
            for entry in self.playlist_history
            if entry.uri != playlist_uri and entry.name != playlist_name
        ]
        self.playlist_history.insert(
            0, PlaylistEntry(name=playlist_name, uri=playlist_uri)
        )
        self.playlist_history = self.playlist_history[:MAX_PLAYLIST_HISTORY]
        self.selected_playlist_uri = playlist_uri
        await self.async_save_playlist_history()
        self.async_notify_listeners()

    async def async_remove_playlist(
        self,
        playlist_uri: str | None = None,
        playlist_name: str | None = None,
    ) -> None:
        """Remove a saved playlist from the selector."""
        entry = None
        if playlist_uri is not None:
            entry = self.playlist_entry_by_uri(playlist_uri)
        elif playlist_name is not None:
            entry = self.playlist_entry_by_name(playlist_name)
        elif self.selected_playlist_uri is not None:
            entry = self.playlist_entry_by_uri(self.selected_playlist_uri)

        if entry is None:
            raise HomeAssistantError("No saved playlist was selected or provided")

        self.playlist_history = [
            playlist for playlist in self.playlist_history if playlist.uri != entry.uri
        ]
        if self.selected_playlist_uri == entry.uri:
            self.selected_playlist_uri = None
        await self.async_save_playlist_history()
        self.async_notify_listeners()

    async def async_start(
        self,
        timer_id: str,
        media_player: str,
        playlist_name: str | None,
        playlist_uri: str | None,
        duration: int,
        notify_service: str,
    ) -> None:
        """Start Spotify playback and schedule a sleep timer."""
        playlist_uri = playlist_uri or self.selected_playlist_uri

        if timer_id in self.timers:
            await self.async_cancel(timer_id, send_notification=False)

        if playlist_uri:
            playlist_entry = self.playlist_entry_by_uri(playlist_uri)
            playlist_name = playlist_name or (
                playlist_entry.name if playlist_entry is not None else None
            )
            await self.async_remember_playlist(playlist_uri, playlist_name)
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
            await self.async_clear_notification(notify_service, timer_id)
            self.async_remove_timer(timer_id)

        async def async_tick(_: datetime) -> None:
            timer = self.timers.get(timer_id)
            if timer is None:
                return
            self.async_notify_listeners()

        cancel_stop = async_track_point_in_time(self.hass, async_finish, ends_at)
        cancel_tick = async_track_time_interval(
            self.hass, async_tick, timedelta(minutes=1)
        )

        self.timers[timer_id] = SleepTimer(
            timer_id=timer_id,
            media_player=media_player,
            playlist_name=normalize_playlist_name(playlist_name, playlist_uri)
            if playlist_uri
            else None,
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
            "Playback will stop when the timer reaches zero.",
            {
                "alert_once": True,
                "chronometer": True,
                "persistent": True,
                "sticky": True,
                "tag": timer_id,
                "when": duration,
                "when_relative": True,
            },
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
            await self.async_clear_notification(notify_service, timer_id)

    @callback
    def async_remove_timer(self, timer_id: str) -> None:
        """Remove a timer and cancel scheduled callbacks."""
        timer = self.timers.pop(timer_id, None)
        if timer is None:
            return
        timer.cancel_stop()
        timer.cancel_tick()
        self.async_notify_listeners()

    async def async_clear_notification(self, notify_service: str, timer_id: str) -> None:
        """Clear a tagged Home Assistant notification."""
        await self.async_send_notification(
            notify_service,
            timer_id,
            "",
            "clear_notification",
        )

    async def async_send_notification(
        self,
        notify_service: str,
        timer_id: str,
        title: str,
        message: str,
        notification_data: dict[str, object] | None = None,
    ) -> None:
        """Send or replace a Home Assistant notification."""
        if "." not in notify_service:
            _LOGGER.warning("Invalid notify service: %s", notify_service)
            return

        payload_data = {
            "tag": timer_id,
            "notification_icon": "mdi:timer-sand",
            **(notification_data or {}),
        }
        domain, service = notify_service.split(".", 1)
        if domain == "notify" and self.hass.states.get(notify_service) is not None:
            mobile_app_service = self.async_get_mobile_app_notify_service(
                notify_service
            )
            if mobile_app_service is not None and (
                notification_data or message == "clear_notification"
            ):
                service_data = {
                    "message": message,
                    "data": payload_data,
                }
                if title:
                    service_data["title"] = title
                await self.hass.services.async_call(
                    "notify",
                    mobile_app_service,
                    service_data,
                    blocking=False,
                )
                return

            if notification_data:
                raise HomeAssistantError(
                    "Android countdown notification data is not supported by "
                    "notify.send_message, and no matching Companion App "
                    f"mobile-app notify action was found for {notify_service}"
                )

            if message == "clear_notification":
                return
            if not self.hass.services.has_service("notify", "send_message"):
                _LOGGER.warning("Notify entity service is not available")
                return
            service_data = {
                ATTR_ENTITY_ID: notify_service,
                "message": message,
            }
            if title:
                service_data["title"] = title
            await self.hass.services.async_call(
                "notify",
                "send_message",
                service_data,
                blocking=False,
            )
            return

        if domain == "notify" and not self.hass.services.has_service(
            domain, service
        ):
            _LOGGER.warning("Notify service not found: %s", notify_service)
            return

        service_data = {
            "message": message,
            "data": payload_data,
        }
        if title:
            service_data["title"] = title
        await self.hass.services.async_call(
            domain, service, service_data, blocking=False
        )

    @callback
    def async_get_mobile_app_notify_service(self, notify_entity: str) -> str | None:
        """Return the mobile app notify service matching a notify entity."""
        _, object_id = notify_entity.split(".", 1)
        mobile_app_service = f"mobile_app_{object_id}"
        if self.hass.services.has_service("notify", mobile_app_service):
            return mobile_app_service
        return None


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


def normalize_playlist_history(history: list[object]) -> list[PlaylistEntry]:
    """Return playlist history entries, migrating URL-only history."""
    entries: list[PlaylistEntry] = []
    seen_names: set[str] = set()
    seen_uris: set[str] = set()

    for item in history:
        if isinstance(item, str):
            name = playlist_name_from_uri(item)
            uri = item
        elif isinstance(item, dict):
            uri = item.get("uri")
            name = item.get("name")
            if not isinstance(uri, str):
                continue
            name = normalize_playlist_name(name if isinstance(name, str) else None, uri)
        else:
            continue

        if name in seen_names or uri in seen_uris:
            continue
        entries.append(PlaylistEntry(name=name, uri=uri))
        seen_names.add(name)
        seen_uris.add(uri)
        if len(entries) >= MAX_PLAYLIST_HISTORY:
            break

    return entries


def normalize_playlist_name(playlist_name: str | None, playlist_uri: str) -> str:
    """Return a friendly playlist name."""
    if playlist_name is not None and playlist_name.strip():
        return playlist_name.strip()
    return playlist_name_from_uri(playlist_uri)


def playlist_name_from_uri(playlist_uri: str) -> str:
    """Return a readable fallback name from a Spotify playlist URI or URL."""
    playlist_id = playlist_uri.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
    if ":" in playlist_id:
        playlist_id = playlist_id.rsplit(":", 1)[-1]
    if playlist_id:
        return f"Playlist {playlist_id[:8]}"
    return "Spotify playlist"


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
            playlist_name=data.get(ATTR_PLAYLIST_NAME),
            playlist_uri=data.get(ATTR_PLAYLIST_URI),
            duration=data[ATTR_DURATION],
            notify_service=notify_service,
        )

    async def async_handle_cancel(call: ServiceCall) -> None:
        data = CANCEL_SERVICE_SCHEMA(dict(call.data))
        await manager.async_cancel(data[ATTR_TIMER_ID])

    async def async_handle_save_playlist(call: ServiceCall) -> None:
        data = SAVE_PLAYLIST_SCHEMA(dict(call.data))
        playlist_name = data.get(ATTR_PLAYLIST_NAME) or manager.draft_playlist_name
        playlist_uri = data.get(ATTR_PLAYLIST_URI) or manager.draft_playlist_uri
        if playlist_name is None or playlist_uri is None:
            raise HomeAssistantError(
                "Playlist name and playlist URI must be provided or entered "
                "on the Spotify Sleep Timer dashboard"
            )
        await manager.async_remember_playlist(
            playlist_uri,
            playlist_name,
        )

    async def async_handle_remove_playlist(call: ServiceCall) -> None:
        data = REMOVE_PLAYLIST_SCHEMA(dict(call.data))
        await manager.async_remove_playlist(
            playlist_uri=data.get(ATTR_PLAYLIST_URI),
            playlist_name=data.get(ATTR_PLAYLIST_NAME),
        )

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
    hass.services.async_register(
        DOMAIN,
        "save_playlist",
        async_handle_save_playlist,
        schema=SAVE_PLAYLIST_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        "remove_playlist",
        async_handle_remove_playlist,
        schema=REMOVE_PLAYLIST_SCHEMA,
    )
