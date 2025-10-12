"""Support for Samsung TV Art Mode sensors."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.components.media_player.const import DOMAIN as MP_DOMAIN
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later, async_track_state_change_event

from .const import DATA_CFG, DATA_WS, DOMAIN
from .entity import SamsungTVEntity
from .slideshow import SlideshowQueueManager

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
        ws_instance = hass.data[DOMAIN][config_entry.entry_id].get(DATA_WS)
        queue_manager = hass.data[DOMAIN][config_entry.entry_id].get("slideshow_queue")

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
            ArtModeStatusSensor(config, config_entry.entry_id, media_player_entity_id, ws_instance),
            CurrentArtworkSensor(config, config_entry.entry_id, media_player_entity_id, ws_instance),
            SlideshowStatusSensor(config, config_entry.entry_id, media_player_entity_id, ws_instance),
        ]
        if queue_manager:
            entities.append(SlideshowNextArtwork(config, config_entry.entry_id, media_player_entity_id, ws_instance, queue_manager))

        async_add_entities(entities, True)
        _LOGGER.debug(
            "Successfully set up art mode sensors for %s",
            config.get(CONF_HOST, "unknown")
        )

    # Wait for TV media player entity to be created and art mode detection to complete
    async_call_later(hass, 10, _add_art_mode_sensors)


class ArtModeSensorBase(SamsungTVEntity, SensorEntity):
    """Base class for art mode sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        config: dict[str, Any],
        entry_id: str,
        media_player_entity_id: str,
        ws_instance: Any = None,
    ) -> None:
        """Initialize the base art mode sensor."""
        super().__init__(config, entry_id)
        self._media_player_entity_id = media_player_entity_id
        self._ws = ws_instance

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

    def _get_media_player_state(self):
        """Get the current media player state."""
        return self.hass.states.get(self._media_player_entity_id)

    def _get_ws_data(self, data_key: str, default=None):
        """Get data from the websocket instance."""
        if not self._ws:
            return default
        return getattr(self._ws, data_key, default)


class ArtModeStatusSensor(ArtModeSensorBase):
    """Sensor for art mode on/off status."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["on", "off", "unavailable"]
    _attr_name = "Art mode status"
    _attr_icon = "mdi:television-ambient-light"

    def __init__(
        self,
        config: dict[str, Any],
        entry_id: str,
        media_player_entity_id: str,
        ws_instance: Any = None,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(config, entry_id, media_player_entity_id, ws_instance)
        self._attr_unique_id = f"{self.unique_id}_art_mode_status"

    @property
    def native_value(self) -> str | None:
        """Return the state of the sensor."""
        # Try to get status directly from websocket first
        if self._ws:
            artmode_status = self._get_ws_data("artmode_status")
            if artmode_status is not None:
                # Convert enum to string
                if hasattr(artmode_status, 'name'):
                    status_name = artmode_status.name.lower()
                    if status_name == "on":
                        return "on"
                    elif status_name == "off":
                        return "off"
                    elif status_name in ["unavailable", "unsupported"]:
                        return "unavailable"

        # Fallback to media player attributes
        media_player_state = self._get_media_player_state()
        if not media_player_state:
            return "unavailable"

        art_mode_status = media_player_state.attributes.get("art_mode_status")
        if art_mode_status in ["on", "off", "unavailable"]:
            return art_mode_status

        return "unavailable"

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional state attributes."""
        value = self.native_value
        attrs = {
            "is_art_mode": value == "on",
            "is_available": value != "unavailable",
            "media_player_entity_id": self._media_player_entity_id,
        }

        # Add current artwork info if available from websocket
        if self._ws:
            current_artwork = self._get_ws_data("_current_artwork")
            if current_artwork and isinstance(current_artwork, dict):
                attrs["current_artwork"] = current_artwork

        return attrs


