"""Support for Samsung TV Art Mode number entities."""

from __future__ import annotations

from datetime import datetime
import logging
from typing import Any

from homeassistant.components.media_player.const import DOMAIN as MP_DOMAIN
from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later, async_track_state_change_event

from .const import DATA_CFG, DATA_WS, DOMAIN
from .entity import SamsungTVEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Samsung TV art mode number entities."""
    # Also set up slideshow number entities
    from .slideshow import async_setup_entry as slideshow_setup
    await slideshow_setup(hass, config_entry, async_add_entities)

    @callback
    def _add_art_mode_numbers(utc_now: datetime) -> None:
        """Create art mode number entities after media player is ready."""
        config = hass.data[DOMAIN][config_entry.entry_id][DATA_CFG]
        ws_instance = hass.data[DOMAIN][config_entry.entry_id].get(DATA_WS)

        # Find the media player entity for this TV using entity registry
        entity_reg = er.async_get(hass)
        tv_entries = er.async_entries_for_config_entry(entity_reg, config_entry.entry_id)
        media_player_entity_id = None

        for tv_entity in tv_entries:
            if tv_entity.domain == MP_DOMAIN:
                media_player_entity_id = tv_entity.entity_id
                break

        if not media_player_entity_id:
            _LOGGER.debug("Media player entity not found for art mode number entities")
            return

        # Check if art mode is supported via media player attributes
        media_player_state = hass.states.get(media_player_entity_id)
        if not media_player_state:
            _LOGGER.debug("Media player state not available yet")
            return

        attributes = media_player_state.attributes
        if not attributes.get("art_mode_supported", False):
            _LOGGER.debug(
                "Art mode not supported on %s, skipping number entity setup",
                config.get(CONF_HOST, "unknown")
            )
            return

        # Create art mode number entities
        entities = [
            ArtBrightnessNumber(config, config_entry.entry_id, media_player_entity_id, ws_instance),
            ArtColorTemperatureNumber(config, config_entry.entry_id, media_player_entity_id, ws_instance),
        ]
        async_add_entities(entities, True)
        _LOGGER.debug(
            "Successfully set up art mode number entities for %s",
            config.get(CONF_HOST, "unknown")
        )

    # Wait for TV media player entity to be created and art mode detection to complete
    async_call_later(hass, 10, _add_art_mode_numbers)


class ArtModeNumberBase(SamsungTVEntity, NumberEntity):
    """Base class for art mode number entities."""

    _attr_has_entity_name = True
    _attr_mode = NumberMode.SLIDER

    def __init__(
        self,
        config: dict[str, Any],
        entry_id: str,
        media_player_entity_id: str,
        ws_instance: Any = None,
    ) -> None:
        """Initialize the base art mode number entity."""
        super().__init__(config, entry_id)
        self._media_player_entity_id = media_player_entity_id
        self._ws = ws_instance
        self._entry_id = entry_id

    def _get_ws_data(self, attr_name: str) -> Any:
        """Get data from WebSocket instance safely."""
        if not self._ws or not hasattr(self._ws, attr_name):
            return None
        return getattr(self._ws, attr_name, None)

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
            # Update state when media player changes
            self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        media_player_state = self.hass.states.get(self._media_player_entity_id)
        if not media_player_state:
            return False

        # Available if art mode is supported and WebSocket is connected
        art_mode_supported = media_player_state.attributes.get("art_mode_supported", False)

        return art_mode_supported and self._ws is not None


class ArtBrightnessNumber(ArtModeNumberBase):
    """Number entity for Art Mode brightness control."""

    _attr_name = "Art mode brightness"
    _attr_icon = "mdi:brightness-6"
    _attr_native_step = 1
    _attr_native_min_value = 0
    _attr_native_max_value = 10

    def __init__(
        self,
        config: dict[str, Any],
        entry_id: str,
        media_player_entity_id: str,
        ws_instance: Any = None,
    ) -> None:
        """Initialize the brightness number entity."""
        super().__init__(config, entry_id, media_player_entity_id, ws_instance)
        self._attr_unique_id = f"{entry_id}_art_brightness_control"

        # Try to get dynamic range from TV
        if self._ws and hasattr(self._ws, 'get_brightness_range'):
            try:
                min_val, max_val = self._ws.get_brightness_range()
                if min_val is not None and max_val is not None:
                    self._attr_native_min_value = min_val
                    self._attr_native_max_value = max_val
            except Exception as exc:
                _LOGGER.debug("Could not get brightness range from TV: %s", exc)

    @property
    def native_value(self) -> float | None:
        """Return the current brightness value."""
        if not self._ws or not hasattr(self._ws, 'get_brightness'):
            return None

        try:
            brightness = self._ws.get_brightness()
            if brightness is not None:
                return float(brightness)
        except Exception as exc:
            _LOGGER.debug("Error getting brightness: %s", exc)

        return None

    async def async_set_native_value(self, value: float) -> None:
        """Update the brightness value."""
        if not self._ws or not hasattr(self._ws, 'set_brightness'):
            _LOGGER.error("WebSocket API not available for setting brightness")
            return

        try:
            # Run in executor since WebSocket operation is synchronous
            await self.hass.async_add_executor_job(
                self._ws.set_brightness, int(value)
            )
            _LOGGER.debug("Set art mode brightness to %d", int(value))

            # Request state update
            self.async_write_ha_state()
        except Exception as exc:
            _LOGGER.error("Error setting brightness to %d: %s", int(value), exc)


class ArtColorTemperatureNumber(ArtModeNumberBase):
    """Number entity for Art Mode color temperature control."""

    _attr_name = "Art mode color temperature"
    _attr_icon = "mdi:thermometer"
    _attr_native_step = 1
    _attr_native_min_value = -50
    _attr_native_max_value = 50

    def __init__(
        self,
        config: dict[str, Any],
        entry_id: str,
        media_player_entity_id: str,
        ws_instance: Any = None,
    ) -> None:
        """Initialize the color temperature number entity."""
        super().__init__(config, entry_id, media_player_entity_id, ws_instance)
        self._attr_unique_id = f"{entry_id}_art_color_temperature_control"

        # Try to get dynamic range from TV
        if self._ws and hasattr(self._ws, 'get_color_temperature_range'):
            try:
                min_val, max_val = self._ws.get_color_temperature_range()
                if min_val is not None and max_val is not None:
                    self._attr_native_min_value = min_val
                    self._attr_native_max_value = max_val
            except Exception as exc:
                _LOGGER.debug("Could not get color temperature range from TV: %s", exc)

    @property
    def native_value(self) -> float | None:
        """Return the current color temperature value."""
        if not self._ws or not hasattr(self._ws, 'get_color_temperature'):
            return None

        try:
            temp = self._ws.get_color_temperature()
            if temp is not None:
                return float(temp)
        except Exception as exc:
            _LOGGER.debug("Error getting color temperature: %s", exc)

        return None

    async def async_set_native_value(self, value: float) -> None:
        """Update the color temperature value."""
        if not self._ws or not hasattr(self._ws, 'set_color_temperature'):
            _LOGGER.error("WebSocket API not available for setting color temperature")
            return

        try:
            # Run in executor since WebSocket operation is synchronous
            await self.hass.async_add_executor_job(
                self._ws.set_color_temperature, int(value)
            )
            _LOGGER.debug("Set art mode color temperature to %d", int(value))

            # Request state update
            self.async_write_ha_state()
        except Exception as exc:
            _LOGGER.error("Error setting color temperature to %d: %s", int(value), exc)
