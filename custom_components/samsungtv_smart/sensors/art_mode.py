"""Art mode-related sensors for Samsung TV Smart integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.core import HomeAssistant

from ..api.smartthings import STStatus
from ..api.samsungws import ArtModeStatus
from .base import SamsungTVSensorBase, SamsungTVArtSensorBase

_LOGGING = logging.getLogger(__name__)


class SamsungTVStatusSensor(SamsungTVSensorBase):
    """Representation of a Samsung TV status sensor (off/on/art)."""

    _attr_device_class = None
    _attr_icon = "mdi:television"

    def __init__(self, config: dict[str, Any], entry_id: str, hass: HomeAssistant) -> None:
        """Initialize the sensor."""
        super().__init__(config, entry_id, hass, use_channel_info=False)
        
        self._attr_name = "TV Status"
        self._attr_unique_id = f"{self.unique_id}_tv_status"

    @property
    def native_value(self) -> str:
        """Return the state of the sensor."""
        if not self._st:
            return "unknown"
        
        return self._st.tv_status

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._st is not None


class SamsungTVArtModeStatusSensor(SamsungTVArtSensorBase):
    """Representation of a Samsung TV art mode status sensor."""

    _attr_device_class = None
    _attr_icon = "mdi:palette"

    def __init__(self, config: dict[str, Any], entry_id: str, hass: HomeAssistant) -> None:
        """Initialize the sensor."""
        super().__init__(config, entry_id, hass, use_channel_info=True)
        
        self._attr_name = "Art Mode Status"
        self._attr_unique_id = f"{self.unique_id}_art_mode_status"

    @property
    def native_value(self) -> str:
        """Return the state of the sensor."""
        # Check if TV is on first
        if not self._st or self._st.state != STStatus.STATE_ON:
            return "off"
        
        # Use WebSocket API if available for more accurate status
        if self._ws and self._ws.artmode_status != ArtModeStatus.Unsupported:
            if self._ws.artmode_status == ArtModeStatus.On:
                return "on"
            elif self._ws.artmode_status == ArtModeStatus.Off:
                return "off"
            elif self._ws.artmode_status == ArtModeStatus.Unavailable:
                return "unavailable"
        
        # Fallback: Check if channel name is exactly "art" (case-insensitive)
        channel_name = self._st.channel_name
        if channel_name and channel_name.lower() == "art":
            return "on"
        
        # Check SmartThings art mode property
        return "on" if self._st.art_mode else "off"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        attributes = {}
        
        # Add WebSocket-specific attributes
        if self._ws and self.art_mode_supported:
            attributes["art_mode_supported"] = True
            attributes["connection_method"] = "websocket"
            
            # Get art settings via WebSocket
            art_settings = self.get_art_settings()
            if art_settings:
                attributes.update(art_settings)
        else:
            attributes["art_mode_supported"] = False
            attributes["connection_method"] = "smartthings"
        
        # Add SmartThings attributes as fallback
        if self._st:
            attributes["smartthings_available"] = True
            if hasattr(self._st, 'art_mode'):
                attributes["smartthings_art_mode"] = self._st.art_mode

        return attributes

    def get_art_settings(self) -> dict[str, Any] | None:
        """Get comprehensive art settings."""
        if not self._ws or not self.art_mode_supported:
            return None

        try:
            settings = {}

            # Get brightness
            brightness = self._ws.get_art_brightness()
            if brightness is not None:
                settings["brightness"] = brightness

            # Get color temperature
            color_temp = self._ws.get_art_color_temperature()
            if color_temp is not None:
                settings["color_temperature"] = color_temp

            # Get slideshow status
            slideshow = self._ws.get_slideshow_status()
            if slideshow:
                settings["slideshow_enabled"] = slideshow.get("value", "off") != "off"
                settings["slideshow_duration"] = slideshow.get("value", "off")
                settings["slideshow_type"] = slideshow.get("type", "slideshow")
                settings["slideshow_category"] = slideshow.get("category_id", "MY-C0002")

            # Get auto rotation status
            auto_rotation = self._ws.get_auto_rotation_status()
            if auto_rotation:
                settings["auto_rotation_enabled"] = auto_rotation.get("value", "off") != "off"
                settings["auto_rotation_duration"] = auto_rotation.get("value", "off")
                settings["auto_rotation_type"] = auto_rotation.get("type", "slideshow")
                settings["auto_rotation_category"] = auto_rotation.get("category_id", "MY-C0002")

            # Get general art mode settings
            art_settings = self._ws.get_artmode_settings()
            if art_settings:
                if isinstance(art_settings, list):
                    for setting in art_settings:
                        if isinstance(setting, dict) and "item" in setting and "value" in setting:
                            settings[f"artmode_{setting['item']}"] = setting["value"]
                elif isinstance(art_settings, dict):
                    settings["artmode_settings"] = art_settings

            return settings
        except Exception as e:
            _LOGGING.debug("Failed to get art settings: %s", e)
            return None


class SamsungTVArtBrightnessSensor(SamsungTVArtSensorBase):
    """Representation of a Samsung TV art mode brightness sensor."""

    _attr_device_class = None
    _attr_icon = "mdi:brightness-6"
    _attr_native_unit_of_measurement = "%"

    def __init__(self, config: dict[str, Any], entry_id: str, hass: HomeAssistant) -> None:
        """Initialize the sensor."""
        super().__init__(config, entry_id, hass, use_channel_info=False)

        self._attr_name = "Art Mode Brightness"
        self._attr_unique_id = f"{self.unique_id}_art_brightness"

    @property
    def native_value(self) -> int | None:
        """Return the brightness value."""
        if not self._ws or not self.art_mode_supported:
            return None

        try:
            return self._ws.get_art_brightness()
        except Exception as e:
            _LOGGING.debug("Failed to get art brightness: %s", e)
            return None


class SamsungTVArtColorTemperatureSensor(SamsungTVArtSensorBase):
    """Representation of a Samsung TV art mode color temperature sensor."""

    _attr_device_class = None
    _attr_icon = "mdi:thermometer"

    def __init__(self, config: dict[str, Any], entry_id: str, hass: HomeAssistant) -> None:
        """Initialize the sensor."""
        super().__init__(config, entry_id, hass, use_channel_info=False)

        self._attr_name = "Art Mode Color Temperature"
        self._attr_unique_id = f"{self.unique_id}_art_color_temperature"

    @property
    def native_value(self) -> int | None:
        """Return the color temperature value."""
        if not self._ws or not self.art_mode_supported:
            return None

        try:
            return self._ws.get_art_color_temperature()
        except Exception as e:
            _LOGGING.debug("Failed to get art color temperature: %s", e)
            return None


class SamsungTVArtSlideshowSensor(SamsungTVArtSensorBase):
    """Representation of a Samsung TV art mode slideshow sensor."""

    _attr_device_class = None
    _attr_icon = "mdi:slideshow"

    def __init__(self, config: dict[str, Any], entry_id: str, hass: HomeAssistant) -> None:
        """Initialize the sensor."""
        super().__init__(config, entry_id, hass, use_channel_info=False)

        self._attr_name = "Art Mode Slideshow"
        self._attr_unique_id = f"{self.unique_id}_art_slideshow"

    @property
    def native_value(self) -> str:
        """Return the slideshow status."""
        if not self._ws or not self.art_mode_supported:
            return "unavailable"

        try:
            slideshow = self._ws.get_slideshow_status()
            if slideshow:
                return "on" if slideshow.get("value", "off") != "off" else "off"
            return "off"
        except Exception as e:
            _LOGGING.debug("Failed to get slideshow status: %s", e)
            return "unknown"

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


class SamsungTVArtAutoRotationSensor(SamsungTVArtSensorBase):
    """Representation of a Samsung TV art mode auto rotation sensor."""

    _attr_device_class = None
    _attr_icon = "mdi:rotate-3d-variant"

    def __init__(self, config: dict[str, Any], entry_id: str, hass: HomeAssistant) -> None:
        """Initialize the sensor."""
        super().__init__(config, entry_id, hass, use_channel_info=False)

        self._attr_name = "Art Mode Auto Rotation"
        self._attr_unique_id = f"{self.unique_id}_art_auto_rotation"

    @property
    def native_value(self) -> str:
        """Return the auto rotation status."""
        if not self._ws or not self.art_mode_supported:
            return "unavailable"

        try:
            auto_rotation = self._ws.get_auto_rotation_status()
            if auto_rotation:
                return "on" if auto_rotation.get("value", "off") != "off" else "off"
            return "off"
        except Exception as e:
            _LOGGING.debug("Failed to get auto rotation status: %s", e)
            return "unknown"

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


class SamsungTVCurrentArtworkSensor(SamsungTVArtSensorBase):
    """Representation of a Samsung TV current artwork sensor."""

    _attr_device_class = None
    _attr_icon = "mdi:image-frame"

    def __init__(self, config: dict[str, Any], entry_id: str, hass: HomeAssistant) -> None:
        """Initialize the sensor."""
        super().__init__(config, entry_id, hass, use_channel_info=False)

        self._attr_name = "Current Artwork"
        self._attr_unique_id = f"{self.unique_id}_current_artwork"

    @property
    def native_value(self) -> str | None:
        """Return the current artwork content ID or name."""
        if not self._ws or not self.art_mode_supported:
            return None

        try:
            current = self._ws.get_current_artwork()
            if current:
                return current.get("content_id") or current.get("title", "Unknown")
            return None
        except Exception as e:
            _LOGGING.debug("Failed to get current artwork: %s", e)
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        attributes = {}

        if not self._ws or not self.art_mode_supported:
            return attributes

        try:
            current = self._ws.get_current_artwork()
            if current:
                # Include all artwork details as attributes
                for key, value in current.items():
                    if key not in ['content_id']:  # Avoid duplicating the state value
                        attributes[key] = value
        except Exception as e:
            _LOGGING.debug("Failed to get current artwork attributes: %s", e)

        return attributes


class SamsungTVAvailableArtworksSensor(SamsungTVArtSensorBase):
    """Representation of a Samsung TV available artworks count sensor."""

    _attr_device_class = None
    _attr_icon = "mdi:image-multiple"

    def __init__(self, config: dict[str, Any], entry_id: str, hass: HomeAssistant) -> None:
        """Initialize the sensor."""
        super().__init__(config, entry_id, hass, use_channel_info=False)

        self._attr_name = "Available Artworks"
        self._attr_unique_id = f"{self.unique_id}_available_artworks"

    @property
    def native_value(self) -> int | None:
        """Return the count of available artworks."""
        if not self._ws or not self.art_mode_supported:
            return None

        try:
            artworks = self._ws.get_available_artworks()
            return len(artworks) if artworks else 0
        except Exception as e:
            _LOGGING.debug("Failed to get available artworks: %s", e)
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        attributes = {}

        if not self._ws or not self.art_mode_supported:
            return attributes

        try:
            artworks = self._ws.get_available_artworks()
            if artworks:
                # Group by category
                categories = {}
                for artwork in artworks:
                    category = artwork.get("category_id", "unknown")
                    if category not in categories:
                        categories[category] = []
                    categories[category].append({
                        "content_id": artwork.get("content_id"),
                        "title": artwork.get("title", "Unknown"),
                        "category": artwork.get("category")
                    })

                attributes["categories"] = categories
                attributes["total_count"] = len(artworks)
        except Exception as e:
            _LOGGING.debug("Failed to get available artworks attributes: %s", e)

        return attributes


class SamsungTVApiVersionSensor(SamsungTVArtSensorBase):
    """Representation of a Samsung TV art API version sensor."""

    _attr_device_class = None
    _attr_icon = "mdi:api"

    def __init__(self, config: dict[str, Any], entry_id: str, hass: HomeAssistant) -> None:
        """Initialize the sensor."""
        super().__init__(config, entry_id, hass, use_channel_info=False)

        self._attr_name = "Art API Version"
        self._attr_unique_id = f"{self.unique_id}_art_api_version"

    @property
    def native_value(self) -> str | None:
        """Return the API version."""
        if not self._ws or not self.art_mode_supported:
            return None

        try:
            return self._ws.get_api_version()
        except Exception as e:
            _LOGGING.debug("Failed to get API version: %s", e)
            return None


class SamsungTVDeviceInfoSensor(SamsungTVArtSensorBase):
    """Representation of a Samsung TV comprehensive device info sensor."""

    _attr_device_class = None
    _attr_icon = "mdi:information"

    def __init__(self, config: dict[str, Any], entry_id: str, hass: HomeAssistant) -> None:
        """Initialize the sensor."""
        super().__init__(config, entry_id, hass, use_channel_info=False)

        self._attr_name = "Device Information"
        self._attr_unique_id = f"{self.unique_id}_device_info"

    @property
    def native_value(self) -> str | None:
        """Return a summary of device info."""
        if not self._ws or not self.art_mode_supported:
            return None

        try:
            device_info = self._ws.get_device_info()
            if device_info:
                # Return a summary value
                model = device_info.get("device_name", "Unknown")
                return f"{model}"
            return None
        except Exception as e:
            _LOGGING.debug("Failed to get device info: %s", e)
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the device information as attributes."""
        attributes = {}

        if not self._ws or not self.art_mode_supported:
            return attributes

        try:
            device_info = self._ws.get_device_info()
            if device_info:
                # Include all device info as attributes
                for key, value in device_info.items():
                    # Clean up attribute names
                    attr_name = key.replace("_", " ").title()
                    attributes[attr_name] = value

                # Add API version as well
                api_version = self._ws.get_api_version()
                if api_version:
                    attributes["Art API Version"] = api_version

        except Exception as e:
            _LOGGING.debug("Failed to get device info attributes: %s", e)

        return attributes
