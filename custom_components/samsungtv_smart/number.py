"""Number entities for Samsung TV Smart integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DATA_CFG, DOMAIN
from .sensors.base import SamsungTVArtSensorBase

_LOGGING = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Samsung TV Number entities based on a config entry."""
    config = hass.data[DOMAIN][entry.entry_id][DATA_CFG]

    entities = []

    # Only add art-related number entities if Frame TV is supported
    # Check if we have WebSocket configuration
    host = config.get("host")
    if host:
        # Check if art mode is supported before adding entities
        try:
            from .api.samsungws import SamsungTVWS
            temp_ws = SamsungTVWS(
                host=host,
                port=config.get("port", 8002),
                token=config.get("token"),
                name=config.get("ws_name", "SamsungTvRemote"),
            )
            if temp_ws.art().supported():
                entities.extend([
                    SamsungTVArtBrightnessNumber(config, entry.entry_id, hass),
                    SamsungTVArtColorTemperatureNumber(config, entry.entry_id, hass),
                    SamsungTVSlideshowDurationNumber(config, entry.entry_id, hass),
                    SamsungTVAutoRotationDurationNumber(config, entry.entry_id, hass),
                ])
            temp_ws.close()
        except Exception as e:
            _LOGGING.debug("Failed to check art mode support: %s", e)

    if entities:
        async_add_entities(entities, True)


class SamsungTVArtNumberBase(SamsungTVArtSensorBase, NumberEntity):
    """Base class for Samsung TV art mode number entities."""

    _attr_mode = NumberMode.SLIDER

    def __init__(self, config: dict[str, Any], entry_id: str, hass: HomeAssistant) -> None:
        """Initialize the number entity."""
        super().__init__(config, entry_id, hass, use_channel_info=False)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return super().available and self.art_mode_supported


class SamsungTVArtBrightnessNumber(SamsungTVArtNumberBase):
    """Number entity for art mode brightness control."""

    _attr_icon = "mdi:brightness-6"
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "%"

    def __init__(self, config: dict[str, Any], entry_id: str, hass: HomeAssistant) -> None:
        """Initialize the brightness number entity."""
        super().__init__(config, entry_id, hass)

        self._attr_name = "Art Mode Brightness"
        self._attr_unique_id = f"{self.unique_id}_art_brightness_control"

    @property
    def native_value(self) -> float | None:
        """Return the current brightness value."""
        if not self._ws or not self.art_mode_supported:
            return None

        try:
            return self._ws.get_art_brightness()
        except Exception as e:
            _LOGGING.debug("Failed to get art brightness: %s", e)
            return None

    async def async_set_native_value(self, value: float) -> None:
        """Set the brightness value."""
        if not self._ws or not self.art_mode_supported:
            return

        try:
            success = await self.hass.async_add_executor_job(
                self._ws.set_art_brightness, int(value)
            )
            if success:
                self.async_write_ha_state()
        except Exception as e:
            _LOGGING.error("Failed to set art brightness: %s", e)


class SamsungTVArtColorTemperatureNumber(SamsungTVArtNumberBase):
    """Number entity for art mode color temperature control."""

    _attr_icon = "mdi:thermometer"
    _attr_native_min_value = 0
    _attr_native_max_value = 10
    _attr_native_step = 1

    def __init__(self, config: dict[str, Any], entry_id: str, hass: HomeAssistant) -> None:
        """Initialize the color temperature number entity."""
        super().__init__(config, entry_id, hass)

        self._attr_name = "Art Mode Color Temperature"
        self._attr_unique_id = f"{self.unique_id}_art_color_temperature_control"

    @property
    def native_value(self) -> float | None:
        """Return the current color temperature value."""
        if not self._ws or not self.art_mode_supported:
            return None

        try:
            return self._ws.get_art_color_temperature()
        except Exception as e:
            _LOGGING.debug("Failed to get art color temperature: %s", e)
            return None

    async def async_set_native_value(self, value: float) -> None:
        """Set the color temperature value."""
        if not self._ws or not self.art_mode_supported:
            return

        try:
            success = await self.hass.async_add_executor_job(
                self._ws.set_art_color_temperature, int(value)
            )
            if success:
                self.async_write_ha_state()
        except Exception as e:
            _LOGGING.error("Failed to set art color temperature: %s", e)