class CurrentArtworkSensor(ArtModeSensorBase):
    """Sensor for currently displayed artwork information."""

    _attr_name = "Current artwork"
    _attr_icon = "mdi:image-frame"

    def __init__(
        self,
        config: dict[str, Any],
        entry_id: str,
        media_player_entity_id: str,
        ws_instance: Any = None,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(config, entry_id, media_player_entity_id, ws_instance)
        self._attr_unique_id = f"{self.unique_id}_current_artwork"

    @property
    def native_value(self) -> str | None:
        """Return the name/title of the current artwork."""
        current_artwork = self._get_current_artwork_data()
        if not current_artwork:
            return None

        # Try different fields for artwork name
        for field in ["title", "name", "content_name", "artwork_name"]:
            if field in current_artwork and current_artwork[field]:
                return current_artwork[field]

        # Fallback to content_id if no name available
        return current_artwork.get("content_id", "Unknown")

    def _get_current_artwork_data(self) -> dict[str, Any] | None:
        """Get current artwork data from websocket."""
        if not self._ws:
            return None

        current_artwork = self._get_ws_data("_current_artwork")
        if current_artwork and isinstance(current_artwork, dict):
            return current_artwork

        return None

    @property
    def available(self) -> bool:
        """Return True if entity is available and art mode is on."""
        if not super().available:
            return False

        # Only available when art mode is actually on
        if self._ws:
            artmode_status = self._get_ws_data("artmode_status")
            if artmode_status and hasattr(artmode_status, 'name'):
                return artmode_status.name.lower() == "on"

        return False

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional artwork attributes."""
        current_artwork = self._get_current_artwork_data()
        if not current_artwork:
            return {"media_player_entity_id": self._media_player_entity_id}

        attrs = {
            "media_player_entity_id": self._media_player_entity_id,
            "content_id": current_artwork.get("content_id"),
            "category": current_artwork.get("category"),
            "category_id": current_artwork.get("category_id"),
            "thumbnail_url": current_artwork.get("thumbnail_url"),
            "full_data": current_artwork,
        }

        # Add any additional fields that might be available
        for field in ["artist", "description", "created_date", "file_type", "dimensions"]:
            if field in current_artwork:
                attrs[field] = current_artwork[field]

        return attrs


class SlideshowStatusSensor(ArtModeSensorBase):
    """Sensor for slideshow status and settings."""

    _attr_name = "Slideshow status"
    _attr_icon = "mdi:slideshow"

    def __init__(
        self,
        config: dict[str, Any],
        entry_id: str,
        media_player_entity_id: str,
        ws_instance: Any = None,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(config, entry_id, media_player_entity_id, ws_instance)
        self._attr_unique_id = f"{self.unique_id}_slideshow_status"
        self._slideshow_data = None

    @property
    def native_value(self) -> str | None:
        """Return the slideshow status."""
        slideshow_data = self._get_slideshow_data()
        if not slideshow_data:
            return "unknown"

        # Try different fields for slideshow status
        for status_field in ["value", "status", "state", "enabled", "running"]:
            if status_field in slideshow_data:
                status = slideshow_data[status_field]
                if isinstance(status, bool):
                    return "on" if status else "off"
                elif isinstance(status, str):
                    return status.lower()

        return "unknown"

    def _get_slideshow_data(self) -> dict[str, Any] | None:
        """Get slideshow data from websocket."""
        if not self._ws:
            return self._slideshow_data

        # Get current slideshow status from websocket
        slideshow_status = self._get_ws_data("_slideshow_status")
        if slideshow_status and isinstance(slideshow_status, dict):
            self._slideshow_data = slideshow_status
            return slideshow_status

        # Request slideshow status if not available
        if self._ws and hasattr(self._ws, 'request_slideshow_status'):
            self._ws.request_slideshow_status()

        return self._slideshow_data

    @property
    def available(self) -> bool:
        """Return True if entity is available and art mode is supported."""
        if not super().available:
            return False

        # Available when art mode is supported (not necessarily on)
        if self._ws:
            artmode_status = self._get_ws_data("artmode_status")
            if artmode_status and hasattr(artmode_status, 'name'):
                return artmode_status.name.lower() != "unsupported"

        return True

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional slideshow attributes."""
        attrs = {"media_player_entity_id": self._media_player_entity_id}

        slideshow_data = self._get_slideshow_data()
        if slideshow_data:
            attrs.update({
                "interval": slideshow_data.get("interval"),
                "category": slideshow_data.get("category"),
                "random_order": slideshow_data.get("random_order"),
                "full_data": slideshow_data,
            })

        return attrs


class SlideshowNextArtwork(SamsungTVEntity, SensorEntity):
    """Sensor for time to next artwork in slideshow."""

    _attr_has_entity_name = True
    _attr_name = "Slideshow time to next"
    _attr_icon = "mdi:timer-sand"
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS

    def __init__(
        self,
        config: dict[str, Any],
        entry_id: str,
        media_player_entity_id: str,
        ws_instance: Any,
        queue_manager: SlideshowQueueManager,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(config, entry_id)
        self._media_player_entity_id = media_player_entity_id
        self._ws = ws_instance
        self._queue_manager = queue_manager
        self._attr_unique_id = f"{entry_id}_slideshow_next_artwork"
        self._switch_entity_id = f"switch.{entry_id.replace('-', '_')}_slideshow"
        self._next_artwork_at: datetime | None = None

    async def async_added_to_hass(self) -> None:
        """Set up state change tracking."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [self._switch_entity_id], self._handle_switch_update
            )
        )

    @callback
    def _handle_switch_update(self, event) -> None:
        """Handle slideshow switch state changes."""
        new_state = event.data.get("new_state")
        if not new_state:
            return

        is_on = new_state.state == "on"
        if is_on:
            interval = new_state.attributes.get("interval", 10) * 60
            self._next_artwork_at = datetime.utcnow() + timedelta(seconds=interval)
        else:
            self._next_artwork_at = None
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        media_player_state = self.hass.states.get(self._media_player_entity_id)
        if not media_player_state:
            return False
        art_mode_supported = media_player_state.attributes.get("art_mode_supported", False)
        return art_mode_supported and self._ws is not None

    @property
    def native_value(self) -> int | None:
        """Return time to next artwork in seconds."""
        if not self._next_artwork_at:
            return None

        remaining = (self._next_artwork_at - datetime.utcnow()).total_seconds()
        return max(0, int(remaining))