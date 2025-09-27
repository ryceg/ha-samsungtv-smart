"""Binary sensor entities for Samsung TV Smart integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DATA_CFG, DOMAIN
from .sensors.base import SamsungTVArtSensorBase

_LOGGING = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Samsung TV Binary Sensor entities based on a config entry."""
    config = hass.data[DOMAIN][entry.entry_id][DATA_CFG]

    entities = []

    # Only add art-related binary sensors if Frame TV is supported
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
                    SamsungTVArtModeSupportedBinarySensor(config, entry.entry_id, hass),
                    SamsungTVSlideshowActiveBinarySensor(config, entry.entry_id, hass),
                    SamsungTVAutoRotationActiveBinarySensor(config, entry.entry_id, hass),
                ])
            temp_ws.close()
        except Exception as e:
            _LOGGING.debug("Failed to check art mode support: %s", e)

    if entities:
        async_add_entities(entities, True)


class SamsungTVArtBinarySensorBase(SamsungTVArtSensorBase, BinarySensorEntity):
    """Base class for Samsung TV art mode binary sensor entities."""

    def __init__(self, config: dict[str, Any], entry_id: str, hass: HomeAssistant) -> None:
        """Initialize the binary sensor entity."""
        super().__init__(config, entry_id, hass, use_channel_info=False)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return super().available and self.art_mode_supported


class SamsungTVArtModeSupportedBinarySensor(SamsungTVArtBinarySensorBase):
    """Binary sensor for Frame TV art mode support detection."""

    _attr_device_class = None
    _attr_icon = "mdi:television-guide"

    def __init__(self, config: dict[str, Any], entry_id: str, hass: HomeAssistant) -> None:
        """Initialize the art mode supported binary sensor."""
        super().__init__(config, entry_id, hass)

        self._attr_name = "Art Mode Supported"
        self._attr_unique_id = f"{self.unique_id}_art_mode_supported"

    @property
    def is_on(self) -> bool:
        """Return True if art mode is supported."""
        return self.art_mode_supported

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        attributes = {}

        if self._ws:
            try:
                # Get API version if available
                api_version = self._ws.get_api_version()
                if api_version:
                    attributes["api_version"] = api_version

                # Get device info if available
                device_info = self._ws.get_device_info()
                if device_info:
                    attributes["device_info"] = device_info

            except Exception as e:
                _LOGGING.debug("Failed to get art mode attributes: %s", e)

        return attributes


class SamsungTVSlideshowActiveBinarySensor(SamsungTVArtBinarySensorBase):
    """Binary sensor for slideshow active status."""

    _attr_device_class = None
    _attr_icon = "mdi:slideshow"

    def __init__(self, config: dict[str, Any], entry_id: str, hass: HomeAssistant) -> None:
        """Initialize the slideshow active binary sensor."""
        super().__init__(config, entry_id, hass)

        self._attr_name = "Slideshow Active"
        self._attr_unique_id = f"{self.unique_id}_slideshow_active"

    @property
    def is_on(self) -> bool:
        """Return True if slideshow is currently active."""
        if not self._ws or not self.art_mode_supported:
            return False

        try:
            slideshow = self._ws.get_slideshow_status()
            if slideshow:
                return slideshow.get("value", "off") != "off"
            return False
        except Exception as e:
            _LOGGING.debug("Failed to get slideshow status: %s", e)
            return False

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        attributes = {}

        if not self._ws or not self.art_mode_supported:
            return attributes

        try:
            slideshow = self._ws.get_slideshow_status()
            if slideshow:
                attributes["duration"] = slideshow.get("value", "off")
                attributes["type"] = slideshow.get("type", "slideshow")
                attributes["category"] = slideshow.get("category_id", "MY-C0002")
        except Exception as e:
            _LOGGING.debug("Failed to get slideshow attributes: %s", e)

        return attributes


class SamsungTVAutoRotationActiveBinarySensor(SamsungTVArtBinarySensorBase):
    """Binary sensor for auto rotation active status."""

    _attr_device_class = None
    _attr_icon = "mdi:rotate-3d-variant"

    def __init__(self, config: dict[str, Any], entry_id: str, hass: HomeAssistant) -> None:
        """Initialize the auto rotation active binary sensor."""
        super().__init__(config, entry_id, hass)

        self._attr_name = "Auto Rotation Active"
        self._attr_unique_id = f"{self.unique_id}_auto_rotation_active"

    @property
    def is_on(self) -> bool:
        """Return True if auto rotation is currently active."""
        if not self._ws or not self.art_mode_supported:
            return False

        try:
            auto_rotation = self._ws.get_auto_rotation_status()
            if auto_rotation:
                return auto_rotation.get("value", "off") != "off"
            return False
        except Exception as e:
            _LOGGING.debug("Failed to get auto rotation status: %s", e)
            return False

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        attributes = {}

        if not self._ws or not self.art_mode_supported:
            return attributes

        try:
            auto_rotation = self._ws.get_auto_rotation_status()
            if auto_rotation:
                attributes["duration"] = auto_rotation.get("value", "off")
                attributes["type"] = auto_rotation.get("type", "slideshow")
                attributes["category"] = auto_rotation.get("category_id", "MY-C0002")
        except Exception as e:
            _LOGGING.debug("Failed to get auto rotation attributes: %s", e)

        return attributes