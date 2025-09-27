"""Base sensor class for Samsung TV Smart sensors."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import (
    CONF_API_KEY, 
    CONF_DEVICE_ID,
    CONF_HOST,
    CONF_MAC,
    CONF_PORT,
    CONF_TOKEN,
)
from homeassistant.core import HomeAssistant

from .. import get_smartthings_api_key
from ..api.smartthings import SmartThingsTV, STStatus
from ..api.samsungws import SamsungTVWS, ArtModeStatus
from ..const import (
    CONF_ST_ENTRY_UNIQUE_ID,
    CONF_WS_NAME,
)
from ..entity import SamsungTVEntity


class SamsungTVSensorBase(SamsungTVEntity, SensorEntity):
    """Base class for Samsung TV sensors that use SmartThings."""

    def __init__(
        self, 
        config: dict[str, Any], 
        entry_id: str, 
        hass: HomeAssistant,
        use_channel_info: bool = False
    ) -> None:
        """Initialize the sensor."""
        super().__init__(config, entry_id)
        
        # Initialize SmartThings connection if available
        self._st = None
        st_entry_uniqueid: str | None = config.get(CONF_ST_ENTRY_UNIQUE_ID)
        
        def api_key_callback() -> str | None:
            """Get new api key and update config entry with the new token."""
            if st_entry_uniqueid:
                return get_smartthings_api_key(hass, st_entry_uniqueid)
            return None

        st_api_key = config.get(CONF_API_KEY)
        device_id = config.get(CONF_DEVICE_ID)
        
        if st_api_key and device_id:
            from homeassistant.helpers.aiohttp_client import async_get_clientsession
            session = async_get_clientsession(hass)
            
            use_callback: bool = st_entry_uniqueid is not None
            self._st = SmartThingsTV(
                api_key=st_api_key,
                device_id=device_id,
                use_channel_info=use_channel_info,
                session=session,
                api_key_callback=api_key_callback if use_callback else None,
            )

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._st is not None and self._st.state != STStatus.STATE_UNKNOWN

    async def async_update(self) -> None:
        """Update the sensor state."""
        if self._st:
            try:
                await self._st.async_device_update()
            except Exception:
                # If update fails, sensor will show as unavailable
                pass


class SamsungTVArtSensorBase(SamsungTVSensorBase):
    """Base class for Samsung TV art mode sensors that use both SmartThings and WebSocket APIs."""

    def __init__(
        self, 
        config: dict[str, Any], 
        entry_id: str, 
        hass: HomeAssistant,
        use_channel_info: bool = False
    ) -> None:
        """Initialize the art sensor."""
        super().__init__(config, entry_id, hass, use_channel_info)
        
        # Initialize WebSocket connection for art mode
        self._ws = None
        
        # Get connection parameters
        host = config.get(CONF_HOST)
        port = config.get(CONF_PORT, 8002)
        token = config.get(CONF_TOKEN)
        ws_name = config.get(CONF_WS_NAME, "SamsungTvRemote")
        mac = config.get(CONF_MAC)
        
        if host:
            self._ws = SamsungTVWS(
                host=host,
                port=port,
                token=token,
                name=ws_name,
            )

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        # Check both SmartThings and WebSocket availability
        st_available = super().available
        ws_available = (
            self._ws is not None 
            and self._ws.artmode_status != ArtModeStatus.Unsupported
        )
        
        # For art sensors, we need at least one connection method
        return st_available or ws_available

    @property
    def art_mode_supported(self) -> bool:
        """Return True if art mode is supported."""
        if self._ws:
            return self._ws.art().supported()
        return False

    @property
    def art_mode_active(self) -> bool:
        """Return True if TV is currently in art mode."""
        if self._ws:
            return self._ws.art().get_artmode()
        if self._st:
            return self._st.art_mode
        return False

    async def async_update(self) -> None:
        """Update both SmartThings and WebSocket data."""
        # Update SmartThings data
        await super().async_update()
        
        # Update WebSocket data if available
        if self._ws and self._ws.is_connected:
            try:
                # The WebSocket connection automatically updates art mode status
                # via event handlers, so no explicit update needed here
                pass
            except Exception:
                # If WebSocket update fails, continue with SmartThings data
                pass

    def get_current_artwork(self) -> dict | None:
        """Get current artwork details via WebSocket."""
        if not self._ws or not self.art_mode_supported:
            return None
        return self._ws.art().get_current()

    def get_available_artworks(self) -> list[dict] | None:
        """Get available artworks via WebSocket."""
        if not self._ws or not self.art_mode_supported:
            return None
        return self._ws.art().available()

    def select_artwork(self, content_id: str) -> bool:
        """Select artwork via WebSocket."""
        if not self._ws or not self.art_mode_supported:
            return False
        return self._ws.art().select_image(content_id, show=True)

    def get_art_settings(self) -> dict | None:
        """Get art mode settings via WebSocket."""
        if not self._ws or not self.art_mode_supported:
            return None
        return self._ws.get_art_settings()

    def get_slideshow_status(self) -> dict | None:
        """Get slideshow status via WebSocket."""
        if not self._ws or not self.art_mode_supported:
            return None
        return self._ws.get_slideshow_status()
    
    def _extract_image_urls(self, artwork_data: dict) -> dict[str, str]:
        """Extract image URLs from artwork data."""
        image_urls = {}
        
        # Most likely image field names based on common API patterns
        image_fields = [
            # Primary image fields
            'image_url', 'imageUrl', 'image', 'url',
            # Thumbnail fields
            'thumbnail_url', 'thumbnailUrl', 'thumbnail', 'thumb',
            # Alternative naming patterns
            'picture_url', 'pictureUrl', 'photo_url', 'photoUrl',
            'file_url', 'fileUrl', 'content_url', 'contentUrl'
        ]
        
        for field in image_fields:
            if field in artwork_data:
                value = artwork_data[field]
                if value and isinstance(value, str):
                    # Check if it looks like a URL or base64 data
                    if (value.startswith(('http://', 'https://', 'data:')) or
                        (value.startswith('/') and len(value) > 5) or  # Relative path
                        len(value) > 100):  # Likely base64 encoded image
                        image_urls[field] = value
        
        # Check nested objects for image data (one level deep only)
        for key, value in artwork_data.items():
            if isinstance(value, dict):
                nested_images = self._extract_image_urls(value)
                for nested_key, nested_value in nested_images.items():
                    image_urls[f"{key}.{nested_key}"] = nested_value
        
        return image_urls
    
    def download_artwork_thumbnail(self, content_id: str) -> bytes | None:
        """Download artwork thumbnail via WebSocket."""
        if not self._ws or not self.art_mode_supported:
            return None
        return self._ws.download_artwork_thumbnail(content_id)
    
