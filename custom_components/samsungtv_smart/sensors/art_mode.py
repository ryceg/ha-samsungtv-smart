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
        if self._st and self._st.art_mode:
            if self._st.art_brightness is not None:
                attributes.setdefault("brightness", self._st.art_brightness)
            
            if self._st.art_matting is not None:
                attributes.setdefault("matting_style", self._st.art_matting)
            
            if self._st.art_sleep_timer is not None:
                attributes.setdefault("sleep_timer", self._st.art_sleep_timer)
        
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
        """Return the state of the sensor."""
        # Use WebSocket API for detailed artwork information
        if self._ws and self.art_mode_active:
            current_artwork = self.get_current_artwork()
            if current_artwork:
                _LOGGING.debug("Current artwork response: %s", current_artwork)
                # Extract artwork name from WebSocket response
                artwork_name = (
                    current_artwork.get("name") or 
                    current_artwork.get("content_id") or
                    current_artwork.get("title")
                )
                _LOGGING.debug("Extracted artwork name: %s", artwork_name)
                return artwork_name
            else:
                _LOGGING.debug("No current artwork data received from WebSocket")
        else:
            _LOGGING.debug("WebSocket not available or art mode not active (ws=%s, art_active=%s)", 
                          bool(self._ws), self.art_mode_active)
        
        # Fallback to SmartThings API (limited info)
        if self._st and self._st.art_mode:
            return self._st.current_artwork
        
        # Return None when art mode is off or no artwork
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        attributes = {}
        
        # Add WebSocket artwork details
        if self._ws and self.art_mode_active:
            current_artwork = self.get_current_artwork()
            if current_artwork:
                # Add artwork metadata
                attributes.update({
                    "content_id": current_artwork.get("content_id"),
                    "category_id": current_artwork.get("category_id"), 
                    "matte_id": current_artwork.get("matte_id"),
                    "portrait_matte_id": current_artwork.get("portrait_matte_id"),
                    "content_type": current_artwork.get("content_type"),
                    "description": current_artwork.get("description"),
                    "artist": current_artwork.get("artist"),
                    "source": "websocket",
                })
                
                # Legacy fields for backward compatibility
                attributes["category"] = current_artwork.get("category_id")
                attributes["artwork_type"] = current_artwork.get("content_type")
                
                # Try to download the actual image data
                content_id = current_artwork.get("content_id")
                if content_id:
                    try:
                        thumbnail_data = self.download_artwork_thumbnail(content_id)
                        if thumbnail_data:
                            import base64
                            attributes["image_data"] = base64.b64encode(thumbnail_data).decode('utf-8')
                            attributes["image_size"] = len(thumbnail_data)
                            # Detect image format
                            if thumbnail_data.startswith(b'\xff\xd8\xff'):
                                attributes["image_format"] = "jpeg"
                                attributes["image_mime_type"] = "image/jpeg"
                            elif thumbnail_data.startswith(b'\x89PNG'):
                                attributes["image_format"] = "png"
                                attributes["image_mime_type"] = "image/png"
                            else:
                                attributes["image_format"] = "unknown"
                            _LOGGING.debug("Downloaded thumbnail: %d bytes (%s)", 
                                         len(thumbnail_data), attributes.get("image_format", "unknown"))
                        else:
                            _LOGGING.debug("Failed to download thumbnail for content_id: %s", content_id)
                    except Exception as ex:
                        _LOGGING.debug("Exception downloading thumbnail: %s", ex)
                
                # Check if response contains any direct image URLs (fallback)
                image_urls = self._extract_image_urls(current_artwork)
                if image_urls:
                    attributes["image_urls"] = image_urls
                    # Set primary image URL if any direct URLs are found
                    for primary_field in ["image_url", "imageUrl", "image", "url"]:
                        if primary_field in image_urls:
                            attributes["image_url"] = image_urls[primary_field]
                            break
                    for thumb_field in ["thumbnail_url", "thumbnailUrl", "thumbnail", "thumb"]:
                        if thumb_field in image_urls:
                            attributes["thumbnail_url"] = image_urls[thumb_field]
                            break
        
        # Add SmartThings artwork info as fallback
        if self._st and self._st.art_mode and self._st.current_artwork:
            attributes.setdefault("artwork_name", self._st.current_artwork)
            attributes.setdefault("source", "smartthings")
        
        # Always include art mode status
        attributes["art_mode_active"] = self.art_mode_active
        attributes["art_mode_supported"] = self.art_mode_supported
        
        return attributes


