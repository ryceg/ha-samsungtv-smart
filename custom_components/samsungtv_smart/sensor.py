"""Support for Samsung TV Art Mode sensors."""

from __future__ import annotations

from datetime import datetime
import logging
from typing import Any

from homeassistant.components.media_player.const import DOMAIN as MP_DOMAIN
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later, async_track_state_change_event

from .const import DATA_CFG, DOMAIN
from .entity import SamsungTVEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Samsung TV art mode sensors."""

    @callback
    def _add_art_mode_sensors(utc_now: datetime) -> None:
        """Create art mode sensors after media player is ready."""
        config = hass.data[DOMAIN][config_entry.entry_id][DATA_CFG]

        # Find the media player entity for this TV using entity registry
        entity_reg = er.async_get(hass)
        tv_entries = er.async_entries_for_config_entry(entity_reg, config_entry.entry_id)
        media_player_entity_id = None

        for tv_entity in tv_entries:
            if tv_entity.domain == MP_DOMAIN:
                media_player_entity_id = tv_entity.entity_id
                break

        if not media_player_entity_id:
            _LOGGER.debug("Media player entity not found for art mode sensors")
            return

        # Check if art mode is supported via media player attributes
        media_player_state = hass.states.get(media_player_entity_id)
        if not media_player_state:
            _LOGGER.debug("Media player state not available yet")
            return

        attributes = media_player_state.attributes
        if not attributes.get("art_mode_supported", False):
            _LOGGER.debug(
                "Art mode not supported on %s, skipping sensor setup",
                config.get(CONF_HOST, "unknown")
            )
            return

        # Create art mode sensors
        entities = [
            ArtModeStatusSensor(config, config_entry.entry_id, media_player_entity_id),
        ]
        async_add_entities(entities, True)
        _LOGGER.debug(
            "Successfully set up art mode sensors for %s",
            config.get(CONF_HOST, "unknown")
        )

    # Wait for TV media player entity to be created and art mode detection to complete
    async_call_later(hass, 10, _add_art_mode_sensors)


class ArtModeStatusSensor(SamsungTVEntity, SensorEntity):
    """Sensor for art mode on/off status."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["on", "off", "unavailable"]
    _attr_has_entity_name = True
    _attr_name = "Art mode status"
    _attr_icon = "mdi:television-ambient-light"

    def __init__(
        self,
        config: dict[str, Any],
        entry_id: str,
        media_player_entity_id: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(config, entry_id)
        self._media_player_entity_id = media_player_entity_id
        self._attr_unique_id = f"{self.unique_id}_art_mode_status"

    async def async_added_to_hass(self) -> None:
        """Set up state change tracking when entity is added to hass."""
        await super().async_added_to_hass()

        # Track media player state changes
        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                [self._media_player_entity_id],
                self._handle_media_player_update
            )
        )

    @callback
    def _handle_media_player_update(self, event) -> None:
        """Handle media player state changes."""
        if event.data.get("entity_id") == self._media_player_entity_id:
            self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        media_player_state = self.hass.states.get(self._media_player_entity_id)
        return (
            media_player_state is not None
            and media_player_state.attributes.get("art_mode_supported", False)
        )

    @property
    def native_value(self) -> str | None:
        """Return the state of the sensor."""
        media_player_state = self.hass.states.get(self._media_player_entity_id)
        if not media_player_state:
            return None

        art_mode_status = media_player_state.attributes.get("art_mode_status")

        # Map media player attribute values to sensor options
        if art_mode_status == "on":
            return "on"
        elif art_mode_status == "off":
            return "off"
        elif art_mode_status == "unavailable":
            return "unavailable"

        # Default to unavailable if status is unclear
        return "unavailable"

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional state attributes."""
        media_player_state = self.hass.states.get(self._media_player_entity_id)
        if not media_player_state:
            return None

        value = self.native_value
        attrs = {
            "is_art_mode": value == "on",
            "is_available": value != "unavailable",
            "media_player_entity_id": self._media_player_entity_id,
        }

        # Add current artwork info if available from media player
        current_artwork = media_player_state.attributes.get("current_artwork")
        if current_artwork and isinstance(current_artwork, dict):
            # Expose artwork data fields for automations/scripts
            attrs["current_artwork"] = current_artwork

        return attrs