class SamsungTVSlideshowDurationNumber(SamsungTVArtNumberBase):
    """Number entity for slideshow duration control."""

    _attr_icon = "mdi:slideshow"
    _attr_native_min_value = 0
    _attr_native_max_value = 1440  # 24 hours in minutes
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "min"

    def __init__(self, config: dict[str, Any], entry_id: str, hass: HomeAssistant) -> None:
        """Initialize the slideshow duration number entity."""
        super().__init__(config, entry_id, hass)

        self._attr_name = "Slideshow Duration"
        self._attr_unique_id = f"{self.unique_id}_slideshow_duration_control"

    @property
    def native_value(self) -> float | None:
        """Return the current slideshow duration value."""
        if not self._ws or not self.art_mode_supported:
            return None

        try:
            slideshow = self._ws.get_slideshow_status()
            if slideshow and slideshow.get("value") != "off":
                # Value is in minutes, extract numeric part
                duration_str = slideshow.get("value", "0")
                if isinstance(duration_str, str) and duration_str.isdigit():
                    return int(duration_str)
                elif isinstance(duration_str, (int, float)):
                    return float(duration_str)
            return 0
        except Exception as e:
            _LOGGING.debug("Failed to get slideshow duration: %s", e)
            return None

    async def async_set_native_value(self, value: float) -> None:
        """Set the slideshow duration value."""
        if not self._ws or not self.art_mode_supported:
            return

        try:
            # Enable slideshow with the specified duration
            success = await self.hass.async_add_executor_job(
                self._ws.set_slideshow,
                value > 0,  # enabled if value > 0
                int(value) if value > 0 else None,  # duration_minutes
                True,  # shuffle
                2  # category (My Pictures)
            )
            if success:
                self.async_write_ha_state()
        except Exception as e:
            _LOGGING.error("Failed to set slideshow duration: %s", e)


class SamsungTVAutoRotationDurationNumber(SamsungTVArtNumberBase):
    """Number entity for auto rotation duration control."""

    _attr_icon = "mdi:rotate-3d-variant"
    _attr_native_min_value = 0
    _attr_native_max_value = 1440  # 24 hours in minutes
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "min"

    def __init__(self, config: dict[str, Any], entry_id: str, hass: HomeAssistant) -> None:
        """Initialize the auto rotation duration number entity."""
        super().__init__(config, entry_id, hass)

        self._attr_name = "Auto Rotation Duration"
        self._attr_unique_id = f"{self.unique_id}_auto_rotation_duration_control"

    @property
    def native_value(self) -> float | None:
        """Return the current auto rotation duration value."""
        if not self._ws or not self.art_mode_supported:
            return None

        try:
            auto_rotation = self._ws.get_auto_rotation_status()
            if auto_rotation and auto_rotation.get("value") != "off":
                # Value is in minutes, extract numeric part
                duration_str = auto_rotation.get("value", "0")
                if isinstance(duration_str, str) and duration_str.isdigit():
                    return int(duration_str)
                elif isinstance(duration_str, (int, float)):
                    return float(duration_str)
            return 0
        except Exception as e:
            _LOGGING.debug("Failed to get auto rotation duration: %s", e)
            return None

    async def async_set_native_value(self, value: float) -> None:
        """Set the auto rotation duration value."""
        if not self._ws or not self.art_mode_supported:
            return

        try:
            # Enable auto rotation with the specified duration
            success = await self.hass.async_add_executor_job(
                self._ws.set_auto_rotation,
                value > 0,  # enabled if value > 0
                int(value) if value > 0 else None,  # duration_minutes
                True,  # shuffle
                2  # category (My Pictures)
            )
            if success:
                self.async_write_ha_state()
        except Exception as e:
            _LOGGING.error("Failed to set auto rotation duration: %s", e)