class SamsungTVAvailableArtworksSensor(SamsungTVArtSensorBase):
    """Representation of a Samsung TV available artworks sensor."""

    _attr_device_class = None
    _attr_icon = "mdi:image-multiple"

    def __init__(self, config: dict[str, Any], entry_id: str, hass: HomeAssistant) -> None:
        """Initialize the sensor."""
        super().__init__(config, entry_id, hass, use_channel_info=False)
        
        self._attr_name = "Available Artworks"
        self._attr_unique_id = f"{self.unique_id}_available_artworks"

    @property
    def native_value(self) -> int:
        """Return the count of available artworks."""
        if not self.art_mode_supported:
            return 0
            
        artworks = self.get_available_artworks()
        if artworks:
            return len(artworks)
        return 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        attributes = {}
        
        if not self.art_mode_supported:
            attributes["error"] = "Art mode not supported"
            return attributes
            
        artworks = self.get_available_artworks()
        if artworks:
            # Group artworks by category
            categories = {}
            artwork_list = []
            
            for artwork in artworks:
                category = artwork.get("category", "Unknown")
                if category not in categories:
                    categories[category] = 0
                categories[category] += 1
                
                artwork_info = {
                    "id": artwork.get("content_id"),
                    "name": artwork.get("name") or artwork.get("title"),
                    "category": category,
                    "content_type": artwork.get("content_type"),
                    "description": artwork.get("description"),
                    "artist": artwork.get("artist"),
                }
                
                # Check if artwork data contains any direct image URLs (rare)
                artwork_image_urls = self._extract_image_urls(artwork)
                if artwork_image_urls:
                    artwork_info["image_urls"] = artwork_image_urls
                
                artwork_list.append(artwork_info)
            
            attributes.update({
                "categories": categories,
                "total_count": len(artworks),
                "artworks": artwork_list[:10],  # Limit to first 10 for state size
                "has_more": len(artworks) > 10,
            })
        else:
            attributes["error"] = "Unable to retrieve artwork list"
        
        return attributes


class SamsungTVSlideshowStatusSensor(SamsungTVArtSensorBase):
    """Representation of a Samsung TV slideshow status sensor."""

    _attr_device_class = None
    _attr_icon = "mdi:slideshow"

    def __init__(self, config: dict[str, Any], entry_id: str, hass: HomeAssistant) -> None:
        """Initialize the sensor."""
        super().__init__(config, entry_id, hass, use_channel_info=False)
        
        self._attr_name = "Slideshow Status"
        self._attr_unique_id = f"{self.unique_id}_slideshow_status"

    @property
    def native_value(self) -> str:
        """Return the slideshow status."""
        if not self.art_mode_supported:
            return "unsupported"
            
        slideshow_data = self.get_slideshow_status()
        if slideshow_data:
            return "on" if slideshow_data.get("enabled", False) else "off"
        return "unknown"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        attributes = {}
        
        if not self.art_mode_supported:
            return {"error": "Art mode not supported"}
            
        slideshow_data = self.get_slideshow_status()
        if slideshow_data:
            attributes.update({
                "enabled": slideshow_data.get("enabled", False),
                "duration_minutes": slideshow_data.get("duration"),
                "slideshow_type": slideshow_data.get("type"),
                "current_position": slideshow_data.get("position"),
                "total_images": slideshow_data.get("total"),
            })
        
        return attributes


class SamsungTVArtSettingsSensor(SamsungTVArtSensorBase):
    """Representation of a Samsung TV art settings sensor."""

    _attr_device_class = None
    _attr_icon = "mdi:tune"

    def __init__(self, config: dict[str, Any], entry_id: str, hass: HomeAssistant) -> None:
        """Initialize the sensor."""
        super().__init__(config, entry_id, hass, use_channel_info=False)
        
        self._attr_name = "Art Settings"
        self._attr_unique_id = f"{self.unique_id}_art_settings"

    @property
    def native_value(self) -> str:
        """Return the current art mode configuration summary."""
        if not self.art_mode_supported:
            return "unsupported"
        elif not self.art_mode_active:
            return "inactive"
        else:
            return "configured"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the art settings as attributes."""
        attributes = {}
        
        if not self.art_mode_supported:
            return {"error": "Art mode not supported"}
        
        # Get settings from WebSocket
        art_settings = self.get_art_settings()
        if art_settings:
            attributes.update(art_settings)
        
        # Add SmartThings settings as fallback
        if self._st and self._st.art_mode:
            attributes.setdefault("brightness", self._st.art_brightness)
            attributes.setdefault("matting_style", self._st.art_matting)
            attributes.setdefault("sleep_timer", self._st.art_sleep_timer)
        
        # Add status information
        attributes.update({
            "art_mode_active": self.art_mode_active,
            "art_mode_supported": self.art_mode_supported,
        })
        
        return attributes