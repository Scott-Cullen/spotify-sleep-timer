from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DATA_MANAGER, DOMAIN
from . import SpotifySleepTimerManager

SENSOR_DESCRIPTION = SensorEntityDescription(
    key="active_timer",
    name="Spotify Sleep Timer",
    icon="mdi:timer-sand",
    native_unit_of_measurement=UnitOfTime.MINUTES,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Spotify Sleep Timer sensor."""
    manager: SpotifySleepTimerManager = hass.data[DOMAIN][DATA_MANAGER]
    async_add_entities([SpotifySleepTimerSensor(manager)])


class SpotifySleepTimerSensor(SensorEntity):
    """Sensor showing the active Spotify sleep timer."""

    entity_description = SENSOR_DESCRIPTION
    _attr_has_entity_name = True
    _attr_name = None
    _attr_suggested_object_id = DOMAIN
    _attr_unique_id = f"{DOMAIN}_active_timer"

    def __init__(self, manager: SpotifySleepTimerManager) -> None:
        self._manager = manager
        self._remove_listener = None

    async def async_added_to_hass(self) -> None:
        """Subscribe to timer changes."""
        self._remove_listener = self._manager.async_add_listener(
            self.async_write_ha_state
        )

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe from timer changes."""
        if self._remove_listener is not None:
            self._remove_listener()
            self._remove_listener = None

    @property
    def native_value(self) -> int | None:
        """Return remaining minutes for the primary active timer."""
        timer = self._manager.primary_timer
        if timer is None:
            return None
        return (timer.remaining_seconds + 59) // 60

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return details about active timers."""
        timer = self._manager.primary_timer
        active_timers = {
            timer_id: {
                "media_player": active.media_player,
                "playlist_name": active.playlist_name,
                "playlist_uri": active.playlist_uri,
                "duration": active.duration,
                "remaining_seconds": active.remaining_seconds,
                "remaining_minutes": (active.remaining_seconds + 59) // 60,
                "ends_at": active.ends_at.isoformat(),
            }
            for timer_id, active in self._manager.timers.items()
        }
        if timer is None:
            return {"active_timers": active_timers}
        return {
            "timer_id": timer.timer_id,
            "media_player": timer.media_player,
            "playlist_name": timer.playlist_name,
            "playlist_uri": timer.playlist_uri,
            "duration": timer.duration,
            "remaining_seconds": timer.remaining_seconds,
            "remaining_minutes": (timer.remaining_seconds + 59) // 60,
            "ends_at": timer.ends_at.isoformat(),
            "active_timers": active_timers,
        }
